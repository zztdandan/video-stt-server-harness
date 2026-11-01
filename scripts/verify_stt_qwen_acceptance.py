#!/usr/bin/env python3
"""stt_qwen 验收指标采集（SPEC §9.3）：只读产物，不改任何文件。

对每部影片输出一份 JSON：任务状态、片长分布、四类计数（从日志抓）、SRT 结构、
ja/zh 段数、残留假名、覆盖率、copy_back 后的 sha256 一致性。

用法：
    python scripts/verify_stt_qwen_acceptance.py \
        --job SAN-484-U=/abs/artifacts/<job_id> \
        --log-root whisper-stt/tmp/logs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


# 假名（平假名 + 片假名）：zh.srt 里出现即说明有未翻译残留。
KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
# SRT 时间轴行。
TS_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})$"
)


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    """把 SRT 解析成 `(start, end, text)`；结构异常直接抛错（不猜）。"""

    content = path.read_text(encoding="utf-8")
    entries: list[tuple[float, float, str]] = []
    for block in [b for b in content.split("\n\n") if b.strip()]:
        lines = block.split("\n")
        if len(lines) < 3:
            raise ValueError(f"malformed SRT block in {path}: {block[:60]!r}")
        match = TS_RE.match(lines[1].strip())
        if not match:
            raise ValueError(f"malformed timestamp in {path}: {lines[1]!r}")
        groups = [int(x) for x in match.groups()]
        start = groups[0] * 3600 + groups[1] * 60 + groups[2] + groups[3] / 1000
        end = groups[4] * 3600 + groups[5] * 60 + groups[6] + groups[7] / 1000
        entries.append((start, end, "\n".join(lines[2:]).strip()))
    return entries


def sha256_file(path: Path) -> str | None:
    """文件 sha256；不存在返回 None（便于区分"没回拷"与"内容不一致"）。"""

    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def srt_metrics(path: Path, *, audio_duration: float | None) -> dict:
    """计算一份 SRT 的结构指标（段数/时长分布/单调性/空文本/覆盖率）。"""

    entries = parse_srt(path)
    durations = [e - s for s, e, _ in entries]
    last_end = max((e for _s, e, _ in entries), default=0.0)
    non_monotonic = sum(
        1
        for (s1, e1, _), (s2, _e2, _) in zip(entries, entries[1:])
        if s2 < e1 - 1e-6
    )
    return {
        "path": str(path),
        "segments": len(entries),
        "chars": sum(len(t) for _s, _e, t in entries),
        "empty_text": sum(1 for _s, _e, t in entries if not t),
        "max_segment_sec": round(max(durations), 3) if durations else 0.0,
        "min_segment_sec": round(min(durations), 3) if durations else 0.0,
        "mean_segment_sec": round(sum(durations) / len(durations), 3) if durations else 0.0,
        "segments_over_30s": sum(1 for d in durations if d > 30.0 + 1e-6),
        "non_monotonic": non_monotonic,
        "last_end_sec": round(last_end, 3),
        "coverage": (
            round(last_end / audio_duration, 4)
            if audio_duration and audio_duration > 0
            else None
        ),
        "sha256": sha256_file(path),
        "kana_entries": sum(1 for _s, _e, t in entries if KANA_RE.search(t)),
    }


def parse_progress_checkpoint(path: Path) -> dict:
    """读取翻译检查点，返回「已翻译 id 键集合」的规模与源 sha256。

    检查点结构（`translate.py` 落盘）：`{"batch_size", "chunk_minutes", "max_chars",
    "source_sha256", "version", "batches": {"<batch_id>": {"done", "ids",
    "translations": {"<id>": "<中文>"}}}}`。这里把各批的 translations 键并起来，
    用于验收判据"检查点键集合 == ja 段数"。
    """

    if not path.is_file():
        return {"exists": False}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"exists": True, "shape": type(payload).__name__}
    batches = payload.get("batches")
    if not isinstance(batches, dict):
        return {
            "exists": True,
            "shape": "flat",
            "keys": len(payload),
            "source_sha256": payload.get("source_sha256"),
        }
    ids: set[str] = set()
    for batch in batches.values():
        translations = batch.get("translations") if isinstance(batch, dict) else None
        if isinstance(translations, dict):
            ids.update(str(key) for key in translations)
    return {
        "exists": True,
        "shape": "batches",
        "batches": len(batches),
        "batches_done": sum(
            1 for b in batches.values() if isinstance(b, dict) and b.get("done")
        ),
        "keys": len(ids),
        "min_key": min(ids, key=int) if ids else None,
        "max_key": max(ids, key=int) if ids else None,
        "source_sha256": payload.get("source_sha256"),
        "version": payload.get("version"),
    }


def main() -> int:
    """命令行入口：逐部采集并打印 JSON。"""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--film",
        action="append",
        required=True,
        help="<name>=<artifact_dir>[:<video_dir>]，可重复",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    report: dict[str, dict] = {}
    for raw in args.film:
        name, _, rest = raw.partition("=")
        artifact_dir, _, video_dir = rest.partition(":")
        artifact = Path(artifact_dir)
        video = Path(video_dir) if video_dir else None

        stem_candidates = [p.name[: -len(".ja.srt")] for p in (artifact / "asr").glob("*.ja.srt")]
        entry: dict = {"artifact_dir": str(artifact), "video_dir": str(video) if video else None}
        if len(stem_candidates) != 1:
            entry["error"] = f"expect exactly one ja.srt, got {stem_candidates}"
            report[name] = entry
            continue
        stem = stem_candidates[0]
        wav = artifact / "audio" / f"{stem}.16k.wav"
        ja = artifact / "asr" / f"{stem}.ja.srt"
        zh = artifact / "translate" / f"{stem}.zh.srt"
        progress = artifact / "translate" / f"{stem}.zh.srt.progress.json"

        audio_duration = None
        if wav.is_file():
            import wave

            with wave.open(str(wav), "rb") as handle:
                audio_duration = handle.getnframes() / float(handle.getframerate())
        entry["audio_duration_sec"] = round(audio_duration, 3) if audio_duration else None
        entry["ja"] = srt_metrics(ja, audio_duration=audio_duration)
        if zh.is_file():
            entry["zh"] = srt_metrics(zh, audio_duration=audio_duration)
        else:
            entry["zh"] = {"path": str(zh), "exists": False}
        entry["checkpoint"] = parse_progress_checkpoint(progress)
        if video is not None:
            entry["copy_back"] = {
                "ja_same": sha256_file(video / f"{stem}.ja.srt") == entry["ja"]["sha256"],
                "zh_same": (
                    zh.is_file()
                    and sha256_file(video / f"{stem}.zh.srt") == entry["zh"].get("sha256")
                ),
                "video_ja_sha256": sha256_file(video / f"{stem}.ja.srt"),
                "video_zh_sha256": sha256_file(video / f"{stem}.zh.srt"),
            }
        report[name] = entry

    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

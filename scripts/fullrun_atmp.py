#!/usr/bin/env python3
"""atmp 全量重做（extract → stt_qwen → translate）的串行驱动与记账器。

为什么单独一个脚本：这一轮要的是**长期计时观测**，不是一次验收。所以脚本自己
不做任何"智能"决策——不调参、不清库、不删产物、失败不改配置——只负责：
  1) 按固定口径发现素材（排除 VR 前缀、排除点目录、排除隔离目录）；
  2) 一部一部地走服务 API 提交标准三步 DAG（串行 = GPU 独占 + 对另一侧干扰最小）；
  3) 等到终态，把每个阶段的起止/耗时/attempt/last_error 记进账本；
  4) 独立校验产物（段数、末条结束时间、覆盖率、残留假名、sha256），不轻信 exit/状态；
  5) 断点续跑：账本里已 succeeded 且产物仍在的片子默认跳过。

账本（唯一事实源）：`tmp/fullrun/ledger.jsonl`，每部一行 JSON，追加写，永不改写历史行。
报告：`tmp/fullrun/report.md`（由账本重新渲染，可随时重算）。

用法：
    python scripts/fullrun_atmp.py run                 # 串行跑完全部（默认）
    python scripts/fullrun_atmp.py run --only SAN-484-U
    python scripts/fullrun_atmp.py run --include-vr    # 把 VR/8K 也算进来
    python scripts/fullrun_atmp.py run --limit 1       # 只跑一部（冒烟）
    python scripts/fullrun_atmp.py run --dry-run       # 只列素材与提交体，不提交
    python scripts/fullrun_atmp.py status              # 打印账本表格
    python scripts/fullrun_atmp.py verify              # 重新校验账本里所有产物
"""

from __future__ import annotations

import argparse
import hashlib
import os
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import configparser
import requests


# 已知的外部冻结窗口（主机休眠/整体停机）：这些时段内的墙钟与阶段计时都被拉长，
# 统计与展示时必须标 †，否则"单片耗时"被系统性高估。窗口由实测日志缺口登记，不猜。
FROZEN_WINDOWS = [
    # 主机休眠 3h18m：期间所有计时被拉长。
    ("2026-11-03T04:12:00+08:00", "2026-11-03T07:30:00+08:00"),
    # 用户为其他任务收回算力，全量跑批人工暂停 2h37m。
    ("2026-11-03T21:23:00+08:00", "2026-11-04T00:00:00+08:00"),
]

# atmp 里视为"电影"的容器扩展名；与服务的 allowed extensions 保持一致口径。
VIDEO_EXTS = {".mp4", ".mkv", ".wmv", ".avi", ".ts", ".mov", ".m2ts", ".flv", ".rmvb"}
# VR / 8K 前缀：本轮按用户口径排除（只跑常规 41 个文件）。
VR_PREFIXES = ("KAVR-", "MDVR-")
# 标准三步 DAG：ASR 阶段显式选 stt_qwen，与 stt / stt_whisperx 互斥。
DAG = {
    "version": 1,
    "stages": [
        {"stage": "extract", "depends_on": []},
        {"stage": "stt_qwen", "depends_on": ["extract"]},
        {"stage": "translate", "depends_on": ["stt_qwen"]},
    ],
}
STAGES = ("extract", "stt_qwen", "translate")
TERMINAL_JOB = {"succeeded", "failed", "blocked", "cancelled"}

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATMP = Path("/srv/media/jellyfin/JELLYFIN/atmp")
DEFAULT_CONFIG = ROOT / "tmp/fullrun/config.ini"
DEFAULT_LEDGER = ROOT / "tmp/fullrun/ledger.jsonl"
DEFAULT_REPORT = ROOT / "tmp/fullrun/report.md"


# ---------------------------------------------------------------------------
# 基础设施：服务端点、HTTP 会话
# ---------------------------------------------------------------------------


def load_endpoint(config_path: Path) -> tuple[str, str]:
    """从配置文件读基址与 token（与 submit_stt_qwen_jobs.py 同一读法）。"""

    parser = configparser.ConfigParser(interpolation=None)
    if not parser.read(config_path, encoding="utf-8"):
        raise SystemExit(f"config not readable: {config_path}")
    host = parser.get("security", "bind_host", fallback="127.0.0.1").strip() or "127.0.0.1"
    port = parser.getint("security", "bind_port", fallback=18000)
    token = parser.get("security", "api_token", fallback="").strip()
    return f"http://{host}:{port}", token


def build_session(token: str) -> requests.Session:
    """构造带鉴权头的会话；鉴权头是 `X-API-Token`（不是 Bearer）。"""

    session = requests.Session()
    if token:
        session.headers.update({"X-API-Token": token})
    return session


# ---------------------------------------------------------------------------
# 素材发现
# ---------------------------------------------------------------------------


def discover_videos(atmp: Path, include_vr: bool) -> list[dict]:
    """发现素材：一层子目录里的视频文件，跳过点目录（含隔离目录）与 VR 前缀。

    不做递归搜索：atmp 的约定是"一部片一个目录"，递归会把 .delete 之类的
    历史残留和隔离目录一起吃进来。
    """

    items: list[dict] = []
    for entry in sorted(atmp.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        is_vr = entry.name.upper().startswith(VR_PREFIXES)
        if is_vr and not include_vr:
            continue
        for file in sorted(entry.iterdir()):
            if not file.is_file() or file.suffix.lower() not in VIDEO_EXTS:
                continue
            items.append(
                {
                    "dir": entry.name,
                    "video_path": str(file),
                    "bytes": file.stat().st_size,
                    "vr": is_vr,
                }
            )
    return items


# ---------------------------------------------------------------------------
# 提交与等待
# ---------------------------------------------------------------------------


def acquire_single_instance_lock(path: Path):
    """单实例锁：同一账本只允许一个驱动写。

    多驱动并发会重复提交同一部片（2026-11-03 07:28 实测：两个驱动同时提交，
    同一部被排了两次），因此用 flock 独占；拿不到锁直接退出，不动已有作业。
    """

    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SystemExit(f"another driver holds {path}; refuse to run")
    handle.write(str(os.getpid()) + "\n")
    handle.flush()
    return handle


def find_job_by_path(session: requests.Session, base: str, video_path: str) -> dict | None:
    """按视频路径查最近一条 job（服务端 by-path 路由）。"""

    try:
        response = session.get(f"{base}/jobs/by-path", params={"video_path": video_path}, timeout=30)
        response.raise_for_status()
        return (response.json() or {}).get("item")
    except Exception:  # noqa: BLE001 - 查不到就按"未提交"处理
        return None


def archive_job(session: requests.Session, base: str, job_id: str, reason: str) -> bool:
    """归档终态失败的作业，释放该视频路径的占用资格（否则重提会被同路径挡住）。"""

    try:
        response = session.post(f"{base}/jobs/{job_id}/archive", json={"reason": reason}, timeout=30)
        return response.status_code == 200
    except Exception:  # noqa: BLE001 - 归档失败不致命，下一轮会再试
        return False


def submit_job(
    session: requests.Session,
    base: str,
    video_path: str,
    translate_batch_size: int | None = None,
    asr_only: bool = False,
) -> dict:
    """提交标准三步 DAG。

    默认**不下发 job_config**（观测配置文件档位）；只有显式指定
    `translate_batch_size` 时才逐作业覆盖，用于口径切换后的新片，
    这样既不必重启服务、也不会影响正在跑的作业。
    """

    payload = {"video_path": video_path, "language": "ja", "dag": DAG}
    if translate_batch_size:
        payload["job_config"] = {"translate": {"batch_size": int(translate_batch_size)}}
    # 提交超时不等于没提交（休眠/重启窗口常见）：先按路径查是否已有在跑作业，
    # 有就接管它，避免同一部片被排两次。
    for attempt in range(3):
        try:
            response = session.post(f"{base}/jobs", json=payload, timeout=60)
        except Exception as exc:  # noqa: BLE001 - 网络层异常按"可能已提交"处理
            existing = find_job_by_path(session, base, video_path)
            if existing and existing.get("status") in {"queued", "running"}:
                print(f"  submit 超时但作业已在跑，接管 {existing['job_id']}", flush=True)
                return {"job_id": existing["job_id"], "adopted": True}
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
            continue
        if response.status_code != 200:
            raise RuntimeError(f"submit failed {response.status_code}: {response.text[:300]}")
        return response.json()
    raise RuntimeError("submit failed after retries")


def poll_job(
    session: requests.Session,
    base: str,
    job_id: str,
    interval: float = 10.0,
    timeout_sec: float = 6 * 3600,
) -> dict:
    """阻塞到 job 终态；超时抛 TimeoutError 由调用方决定取消。

    连续 HTTP 失败计数超过阈值才放弃（服务重启窗口不应当终止整轮）。
    """

    deadline = time.monotonic() + timeout_sec
    consecutive_errors = 0
    last_detail: dict = {}
    while True:
        try:
            response = session.get(f"{base}/jobs/{job_id}", timeout=30)
            response.raise_for_status()
            last_detail = response.json()
            consecutive_errors = 0
        except Exception:  # noqa: BLE001 - 网络抖动按次数阈值处理
            consecutive_errors += 1
            if consecutive_errors >= 30:
                raise
        else:
            status = str(last_detail.get("status", ""))
            if status in TERMINAL_JOB:
                return last_detail
        if time.monotonic() > deadline:
            raise TimeoutError(f"job {job_id} not terminal after {timeout_sec}s")
        time.sleep(interval)


TERMINAL_TASK = {"succeeded", "failed", "blocked", "cancelled"}


def poll_until_asr_done(
    session: requests.Session,
    base: str,
    job_id: str,
    interval: float = 10.0,
    timeout_sec: float = 4 * 3600,
) -> dict:
    """ASR-only 模式：等到 extract 与 stt_qwen 终态就返回，不等 translate。

    为什么需要它：说明白"先停翻译"之后，作业会停在 `translate: queued`，
    若仍按 job 终态等待，驱动会永久阻塞在第一部。ASR 才是本轮要保留的产出。
    """

    deadline = time.monotonic() + timeout_sec
    consecutive_errors = 0
    while True:
        try:
            response = session.get(f"{base}/jobs/{job_id}", timeout=30)
            response.raise_for_status()
            detail = response.json()
            consecutive_errors = 0
        except Exception:  # noqa: BLE001 - 抖动按次数阈值处理
            consecutive_errors += 1
            if consecutive_errors >= 30:
                raise
            detail = None
        if detail is not None:
            tasks = {str(t.get("stage")): t for t in detail.get("tasks", [])}
            stt = tasks.get("stt_qwen") or {}
            if str(stt.get("status")) in TERMINAL_TASK:
                return detail
            if str(detail.get("status")) in {"failed", "blocked", "cancelled"}:
                return detail
        if time.monotonic() > deadline:
            raise TimeoutError(f"job {job_id} ASR not terminal after {timeout_sec}s")
        time.sleep(interval)


def cancel_job(session: requests.Session, base: str, job_id: str) -> None:
    """超时兜底：请求取消，避免串行队列被一个卡死作业永久堵住。"""

    try:
        session.post(f"{base}/jobs/{job_id}/cancel", json={"reason": "fullrun_timeout"}, timeout=30)
    except Exception:  # noqa: BLE001 - 取消失败只记录，不掩盖原始超时
        pass


# ---------------------------------------------------------------------------
# GPU 闸门：不和别人抢显卡
# ---------------------------------------------------------------------------


def _nvidia_smi_path() -> str | None:
    """WSL 下 nvidia-smi 常在 /usr/lib/wsl/lib（不在 PATH），两处都试。"""

    found = shutil.which("nvidia-smi")
    if found:
        return found
    for candidate in ("/usr/lib/wsl/lib/nvidia-smi", "/usr/bin/nvidia-smi"):
        if Path(candidate).is_file():
            return candidate
    return None


def gpu_free_mib() -> int | None:
    """读一次空闲显存（MiB）。取不到返回 None（调用方按"不可判定"处理）。"""

    exe = _nvidia_smi_path()
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return int(out.stdout.strip().splitlines()[0])
    except Exception:  # noqa: BLE001 - 探测失败不阻塞主流程
        return None


def service_warm(session: requests.Session, base: str) -> bool:
    """判断服务进程是否已经加载过模型（=权重常驻显存）。

    依据 `/metrics` 的 `whisper_stt_model_cache_misses_total`：服务进程内每发生一次
    模型加载该计数 +1，重启即归零。用"是否发生过加载"而不是猜显存，避免把自己的
    常驻权重误判成别人占卡。
    """

    try:
        response = session.get(f"{base}/metrics", timeout=10)
        match = re.search(
            r"whisper_stt_model_cache_misses_total\s+([0-9.eE+]+)", response.text
        )
        return bool(match) and float(match.group(1)) >= 1.0
    except Exception:  # noqa: BLE001 - 探测失败按冷启动处理（保守）
        return False


def wait_for_gpu(
    min_free_mib: int,
    interval: float,
    max_wait: float,
    floor_mib: int = 0,
    cold_start: bool = True,
) -> tuple[bool, float]:
    """等空闲显存回到门槛之上；返回 (是否就绪, 实际等待秒数)。

    这是"不影响另一边"的关键机关：对方在用显卡时本驱动让路，一旦空出来自动继续。

    两档门槛是必须的：服务会把 stt_qwen 权重常驻显存（实测约 12.7GiB），所以
    **跑过至少一部之后**空闲显存天然只剩 2–4GiB。此时若还按 12GiB 判，会把自己的
    缓存当成"别人占卡"，把整轮卡死在第二部（2026-11-03 实测踩到）。
    因此：冷启动（还没加载过模型）按 `min_free_mib`；之后只按 `floor_mib`
    判"是否有外部进程又抢显存"。
    """

    started = time.monotonic()
    announced = False
    threshold = min_free_mib if cold_start else max(floor_mib, 0)
    while True:
        free = gpu_free_mib()
        if free is not None and free >= threshold:
            if announced:
                print(f"  GPU 就绪：空闲 {free} MiB ≥ 门槛 {threshold} MiB", flush=True)
            return True, round(time.monotonic() - started, 3)
        if free is None:
            # 不可判定时不去猜：直接放行，让服务自己的门槛做最后一道判断。
            return True, round(time.monotonic() - started, 3)
        waited = time.monotonic() - started
        if waited > max_wait:
            return False, round(waited, 3)
        if not announced:
            print(f"  GPU 忙：空闲 {free} MiB < 门槛 {threshold} MiB，等待中…", flush=True)
            announced = True
        time.sleep(interval)


# ---------------------------------------------------------------------------
# 计时与产物校验
# ---------------------------------------------------------------------------


def _parse_ts(value) -> datetime | None:
    """解析服务写库的 ISO8601（UTC）；空值与非法值一律 None。"""

    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def stage_metrics(detail: dict) -> dict:
    """把 tasks 明细折成"每阶段一行"：状态/attempt/起止/耗时/last_error。"""

    metrics: dict[str, dict] = {}
    for task in detail.get("tasks", []):
        stage = str(task.get("stage", ""))
        started = _parse_ts(task.get("started_at"))
        finished = _parse_ts(task.get("finished_at"))
        duration = (finished - started).total_seconds() if started and finished else None
        metrics[stage] = {
            "task_id": task.get("task_id"),
            "status": task.get("status"),
            "attempt": task.get("attempt"),
            "started_at": task.get("started_at"),
            "finished_at": task.get("finished_at"),
            "duration_sec": round(duration, 3) if duration is not None else None,
            "last_error": task.get("last_error"),
        }
    return metrics


SRT_CUE = re.compile(
    r"\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}", re.MULTILINE
)
KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")


def _srt_end_seconds(text: str) -> float:
    """取 SRT 里最大的一条结束时间（秒）。解析失败返回 0.0，不抛。"""

    best = 0.0
    for match in re.finditer(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->", text):
        hh, mm, ss, ms = (int(part) for part in match.groups())
        best = max(best, hh * 3600 + mm * 60 + ss + ms / 1000.0)
    return best


def read_stage_log_metrics(log_root: Path, job_id: str) -> dict:
    """从 job 的 task.log 里取每阶段 `task_finished` 的 effective_config 指标。

    为什么读日志而不是只读 DB：DB 的 tasks 表只有状态与起止时间，而"速度"要看
    VAD 秒数、批次数、逐批耗时、峰值显存这些**只有日志里有**的量。日志是服务自己写的
    事实，不额外加工；取不到就留空，不猜测。
    """

    # 每阶段只保留这几个字段（其余如模型缓存 key 之类对本轮计时无意义）。
    wanted = {
        "extract": ("source_duration_sec", "sample_rate", "channels", "codec"),
        "stt_qwen": (
            "audio_duration_sec",
            "vad_seconds",
            "vad_speech_segments",
            "vad_speech_frames_ratio",
            "chunks_total",
            "cut_policy_counts",
            "chunk_seconds_min",
            "chunk_seconds_max",
            "chunk_seconds_mean",
            "chunk_zero_speech",
            "max_new_tokens",
            "batches_total",
            "inference_seconds",
            "batch_seconds",
            "peak_vram_gb",
            "lines_total",
            "chars_total",
            "last_end_sec",
            "coverage",
            "align_missing_chunks",
            "empty_chunks",
            "failed_chunks",
            "punct_only_lines",
            "timestamp_cleanup",
            "model_cache_hit",
            "rtf",
        ),
        "translate": (
            "lines_total",
            "batches_total",
            "batch_seconds",
            "chars_total",
            "retry_total",
            "parse_retries",
            "ids_mismatch",
            "partial_retries",
            "parallel",
            "batch_size",
            "llm_calls",
            "prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
        ),
    }
    metrics: dict[str, dict] = {}
    job_dir = log_root / job_id
    if not job_dir.is_dir():
        return metrics
    for stage_dir in job_dir.iterdir():
        if not stage_dir.is_dir():
            continue
        for task_dir in stage_dir.iterdir():
            log_file = task_dir / "task.log"
            if not log_file.is_file():
                continue
            finished = None
            for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("event") in ("task_finished", "task_failed"):
                    finished = row
            if not finished:
                continue
            stage = str(finished.get("stage") or stage_dir.name)
            effective = finished.get("effective_config") or {}
            picked = {key: effective[key] for key in wanted.get(stage, ()) if key in effective}
            picked["attempt"] = finished.get("attempt")
            picked["result"] = finished.get("result")
            picked["error"] = finished.get("error")
            metrics[stage] = picked
    return metrics


def read_service_log_translate_stats(service_log: Path, job_id: str) -> dict:
    """从服务 stdout 日志里统计该 job 的翻译批次行为（重试/parse/耗时）。

    为什么要单独读：task.log 只记阶段起止，逐批重试与 error_class 在服务日志里。
    这是"错误情况"的唯一可信来源，因此按 job_id 精确过滤，不做模糊匹配。
    """

    stats = {
        "batches_ok": 0,
        "retries": 0,
        "error_class": {},
        "elapsed_ms_total": 0,
        "max_attempt": 0,
    }
    if not service_log.is_file():
        return stats
    ok_re = re.compile(r"translate batch succeeded: job_id=(\S+) .*elapsed_ms=(\d+)")
    retry_re = re.compile(
        r"translate batch retry: job_id=(\S+) .*attempt=(\d+)/(\d+) error_class=(\w+) elapsed_ms=(\d+)"
    )
    for line in service_log.read_text(encoding="utf-8", errors="replace").splitlines():
        match = ok_re.search(line)
        if match and match.group(1) == job_id:
            stats["batches_ok"] += 1
            stats["elapsed_ms_total"] += int(match.group(2))
            continue
        match = retry_re.search(line)
        if match and match.group(1) == job_id:
            stats["retries"] += 1
            stats["elapsed_ms_total"] += int(match.group(5))
            stats["max_attempt"] = max(stats["max_attempt"], int(match.group(2)))
            key = match.group(4)
            stats["error_class"][key] = stats["error_class"].get(key, 0) + 1
    return stats


def load_log_root(config_path: Path) -> Path:
    """从配置读 `[runtime] log_root`；读不到就回落到 workspace 的 tmp/fullrun/logs。"""

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(config_path, encoding="utf-8")
    raw = parser.get("runtime", "log_root", fallback="").strip()
    return Path(raw) if raw else ROOT / "tmp/fullrun/logs"


def probe_duration(video_path: Path) -> float | None:
    """ffprobe 取容器时长（只读头部，不整片读盘）。失败返回 None。"""

    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return float(out.stdout.strip())
    except Exception:  # noqa: BLE001 - 时长只是参考值，取不到就留空
        return None


def verify_outputs(video_path: Path, duration: float | None) -> dict:
    """校验回拷到视频目录的两份字幕；缺文件即判 not_ok（不补、不猜）。"""

    stem = video_path.stem
    ja = video_path.parent / f"{stem}.ja.srt"
    zh = video_path.parent / f"{stem}.zh.srt"
    result: dict = {
        "ja_path": str(ja),
        "zh_path": str(zh),
        "ja_exists": ja.is_file(),
        "zh_exists": zh.is_file(),
        "ok": False,
    }
    if not (result["ja_exists"] and result["zh_exists"]):
        return result

    ja_text = ja.read_text(encoding="utf-8", errors="replace")
    zh_text = zh.read_text(encoding="utf-8", errors="replace")
    result.update(
        {
            "ja_bytes": ja.stat().st_size,
            "zh_bytes": zh.stat().st_size,
            "ja_cues": len(SRT_CUE.findall(ja_text)),
            "zh_cues": len(SRT_CUE.findall(zh_text)),
            "ja_last_end_sec": round(_srt_end_seconds(ja_text), 3),
            "zh_kana_residue": len(KANA.findall(zh_text)),
            "ja_sha256": hashlib.sha256(ja.read_bytes()).hexdigest(),
            "zh_sha256": hashlib.sha256(zh.read_bytes()).hexdigest(),
            "video_duration_sec": round(duration, 3) if duration else None,
        }
    )
    if duration:
        result["coverage"] = round(result["ja_last_end_sec"] / duration, 5)
    result["ok"] = bool(
        result["ja_cues"] > 0
        and result["ja_cues"] == result["zh_cues"]
        and (not duration or (result.get("coverage") or 0) >= 0.98)
    )
    return result


# ---------------------------------------------------------------------------
# 账本
# ---------------------------------------------------------------------------


# 账本行的"优劣"排序：成功且产物校验通过的才是终态，其余只作历史。
# 为什么不是"后写覆盖前写"：主机会休眠，休眠期间 HTTP 超时会把已完成的行覆盖成 error
# （2026-11-03 04:12–07:30 实测踩到，4 部片被改写成 error），追加历史必须可回溯。
_STATUS_RANK = {
    "succeeded": 3,
    "timeout": 2,
    "failed": 1,
    "error": 1,
    "blocked": 0,
    "cancelled": 0,
}


def _row_rank(row: dict) -> tuple:
    """账本行排序键：状态等级 → 产物校验 → 完成时间。"""

    verify_ok = bool((row.get("verify") or {}).get("ok"))
    return (
        _STATUS_RANK.get(str(row.get("status", "")), 0),
        1 if verify_ok else 0,
        str(row.get("finished_at") or ""),
    )


def read_ledger(path: Path) -> dict[str, dict]:
    """读账本：同一 video_path 保留"最优"行（成功+校验通过优先），历史行仍在文件里。"""

    best: dict[str, dict] = {}
    if not path.is_file():
        return best
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = str(row.get("video_path", ""))
        if not key:
            continue
        if key not in best or _row_rank(row) > _row_rank(best[key]):
            best[key] = row
    return best


def append_ledger(path: Path, record: dict) -> None:
    """追加一行账本（不重写历史）。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _fmt_sec(value) -> str:
    """耗时秒 → 人类可读（保留 1 位小数，None → —）。"""

    if value is None:
        return "—"
    total = float(value)
    if total < 60:
        return f"{total:.1f}s"
    return f"{total / 60:.1f}m"


def render_report(ledger: dict[str, dict], out_path: Path) -> None:
    """按账本渲染 Markdown 报告（可反复重算，不含推测值）。"""

    rows = list(ledger.values())
    rows.sort(key=lambda r: (r.get("finished_at") or r.get("submitted_at") or ""))
    lines = [
        "# atmp 全量重做 · 计时台账",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 素材口径：{DEFAULT_ATMP}，排除 VR 前缀 {VR_PREFIXES} 与点目录",
        "- 账本：`tmp/fullrun/ledger.jsonl`（每部一行，追加写）",
        "",
        "| # | 影片 | 状态 | extract | stt_qwen | translate | 合计 | ja/zh 段 | 覆盖率 | 备注 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(rows, start=1):
        stages = row.get("stages", {})
        verify = row.get("verify", {})
        note = row.get("note") or ""
        if row.get("error"):
            note = (note + " " + str(row["error"])).strip()
        cues = f"{verify.get('ja_cues', '—')}/{verify.get('zh_cues', '—')}"
        coverage = verify.get("coverage")
        # 墙钟远大于各阶段之和 = 中间有主机休眠/服务停机等外部冻结窗口，必须标出来，
        # 否则"单片耗时"会被系统性高估（2026-11-03 ABF-394-U 就含 3h18m 休眠）。
        stage_sum = sum(
            float((stages.get(name) or {}).get("duration_sec") or 0)
            for name in ("extract", "stt_qwen", "translate")
        )
        total = row.get("total_sec")
        # 两种污染都要标：① 墙钟远大于阶段之和（排队/停机）；② 命中已登记的休眠窗口。
        frozen = (isinstance(total, (int, float)) and total - stage_sum > 600) or overlaps_frozen(row)
        total_text = _fmt_sec(total) + ("†" if frozen else "")
        cov_text = f"{coverage:.4f}" if isinstance(coverage, (int, float)) else "—"
        lines.append(
            "| {idx} | {name} | {status} | {extract} | {stt} | {tr} | {total} | {cues} | {cov} | {note} |".format(
                idx=index,
                name=row.get("dir") or Path(row.get("video_path", "")).stem,
                status=row.get("status", "?"),
                extract=_fmt_sec(stages.get("extract", {}).get("duration_sec")),
                stt=_fmt_sec(stages.get("stt_qwen", {}).get("duration_sec")),
                tr=_fmt_sec(stages.get("translate", {}).get("duration_sec")),
                total=total_text,
                cues=cues,
                cov=cov_text,
                note=note.replace("|", "/")[:60],
            )
        )
    total_ok = sum(1 for r in rows if r.get("status") == "succeeded" and (r.get("verify") or {}).get("ok"))
    lines += ["", f"**进度：{total_ok}/{len(rows)} 部成功且产物校验通过**", ""]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_status(ledger: dict[str, dict]) -> None:
    """终端表格（给 agent 快速看进度，字段比报告少）。"""

    header = f"{'影片':<22}{'状态':<11}{'extract':>9}{'stt_qwen':>10}{'translate':>11}{'合计':>10}  校验"
    print(header)
    print("-" * len(header))
    for row in sorted(ledger.values(), key=lambda r: (r.get("finished_at") or r.get("submitted_at") or "")):
        stages = row.get("stages", {})
        verify = row.get("verify") or {}
        print(
            f"{row.get('dir', ''):<22}{row.get('status', '?'):<11}"
            f"{_fmt_sec(stages.get('extract', {}).get('duration_sec')):>9}"
            f"{_fmt_sec(stages.get('stt_qwen', {}).get('duration_sec')):>10}"
            f"{_fmt_sec(stages.get('translate', {}).get('duration_sec')):>11}"
            f"{_fmt_sec(row.get('total_sec')):>10}"
            f"  {'ok' if verify.get('ok') else 'FAIL'}"
        )


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------


class GpuSampler:
    """跑片期间每 10s 采一次显存/利用率，用于回答"到底谁把卡吃满"。

    为什么在驱动侧采而不只信 torch 的 peak：`peak_vram_gb` 是分配器口径，不含
    CUDA context、显存碎片与其他进程；判断"会不会超"必须看整卡口径（WSL 的
    nvidia-smi 反映宿主整体占用）。
    """

    def __init__(self, interval: float = 10.0) -> None:
        self.interval = interval
        self.samples: list[tuple[float, int, int, int]] = []  # (t, used, free, util)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _read(self) -> tuple[int, int, int] | None:
        exe = _nvidia_smi_path()
        if not exe:
            return None
        try:
            out = subprocess.run(
                [exe, "--query-gpu=memory.used,memory.free,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=20, check=False,
            )
            used, free, util = (int(part.strip()) for part in out.stdout.strip().split(","))
            return used, free, util
        except Exception:  # noqa: BLE001 - 采样失败不影响主流程
            return None

    def _run(self) -> None:
        while not self._stop.is_set():
            values = self._read()
            if values:
                self.samples.append((time.time(), *values))
            self._stop.wait(self.interval)

    def __enter__(self) -> "GpuSampler":
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()

    def summary(self) -> dict:
        if not self.samples:
            return {}
        used = [item[1] for item in self.samples]
        util = [item[3] for item in self.samples]
        return {
            "samples": len(self.samples),
            "max_used_mib": max(used),
            "min_free_mib": min(item[2] for item in self.samples),
            "avg_util_pct": round(sum(util) / len(util), 1),
        }


def run_one(
    session: requests.Session,
    base: str,
    item: dict,
    poll_interval: float,
    job_timeout: float,
    log_root: Path,
    service_log: Path,
    translate_batch_size: int | None = None,
    asr_only: bool = False,
) -> dict:
    """跑一部片：提交 → 等待 → 记账 → 校验。异常一律折成账本里的一行。"""

    video = Path(item["video_path"])
    record: dict = {
        "dir": item["dir"],
        "video_path": item["video_path"],
        "bytes": item["bytes"],
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    started = time.monotonic()
    job_id = None
    sampler = GpuSampler()
    try:
      with sampler:
        # 先查在飞作业：驱动重启/切换后不能把已在跑的同一部再提一次。
        existing = find_job_by_path(session, base, item["video_path"])
        existing_status = str((existing or {}).get("status", ""))
        # 已成功的在飞/历史作业也接管：重跑同一部没有意义，且会白烧一遍 STT。
        if existing and existing_status in {"queued", "running", "succeeded"}:
            print(f"  接管在飞作业 {existing['job_id']}", flush=True)
            submit = {"job_id": existing["job_id"], "adopted": True}
            record["adopted_existing"] = True
        else:
            if existing and existing_status in {"failed", "blocked", "cancelled"}:
                # 失败作业占着同路径：先归档再重提，否则会被路径幂等挡住、永远重跑不了。
                if archive_job(session, base, str(existing["job_id"]), "fullrun_retry"):
                    print(f"  已归档失败作业 {existing['job_id']}，重提", flush=True)
            submit = submit_job(session, base, item["video_path"], translate_batch_size)
        job_id = submit.get("job_id")
        record["job_id"] = job_id
        record["stages_plan"] = submit.get("stages")
        detail = (
            poll_until_asr_done(session, base, job_id, interval=poll_interval, timeout_sec=job_timeout)
            if asr_only
            else poll_job(session, base, job_id, interval=poll_interval, timeout_sec=job_timeout)
        )
    except TimeoutError as exc:
        # 超时不是"没结果"：请求取消并把原因写清楚，绝不按成功记账。
        if job_id:
            cancel_job(session, base, job_id)
        record.update({"status": "timeout", "error": str(exc), "job_id": job_id})
    except Exception as exc:  # noqa: BLE001 - 提交/轮询异常也要落账
        record.update({"status": "error", "error": f"{type(exc).__name__}: {exc}", "job_id": job_id})
    else:
      if asr_only:
        record.update({
            "status": "asr_done",
            "finished_at": detail.get("finished_at"),
            "stages": stage_metrics(detail),
            "stage_log": read_stage_log_metrics(log_root, str(job_id)),
            "note": "translate paused by config (translate_workers=0)",
        })
        errors = [
            {"stage": stage, "last_error": metrics.get("last_error")}
            for stage, metrics in record["stages"].items()
            if metrics.get("last_error")
        ]
        if errors:
            record["stage_errors"] = errors
      else:
        record.update(enrich_from_detail(detail, video, str(job_id), log_root, service_log))
    gpu_summary = sampler.summary()
    if gpu_summary:
        record["gpu"] = gpu_summary
    record["total_sec"] = round(time.monotonic() - started, 3)
    return record


def enrich_from_detail(
    detail: dict,
    video: Path,
    job_id: str,
    log_root: Path,
    service_log: Path | None = None,
) -> dict:
    """把一次 job 明细折成账本字段：阶段耗时、日志指标、产物校验。

    抽成独立函数是为了让"接管"（adopt）与正常跑完走**同一条**记账路径，
    否则恢复出来的行与正常行字段不一致，事后无法比较。
    """

    enriched: dict = {
        "status": detail.get("status"),
        "finished_at": detail.get("finished_at"),
        "job_finished_at": detail.get("finished_at"),
        "stages": stage_metrics(detail),
        "stage_log": read_stage_log_metrics(log_root, job_id),
    }
    if service_log is not None:
        stats = read_service_log_translate_stats(service_log, job_id)
        if stats["batches_ok"] or stats["retries"]:
            enriched["stage_log"].setdefault("translate", {})["log_stats"] = stats
    errors = [
        {"stage": stage, "last_error": metrics.get("last_error")}
        for stage, metrics in enriched["stages"].items()
        if metrics.get("last_error")
    ]
    if errors:
        enriched["stage_errors"] = errors
    enriched["verify"] = verify_outputs(video, probe_duration(video))
    if enriched["status"] == "succeeded" and not enriched["verify"].get("ok"):
        # 状态成功但产物不达标：这是最危险的组合，必须显式标出来。
        enriched["note"] = "status=succeeded but verify FAILED"
    return enriched


def cmd_adopt(args: argparse.Namespace) -> int:
    """接管"服务里已跑完、但账本里没有"的作业（驱动崩溃/重启后的补记）。

    只补记不重跑：从 API 读明细、从日志读速度细节、对产物做独立校验。
    """

    ledger_path = Path(args.ledger)
    log_root = load_log_root(Path(args.config))
    service_log = Path(args.service_log)
    base, token = load_endpoint(Path(args.config))
    session = build_session(token)
    ledger = read_ledger(ledger_path)
    adopted = 0
    for job_id in [item.strip() for item in args.job.split(",") if item.strip()]:
        response = session.get(f"{base}/jobs/{job_id}", timeout=30)
        response.raise_for_status()
        detail = response.json()
        video = Path(detail["video_path"])
        record = {
            "dir": video.parent.name,
            "video_path": str(video),
            "job_id": job_id,
            "submitted_at": detail.get("created_at"),
            "adopted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        record.update(enrich_from_detail(detail, video, job_id, log_root, service_log))
        # 墙钟必须用 job 的 created_at→finished_at：服务重启会让 task 的 started_at
        # 被恢复时的 claim 覆盖，逐阶段相加会低估真实耗时（本次首片就低了 22 分钟）。
        created = _parse_ts(detail.get("created_at"))
        finished = _parse_ts(detail.get("finished_at"))
        if created and finished:
            record["total_sec"] = round((finished - created).total_seconds(), 3)
        else:
            record["total_sec"] = None
        if any((record["stages"].get(stage) or {}).get("attempt") for stage in STAGES):
            record["timing_note"] = "阶段计时为最后一次 attempt 的起止；中途发生服务重启"
        append_ledger(ledger_path, record)
        ledger[str(video)] = record
        adopted += 1
        print(f"adopted {video.parent.name}: {record['status']} verify={'ok' if record['verify'].get('ok') else 'FAIL'}")
    render_report(ledger, Path(args.report))
    print(f"adopt: {adopted} 个作业补记完成")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """串行主循环：一部终态后才提交下一部。"""

    config_path = Path(args.config).expanduser()
    ledger_path = Path(args.ledger)
    lock_handle = acquire_single_instance_lock(ledger_path.with_suffix(".lock"))
    assert lock_handle  # 持有到进程结束，进程退出自动释放
    base, token = load_endpoint(config_path)
    session = build_session(token)
    atmp = Path(args.atmp)
    ledger = read_ledger(ledger_path)

    items = discover_videos(atmp, include_vr=args.include_vr)
    if args.only:
        wanted = {name.strip() for name in args.only.split(",") if name.strip()}
        items = [item for item in items if item["dir"] in wanted]
    if args.skip:
        skipped = {name.strip() for name in args.skip.split(",") if name.strip()}
        items = [item for item in items if item["dir"] not in skipped]
    pending = []
    for item in items:
        previous = ledger.get(item["video_path"])
        if previous and previous.get("status") == "succeeded" and (previous.get("verify") or {}).get("ok") and not args.force:
            continue
        pending.append(item)

    print(f"素材 {len(items)} 部，待跑 {len(pending)} 部（账本已有 {len(ledger)} 行）", flush=True)
    if args.limit:
        pending = pending[: args.limit]
    if args.dry_run:
        for item in pending:
            print(json.dumps({"url": f"{base}/jobs", "payload": {"video_path": item["video_path"], "language": "ja", "dag": DAG}}, ensure_ascii=False))
        return 0

    for index, item in enumerate(pending, start=1):
        print(f"[{index}/{len(pending)}] {item['dir']} 开始 {datetime.now().astimezone().strftime('%H:%M:%S')}", flush=True)
        # 每部片开跑前都过一遍 GPU 闸门：中途有人用显卡就暂停，空出来再继续。
        # 服务已加载模型时显存被自己占满（实测空闲 90–200MiB），再按任何门槛判都会永久等待；
        # 此时显存归我们所有，直接放行，冷启动才做闸门检查。
        warm = service_warm(session, base)
        if warm:
            ready, waited = True, 0.0
        else:
            ready, waited = wait_for_gpu(
                int(args.min_free_vram_gb * 1024),
                args.gpu_wait_interval,
                args.gpu_max_wait,
                floor_mib=int(args.gate_floor_gb * 1024),
                cold_start=True,
            )
        if not ready:
            print(f"  GPU 等待超时（{waited:.0f}s），本轮停止：已完成的片子都已入账", flush=True)
            return 3
        record = run_one(
            session, base, item, args.poll_interval, args.job_timeout,
            load_log_root(config_path), Path(args.service_log),
            args.translate_batch_size,
            args.asr_only,
        )
        if waited >= 1:
            record["gpu_waited_sec"] = waited
        if args.translate_batch_size:
            record["translate_batch_size"] = args.translate_batch_size
        append_ledger(ledger_path, record)
        ledger[item["video_path"]] = record
        render_report(ledger, Path(args.report))
        stages = record.get("stages", {})
        print(
            "  -> {status} extract={e} stt={s} translate={t} total={tot} verify={v}".format(
                status=record.get("status"),
                e=_fmt_sec(stages.get("extract", {}).get("duration_sec")),
                s=_fmt_sec(stages.get("stt_qwen", {}).get("duration_sec")),
                t=_fmt_sec(stages.get("translate", {}).get("duration_sec")),
                tot=_fmt_sec(record.get("total_sec")),
                v="ok" if (record.get("verify") or {}).get("ok") else "FAIL",
            ),
            flush=True,
        )
        if record.get("error"):
            print(f"  !! {record['error']}", flush=True)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """打印账本表格。"""

    print_status(read_ledger(Path(args.ledger)))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """重新校验所有已记账的产物（用于事后审计，不看 job 状态）。"""

    ledger = read_ledger(Path(args.ledger))
    bad = 0
    for row in ledger.values():
        video = Path(row["video_path"])
        verify = verify_outputs(video, probe_duration(video))
        flag = "ok" if verify.get("ok") else "FAIL"
        if not verify.get("ok"):
            bad += 1
        print(f"{flag:<5}{row.get('dir', ''):<22}{verify.get('ja_cues')}/{verify.get('zh_cues')} cues")
    print(f"FAIL {bad} / {len(ledger)}")
    return 0 if bad == 0 else 1


def cmd_backfill(args: argparse.Namespace) -> int:
    """把日志里的速度细节补进账本（对已记账的行幂等：内容没变就不追加）。"""

    ledger_path = Path(args.ledger)
    log_root = load_log_root(Path(args.config))
    service_log = Path(args.service_log)
    rows = list(read_ledger(ledger_path).values())
    added = 0
    for row in rows:
        job_id = row.get("job_id")
        if not job_id:
            continue
        metrics = read_stage_log_metrics(log_root, str(job_id))
        translate_stats = read_service_log_translate_stats(service_log, str(job_id))
        if translate_stats["batches_ok"] or translate_stats["retries"]:
            metrics.setdefault("translate", {})["log_stats"] = translate_stats
        if not metrics:
            continue
        if json.dumps(metrics, sort_keys=True) == json.dumps(row.get("stage_log"), sort_keys=True):
            continue
        enriched = dict(row)
        enriched["stage_log"] = metrics
        enriched["backfilled_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        append_ledger(ledger_path, enriched)
        added += 1
    render_report(read_ledger(ledger_path), Path(args.report))
    print(f"backfill: {added} 行补全（账本共 {len(rows)} 行）")
    return 0


def overlaps_frozen(row: dict) -> bool:
    """该片的作业窗口是否与已知冻结窗口重叠（重叠即计时被污染）。"""

    start = _parse_ts(row.get("submitted_at"))
    end = _parse_ts(row.get("finished_at")) or _parse_ts(row.get("job_finished_at"))
    if not start or not end:
        return False
    for raw_start, raw_end in FROZEN_WINDOWS:
        window_start = _parse_ts(raw_start)
        window_end = _parse_ts(raw_end)
        if window_start and window_end and start < window_end and end > window_start:
            return True
    return False


def render_detail_table(ledger: dict[str, dict]) -> str:
    """渲染"逐片逐阶段"明细表（Markdown），用于写进台账文档。

    每列都来自账本或服务日志，不做二次估算；缺失值统一写 —。
    """

    rows = list(ledger.values())
    rows.sort(key=lambda r: (r.get("submitted_at") or ""))
    lines = [
        "| # | 影片 | 时长 | 状态 | extract | stt_qwen | STT RTF | VAD | 片/批 | 峰值显存 | translate(墙钟) | 翻译API累计 | 重试 | 合计 | ja/zh 段 | 覆盖 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(rows, start=1):
        stages = row.get("stages") or {}
        log = row.get("stage_log") or {}
        stt = log.get("stt_qwen") or {}
        tr = log.get("translate") or {}
        tr_stats = tr.get("log_stats") or {}
        verify = row.get("verify") or {}
        duration = verify.get("video_duration_sec")
        api_ms = tr_stats.get("elapsed_ms_total")
        cues = f"{verify.get('ja_cues', '—')}/{verify.get('zh_cues', '—')}"
        coverage = verify.get("coverage")
        # 墙钟远大于各阶段之和 = 中间有主机休眠/服务停机等外部冻结窗口，必须标出来，
        # 否则"单片耗时"会被系统性高估（2026-11-03 ABF-394-U 就含 3h18m 休眠）。
        stage_sum = sum(
            float((stages.get(name) or {}).get("duration_sec") or 0)
            for name in ("extract", "stt_qwen", "translate")
        )
        total = row.get("total_sec")
        # 两种污染都要标：① 墙钟远大于阶段之和（排队/停机）；② 命中已登记的休眠窗口。
        frozen = (isinstance(total, (int, float)) and total - stage_sum > 600) or overlaps_frozen(row)
        total_text = _fmt_sec(total) + ("†" if frozen else "")
        lines.append(
            "| {idx} | {name} | {dur} | {status} | {extract} | {stt} | {rtf} | {vad} | {chunks}/{batches} | {vram} | {tr} | {api} | {retry} | {total} | {cues} | {cov} |".format(
                idx=index,
                name=row.get("dir", "—"),
                dur=f"{duration / 60:.0f}min" if isinstance(duration, (int, float)) else "—",
                status=row.get("status", "—"),
                extract=_fmt_sec((stages.get("extract") or {}).get("duration_sec")),
                stt=_fmt_sec((stages.get("stt_qwen") or {}).get("duration_sec")),
                rtf=f"{stt['rtf']:.3f}" if isinstance(stt.get("rtf"), (int, float)) else "—",
                vad=f"{stt['vad_seconds']:.1f}s" if isinstance(stt.get("vad_seconds"), (int, float)) else "—",
                chunks=stt.get("chunks_total", "—"),
                batches=stt.get("batches_total", "—"),
                vram=f"{stt['peak_vram_gb']:.1f}G" if isinstance(stt.get("peak_vram_gb"), (int, float)) else "—",
                tr=_fmt_sec((stages.get("translate") or {}).get("duration_sec")),
                api=f"{api_ms / 1000 / 60:.0f}min" if api_ms else "—",
                retry=tr_stats.get("retries", "—"),
                total=total_text,
                cues=cues,
                cov=f"{coverage:.4f}" if isinstance(coverage, (int, float)) else "—",
            )
        )
    lines.append("")
    lines.append("> † 墙钟比各阶段之和多出 10 分钟以上：含主机休眠/服务停机等外部冻结窗口，不代表真实处理耗时。")
    return "\n".join(lines)


def cmd_table(args: argparse.Namespace) -> int:
    """打印明细表（便于直接贴进台账文档）。"""

    print(render_detail_table(read_ledger(Path(args.ledger))))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """汇总统计：每阶段总量/中位数/每音频小时成本，以及失败与重试面。

    只统计"阶段有真实起止时间"的行——没跑到的阶段按缺失处理，不当 0。
    """

    ledger = read_ledger(Path(args.ledger))
    rows = list(ledger.values())
    done = [r for r in rows if r.get("status") == "succeeded"]
    audio_sec = sum(
        (r.get("verify") or {}).get("video_duration_sec") or 0 for r in done
    )

    def collect(stage: str) -> list[float]:
        values = []
        for row in done:
            duration = (row.get("stages", {}).get(stage) or {}).get("duration_sec")
            if isinstance(duration, (int, float)):
                values.append(float(duration))
        return values

    def median(values: list[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        mid = len(ordered) // 2
        return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2

    print(f"账本行 {len(rows)}；succeeded {len(done)}；音频合计 {audio_sec / 3600:.2f} 小时")
    print(f"{'阶段':<12}{'样本':>5}{'合计':>12}{'中位':>10}{'每音频小时':>12}")
    for stage in STAGES:
        values = collect(stage)
        total = sum(values)
        per_hour = total / (audio_sec / 3600) if audio_sec and values else 0.0
        print(f"{stage:<12}{len(values):>5}{_fmt_sec(total):>12}{_fmt_sec(median(values)):>10}{_fmt_sec(per_hour):>12}")
    totals = [float(r.get("total_sec") or 0) for r in done]
    print(f"{'合计(墙钟)':<12}{len(totals):>5}{_fmt_sec(sum(totals)):>12}{_fmt_sec(median(totals)):>10}")

    retried = [
        (row.get("dir"), stage, (row["stages"][stage] or {}).get("attempt"))
        for row in done
        for stage in STAGES
        if ((row.get("stages") or {}).get(stage) or {}).get("attempt")
    ]
    print(f"\n发生过重试的阶段：{len(retried)}")
    for item in retried[:20]:
        print("  ", item)
    failures = [r for r in rows if r.get("status") != "succeeded"]
    print(f"\n非成功行：{len(failures)}")
    for row in failures:
        print(f"  {row.get('dir')}: {row.get('status')} {row.get('error') or ''}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """CLI：run / status / verify。"""

    parser = argparse.ArgumentParser(description="atmp 全量重做驱动（串行、记账、可续跑）")
    sub = parser.add_subparsers(dest="command")

    def add_common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--config", default=str(DEFAULT_CONFIG))
        target.add_argument("--atmp", default=str(DEFAULT_ATMP))
        target.add_argument("--ledger", default=str(DEFAULT_LEDGER))
        target.add_argument("--report", default=str(DEFAULT_REPORT))

    run = sub.add_parser("run", help="串行跑（默认命令）")
    add_common(run)
    run.add_argument("--poll-interval", type=float, default=10.0)
    run.add_argument("--job-timeout", type=float, default=6 * 3600, help="单部超时秒数（超时即取消并记账）")
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--only", default="", help="逗号分隔的目录名白名单")
    run.add_argument("--skip", default="", help="逗号分隔的目录名黑名单（隔离问题片用）")
    run.add_argument("--force", action="store_true", help="忽略账本里已成功的行")
    run.add_argument("--include-vr", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument(
        "--min-free-vram-gb",
        type=float,
        default=12.0,
        help="开跑前要求的空闲显存（GiB），与 config 的 min_free_vram_gb 对齐",
    )
    run.add_argument("--gpu-wait-interval", type=float, default=60.0)
    run.add_argument("--gpu-max-wait", type=float, default=12 * 3600, help="单部等待 GPU 的上限秒数")
    run.add_argument(
        "--gate-floor-gb",
        type=float,
        default=1.0,
        help="非首部时的显存下限（GiB）：只用来发现外部进程抢卡；"
        "服务自身常驻权重后空闲基线仅约 1.6GiB，门槛不能设高",
    )
    run.add_argument("--service-log", default=str(ROOT / "tmp/fullrun/service.log"))
    run.add_argument(
        "--asr-only",
        action="store_true",
        help="只跑 extract+stt_qwen，translate 保持 queued（配合 translate_workers=0）",
    )
    run.add_argument(
        "--translate-batch-size",
        type=int,
        default=0,
        help="逐作业下发 translate.batch_size（0=用配置默认）；口径切换时用它，不必重启服务",
    )
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="打印账本")
    add_common(status)
    status.set_defaults(func=cmd_status)

    verify = sub.add_parser("verify", help="重新校验产物")
    add_common(verify)
    verify.set_defaults(func=cmd_verify)

    table = sub.add_parser("table", help="打印逐片明细表（Markdown）")
    add_common(table)
    table.set_defaults(func=cmd_table)

    stats = sub.add_parser("stats", help="汇总每阶段速度")
    add_common(stats)
    stats.set_defaults(func=cmd_stats)

    backfill = sub.add_parser("backfill", help="从日志补全账本里的速度细节")
    add_common(backfill)
    backfill.add_argument("--service-log", default=str(ROOT / "tmp/fullrun/service.log"))
    backfill.set_defaults(func=cmd_backfill, service_log=str(ROOT / "tmp/fullrun/service.log"))

    adopt = sub.add_parser("adopt", help="接管已跑完但未记账的作业")
    add_common(adopt)
    adopt.add_argument("--job", required=True, help="逗号分隔的 job_id")
    adopt.add_argument("--service-log", default=str(ROOT / "tmp/fullrun/service.log"))
    adopt.set_defaults(func=cmd_adopt, service_log=str(ROOT / "tmp/fullrun/service.log"))

    parser.set_defaults(func=cmd_run, poll_interval=10.0, job_timeout=6 * 3600, limit=0,
                        only="", force=False, include_vr=False, dry_run=False,
                        min_free_vram_gb=12.0, gpu_wait_interval=60.0, gate_floor_gb=1.0,
                        gpu_max_wait=12 * 3600,
                        config=str(DEFAULT_CONFIG), atmp=str(DEFAULT_ATMP),
                        ledger=str(DEFAULT_LEDGER), report=str(DEFAULT_REPORT),
                        service_log=str(ROOT / "tmp/fullrun/service.log"),
                        translate_batch_size=0, asr_only=False, skip="")
    return parser


def main(argv: list[str] | None = None) -> int:
    """入口：无子命令按 run 处理（便于直接 `python scripts/fullrun_atmp.py`）。"""

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        argv.insert(0, "run")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""按标准三步 DAG（extract → stt_qwen → translate）向 whisper-stt 服务提交任务。

与 `submit_jobs_from_video_paths.py` 的区别只有一个：DAG 的第二阶段换成 `stt_qwen`。
刻意做成独立脚本而不是改旧脚本，避免影响既有的 whisperx 提交路径。

用法：
    python scripts/submit_stt_qwen_jobs.py \
        --config whisper-stt/config.ini \
        --video /srv/.../SAN-484-U/SAN-484-U.mp4 \
        --video /srv/.../ABF-394-U/ABF-394-U.mp4 \
        --dry-run
"""

from __future__ import annotations

import argparse
import configparser
import json
from pathlib import Path

import requests


# 标准三步 DAG：ASR 阶段显式选 stt_qwen（与 stt / stt_whisperx 互斥）。
STT_QWEN_DAG = {
    "version": 1,
    "stages": [
        {"stage": "extract", "depends_on": []},
        {"stage": "stt_qwen", "depends_on": ["extract"]},
        {"stage": "translate", "depends_on": ["stt_qwen"]},
    ],
}


def load_service_endpoint(config_path: Path) -> tuple[str, str]:
    """从配置文件读基址与 token（bind_host/bind_port 来自 [security]）。"""

    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")
    host = parser.get("security", "bind_host", fallback="127.0.0.1").strip() or "127.0.0.1"
    port = parser.getint("security", "bind_port", fallback=18000)
    token = parser.get("security", "api_token", fallback="").strip()
    return f"http://{host}:{port}", token


def build_payload(video_path: str) -> dict:
    """构造请求体：只覆盖白名单内的 stt_qwen 参数（切片参数留配置默认值）。

    这里刻意**不下发** job_config.stt_qwen：验收要验证的是"配置里的本轮落地档"
    真的生效，而不是请求里临时改出来的值。
    """

    return {
        "video_path": video_path,
        "language": "ja",
        "dag": STT_QWEN_DAG,
        "job_config": {
            # 翻译沿用 C 段默认；只把并发/批次显式写出来便于复现（非提速手段）。
            "translate": {"parallel": 4, "batch_size": 100},
        },
    }


def main() -> int:
    """解析参数并逐个提交；失败立刻返回非 0（不吞错）。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="whisper-stt/config.ini")
    parser.add_argument("--video", action="append", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    base_url, token = load_service_endpoint(Path(args.config))
    # 鉴权头是 `X-API-Token`（见 api/app.py 的 _api_token_guard），不是 Bearer。
    headers = {"X-API-Token": token} if token else {}

    for video in args.video:
        payload = build_payload(video)
        if args.dry_run:
            print(json.dumps({"url": f"{base_url}/jobs", "payload": payload}, ensure_ascii=False))
            continue
        response = requests.post(
            f"{base_url}/jobs", json=payload, headers=headers, timeout=60
        )
        print(response.status_code, response.text, flush=True)
        response.raise_for_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

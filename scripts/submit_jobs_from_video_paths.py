#!/usr/bin/env python3
"""读取 video_paths.txt 并批量提交任务到 whisper-stt 服务。"""

from __future__ import annotations

import argparse
import configparser
from pathlib import Path
import sys

import requests


def load_video_paths(path_file: Path) -> list[str]:
    """读取视频绝对路径列表；文件为空时抛出异常。"""

    lines = [
        line.strip()
        for line in path_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        raise ValueError("video_paths.txt is empty")
    return lines


def load_api_token(config_path: Path) -> str:
    """从配置文件读取 security.api_token。"""

    cp = configparser.ConfigParser()
    cp.read(config_path, encoding="utf-8")
    return cp.get("security", "api_token", fallback="").strip()


def build_payload(video_path: str) -> dict:
    """构建与显式 DAG E2E 对齐的请求体。"""

    return {
        "video_path": video_path,
        "language": "ja",
        "dag": {
            "version": 1,
            "stages": [
                {"stage": "extract", "depends_on": []},
                {"stage": "stt_whisperx", "depends_on": ["extract"]},
                {"stage": "translate", "depends_on": ["stt_whisperx"]},
            ],
        },
        "job_config": {
            "stt_whisperx": {
                "batch_size": 16,
                "align_enabled": True,
            },
            "translate": {
                "chunk_minutes": 20,
                "retry": 8,
            },
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="Submit jobs from video_paths file")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:18000",
        help="service base url",
    )
    parser.add_argument(
        "--video-paths",
        default="/home/base/repo/video-stt-whisper-server/scripts/video_paths.txt",
        help="absolute path to video paths file",
    )
    parser.add_argument(
        "--config-path",
        default="/home/base/video-stt-server/data/config.ini",
        help="config path used for fallback token lookup",
    )
    parser.add_argument(
        "--api-token",
        default="",
        help="X-API-Token value; if empty, load from --config-path",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="request timeout seconds",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="only submit first N videos; <=0 means all",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """读取路径并提交任务。"""

    args = parse_args(argv)
    base_url = args.base_url.rstrip("/")
    video_paths_file = Path(args.video_paths)
    config_path = Path(args.config_path)

    if not video_paths_file.is_file():
        print(f"missing video paths file: {video_paths_file}", file=sys.stderr)
        return 2

    token = str(args.api_token).strip()
    if not token:
        if not config_path.is_file():
            print(
                f"missing config file for token lookup: {config_path}", file=sys.stderr
            )
            return 2
        token = load_api_token(config_path)
    if not token:
        print("empty api token", file=sys.stderr)
        return 2

    try:
        videos = load_video_paths(video_paths_file)
    except Exception as exc:
        print(f"failed to load video paths: {exc}", file=sys.stderr)
        return 2

    if args.limit > 0:
        videos = videos[: args.limit]

    invalid = [p for p in videos if not Path(p).is_absolute() or not Path(p).is_file()]
    if invalid:
        print("invalid video paths detected:", file=sys.stderr)
        for p in invalid:
            print(f"- {p}", file=sys.stderr)
        return 2

    session = requests.Session()
    session.trust_env = False
    headers = {"X-API-Token": token}

    try:
        health = session.get(f"{base_url}/docs", timeout=args.timeout)
        health.raise_for_status()
    except Exception as exc:
        print(f"service not reachable at {base_url}: {exc}", file=sys.stderr)
        return 3

    accepted = 0
    for idx, video_path in enumerate(videos, start=1):
        payload = build_payload(video_path)
        try:
            resp = session.post(
                f"{base_url}/jobs",
                json=payload,
                headers=headers,
                timeout=args.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            job_id = str(data.get("job_id", ""))
            queue_ahead = data.get("queue_ahead")
            accepted_flag = bool(data.get("accepted", False))
            if accepted_flag:
                accepted += 1
            print(
                f"[{idx:03d}/{len(videos):03d}] accepted={accepted_flag} "
                f"job_id={job_id} queue_ahead={queue_ahead} video={video_path}"
            )
        except Exception as exc:
            print(
                f"[{idx:03d}/{len(videos):03d}] submit_failed "
                f"video={video_path} err={exc}",
                file=sys.stderr,
            )

    print(f"done: accepted={accepted}/{len(videos)}")
    return 0 if accepted > 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())

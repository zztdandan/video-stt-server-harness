# 架构与关键功能

## 组件分层

- `scripts/run_video_ja_srt.sh`
  - 统一入口，负责读取环境变量并调用 Python 主流程。
- `whisper_stt/transcribe_video.py`
  - 负责媒体探测、抽音频、Whisper 转写、SRT 写出。
- `whisper_stt/translate_srt_ja_to_zh.py`
  - 负责 SRT 解析、分批并发调用模型、断点续跑与中文 SRT 输出。

## 关键能力清单

### A. 转写链路

- 自动运行时选择：
  - `device=auto` -> 有 CUDA 用 `cuda`，否则 `cpu`
  - `compute_type=auto` -> CUDA 用 `float16`，CPU 用 `int8`
- 先抽音频（可关闭）：
  - `ffmpeg` 转 `16kHz` + `mono` + `pcm_s16le`
- SRT 写出：标准时间戳 `HH:MM:SS,mmm`

### B. 翻译链路

- 支持超大 SRT：按批发送，默认至少 200 段/请求。
- 动态并发：最多 16，按批次数自动收敛。
- 发送节流：请求派发间隔 1 秒。
- 失败重试：带重试日志与总重试计数。
- 断点续跑：`*.progress.json` 持久化已完成映射。

### C. 可观测性

- 三阶段统一输出：
  - 进度条
  - 已耗时
  - ETA
  - 预计完成时间

## 输入/输出约定

- 输入：本地视频文件（mp4/mkv 等）
- 中间产物：可选 `*.tmp.16k.wav`
- 输出：
  - `*.ja.srt`
  - `*.zh.srt`
  - `*.zh.srt.progress.json`

## 可配置项（高频）

- 转写：`DEVICE`、`COMPUTE_TYPE`、`PREEXTRACT_WAV`、`PROGRESS_EVERY`
- 翻译：`--batch-size`（最小200策略）、`--parallel`、`--request-interval`、`--retry`

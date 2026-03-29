# Whisper STT 项目记忆（本轮沉淀）

## 目标与约束

- 目标：对本地视频做日语 ASR，并产出可用的 `ja.srt` 与 `zh.srt`。
- 关键约束：
  - 必须复用仓库根目录共享环境 `/.venv`，不新增子项目 venv。
  - 允许并已使用 `ffmpeg` 做音频预处理。
  - 翻译调用外部 LLM 接口，需支持大文件分批与断点续跑。

## 已验证结论

- 仓库已有 STT 依赖：`faster-whisper` 与 `openai-whisper`，可直接在共享 venv 使用。
- `ffmpeg` 预抽音频（16k/mono/wav）后再送 `faster-whisper`，链路更稳定、可观测性更强。
- 转写与翻译都需要“进度可见”，否则长任务不可控。

## 关键实现变化

- 新增子项目：`whisper-stt/`。
- 新增转写脚本：`whisper-stt/whisper_stt/transcribe_video.py`。
- 新增翻译脚本：`whisper-stt/whisper_stt/translate_srt_ja_to_zh.py`。
- 新增启动脚本：`whisper-stt/scripts/run_video_ja_srt.sh`。
- 文档入口：`whisper-stt/README.md`。

## 进度可视化标准（统一）

- 必须提供：进度条、已耗时、ETA、预计完成时间。
- 阶段标签：
  - `EXTRACT`：ffmpeg 抽音频
  - `TRANSCRIBE`：Whisper 转写
  - `TRANSLATE`：SRT 翻译
- 翻译额外日志：`DISPATCH`（请求派发）与 `RETRY`（重试次数）。

## 翻译发送策略（当前最终版）

- 每请求至少 200 段字幕（`batch_size = max(传入值, 200)`）。
- 非严格 16 线：实际并发 `workers = min(16, 批次数)`。
- 请求派发间隔 1 秒（`request_interval=1`）。
- 失败重试并计数，支持断点续跑（`.progress.json`）。

## 实战经验

- 先短片联调，再长片全量，可显著降低返工成本。
- 代理环境可能干扰外部 API 调用；翻译脚本默认关闭环境代理读取（`--disable-proxy`）。
- 对于时间跨度判断，优先用 `ffprobe` 检查源媒体真实时长，避免仅凭播放器印象。

## 结果产物约定

- 日语字幕：`<video>.ja.srt`
- 中文字幕：`<video>.zh.srt`
- 翻译进度缓存：`<video>.zh.srt.progress.json`

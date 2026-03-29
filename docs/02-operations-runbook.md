# Whisper STT 操作手册（Runbook）

## 1) 环境前置

- 使用仓库根目录共享环境：`/home/base/repo/qwen-tts-test/.venv`
- 进入仓库根目录执行。
- 确保系统可用：`ffmpeg`、`ffprobe`。

## 2) 视频 -> 日语字幕（ja.srt）

使用一键脚本：

```bash
INPUT_VIDEO="/abs/path/to/video.mp4" \
OUTPUT_SRT="/abs/path/to/video.ja.srt" \
DEVICE="auto" \
COMPUTE_TYPE="auto" \
PREEXTRACT_WAV="true" \
KEEP_TEMP_AUDIO="false" \
PROGRESS_EVERY="40" \
bash whisper-stt/scripts/run_video_ja_srt.sh
```

### 参数建议

- GPU：`DEVICE=cuda COMPUTE_TYPE=float16`
- CPU：`DEVICE=cpu COMPUTE_TYPE=int8`
- 若排查解码问题：保留中间音频 `KEEP_TEMP_AUDIO=true`

## 3) 日语字幕 -> 中文字幕（zh.srt）

```bash
./.venv/bin/python whisper-stt/whisper_stt/translate_srt_ja_to_zh.py \
  --input "/abs/path/to/video.ja.srt" \
  --output "/abs/path/to/video.zh.srt" \
  --base-url "https://www.right.codes/codex/v1" \
  --api-key "<YOUR_API_KEY>" \
  --model "gpt-5.1-codex-mini" \
  --batch-size 200 \
  --parallel 16 \
  --request-interval 1 \
  --retry 6 \
  --timeout 240
```

## 4) 输出日志解释

- `EXTRACT ...`：ffmpeg 抽音频进度。
- `TRANSCRIBE ...`：Whisper 转写进度。
- `DISPATCH ...`：翻译请求派发序列。
- `RETRY ...`：翻译请求失败重试。
- `TRANSLATE ...`：翻译总体完成率与 ETA。

## 5) 标准执行顺序（建议）

1. 先裁 2-3 分钟短片联调（看三段进度都正常）。
2. 短片验证后，再跑长片全量。
3. 对比 `ja.srt/zh.srt` 行数一致性。
4. 抽查头尾字幕内容与时间戳。

## 6) 交付前核对清单

- 文件存在：`*.ja.srt`、`*.zh.srt`
- 行数一致：`wc -l ja.srt zh.srt`
- 末尾时间戳合理（不超过媒体总时长）
- 翻译进度文件可用于续跑：`*.zh.srt.progress.json`

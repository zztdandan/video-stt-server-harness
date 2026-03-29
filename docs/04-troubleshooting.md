# 故障排查与恢复指南

## 1) 进度看起来不动

- 短视频阶段可能很快完成，日志刷新间隔导致只看到少量行。
- 长视频应持续看到 `EXTRACT/TRANSCRIBE/TRANSLATE` 进度。

建议：

- 转写调小 `PROGRESS_EVERY`（例如 20 或 10）。
- 翻译保持 `request_interval=1`，并观察 `DISPATCH` 与 `TRANSLATE`。

## 2) 翻译接口偶发报错

常见：`JSONDecodeError`、`ConnectTimeout`、`ProxyError`。

处理：

- 已内置重试（可调 `--retry`）。
- 默认禁用环境代理（`--disable-proxy`），避免代理干扰。
- 使用 `.progress.json` 直接续跑，不要从头重来。

## 3) 片长感觉不对

- 先用 `ffprobe` 查真实时长，避免播放器 UI 误读。
- 再比对字幕末条时间戳，确认是否在合理范围内。

## 4) 速度慢

- 优先启用 GPU：`DEVICE=cuda COMPUTE_TYPE=float16`。
- 保留抽音频：`PREEXTRACT_WAV=true`，通常更稳定。
- 模型可权衡：`faster-whisper-small` 准确率/速度平衡较好。

## 5) 文件校验失败

- 使用：`wc -l ja.srt zh.srt` 检查行数一致。
- 抽查首尾条目与时间戳格式。

## 6) 安全与合规提醒

- API Key 不要写入仓库文档或代码。
- 仅在本地环境变量或临时命令行传入密钥。

# 故障排查与恢复指南

## 1) 进度看起来不动

- 短视频阶段可能很快完成，日志刷新间隔导致只看到少量行。
- 长视频应持续看到 `EXTRACT/TRANSCRIBE/TRANSLATE` 进度。

建议：

- 转写调小 `PROGRESS_EVERY`（例如 20 或 10）。
- 翻译保持 `request_interval=1`，并观察 `DISPATCH` 与 `TRANSLATE`。
- 服务模式：`GET /jobs/{job_id}/progress` 返回内存进度快照；`GET /admin/shutdown/status` 的 `inflight` 可确认是否还有在途任务。

## 2) 翻译接口偶发报错

常见：`JSONDecodeError`、`ConnectTimeout`、`ProxyError`。

处理：

- 已内置重试（`--retry` / `[translation] retry`），只对连接错误、超时、5xx、JSON 解析失败与 id 不匹配重试。
- **4xx（鉴权/参数错误）不会重试**：看到 401/403/400 请先检查 `api_key`、`base_url`、`model` 与配额，而不是加大重试。
- 默认禁用环境代理（`disable_proxy=true`），避免代理干扰。
- 续跑直接复用 `*.progress.json`（逐批检查点），不要从头重来；若源 `ja.srt` 被改动，检查点会因 `source_sha256` 不匹配而全量重算。
- 缺 id 告警 `translate_partial` 表示该批部分条目模型未返回，已保留日文原文；需要严格模式可设 `strict_ids=true`。

## 3) 片长感觉不对

- 先用 `ffprobe` 查真实时长，避免播放器 UI 误读。
- 再比对字幕末条时间戳，确认是否在合理范围内。

## 4) 速度慢

- 优先启用 GPU：`DEVICE=cuda COMPUTE_TYPE=float16`。
- 保留抽音频：`PREEXTRACT_WAV=true`，通常更稳定。
- 模型可权衡：`faster-whisper-small` 准确率/速度平衡较好。
- 服务模式先看 `/metrics`：`whisper_stt_model_cache_hits_total` 长期不增长说明模型缓存未命中；
  `whisper_stt_queue_depth` 堆积说明 worker 数不足或阶段超时。

## 5) 文件校验失败

- 使用：`wc -l ja.srt zh.srt` 检查行数一致。
- 抽查首尾条目与时间戳格式。
- 服务模式产物在 `artifacts/<job_id>/{audio,asr,translate}/`；找到对应的 `asr/<stem>.ja.srt` 与 `translate/<stem>.zh.srt`。

## 6) 安全与合规提醒

- API Key / token 不要写入仓库文档或代码；只在环境变量或本地 `config.ini`（已被 gitignore）中保存。
- `docs/hf-token.md` 已删除：HF token 统一用 `HF_TOKEN` 环境变量；主仓库 `.gitignore` 已忽略 `docs/hf-token.md`、`docs/*token*`、`*.token`、`token.env`、`.env`。
- 曾经落盘的 HF token 与 `config.ini` 中的 API key 需要**人工轮换**（属交付前置动作）；
  本地删除/忽略文件不等于供应商侧已撤销，当前没有 provider 端撤销证据，不能宣称已完成。

## 7) 启动被拒绝（fail-closed）

- `[security] require_token=true` 且 `api_token` 为空 → 拒绝启动（预期行为，不是 bug）。
  先设置真实 token（建议 `≥16` 字符；代码只拒绝空/占位 token，短 token 仅告警），或显式 `require_token=false`（不推荐）。
- `api_token` 含 `<`、`>` 或等于示例占位值时，`allow_placeholder_token=false` 也会拒绝启动。
- 历史 `parallel=16` 配置仍可加载，但会按 16 并发运行；升级后请改为 2。

## 8) 任务卡住或状态异常

| 现象 | 原因 | 处理 |
|---|---|---|
| 任务长时间 `claimed` 但无进度 | worker 崩溃 / hang | 租约超过 `lease_timeout_sec` 后由 reaper 回收（attempt+1）；超预算转 `failed` |
| 下游任务一直 `queued` | 上游失败未级联（旧版本） | v0.5.0 起上游失败会把下游置 `blocked`；查 task 日志 `upstream_failed:<task_id>` |
| job `failed` 想原地重跑 | 旧流程要求先 archive | 用 `POST /jobs/{job_id}/retry`（仅 failed）；返回受影响 task 数 |
| 想放弃排队中的 job | — | 用 `POST /jobs/{job_id}/cancel`（仅 queued / 全部任务未开始） |
| 停机后进程不退出 | 有僵尸 `claimed` 任务 | v0.5.0 起 `can_exit` 只看本进程在途任务，超过 `drain_timeout_sec` 以冻结的 task/owner/attempt 三元组强制回滚并退出 |
| 同一任务被两个 worker 写结果 | 旧 attempt 复活 | fencing 拒绝旧 attempt 写回并记 `fenced_stale_result`；worker boot nonce 防 ABA 已复验 |
| 服务模式跑完但视频目录没有 `zh.srt` | copy_back sink 失败 / 目标不在白名单 / 跨 FS 发布错误 | 查 `copy_back_target_resolve_failed`、`allowed_copy_back_roots` 与服务日志；真实 sink 与跨 FS 回写已实现并复验 |
| 恢复后无限重试 | 崩溃恢复不计数（旧版本） | v0.5.0 起恢复消耗重试预算；`recovery_counts_as_attempt=false` 仅用于调试 |
| ASR 报 `missing_audio_artifact` | wav 不存在或为 0 字节 | 检查 extract 任务日志；新契约不允许回退读原视频 |

## 9) 常见错误码速查

- DAG：`dag_version_not_supported`、`dag_missing_asr_stage`、`dag_asr_stage_conflict`、`dag_missing_extract_dependency`、`dag_translate_without_asr`
- 路径与安全：`video_path_not_absolute`、`video_path_not_file`、`video_path_extension_not_allowed`、`video_path_outside_allowed_roots`、`invalid_api_token`、`copy_back_target_resolve_failed`
- 任务：`lease_expired`、`lease_expired_retry_exhausted`、`fenced_stale_result`、`upstream_failed:<task_id>`、`missing_audio_artifact`
- 接口：`job_not_found`、`job_config_key_not_supported`、`job_config_value_out_of_range`

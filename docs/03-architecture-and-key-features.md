# 架构与关键功能

## 组件分层

- `scripts/run_video_ja_srt.sh`
  - 统一入口，负责读取环境变量并调用 Python 主流程（内部先抽 16k mono wav）。
- `whisper_stt/transcribe_video.py` / `transcribe_video_whisperx.py`
  - 负责媒体探测、抽音频、Whisper / WhisperX 转写、SRT 写出。
- `whisper_stt/translate_srt_ja_to_zh.py`
  - 负责 SRT 解析、分批受限并发调用模型、检查点续跑与中文 SRT 输出。
- `whisper_stt_service/`（服务模式）
  - `api/`：FastAPI 路由（jobs / queue / admin / health / metrics）。
  - `repo/`：SQLite 仓储、迁移、租约与任务状态机。
  - `service/runtime.py`：worker 池、租约心跳、reaper、有界停机。
  - `service/model_cache.py`：进程内模型缓存 + 每模型并发信号量。
  - `executor/`：`extract` / `stt` / `stt_whisperx` / `translate` 四个阶段执行器与原子写工具。

## 关键能力清单

### A. 转写链路（wav 契约）

- 自动运行时选择：
  - `device=auto` -> 有 CUDA 用 `cuda`，否则 `cpu`
  - `compute_type=auto` -> CUDA 用 `float16`，CPU 用 `int8`
- **ASR 只吃 wav**：`extract` 用 ffmpeg 产出 `16kHz + mono + pcm_s16le` 的 `audio/<stem>.16k.wav`，
  `stt` / `stt_whisperx` 的输入固定为该 wav；wav 缺失或 0 字节时任务失败并报
  `missing_audio_artifact`（不静默回退读原视频）。
- DAG 语义校验（入队即拒绝）：必须恰好一个 ASR 阶段、ASR 依赖闭包必须含 `extract`、
  `translate` 依赖闭包必须含该 ASR 阶段；错误码 `dag_version_not_supported`、
  `dag_missing_asr_stage`、`dag_asr_stage_conflict`、`dag_missing_extract_dependency`、`dag_translate_without_asr`。
- SRT 写出：标准时间戳 `HH:MM:SS,mmm`，临时文件 + 原子替换，中断不留半成品。

### B. 翻译链路

- 支持超大 SRT：按批发送，三重上限（时间窗 `chunk_minutes` + 条目 `batch_size` 200 + 字符 `max_chars` 12000）同时生效、取先到者。
- **并发上限 2（可配）**：`ThreadPoolExecutor(max_workers=min(parallel, 批次数))`，默认 `parallel=2`（v0.4.0 配置里的 16 会被读成 16，需手动改为 2）；
  结果按批次序号聚合后按原文顺序写回，不按完成顺序。
- 发送节流：`request_interval` 为批次派发最小间隔（默认 1 秒，0 关闭）。
- 失败重试：只对连接错误 / 超时 / 5xx / JSON 解析失败 / id 不匹配重试；4xx 不重试直接失败。
  请求带 `Idempotency-Key: sha256(job_id|batch_id|source_sha256)`；每次重试记录 `batch_id`、`attempt`、`error_class`、`elapsed_ms`。
- **按批检查点续跑**：`*.progress.json` 每批成功后原子写入，并与源 `source_sha256` 比对；
  源变更则全量重算，源不变则只补未完成批次（不再“先删检查点再全量重翻”）。
  检查点发布绑定冻结租约身份；原“锁外二写”和动态借身份反例已由 P1 独立复验关闭。
- 缺 id 降级：默认保留日文原文并记 `translate_partial` 警告，不静默丢行；
  `strict_ids=true` 时缺失即整批失败。
- 原子写：`atomic_write_text`（同目录临时文件 → flush + fsync → `os.replace`），
  zh.srt、检查点、ja.srt 全部走该工具；检查点在冻结租约身份下发布，原锁外二写反例已复验关闭。
- copyback 真实 sink：脚本/服务模式都把 ja/zh 回写视频目录；跨 FS 回写与 copy 期间 symlink 替换两路径已独立复验，不能退化为跨 FS rename。

### C. 任务生命周期与资源

- 租约心跳（`lease_timeout_sec/3`，下限 10s）+ 过期回收（attempt+1，超预算 `failed` 并级联 `blocked`）。
- 结果写回带 fencing（`status='claimed' AND lease_owner AND attempt`），旧 attempt 写回被拒；
  租约身份 ABA（worker boot nonce）、stop/drain tuple-fenced 回滚、finally compare-and-remove、
  promotion 异常收敛、atomic fenced 单写均已由 P1 原反例独立复验关闭。
- 崩溃恢复消耗重试预算；`[timeouts] drain_timeout_sec` 保证停机有界。
- 模型缓存：`[runtime] model_cache_size`（默认 2，LRU）与 `model_parallelism`（默认 1，同卡串行）；
  同 key 模型只冷启动一次，日志记 `model_cache_hit/miss key=... elapsed_ms=...`。
- SQLite：`journal_mode=WAL`、`synchronous=NORMAL`、`busy_timeout=30000`、`foreign_keys=ON`；
  网络盘检测失败时回退 `DELETE` 并告警；schema 由 `repo/migrations/` 版本化执行。

### D. 安全默认值

- `[security]`：`api_token`（空 = 鉴权关闭）、`require_token`（默认 true）、`allow_placeholder_token`（默认 false）、
  `docs_enabled`（默认 false）、`allowed_video_roots`、`allowed_copy_back_roots`、`bind_host`（默认 127.0.0.1）、`bind_port`（默认 18000）。
- token 比较用 `hmac.compare_digest`；鉴权失败日志只记来源 IP 与 `request_id`，不含 token 明文。
- token 只拒绝“空（且 require_token=true）”与“占位符（`<`、`>` 或示例值）”，**不设硬性长度下限**；过短 token 仅告警。
- 示例配置（`config.example.ini`）故意 fail-closed：首次启动需设置真实 token，或显式 `require_token=false`。
- 默认只监听 127.0.0.1；公网部署必须前置反向代理 + TLS。

### E. 可观测性

- 三阶段统一输出：进度条、已耗时、ETA、预计完成时间。
- `logging.config.dictConfig`（控制台 + 轮转文件），支持 JSON 行与 `request_id` 贯穿。
- `/healthz`、`/readyz`、`/metrics`（Prometheus 文本，`prometheus_client`）。
- `/queue/summary` 的 `throughput` 为最近 5 分钟各阶段完成数。

## 输入/输出约定

- 输入：本地视频文件（mp4/mkv/mov/avi/webm/ts/m2ts）
- 中间产物：脚本模式可选 `*.tmp.16k.wav`（`PREEXTRACT_WAV`）；服务模式固定 `artifacts/<job_id>/audio/<stem>.16k.wav`
- 输出：
  - `*.ja.srt`
  - `*.zh.srt`
  - `*.zh.srt.progress.json`

## 可配置项（高频）

- 转写：`DEVICE`、`COMPUTE_TYPE`、`PREEXTRACT_WAV`、`PROGRESS_EVERY`
- 翻译：`--batch-size`、`--parallel`（默认 2）、`--request-interval`、`--retry`、`max_chars`、`checkpoint_enabled`、`strict_ids`
- 生命周期：`[timeouts] lease_timeout_sec`、`drain_timeout_sec`、`[runtime] recovery_counts_as_attempt`、`model_cache_size`、`model_parallelism`
- 安全：`[security]` 各键（见 D）

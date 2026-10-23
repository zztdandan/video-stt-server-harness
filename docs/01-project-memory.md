# Whisper STT 项目记忆（本轮沉淀）

## 目标与约束

- 目标：对本地视频做日语 ASR，并产出可用的 `ja.srt` 与 `zh.srt`。
- 关键约束：
  - 必须复用仓库根目录共享环境 `/home/base/repo/video-stt-whisper-server/.venv`，不新增子项目 venv（子仓库与 `.worktrees/*` 均不得创建 `.venv`）。
  - 允许并已使用 `ffmpeg` 做音频预处理；ASR 只消费 extract 产出的 16k mono wav（v0.5.0 起的 wav 契约，旧行为是 ASR 直接读原视频）。
  - 翻译调用外部 LLM 接口（OpenAI 兼容），需支持大文件分批、受限并发与断点续跑。

## 已验证结论

- 仓库已有 STT 依赖：`faster-whisper` 与 `openai-whisper`，可直接在共享 venv 使用。
- `ffmpeg` 预抽音频（16k/mono/pcm_s16le/wav）后再送 `faster-whisper`，链路更稳定、可观测性更强。
- 转写与翻译都需要“进度可见”，否则长任务不可控。
- 进程内模型缓存（`whisper_stt_service/service/model_cache.py`）+ 每模型并发信号量，避免每个 task 重新加载 GB 级模型、显存随 worker 数线性叠加。

## 关键实现变化

- 新增子项目：`whisper-stt/`（实现代码）；主仓库只放文档、SPEC 与协调内容。
- 脚本模式：`whisper-stt/whisper_stt/transcribe_video.py`、`transcribe_video_whisperx.py`、`translate_srt_ja_to_zh.py`。
- 服务模式：`whisper_stt_service/`（FastAPI + SQLite + worker 池），入口 `whisper_stt_service/main.py`。
- 启动脚本：`whisper-stt/scripts/run_video_ja_srt.sh`、`run_video_ja_srt_whisperx.sh`、`run_video_ja_zh.sh`（脚本内部统一调用主仓库 `.venv`）。
- 文档入口：`whisper-stt/README.md`（英文）/ `whisper-stt/README.zh-CN.md`（中文）；长期文档在主仓库 `docs/`。

## 进度可视化标准（统一）

- 必须提供：进度条、已耗时、ETA、预计完成时间。
- 阶段标签：
  - `EXTRACT`：ffmpeg 抽音频
  - `TRANSCRIBE`：Whisper 转写
  - `TRANSLATE`：SRT 翻译
- 翻译额外日志：`DISPATCH`（请求派发）与 `RETRY`（重试次数）。

## 翻译发送策略（v0.5.0 实现，已独立复验）

> 历史（v0.4.0 及以前）：旧实现的“每请求至少 200 段 / 非严格 16 线并发（workers = min(16, 批次数)）/ 请求派发间隔 1 秒 / 失败重试 + `.progress.json` 续跑”中，16 并发与断点续跑在服务端并未真正生效（`parallel` 只参与 sleep、`*.progress.json` 先删后只写不读）。以下为 v0.5.0 的实现行为；七项 P1 已由官方实施代理修复并经 Sol 原反例独立复验。

- 分批三重上限同时生效、取先到者：`chunk_minutes`（时间窗，默认 20）、`batch_size`（条目数，默认 200）、`max_chars`（字符数，默认 12000）。单条字幕超过 `max_chars` 时单独成批且**不截断原文**。
- 受限并发：`parallel` 默认 **2**（由 16 下调）；线程池执行批次，结果按批次序号与原文顺序聚合写回（不按完成顺序）。
- 请求派发间隔：`request_interval` 表示“批次派发最小间隔”，默认 1.0 秒，置 0 关闭。
- 失败重试：只对连接错误、超时、HTTP 5xx、JSON 解析失败、id 不匹配重试；4xx 直接失败（避免无意义计费）；请求附带 `Idempotency-Key`。
- 断点续跑：`<output>.progress.json` 每批成功后原子写入，并以源文件 `source_sha256` 校验；源变更则全量重算。
- 缺 id 降级：默认保留日文原文并记 `translate_partial` 警告（`strict_ids=false`）；`strict_ids=true` 时缺失即整批失败。
- 配置优先级：`job_config.translate` > `[translation]` > 代码默认值。

## 任务生命周期（v0.5.0 实现，已独立复验）

- 租约心跳 + 过期回收（reaper）+ 结果写回 fencing（旧 attempt 写回被拒并记 `fenced_stale_result`）。
- 失败级联：上游失败后下游任务置 `blocked`（终态），job 聚合为 `failed`。
- 启动恢复消耗重试预算（`[runtime] recovery_counts_as_attempt=true`），超预算直接 `failed`。
- 有界停机：`can_exit` 只看本进程在途 worker；`[timeouts] drain_timeout_sec`（默认 300）超时以冻结的 task/owner/attempt 三元组强制回滚本进程 claimed 并退出；退出通过注入回调完成。租约身份 ABA、stop/drain tuple-fenced 回滚、promotion 异常收敛、worker boot nonce 已纳入 P1 复验。
- 新增 `POST /jobs/{job_id}/retry`（仅 failed job）与 `POST /jobs/{job_id}/cancel`（仅 queued / 全部任务未开始 → `cancelled`）。

## 实战经验

- 先短片联调，再长片全量，可显著降低返工成本。
- 代理环境可能干扰外部 API 调用；翻译默认关闭环境代理读取（`disable_proxy=true`）。
- 对于时间跨度判断，优先用 `ffprobe` 检查源媒体真实时长，避免仅凭播放器印象。
- 真实 2 小时样本端到端验收与显存峰值采样需要可用的长片素材 + 可用 NVIDIA GPU；2026-10-23 复核：`tests/e2e/video_paths.txt` 的 4 条 `/srv/media/...` 路径仍全部不存在，`/srv/media/jellyfin` 为空，本机只有 30s / 180s 样本；`nvidia-smi` 退出 255 并报 `NVML GPU access blocked by OS`。因此这两项**尚未验收**（见 `02-operations-runbook.md` 第 8 节）。

## 结果产物约定

- 脚本模式：日语字幕 `<video>.ja.srt`，中文字幕 `<video>.zh.srt`，翻译进度缓存 `<video>.zh.srt.progress.json`（命名与 v0.4.0 一致）。
- 服务模式（每个 job 独立目录，阶段唯一写者）：

```text
artifacts/<job_id>/
  audio/<stem>.16k.wav            # extract 输出（16k mono pcm_s16le）
  asr/<stem>.ja.srt               # stt / stt_whisperx 输出（唯一 ASR 阶段）
  translate/<stem>.zh.srt         # translate 输出
  translate/<stem>.zh.srt.progress.json
```

- `jobs.output_ja_path` / `jobs.output_zh_path` 继续指向最终产物（API 兼容）；脚本/服务模式 `copy_back` 均使用真实 sink，把 ja/zh 复制回视频所在目录；跨 FS 与 copy 期间 symlink 替换已有独立复验。

## 环境与工具链

- Python 3.10，唯一共享环境 `/home/base/repo/video-stt-whisper-server/.venv`。依赖清单与锁文件：主仓库 `pyproject.toml` / `uv.lock`，子仓库 `pyproject.toml` / `uv.lock`（版本 0.5.0）。2026-10-24 已把 child/root 锁的普通包源归一为公共 PyPI（`pypi.org/simple` / `files.pythonhosted.org`），torch/torchaudio 保持 explicit cu128，版本/哈希/依赖图等价。
- CI：`whisper-stt/.github/workflows/ci.yml`，CPU-only（Python 3.10 + `uv sync --group dev`，不装 gpu 组），默认跳过 manual / e2e，含 secret 扫描与语法门禁。run 39981535390 @ bba96a0 锁校验失败（宿主机 TUNA 镜像）；run 39995654486 @ 66678d0 锁校验通过但 2 个 clean-runner 用例失败；随后连续两个绿色提交：2623545 → 39996457310、5e67c7b → 39997343133。v0.5.0 tag 待父创建。
- 真实媒体用例：`whisper-stt/tests/manual/test_real_media.py`，需 `WHISPER_STT_REAL_MEDIA=1` 才执行。
- 密钥治理：`docs/hf-token.md` 已删除，HF token 统一用 `HF_TOKEN` 环境变量；主仓库 `.gitignore` 已加入 `docs/hf-token.md`、`docs/*token*`、`*.token`、`token.env`、`.env`。

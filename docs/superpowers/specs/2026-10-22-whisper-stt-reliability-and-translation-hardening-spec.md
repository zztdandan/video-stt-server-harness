# Whisper STT 可靠性与翻译链路加固 SPEC

- **日期**：2026-10-22
- **状态**：已实施并通过独立验收（2026-10-24；子仓库 main/tag `v0.5.0` = 699bb85，四次连续远端 CI 绿；验收报告 docs/superpowers/executions/2026-10-24-sol-final-acceptance-v0.5.0.md，执行记录 docs/superpowers/plans/2026-10-22-hardening-execution.md。真实 2h 媒体、GPU 显存、供应商 token 轮换为发布后跟踪项，未验证）
- **适用仓库**：主仓库 `/home/base/repo/video-stt-whisper-server`；实现代码在子仓库 `whisper-stt/`
- **文档位置约束**：本 SPEC 及后续执行记录只放主仓库 `docs/`，不放进子仓库
- **实施环境约束**：所有 Python 执行只用主仓库 `.venv`；子仓库和 worktree 不得创建独立 venv；写代码时保留全部现有注释与 docstring

---

## 0. 摘要

本项目已是一条**跑得通的内部原型**（脚本模式 + FastAPI/SQLite 服务模式，55 个单测全绿），但存在四类系统性问题：

1. **任务生命周期不闭环**：租约只写不读、僵尸 claimed 会让 drain 停机永久挂住、崩溃恢复不消耗重试预算、失败不向下游传播。
2. **文档承诺与实现不符**：翻译“16 并发”“断点续跑”在服务端都不存在；extract 产物无人消费。
3. **正确性/安全缺陷**：`/jobs/by-path` 被动态路由吞掉恒 404；DAG 只有结构校验；占位 token 被当成有效口令；产物写入非原子。
4. **交付卫生不足**：无 CI、无 tag、根依赖清单未入库、密钥文件散落、文档漂移。

本轮不做重构，按“先闭环、再正确、后效率、最后交付”的顺序增量修复。用户已对四个争议点拍板（见第 3 节）。

---

## 1. 背景与已核实证据

### 1.1 当前架构

```
POST /jobs
  └─ SQLite jobs/tasks（DAG: depends_on_task_id，JSON 编码）
       ├─ extract  worker 池：ffmpeg → 16k mono wav
       ├─ stt      worker 池：faster-whisper → ja.srt
       ├─ stt_whisperx worker 池：WhisperX VAD+batched ASR+align → ja.srt
       └─ translate worker 池：OpenAI 兼容接口 → zh.srt → copy_back 到视频目录
```

- 入口：`whisper_stt_service/main.py` → `service/bootstrap.py` → `api/app.py`
- 核心：`repo/job_repository.py`（920 行）、`service/runtime.py`（711 行）
- 执行器：`executor/{extract,stt,stt_whisperx,translate}.py`
- 测试：`tests/unit` 55 个（全绿，约 28s）；`tests/e2e` 需真实视频 + 手工起服务
- 无 CI、无 Docker、无迁移工具、无 logging 配置

### 1.2 已实测确认的问题（实施时必须逐条验收）

| # | 问题 | 证据位置 | 实测结果 |
|---|---|---|---|
| 1 | `/jobs/by-path` 恒 404 | `api/routes/jobs.py:86` 注册在 `:43` 的 `/jobs/{job_id}` 之后 | TestClient 返回 `404 job_not_found` |
| 2 | 翻译逐批串行 | `executor/translate.py:163,232`：`parallel` 只参与 `time.sleep` | 代码确认，无并发 |
| 3 | 断点续跑不生效 | `executor/translate.py:153` 先删 `.progress.json`，`:209` 只写不读 | 重试/重启整部重翻 |
| 4 | extract 产物无人消费 | `service/runtime.py:401` 写 wav；`executor/stt.py:229` 直接读视频 | wav 仅占磁盘 |
| 5 | 租约不回收 | `repo/job_repository.py:459` 写 lease，全仓库无读取 | 1s 租约过期 2s 后仍不可再领取 |
| 6 | 停机被僵尸 claimed 卡死 | `service/runtime.py:153` `can_exit` 要求 `claimed_count==0` | 有僵尸 claimed 则 drain 永不退出 |
| 7 | 崩溃恢复不计数 | `repo/job_repository.py:619` 无条件回 `queued`，attempt 不变 | 崩溃-重启可无限重试 |
| 8 | 失败不级联 | `repo/job_repository.py:534`、`:575` | 实测下游永久 `queued` |
| 9 | DAG 无语义校验 | `core/dag.py:23` | 接受只有 translate 的 DAG；允许 stt 与 stt_whisperx 并存且写同一 `output_ja_path` |
| 10 | 模型零缓存 | `executor/stt.py:178`、`stt_whisperx.py:212` | 每个 task 重新加载 GB 级模型 |
| 11 | 无 logging 配置 | 全仓库无 `basicConfig/dictConfig` | 应用 INFO 日志无 handler |
| 12 | 非原子写 | `executor/common.py:272`、`stt.py:247` | 中断留下半成品字幕 |
| 13 | 占位 token 被启用 | `config.example.ini:13` + `core/config.py:338` + `api/app.py:44` | 示例口令即有效口令 |
| 14 | 密钥落盘 | `whisper-stt/config.ini`（真实 API key）、`docs/hf-token.md`（真实 HF token，未忽略） | 有误提交风险 |
| 15 | 交付卫生 | 根 `pyproject.toml`/`uv.lock` 未跟踪；子仓库 `version=0.4.0` 无 v0.4.0 tag；两个未提交改动；子仓库 92K 空 `.venv`；`tests/unit/test_workers_real_media_inputs.py` 被 gitignore | 见 `git status` |

> 参考：一轮 `gpt-6-astra` 交叉评估同意上述判断，并补充“超时重试可能重复计费”“字幕应临时文件+原子替换”两点，均已纳入本 SPEC（C.6、C.7）。

---

## 2. 目标与非目标

### 2.1 目标

1. 任务从入队到终态**可收敛**：崩溃、hang、重启、失败都有确定的最终状态，drain 停机有界。
2. API/DAG 在**入队时**拒绝确定性失败，而不是运行期才炸。
3. extract 产物被 ASR 真正消费（wav 契约），三个阶段产物归属唯一。
4. 翻译链路行为与文档一致：受限并发、真实续跑、配置全部生效、写入原子、成本可解释。
5. 进程内模型加载有缓存与并发上限，显存不再随 worker 数线性叠加。
6. 可观测性达到“排障不靠猜”：结构化日志、健康检查、指标、任务日志含真实生效配置。
7. 安全默认值安全：占位口令拒绝启动、暴露面参数化、路径白名单可配、密钥不进仓库。
8. 交付可复现：CI、tag、锁文件、文档与代码一致。

### 2.2 非目标

Web 控制台、MCP/Agent Skill、多用户配额、说话人分离、SQLite → Postgres、完整指标告警平台。这些是路线图功能，不阻塞本轮。

---

## 3. 决策记录（2026-10-22，已拍板，实施时不得再改）

> 以下为直接用户决定，优先于本 SPEC 其他描述。

| 编号 | 决策 | 落地含义 |
|---|---|---|
| **D1** | **保留 extract，ASR 必须消费 wav** | `stt` 与 `stt_whisperx` 的输入改为 extract 产出的 16k mono wav，不再直接读原视频；extract 成为 ASR 的硬前置 |
| **D2** | **翻译并发 16 → 2，其他配置不动** | `[translation] parallel` 默认改为 2；不新增独立“全局限流器/令牌桶”，**并发上限本身就是限流手段**；保留 `request_interval` 现有节流语义与默认值；其余翻译参数保持现值 |
| **D3** | **SQLite 启用 WAL** | 每个连接设置 `journal_mode=WAL`、`synchronous=NORMAL`、`busy_timeout` |
| **D4** | **暴露面参数化，不写死** | 鉴权开关、占位口令策略、docs 开关、绑定地址、视频/回写路径白名单全部进配置，默认取安全值 |
| **D5** | 其余改进按评审意见执行 | 路由修复、DAG 语义、租约/停机、级联失败、模型缓存、原子写、可观测性、CI、文档同步 |

**对 D2 的解释（写入实现契约）**：当前代码“无任何并发限制”（逐批串行）。本轮改为**受限线程池并发**，上限 2，不做额外的速率限制器；`request_interval` 保留为“批次派发间隔”，默认 1.0，置 0 可关闭。不得再把“16 并发”写进文档。

---

## 4. 详细设计

### A. 任务生命周期闭环（P0）

#### A.1 租约心跳

- worker 领取任务后启动心跳（可在 worker 主循环内用时间片实现，无需新线程）：每 `lease_timeout_sec / 3`（下限 10s）续租一次。
- 续租 SQL 必须带 fencing：

```sql
UPDATE tasks
   SET lease_expires_at = :new_expiry, updated_at = :now
 WHERE task_id = :task_id
   AND status = 'claimed'
   AND lease_owner = :worker_id
   AND attempt = :attempt
```

- 影响行数为 0 表示已被回收/被他人接管：worker 应尽快中止当前执行（协作式检查点：extract 每读一行 progress、STT 每 N 段、translate 每批检查一次），并放弃写结果。

#### A.2 过期回收（reaper）

- 新增后台循环：每 `lease_timeout_sec / 3` 扫描一次。
- 单任务事务内：

```sql
UPDATE tasks
   SET status = 'queued',
       attempt = attempt + 1,
       lease_owner = NULL,
       lease_expires_at = NULL,
       last_error = 'lease_expired',
       updated_at = :now
 WHERE task_id = :task_id
   AND status = 'claimed'
   AND lease_expires_at < :now
```

- 若 `attempt + 1 > max_retries`：置 `failed`（`last_error='lease_expired_retry_exhausted'`），并执行 A.4 级联。
- 每次回收写 task 日志事件 `lease_reclaimed`，含旧 `lease_owner`、`attempt`。
- 回收后刷新所属 job 状态。

#### A.3 结果写回 fencing

`mark_task_succeeded/failed` 增加 `worker_id`、`attempt` 参数，SQL 带：

```sql
AND status = 'claimed' AND lease_owner = :worker_id AND attempt = :attempt
```

- 影响行数 0：记录 `fenced_stale_result`（task 日志），**不得**改任务状态、不得刷新 job 状态。
- 目的：防止“复活的老 worker”把新 attempt 的结果覆盖掉。

#### A.4 失败级联

- 新增任务状态 `blocked`（终态，表示“上游失败，本任务不再执行”）。
- `mark_task_failed` 进入 `failed` 时，在同一事务内把**所有直接或间接依赖它且仍为 `queued` 的任务**置为 `blocked`，`last_error='upstream_failed:<task_id>'`。
- job 聚合：任一任务 `failed` 或 `blocked` → job `failed`；全部 `succeeded` → `succeeded`；有 `claimed` → `running`；否则 `queued`。
- `queue_summary` 增加 `blocked` 计数，避免“幽灵排队”指标。

#### A.5 启动恢复计数

- `recover_claimed_to_queued` 改为：把 `claimed` 回 `queued` 时 `attempt+1`；超预算直接 `failed` + 级联。
- 新增配置 `[runtime] recovery_counts_as_attempt = true`；置 false 时保持旧行为（仅调试用）。
- 启动日志输出恢复条数、其中超预算失败条数。

#### A.6 有界停机

- `can_exit` 改为：drain 已请求 且 本进程无在途 worker 状态；全局 `claimed_count` 只作为告警指标（多实例场景），不再作为唯一判据。
- 增加 `[timeouts] drain_timeout_sec`（默认 300）：超时后停止等待、强制回滚本进程 claimed（fencing 保护），并退出。
- 退出方式改为**注入回调**：`WorkerRuntime(..., exit_callback)`；`bootstrap` 里接 `server.should_exit = True`，默认回退 `SIGTERM`。禁止在运行时里直接 `os.kill(os.getpid(), SIGTERM)` 造成测试自杀。
- `GET /admin/shutdown/status` 增加 `drain_deadline_at`、`inflight`、`blocked` 字段。

#### A.7 重跑与取消 API

- `POST /jobs/{job_id}/retry`：仅允许 job 为 `failed`；把 `failed`/`blocked` 任务重置为 `queued`、`attempt=0`、清 `last_error`，job 回 `queued`；返回受影响 task 数。用于消除“同路径必须 archive 才能重跑”的摩擦。
- `POST /jobs/{job_id}/cancel`：仅允许 `queued` 或全部任务未开始；置 `cancelled`（新终态）并释放路径占用。运行中取消不在本轮范围。
- 两个接口都要写 task 日志与 job `updated_at`。

### B. API 与 DAG 语义

#### B.1 路由顺序

- 把 `@router.get("/jobs/by-path")` 移到 `/jobs/{job_id}` **之前**。
- 新增回归测试：先 `POST /jobs`，再 `GET /jobs/by-path?video_path=...` 必须 200 且 `item.job_id` 一致。
- 可选加固：`job_id` 统一以 `job-` 开头，路由层加正则约束，避免未来再被动态段吞掉。

#### B.2 DAG 语义校验（入队即拒绝）

在 `core/dag.py` 增加：

1. `version` 必须为 1（缺省视为 1）。
2. 必须包含恰好一个 ASR 阶段：`stt` 与 `stt_whisperx` 二选一，不得同时出现，也不得都不出现。
3. ASR 阶段的依赖闭包中必须包含 `extract`（D1 的 wav 契约）。
4. 若 DAG 含 `translate`，其依赖闭包必须包含该 ASR 阶段。
5. 任何阶段不得依赖自身（已有）、不得重复（已有）、不得成环（已有）。
6. 返回更明确的错误码：`dag_asr_stage_conflict`、`dag_missing_asr_stage`、`dag_missing_extract_dependency`、`dag_translate_without_asr`、`dag_version_not_supported`。

对应测试覆盖以上 5 种拒绝 + 3 种合法形态（extract→stt→translate、extract→stt_whisperx→translate、extract→stt 仅转写）。

#### B.3 产物所有权（每阶段唯一写者）

- 目录改为：

```
artifacts/<job_id>/
  audio/<stem>.16k.wav        # extract 输出
  asr/<stem>.ja.srt           # stt / stt_whisperx 输出（唯一 ASR 阶段）
  translate/<stem>.zh.srt     # translate 输出
  translate/<stem>.zh.srt.progress.json
```

- 在 `enqueue` 时把每个 task 的输入/输出路径算好，写入 `task_config_json` 的 `io` 段（**不新增 DB 列**）：

```json
{"stage": "stt", "effective_config": {...}, "io": {"input_path": ".../audio/x.16k.wav", "output_path": ".../asr/x.ja.srt"}}
```

- `TaskExecutionContext` 增加 `input_path`、`output_path`（从 `io` 读取，缺失时按旧规则回退）。
- `jobs.output_ja_path` 指向 ASR 产物，`jobs.output_zh_path` 指向翻译产物，保持 API 兼容。
- 运行时按 `ctx.input_path`/`ctx.output_path` 调用执行器，不再用 `ctx.video_path` 直接转写。
- 归档/清理仍以 job 目录为单位；失败 job 目录保留。

### C. 翻译链路

#### C.1 受限并发（D2）

- 用 `ThreadPoolExecutor(max_workers=min(parallel, len(batches)))` 执行批次；`parallel` 默认 2。
- 结果按 batch 序号聚合，最终按原 SRT 顺序写回（不得按完成顺序）。
- 共享 `requests.Session`（每 worker 一个，或线程本地），`trust_env = not disable_proxy`。
- 派发节流：`request_interval` 作为“批次派发最小间隔”，用 `threading.Lock` + 时间戳实现；0 表示关闭。
- 任意批次失败：不再调度新批次，等待在途批次结束后抛出，交由任务重试；已完成批次必须已落检查点。

#### C.2 配置全部生效

- `parallel`、`batch_size`、`timeout`、`disable_proxy`、`request_interval`、`retry`、`chunk_minutes`、`copy_back` 从配置读取；`job_config.translate` 覆盖优先。
- 移除“读取后只用于 sleep”的假实现。
- 配置优先级：`job_config` > `[translation]` > 代码默认。

#### C.3 分批策略（时间窗 + 条目/字符上限）

- 先按 `chunk_minutes` 时间窗分组，再对每组按 `batch_size`（默认 200）与 `max_chars`（默认 12000，新增）二次切分；三个上限同时生效，取先到者。
- 保证同一时间窗内顺序稳定；batch_id = `window_no + '/' + part_no`。
- 单条字幕超过 `max_chars` 时单独成批，不得截断原文。

#### C.4 真实断点续跑

- 检查点文件：`<output>.progress.json`，结构：

```json
{"version": 1, "source_sha256": "...", "chunk_minutes": 20, "max_chars": 12000,
 "batches": {"0/0": {"done": true, "ids": [1, 2, 3]}}}
```

- 启动时读取：`source_sha256` 与当前 ja.srt 一致才复用，否则全量重算。
- 每批成功立即原子写检查点（见 C.7）。
- 任务成功完成后保留检查点 `progress_ttl_sec`，之后由清理逻辑删除；任务重试时复用。
- 禁止在 `run_translate` 开头无条件删除检查点。
- `checkpoint_enabled=false` 时退化为旧行为（不写/不读检查点），仅用于排障；默认 true。

#### C.5 部分缺失 id 的降级

- `_call_translate_api` 允许返回 id 子集：先接受返回项，仅对缺失 id 以更小批次重试；重试仍缺失时，默认**保留日文原文**写入 zh.srt，并记 `translate_partial` 警告（含缺失数量）。
- 新增 `[translation] strict_ids = false`；置 true 时缺失即整批失败，行为与旧实现一致。
- 禁止静默丢字幕。

#### C.6 重复计费控制

- 重试只针对：连接错误、超时、HTTP 5xx、JSON 解析失败、id 不匹配。
- 4xx（鉴权/参数）不重试，直接失败，避免无意义计费。
- 请求带 `Idempotency-Key: sha256(job_id|batch_id|source_sha256)`（上游不支持时无副作用）。
- 每次重试记录 `batch_id`、`attempt`、`error_class`、`elapsed_ms`，便于成本审计。
- 检查点在“请求发出前”记录 `inflight` 标记，超时重试后可识别并只补该批。

#### C.7 原子写入

- 新增工具 `atomic_write_text(path, text)`：同目录 `.tmp-<pid>-<uuid>` 写入 → `flush` + `os.fsync` → `os.replace`。
- `_dump_srt`、检查点写入、STT/WhisperX 的 ja.srt 输出全部改用该工具（STT 可先写临时文件，循环结束后替换）。
- 失败时删除临时文件，不影响已有产物。

### D. 模型加载与资源

- 新增 `service/model_cache.py`：
  - `get_whisper_model(model_path, device, compute_type)`：进程内按 key 缓存 `WhisperModel`，`threading.Lock` 保护，引用计数。
  - `get_batched_pipeline(model)` 与模型同生命周期。
  - `get_whisperx_bundle(model, vad_config, align_root, language, device, compute)`：缓存 ASR + VAD + align 三件套。
  - `get_align_model(language, device, model_dir)`：按语言缓存。
- 新增 `[runtime] model_cache_size`（默认 2）：超出时按 LRU 释放；0 表示不缓存（仅调试）。
- 新增 `[runtime] model_parallelism`（默认 1）：每个模型实例的并发转写信号量，避免同卡 OOM；取不到信号量时排队，不失败。
- 进程退出（lifespan finally）清空缓存并释放。
- 记录冷启动耗时与命中率日志（`model_cache_hit/miss key=... elapsed_ms=...`）。

### E. extract → ASR 的 wav 契约（D1）

- `run_extract` 输出路径来自 `ctx.output_path`（`audio/<stem>.16k.wav`），参数保持 16k/mono/pcm_s16le。
- `run_stt` / `run_stt_whisperx` 的输入改为 `ctx.input_path`（wav）；`_probe_duration` 用 wav；WhisperX `load_audio` 用 wav。
- 若 wav 不存在或为 0 字节：任务失败，错误码 `missing_audio_artifact`（不静默回退视频）。
- 校验 DAG 保证 extract 在 ASR 前（B.2-3）。
- 脚本模式对齐：`scripts/run_video_ja_srt.sh` 与 `transcribe_video.py` 的预抽 wav 行为保持一致；文档写明“ASR 只吃 wav”。
- 可选清理：extract 成功后保留 wav 供重试；job 成功后由 artifact 清理统一删除。

### F. SQLite

- 连接初始化执行：

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 30000;
PRAGMA foreign_keys = ON;
```

- 注意：WAL 只适用于本地磁盘；`db_path` 位于网络盘时启动告警并回退 `journal_mode=DELETE`。
- 新增 `schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT)`；把现有“建表 + 补列”收进 `migrations/001_initial.py`、`002_*.py`，启动时按版本执行。
- 保留 `_ensure_column` 作为兜底，但新变更一律走迁移。
- 领取查询优化（**先测再改**）：记录 `claim_next` 的 P95 延迟与 SQLite busy 次数；若成为瓶颈，再引入 `task_deps(task_id, dep_task_id)` 表与单条 JOIN 领取 SQL。本 SPEC 不强制第一阶段做。
- `_refresh_job_status` 保留，但只在状态变更时调用；增加索引缺失检查（`EXPLAIN QUERY PLAN` 记录到启动日志）。

### G. 可观测性

- `bootstrap` 中 `logging.config.dictConfig`：
  - 控制台 + `log_root/service.log`（轮转 10MB × 5）。
  - `WHISPER_STT_LOG_LEVEL`（默认 INFO）。
  - `WHISPER_STT_LOG_JSONL=1` 时输出 JSON 行。
  - 同时配置 `uvicorn`、`uvicorn.error`、`uvicorn.access` 与应用 logger。
- 请求中间件：生成 `request_id`（`X-Request-ID` 透传或 uuid），响应头回写；日志与错误包含 request_id。
- 新增接口：
  - `GET /healthz`：进程存活 + DB 可查询（`SELECT 1`）。
  - `GET /readyz`：配置完整、DB 可写、model_path 存在、artifact_root 可写；不满足返回 503 + 明细。
  - `GET /metrics`：Prometheus 文本。依赖 `prometheus_client`。指标：
    - `whisper_stt_tasks_claimed_total{stage}`
    - `whisper_stt_tasks_finished_total{stage,result}`
    - `whisper_stt_task_duration_seconds{stage}`（histogram）
    - `whisper_stt_queue_depth{stage,status}`（gauge，采集时读 DB）
    - `whisper_stt_translate_batches_total{result}`、`whisper_stt_translate_retries_total`
    - `whisper_stt_model_cache_hits_total`、`..._misses_total`
- `/queue/summary` 的 `throughput` 改为“最近 5 分钟完成数/阶段”，不再返回空 dict。
- `metrics_enabled=false` 时不注册 `/metrics`（返回 404），其余观测能力保留。
- 修正 `_build_task_started_extra`：STT/WhisperX 快照使用该 task 的 `effective_config`，而非全局 settings。
- task 日志字段统一：`timestamp,request_id,job_id,task_id,stage,worker_id,event,result,attempt,effective_config,error`。

### H. 安全与暴露面（D4）

- `[security]` 新增并全部配置化：

| 键 | 默认 | 语义 |
|---|---|---|
| `api_token` | 空 | 空 = 鉴权关闭（启动 WARN） |
| `require_token` | true | true 且 token 为空 → 启动失败 |
| `allow_placeholder_token` | false | 含 `<`、`>` 或等于示例值 → 启动失败 |
| `docs_enabled` | false | 关闭时 `/docs`、`/redoc`、`/openapi.json` 返回 404；开启时仍受 token 保护 |
| `allowed_video_roots` | 空 | 逗号分隔；非空时视频路径必须 resolve 后位于其下 |
| `allowed_copy_back_roots` | 空 | 非空时 copy_back 目标必须位于其下；默认仅允许视频所在目录 |
| `bind_host` | 127.0.0.1 | 供启动脚本读取 |
| `bind_port` | 18000 | 同上 |

- token 校验改 `hmac.compare_digest`；鉴权失败记录来源 IP 与 request_id（不含 token 明文）。
- `POST /jobs` 路径校验：绝对路径、`is_file`、`resolve(strict=True)`、扩展名白名单（mp4/mkv/mov/avi/webm/ts/m2ts），并做白名单校验。
- `copy_back` 目标 resolve 后校验，拒绝符号链接逃逸。
- 默认只监听 127.0.0.1；新增 `scripts/run_service.sh`，从 `[security] bind_host/bind_port` 读取监听地址并启动 uvicorn；README 明确“公网部署必须前置反向代理 + TLS”。
- 密钥治理：
  - 删除 `docs/hf-token.md`，改用 `HF_TOKEN` 环境变量；把该文件加入 `.gitignore`。
  - 轮换已落盘的 HF token 与 `config.ini` 中的 API key（用户操作，SPEC 标记为交付前置）。
  - 新增 `docs/*token*` 忽略规则；CI 增加简单 secret 扫描（`grep -E 'sk-[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}'`）。

### I. 仓库、CI 与文档

- 主仓库：
  - 提交 `pyproject.toml`、`uv.lock`、`docs/superpowers/specs/*`、`docs/superpowers/plans/*`、`docs/research/*`。
  - `.gitignore` 增加 `docs/hf-token.md`、`*.token`、`.codex/`。
- 子仓库：
  - 提交 `llm_fallback` 相关改动并补测试（profile 选择、去重、attempt 2 起用回退模型）。
  - 删除根目录空 `.venv`；`.gitignore` 增加 `.venv/`。
  - 把 `tests/unit/test_workers_real_media_inputs.py` 移出 ignore，改名为 `tests/manual/test_real_media.py`，加 `pytest.mark.skipif(not os.getenv("WHISPER_STT_REAL_MEDIA"))`。
  - 补 tag：在 `b029d07` 打 `v0.4.0`（补历史）；本轮完成后版本升 `0.5.0` 并打 `v0.5.0`。
- CI（`.github/workflows/ci.yml`）：
  - Python 3.10 + `uv sync --group dev`（不装 gpu group）。
  - `pytest -q`（默认跳过真实媒体与 E2E）。
  - `ruff check`（若项目接受；否则仅 pytest）。
  - 用 fake executor 覆盖 A/B/C 关键路径，不依赖 ffmpeg/模型/网络。
- 文档：
  - `docs/02-operations-runbook.md`：venv 路径改为 `/home/base/repo/video-stt-whisper-server/.venv`；补充 retry/cancel、健康检查、指标。
  - `docs/01`、`docs/03`：删除“16 并发”“假续跑”描述，改为“并发上限 2（可配）”“按批检查点续跑”“ASR 消费 wav”。
  - 子仓库 README（中英）：同步 v0.5.0 行为、配置表、错误码；按 AGENTS 要求在 roadmap 中把已完成项打勾。
  - 新增 `docs/05-api-reference.md`（可选）：接口、状态机、错误码。

---

## 5. 配置项变更汇总

```ini
[translation]
parallel = 2                 # 由 16 改为 2（D2）
batch_size = 200             # 真正生效
max_chars = 12000            # 新增
chunk_minutes = 20
request_interval = 1.0       # 批次派发间隔，0 = 关闭
retry = 10
timeout = 240
disable_proxy = true         # 真正生效
copy_back = __video_dir__
checkpoint_enabled = true    # 新增
strict_ids = false           # 新增

[timeouts]
lease_timeout_sec = 600
drain_timeout_sec = 300      # 新增

[runtime]
recovery_counts_as_attempt = true   # 新增
model_cache_size = 2                 # 新增
model_parallelism = 1                # 新增

[security]
api_token =
require_token = true
allow_placeholder_token = false
docs_enabled = false
allowed_video_roots =
allowed_copy_back_roots =
bind_host = 127.0.0.1
bind_port = 18000

[observability]              # 新增 section
log_level = INFO
log_jsonl = false
metrics_enabled = true
```

`config.example.ini` 与本机 `config.ini` 都要更新；旧配置必须可加载（新键有默认值），但 `parallel=16` 会被读成 16，因此**发布说明必须提示改成 2**。

> 注意（有意的 fail-closed）：示例配置下 `require_token=true` 且 `api_token` 为空/占位，**首次启动会拒绝启动**。这不是 bug；README/runbook 必须写明“先设置真实 token，或显式 `require_token=false` 自行承担风险”。E2E 驱动与本地联调脚本需同步设置 token。

---

## 6. 数据与兼容性

- 任务状态新增：`blocked`、`cancelled`。查询接口无需改表，前端/脚本需容忍新值。
- `tasks` 表新增列：无。输入/输出路径放在 `task_config_json.io`，避免迁移。
- `jobs.status` 不变（`queued/running/succeeded/failed`）。
- 旧 job 的产物路径仍可读；新 job 用新布局。`get_job_detail` 对旧 job 回退旧字段。
- 历史 job 若 DAG 不含 extract（或同时含两个 ASR 阶段），`retry` 会被新校验拒绝：接口返回 409 + 原因，需按新 DAG 重新入队；不做静默降级。
- API 只增不改：新增 `/jobs/{id}/retry`、`/jobs/{id}/cancel`、`/healthz`、`/readyz`、`/metrics`；`/jobs/by-path` 由 404 变为 200（修复）。
- 配置只增不改名；`parallel` 默认值变化属于行为变更，写入 release note。
- 数据库：自动迁移，启动即执行；迁移失败则拒绝启动（fail-fast）。

---

## 7. 测试计划与验收标准

### 7.1 单元测试（不依赖模型/ffmpeg/网络）

| 模块 | 用例 |
|---|---|
| 生命周期 A | 租约过期被回收且 attempt+1；心跳只续自己的租约；fencing 下旧 worker 写回被拒；失败级联置 blocked；恢复超预算转 failed；drain 在无在途时 can_exit；有僵尸 claimed 时仍能退出 |
| API B | by-path 200；5 种非法 DAG 各返回明确错误；3 种合法 DAG 通过；retry/cancel 状态机 |
| 翻译 C | 时间窗+条目+字符三重切分；并发上限不超过 2；检查点写入/读取/源变更失效；部分 id 降级保留原文；原子写在异常时不留半成品；4xx 不重试 |
| extract/wav E | enqueue 生成 `io` 路径；stt 读取 wav；wav 缺失失败 |
| 模型 D | 相同 key 只加载一次；LRU 逐出；信号量限流 |
| SQLite F | WAL 生效；迁移幂等；迁移失败拒绝启动 |
| 安全 H | 占位 token 拒绝启动；路径白名单越界 400；docs 关闭时 404；token 常量时间比较（行为测试） |
| 观测 G | task_started 使用 effective_config；/healthz、/readyz、/metrics 返回 200 且含关键指标 |

### 7.2 集成/E2E

- fake executor 集成测试：起服务 → 提交 job → 模拟 extract/stt/translate 成功、失败、hang、进程重启 → 断言最终状态与日志。
- 真实媒体 E2E（手动/夜间任务）：2 小时样本跑完整链路，记录：
  - 各阶段墙钟、翻译批次数、请求数、token 消耗（若上游返回 usage）；
  - 显存峰值（`nvidia-smi` 采样）；
  - 中途 `kill -9` 后重启，验证只补未完成批次。
- 回归基线：改动前后同一视频的 ja.srt 文本差异率、zh.srt 行数一致性、时间戳末条不超过媒体时长。

### 7.3 每个批次的完成定义（DoD）

1. 代码 + 测试 + 文档 + `config.example.ini` 同步。
2. `pytest -q` 全绿；新增用例覆盖本次改动。
3. 无新增裸 `except`、无吞异常；日志含 task_id/job_id。
4. 不删除既有注释/docstring；新增函数必须有 docstring。
5. 在 PR/提交说明中写明行为变更与回滚方式。

---

## 8. 实施批次

> 顺序即依赖顺序；每批可独立合并、独立回滚。

### 批次 1：任务生命周期闭环（P0，2–3 天）

范围：A.1–A.7、F 的 WAL 部分、`blocked/cancelled` 状态、reaper、fencing、有界停机、retry/cancel API、恢复计数。
文件：`repo/job_repository.py`、`repo/database.py`、`service/runtime.py`、`service/bootstrap.py`、`core/config.py`、`api/routes/jobs.py`、`api/routes/admin.py`。
验收：
- `kill -9` worker 后，任务在 `lease_timeout_sec` 内被重新领取且 attempt 递增；
- 模拟 hang（不释放 claimed、不续租），drain 在 `drain_timeout_sec` 内退出；
- 上游 failed 后下游为 `blocked`，job 为 `failed`；
- 旧 attempt 的 succussed 写回被 fencing 拒绝；
- `/jobs/{id}/retry` 能把 failed job 拉回 queued 并重跑。

### 批次 2：API/DAG 正确性 + wav 契约（2 天）

范围：B.1–B.3、E、H 的路径与 token 部分。
文件：`api/routes/jobs.py`、`core/dag.py`、`repo/job_repository.py`、`service/runtime.py`、`executor/stt.py`、`executor/stt_whisperx.py`、`executor/extract.py`、`core/config.py`。
验收：
- by-path 返回 200；
- 5 类非法 DAG 入队即 400，错误码明确；
- ASR 实际读取 `audio/*.16k.wav`（日志/断点可证）；
- 产物目录符合 B.3；
- 占位 token 拒绝启动；路径白名单生效。

### 批次 3：模型缓存与资源上限（1–2 天）

范围：D。
文件：新增 `service/model_cache.py`；改 `executor/stt.py`、`stt_whisperx.py`、`service/runtime.py`、`core/config.py`。
验收：
- 同一模型 2 个 task 只冷启动一次（日志 hit/miss 可证）；
- 显存峰值不随 worker 数线性增长；
- `model_parallelism=1` 时同卡串行转写不失败。

### 批次 4：翻译链路（3–4 天）

范围：C.1–C.7。
文件：`executor/translate.py`、`executor/common.py`、新增 `executor/atomic.py`、`core/config.py`、`api/routes/jobs.py`（job_config 白名单补充新键）。
验收：
- 并发不超过 2（可用 fake post_func 统计并发峰值）；
- 中途 kill 重跑只补未完成批次（检查点文件可证）；
- 缺 id 时 zh.srt 保留原文并告警，不丢行；
- 4xx 不重试、5xx 重试且带 Idempotency-Key；
- zh.srt 写入原子（人为中断不留半成品）。

### 批次 5：可观测性（1–2 天）

范围：G。
文件：`service/bootstrap.py`、`api/app.py`、`api/routes/queue.py`、`service/runtime.py`、`pyproject.toml`（prometheus_client）。
验收：
- 应用 INFO 日志落盘；request_id 贯穿；
- /healthz /readyz /metrics 可用；
- task_started 快照等于 task 的 effective_config；
- /queue/summary throughput 非空。

### 批次 6：交付与文档（1–2 天）

范围：I。
验收：
- CI 在两个新提交上绿；
- 根 `pyproject.toml`/`uv.lock` 已跟踪；
- 子仓库有 `v0.4.0`、`v0.5.0` tag；版本号一致；
- 无密钥入库；`docs/hf-token.md` 已删除并轮换；
- 子仓库无空 `.venv`；真实媒体测试不再被 ignore；
- README/docs 与实现一致，roadmap 完成项打勾。

---

## 9. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 租约心跳频繁写库 | 写放大、busy | 心跳间隔 ≥10s；WAL；批量提交；观测 busy 次数 |
| 回收误伤长任务 | 双跑/覆盖 | 心跳 + fencing + 回收阈值 = 3 倍心跳；回收前二次校验 |
| 并发 2 仍可能触发上游限流 | 5xx 重试 | 保守 2；`request_interval` 可调；4xx 不重试 |
| 检查点文件与源不一致 | 错误复用 | source_sha256 校验；不一致全量重算 |
| 新产物布局影响旧脚本 | 脚本找不到文件 | jobs 表字段继续指向最终产物；文档给出新路径；旧 job 兼容 |
| WAL 在网络盘不可用 | 启动失败/损坏 | 启动探测，失败回退 DELETE 并告警 |
| 迁移失败 | 服务不可用 | 启动前备份 DB；迁移事务化；失败 fail-fast 并打印版本 |
| 并发改动引入顺序错乱 | 字幕错位 | 按 batch 序号聚合后再写；单测断言顺序 |

回滚：每批次独立提交，配置向后兼容；回滚只需回退该批次代码并保留旧配置键。

---

## 10. 非目标（明确不做）

- 不把 SQLite 换成 Postgres/Redis；
- 不做 Web 控制台、MCP、Agent Skill；
- 不做多用户权限/配额；
- 不做说话人分离（VAD diarization 调研另立项目）；
- 不追求“全局限流器/令牌桶”（D2）；
- 不重构 `job_repository.py` 的分层（只做必要修改）。

---

## 11. 交付清单（新会话直接照此执行）

- [ ] 批次 1：生命周期闭环 + WAL + retry/cancel
- [ ] 批次 2：by-path 修复、DAG 语义、wav 契约、路径/token 安全
- [ ] 批次 3：模型缓存 + 并发上限
- [ ] 批次 4：翻译受限并发、配置生效、检查点、原子写、部分 id、幂等键
- [ ] 批次 5：logging、health、metrics、日志快照修正
- [ ] 批次 6：CI、tag、锁文件、密钥清理、文档同步、roadmap 打勾
- [ ] 交付前：真实 2h 样本跑通，记录前后耗时/请求数/显存
- [ ] 交付前：确认 `parallel=2` 已写入本机 `config.ini` 与 `config.example.ini`

---

## 附：关键文件索引

- 仓储/状态机：`whisper_stt_service/repo/job_repository.py`、`repo/database.py`
- 运行时：`whisper_stt_service/service/runtime.py`、`service/bootstrap.py`
- API：`whisper_stt_service/api/app.py`、`api/routes/*.py`
- DAG/配置：`whisper_stt_service/core/dag.py`、`core/config.py`
- 执行器：`whisper_stt_service/executor/*.py`
- 测试：`tests/unit/*`、`tests/e2e/*`
- 配置模板：`whisper-stt/config.example.ini`
- 文档：`docs/01`–`docs/04`、`docs/superpowers/specs/`

# Whisper STT Pipeline Service 调整说明（2026-03-30）

范围：基于 `2026-03-29-whisper-stt-pipeline-service-design.md` 的本轮落地修正，记录“去骨架化”实现与运行规避项。

## 1. 本轮结论

1. 服务已从 API/worker 骨架推进为真实链路实现：`POST /jobs` 真入队，`GET /jobs/{job_id}` 与 `GET /jobs/{job_id}/progress` 返回真实 job/task 状态。
2. E2E 的 502 根因不是视频路径，而是本机代理环境变量劫持 localhost 请求；已在 E2E 驱动中显式关闭 requests 环境代理读取。
3. 之前 STT 阶段失败的根因是模型目录相对路径在工作目录下不可达；已将模型目录纳入 `config.ini`，支持绝对路径配置。

## 2. 规格修正点

### 2.1 配置项补充（新增）

在 `[runtime]` 下新增：

- `model_path`：faster-whisper 模型目录，支持绝对路径。

说明：

- 服务默认读取 `config.ini` 中的 `runtime.model_path`。
- 若存在 `WHISPER_STT_MODEL` 环境变量，则作为更高优先级覆盖。

### 2.2 API 行为（从骨架改为真实）

- `POST /jobs`：执行真实入队（含同路径幂等/拒绝规则），返回真实 `job_id/accepted/queue_ahead/message`。
- `GET /jobs/{job_id}`：返回 job 元信息 + 三阶段 task 状态、重试、时间戳、错误字段。
- `GET /jobs/{job_id}/progress`：在 DB 任务状态基础上，按 task 拼接内存进度快照（若存在）。
- `GET /jobs`、`GET /tasks`：支持筛选 + 分页。
- `GET /queue/summary`：返回阶段状态计数、活动 worker 视图。

### 2.3 worker/恢复行为（从骨架改为真实）

- 启动先执行 `claimed -> queued` 恢复。
- 三阶段 worker 执行真实 `extract/stt/translate`，并写入进度事件。
- 失败按 `attempt/max_retries` 回退或最终失败。
- 停机执行回收，确保在途 `claimed` 可恢复。

### 2.4 E2E 代理规避（运行约束）

- E2E 驱动中 `requests.Session().trust_env = False`，避免读取 `HTTP_PROXY/HTTPS_PROXY`。
- 命令行执行仍建议显式清空代理变量，防止子进程/第三方库误用代理。

## 3. 与原设计保持一致项

- SQLite 作为唯一持久化队列与状态存储。
- 三阶段依赖链：`extract -> stt -> translate`。
- 进度百分比仅内存存储（TTL 清理）。
- 路径校验、参数化 SQL、阶段重试与聚合 job 状态规则。

## 4. 本轮建议运行基线

`config.ini` 中至少保证：

- `[runtime].db_path` 指向工作目录下可写路径（建议 `./tmp/whisper_stt_service.db`）。
- `[runtime].log_root` 指向可写目录（建议 `./tmp/logs`）。
- `[runtime].model_path` 使用绝对路径，避免工作目录差异导致模型找不到。

# Whisper STT 流水线服务设计

日期：2026-03-29  
范围：`whisper-stt` 子项目服务化改造

## 1. 目标

将当前 CLI 流程改造为 Python HTTP 服务，能力如下：

1. 接收 `video_path` 与 STT 源语言 `language`。
2. 入队前校验视频文件存在。
3. 每个视频创建 3 段流水线任务：
   - `extract`（ffmpeg 视频转 wav）
   - `stt`（wav/视频转源语言字幕）
   - `translate`（源语言字幕翻译为简中字幕，沿用现有 16 并发翻译能力）
4. 最终字幕固定写回视频同目录。
5. 以 SQLite 作为唯一持久化队列与状态存储。
6. 三阶段各自可配置多 worker 线程并行，形成流水线并发。

## 2. 已确认约束

- `language` 仅表示 STT 源语言。
- 翻译目标固定为简体中文。
- 输出目录固定为视频所在目录。
- 同路径重复提交规则：
  - 若该路径已有任务已开始（任一阶段进入执行）：拒绝新建。
  - 若该路径已有一组 3 任务且都在排队：幂等返回现有 `job_id`。
  - 若该路径最近一组 3 任务均已结束：允许新建。
- 细粒度百分比进度不落库，仅保存在内存。
- 已完成任务的内存进度最多保留 1 小时，之后清理。
- 服务重启后必须可恢复并继续处理数据库中的任务。

## 3. 总体架构

组件：

1. HTTP API 服务（建议 FastAPI）。
2. SQLite 仓储层（`jobs`、`tasks`）。
3. 三类 worker 池：
   - `extract` worker
   - `stt` worker
   - `translate` worker
4. 调度巡检线程（默认每 180 秒）用于唤醒空闲 worker 拉取任务。
5. 内存 `ProgressStore` 与异步 `progress_queue` 消费线程。
6. 按任务独立目录写结构化日志。

主流程：

1. API 收到入队请求。
2. 事务内执行幂等/拒绝判定。
3. 成功入队时一次性写入 1 条 job + 3 条 tasks（带依赖链）。
4. 各阶段 worker 从 SQLite 原子领取可执行任务。
5. 前置阶段完成后解锁后置阶段。
6. 进度仅写入内存通道。
7. 最终状态持久化到 DB。

## 4. 数据模型

### 4.1 `jobs` 表（视频级主记录）

- `job_id` TEXT PRIMARY KEY
- `video_path` TEXT NOT NULL
- `source_language` TEXT NOT NULL
- `status` TEXT NOT NULL  -- `queued|running|succeeded|failed`
- `output_ja_path` TEXT NOT NULL
- `output_zh_path` TEXT NOT NULL
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL
- `finished_at` TEXT NULL
- 索引：
  - `(video_path, created_at DESC)`
  - `(status, created_at DESC)`

### 4.2 `tasks` 表（单表承载三阶段队列）

- `task_id` TEXT PRIMARY KEY
- `job_id` TEXT NOT NULL REFERENCES jobs(job_id)
- `stage` TEXT NOT NULL  -- `extract|stt|translate`
- `status` TEXT NOT NULL -- `queued|claimed|succeeded|failed`
- `depends_on_task_id` TEXT NULL REFERENCES tasks(task_id)
- `attempt` INTEGER NOT NULL DEFAULT 0
- `max_retries` INTEGER NOT NULL
- `timeout_sec` INTEGER NOT NULL
- `lease_owner` TEXT NULL
- `lease_expires_at` TEXT NULL
- `claimed_at` TEXT NULL
- `started_at` TEXT NULL
- `finished_at` TEXT NULL
- `last_error` TEXT NULL
- `log_dir` TEXT NOT NULL
- `log_file` TEXT NOT NULL
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL
- 索引：
  - `(stage, status, created_at)`
  - `(job_id, stage)`
  - `(status, lease_expires_at)`

## 5. 任务依赖关系

每个 job 在同一事务中创建 3 条任务：

1. `extract`（无依赖）
2. `stt` 依赖 `extract.task_id`
3. `translate` 依赖 `stt.task_id`

领取条件：

- 任务必须是 `status='queued'`。
- 若存在 `depends_on_task_id`，其依赖任务必须是 `status='succeeded'`。

## 6. SQLite 领取加锁与并发安全

领取流程必须原子化：

1. `BEGIN IMMEDIATE`。
2. 按 FIFO（`created_at`，再 `task_id`）查询当前阶段可领取任务。
3. 原子更新该任务为 `claimed`，并写入 `lease_owner`、`lease_expires_at`、`claimed_at`、`started_at`、`updated_at`。
4. `COMMIT`。

若更新影响行数为 0，表示被并发 worker 抢占，当前 worker 立即重试。

## 7. 重启与停机恢复（双保险）

### 7.1 服务启动恢复

在启动 worker 前，先做恢复事务：

- 将全部 `claimed` 任务回退为 `queued`。
- 清空 `lease_owner` 与 `lease_expires_at`。
- 记录恢复数量日志。

原因：进程已重启，旧 `claimed` 不可能仍在运行。

### 7.2 优雅停机

1. 停止接收新领取。
2. 通知 worker 中断当前任务并执行回滚清理。
3. 将当前 `claimed` 任务回写为 `queued`。
4. 刷新进度队列后退出。

### 7.3 阶段回滚与开工前清理

- `extract`：删除残留或已存在的目标 wav 后重做。
- `stt`：删除残留或已存在的源语言 srt 后重做。
- `translate`：删除残留或已存在的 zh srt 及翻译进度副产物后重做。

worker 每次开工前都执行目标文件存在检查并清理，保证可重复恢复。

## 8. 进度模型（仅内存）

不在 SQLite 持久化百分比进度。

### 8.1 内存结构

- `ProgressStore`：按 `task_id` 保存最新百分比、描述、worker_id、更新时间。
- 已完成进度保留区：完成后保留至 `progress_ttl_sec`（默认 3600）。
- 清理线程定期删除过期项。

### 8.2 事件通道

- worker 把进度事件写入有界 `progress_queue`。
- 消费线程更新 `ProgressStore`。
- 队列满时按 task 合并为“最新事件”，不阻塞执行线程。

## 9. API 设计

### 9.1 `POST /jobs`

请求：

- `video_path`（绝对路径）
- `language`（STT 源语言）

行为：

1. 校验 `video_path` 存在且是普通文件。
2. 按同路径规则执行拒绝/幂等/新建。

返回字段：

- `job_id`
- `accepted`（是否新建）
- `queue_ahead`（该次入队时前方 job 数）
- `message`（`created|idempotent_returned|rejected_started`）

### 9.2 `GET /jobs/{job_id}`

返回：

- job 元信息与状态
- 3 个 task 的状态、重试、时间戳、错误信息

### 9.3 `GET /jobs/{job_id}/progress`

单次返回：

- 该 job 关联 task 状态（DB）
- 若内存有该 task 进度，则附带进度快照

不做 `unavailable/expired` 推断；没有内存进度则不返回进度字段。

### 9.4 `GET /jobs/by-path?video_path=...`

- 默认仅返回该路径最新 1 条 job。

### 9.5 `GET /jobs`

支持筛选与分页：

- 筛选：`status`、`video_path_like`、`created_from`、`created_to`、`language`、`has_failed_tasks`
- 分页：`page`、`page_size`（默认 20，最大 200）
- 排序：`sort_by=created_at|updated_at`，`order=asc|desc`

### 9.6 `GET /tasks`

运维查询接口（筛选+分页）：

- 筛选：`stage`、`status`、`job_id`、`lease_owner`、`updated_from`、`updated_to`

### 9.7 `GET /queue/summary`

返回队列摘要：

- 各阶段状态计数（`queued|claimed|succeeded|failed`）
- worker 配置与活动 worker 视图
- 最近吞吐快照

## 10. 日志与产物目录

- 每个 task 使用独立日志目录与日志文件。
- 目录规范：`{log_root}/{job_id}/{stage}/{task_id}/task.log`
- 日志记录：领取、启动、关键进度、完成、失败、重试、恢复动作。

## 11. 配置项（`config.ini`）

保留现有 `[llm]`、`[translation]`，新增：

### `[workers]`

- `extract_workers`
- `stt_workers`
- `translate_workers`
- `scheduler_interval_sec`（默认 180）
- `poll_interval_sec`（默认 1-2）

### `[timeouts]`

- `extract_timeout_sec`
- `stt_timeout_sec`
- `translate_timeout_sec`
- `lease_timeout_sec`

### `[retry]`

- `extract_max_retries`
- `stt_max_retries`
- `translate_max_retries`

### `[runtime]`

- `db_path`
- `progress_ttl_sec`（默认 3600）
- `log_root`

## 12. 失败与重试策略

- 阶段任务失败后 `attempt + 1`。
- 若 `attempt <= max_retries`，回到 `queued`。
- 超过重试上限则置 `failed`。
- 下游任务保持 `queued` 但因依赖失败而不可领取。
- job 状态由三阶段聚合得到：
  - 任一阶段最终 `failed`：`job.failed`
  - 三阶段全 `succeeded`：`job.succeeded`
  - 其他情况：`job.queued` 或 `job.running`

## 13. 安全与校验

- 要求 `video_path` 为绝对路径。
- 入队前校验路径存在且为普通文件。
- SQL 全部参数化。
- 日志与命令调用时做路径安全处理。

## 14. 测试策略

1. 单元测试：
   - 幂等判定矩阵
   - 依赖可领取判定
   - 进度内存 TTL 清理
   - 三类 worker 独立运行测试（`extract` / `stt` / `translate`）
   - 强制删除后重做逻辑测试（目标文件已存在时先删再执行）
2. 并发测试：
   - 多 worker 同阶段领取无重复
3. 恢复测试：
   - 启动时 `claimed -> queued`
   - 优雅停机回滚与状态回写
4. API 测试：
   - 入队/拒绝/幂等返回
   - 筛选分页契约
5. 端到端 E2E 真实链路测试：
   - 在测试目录保留一个路径文件（例如 `whisper-stt/tests/e2e/video_paths.txt`），由你每次写入 3 个真实视频绝对路径。
   - 测试脚本使用真实方式启动服务进程。
   - 启动后由注入脚本读取 `video_paths.txt`，逐条调用真实 API `POST /jobs` 入队。
   - 另启一个轮询脚本，周期性调用 `GET /jobs/{job_id}/progress`（以及必要的 `GET /jobs/{job_id}`）观察状态。
   - 轮询终止条件：
     - 全部任务完成（成功或失败）即停止；或
     - 达到 30 分钟上限自动停止并输出当时状态快照。
   - 该 E2E 测试必须完整覆盖：服务启动、入队、worker 消费、阶段推进、最终完成。
   - 该测试场景按真实运行行为设计，支持你每次替换不同视频路径重复验证。

### 14.1 E2E 执行产物

- 生成 E2E 过程日志（服务日志、注入脚本日志、轮询日志）。
- 保存最终汇总报告：每个 `job_id` 的最终状态、耗时、失败原因（若有）。
- 失败时保留最近一次 progress 快照，便于定位卡点。

### 14.2 测试素材与目录约定

- 可直接复用 `whisper-stt/output` 下现有两个示例视频文件作为测试输入。
- 同目录下杂乱文件用于验证“存在目标文件时强制删除后重做”逻辑。
- E2E 与单元测试脚本应明确区分测试产物目录，避免污染业务输出目录。

## 16. 业务日志要求

所有关键业务动作必须有可检索日志（控制台与任务日志文件至少其一，建议两者都有）：

- 任务领取与状态变更（`queued -> claimed -> succeeded/failed`）。
- 幂等返回与拒绝入队判定结果。
- 启动恢复（`claimed -> queued`）与优雅停机回滚。
- 文件删除后重做动作（含删除目标、原因、执行结果）。
- 依赖阻塞、重试、超时、失败原因。

日志字段至少包含：`job_id`、`task_id`、`stage`、`worker_id`、`event`、`result`、`timestamp`。

## 17. 本次不做

- Redis 或分布式队列
- 多实例 active-active 竞争调度
- 细粒度进度持久化历史

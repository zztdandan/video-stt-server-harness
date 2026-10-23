# 批次 1 执行记录：任务生命周期闭环 + WAL

- **日期**：2026-10-22
- **SPEC**：`docs/superpowers/specs/2026-10-22-whisper-stt-reliability-and-translation-hardening-spec.md`（批次 1）
- **工作树**：`/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening`
- **范围**：A.1–A.7、F 的 WAL 部分、`blocked/cancelled` 状态、reaper、fencing、有界停机、retry/cancel API、恢复计数

## 1. 完成项

| 编号 | 内容 | 落地位置 |
|---|---|---|
| A.1 | 租约心跳：带外守护线程按 `max(lease/3, 10s)` 续租；续租 SQL 带 `status/lease_owner/attempt` fencing；失败即标记租约丢失 | `service/runtime.py` `FencedLease`、`repo.heartbeat_task` |
| A.1 | 协作式取消：`cancel_check()` 只读本地事件 + 1s 节流 DB 时间片校验（发现被回收/接管） | `WorkerRuntime._make_cancel_check` |
| A.2 | 过期回收 reaper：每 `lease/3`（下限 1s）扫描；attempt+1 回 queued，超预算 failed(`lease_expired_retry_exhausted`) + 级联；写 `lease_reclaimed` 事件 | `repo.reclaim_expired_leases`、`runtime._reaper_loop` |
| A.3 | 写回 fencing：`mark_task_succeeded/failed(worker_id=, attempt=)`；命中 0 行返回拒绝，不改状态、不刷新 job，运行时记 `fenced_stale_result` | `repo/job_repository.py`、`runtime._record_fenced_stale` |
| A.4 | 失败级联：进入 failed 时同事务把直接/间接下游 queued 置 `blocked`（`upstream_failed:<task_id>`）；job 聚合含 blocked→failed；`queue_summary` 出现 blocked 计数 | `_cascade_blocked`、`_refresh_job_status` |
| A.5 | 启动恢复计数：`recovery_counts_as_attempt`（默认 true）；返回 `{recovered, failed}` 并写启动日志 | `repo.recover_claimed_to_queued`、`runtime.start/startup_stats` |
| A.6 | 有界停机：`can_exit` 仅看“drain 且本进程无在途”或超时；`drain_timeout_sec` 超时强制回滚本进程 claimed；`exit_callback` 注入（bootstrap→`server.should_exit`，未绑定回退 SIGTERM） | `runtime.shutdown_status/_shutdown_watch_loop/_force_drain_timeout`、`bootstrap.py`、`main.py` |
| A.6 | `GET /admin/shutdown/status` 增加 `drain_deadline_at`、`drain_remaining_sec`、`drain_timed_out`、`inflight`、`blocked` | `runtime.shutdown_status` |
| A.7 | `POST /jobs/{id}/retry`（仅 failed；重置 failed/blocked→queued、attempt=0、清 last_error；历史非法 DAG → 409） | `repo.retry_job`、`api/routes/jobs.py` |
| A.7 | `POST /jobs/{id}/cancel`（仅全 queued；任务→cancelled、job 终态化并释放路径占用；BEGIN IMMEDIATE 内判定防 claim 竞态） | `repo.cancel_job`、`api/routes/jobs.py` |
| B.1 | `/jobs/by-path` 移到 `/jobs/{job_id}` 之前（404→200） | `api/routes/jobs.py` |
| F | SQLite WAL 探测（非本地盘回退 DELETE）、`busy_timeout`、`synchronous`、`schema_migrations` + 迁移 002 索引、`EXPLAIN QUERY PLAN` 启动记录 | `repo/database.py`（已移交数据库 owner） |
| 配置 | `[timeouts] drain_timeout_sec`、`[runtime] recovery_counts_as_attempt`、`[runtime] sqlite_wal_enabled`，均带默认值向后兼容 | `core/config.py`、`config.example.ini` |

## 2. 行为变更

1. `mark_task_succeeded/mark_task_failed` 现在要求任务仍处于 `claimed`（fenced 时还要求 owner/attempt 匹配）；对已回收/已终态任务写回返回 False / `"fenced_stale_result"`。
2. `can_exit` 不再受全局 `claimed_count` 阻塞（仅告警），僵尸 claimed 不会让 drain 永久挂住。
3. jobs.status 取值不变（queued/running/succeeded/failed）；任务新增 `blocked`、`cancelled`。
4. 心跳默认不小于 10s；租约极短（< 30s）时心跳间隔与 reaper 间隔一致，存在轻微回收误伤风险，建议 `lease_timeout_sec` ≥ 600。

## 3. 验证命令与结果

```bash
cd /home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening
/home/base/repo/video-stt-whisper-server/.venv/bin/python -m pytest -q
# 309 passed, 3 deselected
/home/base/repo/video-stt-whisper-server/.venv/bin/python -m ruff check whisper_stt_service/ tests/
# All checks passed!
```

新增/更新测试：

- `tests/unit/test_task_lifecycle_lease.py`：回收 attempt+1 与事件、超预算 failed+级联、心跳只续自己、fenced 成功/失败拒绝、级联 blocked、恢复计数/调试模式、retry 状态机、历史非法 DAG 409、cancel 与路径释放。
- `tests/unit/test_runtime_lease_and_drain.py`：心跳间隔派生、长阻塞执行期间心跳保活、回收后 cancel_check=True、他人接管时间片检查、执行器异常级联、fenced 陈旧写回日志、停机状态字段、drain 超时强制回滚 + 退出回调、退出回调失败回退 SIGTERM、启动恢复统计。
- `tests/unit/test_api_job_control.py`：by-path 200、retry/cancel 状态机与 404/409、历史非法 DAG 409。
- 更新：`test_runtime_shutdown_status.py`（can_exit 语义）、`test_repository_dependency_payload.py`（DAG 语义 + 先领取再写回）。

## 4. 未完成 / 交接项

1. **产物路径与 IO**：runtime 仍用 `ctx.video_path` 推导 extract 输出 wav、ASR 输入读取 `ctx.task_config["io"]["input_path"]`（缺失回退视频）。B.3 需要
   `extract→audio/<stem>.16k.wav`、ASR→`asr/<stem>.ja.srt`、translate→`translate/<stem>.zh.srt` 的完整 io 契约。
2. **翻译检查点 TTL 清理**：`progress_ttl_sec` 的 checkpoint 清理留给运行时后续批次。
3. **运行中取消**：`cancel` 目前仅覆盖未开始 job；运行中取消（走 `FencedLease.request_abort`）本轮不做。
4. **多实例**：startup recovery 仍会把其他实例的 claimed 一并回退（沿用旧行为）；`status.last_error` 记录为 `recovered_after_restart`。
5. **配置整合**：`sqlite_wal_enabled` 已由 bootstrap 传入 `Database`；安全/模型/翻译/观测配置由后续批次整合。
6. `[workers] poll_interval_sec` 为整数秒，drain 期间 worker 空转等待 1s，未做细化。

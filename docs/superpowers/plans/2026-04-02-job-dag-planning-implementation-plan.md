# Job DAG Planning & Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持现有 `POST /jobs` 调用兼容的前提下，把内部 job 创建切到 DAG 规划模型，支持 job 级 stage 配置覆盖、task 配置快照、归档接口，以及基于现有真实数据集的 5 分钟 E2E 验证。

**Architecture:** 在 `api -> repository -> db` 链路中引入 DAG 归一化和校验层，入队时先生成 `dag_json/job_config_json/task_config_json`，再落库并回填依赖 task id。调度仍复用现有 worker + `claim_next(stage)` 模型，仅扩展“可领取”判定为“所有依赖均成功”。归档通过单事务完成主表到归档表迁移，并释放同路径活跃占用。

**Tech Stack:** Python 3.10+, FastAPI, SQLite, pytest, requests, uvicorn, 现有 `tests/e2e/video_paths.txt` 真实数据集。

---

### Task 1: Worktree 准备与本地测试资产复制

**Files:**
- Modify: `.worktrees/`（主仓根目录下作为容器，仅存放 child repo worktree）
- Copy (gitignored): `whisper-stt/config.ini` -> `.worktrees/<branch>/config.ini`
- Copy (gitignored): `whisper-stt/tests/e2e/video_paths.txt` -> `.worktrees/<branch>/tests/e2e/video_paths.txt`

- [ ] **Step 1: 为 child repo 创建独立 worktree**

```bash
git -C whisper-stt worktree add /home/base/repo/video-stt-whisper-server/.worktrees/whisper-stt-job-dag -b feat/job-dag-planning
```

Expected: 输出 `Preparing worktree` 且新目录可见。

- [ ] **Step 2: 复制 `config.ini` 到新 worktree（因被 gitignore 忽略）**

```bash
cp /home/base/repo/video-stt-whisper-server/whisper-stt/config.ini /home/base/repo/video-stt-whisper-server/.worktrees/whisper-stt-job-dag/config.ini
```

Expected: 新 worktree 下存在 `config.ini`，且不进入 git 追踪。

- [ ] **Step 3: 复制 E2E 数据集 `video_paths.txt` 到新 worktree（因被 gitignore 忽略）**

```bash
cp /home/base/repo/video-stt-whisper-server/whisper-stt/tests/e2e/video_paths.txt /home/base/repo/video-stt-whisper-server/.worktrees/whisper-stt-job-dag/tests/e2e/video_paths.txt
```

Expected: 新 worktree 下 `tests/e2e/video_paths.txt` 存在，内容为当前 9 条真实视频路径。

- [ ] **Step 4: 验证忽略规则仍生效**

```bash
git -C /home/base/repo/video-stt-whisper-server/.worktrees/whisper-stt-job-dag status --short
```

Expected: `config.ini` 与 `tests/e2e/video_paths.txt` 不出现在 `git status`。

- [ ] **Step 5: 提交初始化（仅脚手架/文档变更时）**

```bash
git add .
git commit -m "chore: prepare isolated worktree runtime assets"
```

Expected: commit 仅包含可追踪文件，不包含 gitignored 资产。

### Task 2: Schema 增量迁移与归档表落地

**Files:**
- Modify: `whisper-stt/whisper_stt_service/db.py`
- Test: `whisper-stt/tests/unit/test_repository_enqueue.py`
- Create: `whisper-stt/tests/unit/test_db_schema_migration.py`

- [ ] **Step 1: 先写失败测试，锁定新列与归档表要求**

```python
def test_init_schema_adds_dag_and_archive_tables(tmp_path: Path) -> None:
    db = Database(tmp_path / "q.db")
    db.init_schema()
    with db.connect() as conn:
        jobs_cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
        tasks_cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
        archive_tables = {
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "dag_json" in jobs_cols
    assert "job_config_json" in jobs_cols
    assert "task_config_json" in tasks_cols
    assert "jobs_archive" in archive_tables
    assert "tasks_archive" in archive_tables
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q whisper-stt/tests/unit/test_db_schema_migration.py`
Expected: FAIL，提示缺少新增列/归档表。

- [ ] **Step 3: 在 `db.py` 实现增量 schema 演进**

```python
def _ensure_column(conn: sqlite3.Connection, table: str, column_sql: str, column_name: str) -> None:
    existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column_name not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_sql}")

# init_schema 中新增：
_ensure_column(conn, "jobs", "dag_json TEXT", "dag_json")
_ensure_column(conn, "jobs", "job_config_json TEXT", "job_config_json")
_ensure_column(conn, "tasks", "task_config_json TEXT", "task_config_json")

conn.executescript("""
CREATE TABLE IF NOT EXISTS jobs_archive (
    job_id TEXT PRIMARY KEY,
    video_path TEXT NOT NULL,
    source_language TEXT NOT NULL,
    status TEXT NOT NULL,
    output_ja_path TEXT NOT NULL,
    output_zh_path TEXT NOT NULL,
    dag_json TEXT,
    job_config_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    archived_at TEXT NOT NULL,
    archive_reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks_archive (
    task_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    depends_on_task_id TEXT,
    task_config_json TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL,
    timeout_sec INTEGER NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    claimed_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    last_error TEXT,
    log_dir TEXT NOT NULL,
    log_file TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT NOT NULL,
    archive_reason TEXT NOT NULL
);
""")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest -q whisper-stt/tests/unit/test_db_schema_migration.py`
Expected: PASS。

- [ ] **Step 5: 提交 schema 任务**

```bash
git add whisper_stt_service/db.py tests/unit/test_db_schema_migration.py
git commit -m "feat: add DAG columns and archive schema migration"
```

### Task 3: DAG 模型、stage 注册表与请求校验

**Files:**
- Create: `whisper-stt/whisper_stt_service/dag.py`
- Create: `whisper-stt/whisper_stt_service/stages.py`
- Modify: `whisper-stt/whisper_stt_service/api.py`
- Test: `whisper-stt/tests/unit/test_api_jobs.py`
- Create: `whisper-stt/tests/unit/test_dag_validation.py`

- [ ] **Step 1: 先写 DAG 校验失败测试（空 stages、重复、缺失依赖、环、未知 stage）**

```python
def test_validate_dag_rejects_cycle() -> None:
    dag = {
        "version": 1,
        "stages": [
            {"stage": "extract", "depends_on": ["translate"]},
            {"stage": "translate", "depends_on": ["extract"]},
        ],
    }
    with pytest.raises(ValueError, match="dag_cycle_detected"):
        normalize_and_validate_dag(dag)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q whisper-stt/tests/unit/test_dag_validation.py`
Expected: FAIL，目标函数尚不存在。

- [ ] **Step 3: 实现 stage 注册表与 DAG 归一化**

```python
# stages.py
SUPPORTED_STAGES = ("extract", "stt", "translate")

# dag.py
def build_default_dag() -> dict:
    return {
        "version": 1,
        "stages": [
            {"stage": "extract", "depends_on": []},
            {"stage": "stt", "depends_on": ["extract"]},
            {"stage": "translate", "depends_on": ["stt"]},
        ],
    }

def normalize_and_validate_dag(raw: dict | None) -> dict:
    # 完成默认补齐 + 唯一性 + 引用存在性 + 自依赖 + 环检测 + stage 支持性校验
```

- [ ] **Step 4: 扩展 API 请求结构与 400 错误返回**

```python
class CreateJobReq(BaseModel):
    video_path: str
    language: str
    dag: dict | None = None
    job_config: dict | None = None

@app.post("/jobs")
def create_job(req: CreateJobReq):
    try:
        result = repo_impl.enqueue(
            video_path=req.video_path,
            language=req.language,
            dag=req.dag,
            job_config=req.job_config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
```

- [ ] **Step 5: 跑单测确认 API + DAG 校验通过**

Run: `uv run pytest -q whisper-stt/tests/unit/test_dag_validation.py whisper-stt/tests/unit/test_api_jobs.py`
Expected: PASS。

- [ ] **Step 6: 提交校验层任务**

```bash
git add whisper_stt_service/stages.py whisper_stt_service/dag.py whisper_stt_service/api.py tests/unit/test_dag_validation.py tests/unit/test_api_jobs.py
git commit -m "feat: add DAG validation and create-job request extensions"
```

### Task 4: Repository 入队 DAG 化与 task 配置快照

**Files:**
- Modify: `whisper-stt/whisper_stt_service/repository.py`
- Modify: `whisper-stt/whisper_stt_service/config.py`
- Test: `whisper-stt/tests/unit/test_repository_enqueue.py`
- Create: `whisper-stt/tests/unit/test_repository_dag_enqueue.py`

- [ ] **Step 1: 先写失败测试，覆盖默认 DAG、显式 DAG、job_config、task_config 快照**

```python
def test_enqueue_persists_default_dag_and_task_config_snapshot(tmp_path: Path) -> None:
    db = Database(tmp_path / "q.db")
    db.init_schema()
    repo = JobRepository(db)
    created = repo.enqueue(video_path="/tmp/a.mp4", language="ja", dag=None, job_config=None)
    item = repo.get_job_detail(created.job_id)
    assert item is not None
    assert item["dag"]["stages"][0]["stage"] == "extract"
    assert item["tasks"][0]["task_config"]["stage"] == "extract"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q whisper-stt/tests/unit/test_repository_dag_enqueue.py`
Expected: FAIL。

- [ ] **Step 3: 改造 `enqueue()` 支持 DAG 节点展开与依赖回填**

```python
def enqueue(self, video_path: str, language: str, dag: dict | None = None, job_config: dict | None = None) -> EnqueueResult:
    normalized_dag = normalize_and_validate_dag(dag)
    normalized_job_config = normalize_and_validate_job_config(job_config, normalized_dag)
    # 先创建 job(dag_json/job_config_json)
    # 再按 stages 创建 tasks（暂存 stage->task_id）
    # 最后按 depends_on 回填 depends_on_task_id（单值或 JSON 数组字符串）
```

- [ ] **Step 4: 写入 task 级配置快照并提供兼容读取**

```python
effective = merge_stage_config(stage, defaults=self.stage_defaults, overrides=normalized_job_config.get(stage, {}))
task_config_json = json.dumps({"stage": stage, "effective_config": effective}, ensure_ascii=False)

def _parse_task_config(raw: str | None) -> dict:
    if not raw:
        return {"stage": "", "effective_config": {}}
    return json.loads(raw)
```

- [ ] **Step 5: 更新 `get_job_detail()` / `get_progress` 返回 `dag`、`job_config`、`task_config`**

Run: `uv run pytest -q whisper-stt/tests/unit/test_repository_dag_enqueue.py whisper-stt/tests/unit/test_api_jobs.py`
Expected: PASS。

- [ ] **Step 6: 提交入队 DAG 化任务**

```bash
git add whisper_stt_service/repository.py whisper_stt_service/config.py tests/unit/test_repository_enqueue.py tests/unit/test_repository_dag_enqueue.py tests/unit/test_api_jobs.py
git commit -m "feat: convert enqueue flow to DAG planning with task config snapshots"
```

### Task 5: 依赖兼容解析、多依赖领取与状态聚合修正

**Files:**
- Modify: `whisper-stt/whisper_stt_service/repository.py`
- Test: `whisper-stt/tests/unit/test_repository_claim.py`
- Create: `whisper-stt/tests/unit/test_repository_dependency_payload.py`

- [ ] **Step 1: 先写失败测试（单依赖、多依赖、非法载荷）**

```python
def test_claim_next_requires_all_dependencies_succeeded(tmp_path: Path) -> None:
    # 构造 join 节点依赖 [a, b]，仅 a 成功时不可领取；a+b 均成功后可领取
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q whisper-stt/tests/unit/test_repository_dependency_payload.py`
Expected: FAIL。

- [ ] **Step 3: 实现 `depends_on_task_id` 兼容解析与写入编码**

```python
def decode_dependency_payload(raw: str | None) -> list[str]:
    if raw is None or raw == "":
        return []
    text = raw.strip()
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("invalid_dependency_payload")
        return [str(x) for x in parsed if str(x).strip()]
    return [text]
```

- [ ] **Step 4: 调整 `claim_next` 可领取判定为“全部依赖 succeeded”**

```python
# 领取候选后，逐条 decode depends_on_task_id 并查询依赖 task 状态
# 任一依赖非 succeeded 则跳过，继续找下一个 queued task
```

- [ ] **Step 5: 覆盖状态聚合不再依赖固定三阶段数量**

Run: `uv run pytest -q whisper-stt/tests/unit/test_repository_claim.py whisper-stt/tests/unit/test_repository_dependency_payload.py`
Expected: PASS。

- [ ] **Step 6: 提交依赖与调度任务**

```bash
git add whisper_stt_service/repository.py tests/unit/test_repository_claim.py tests/unit/test_repository_dependency_payload.py
git commit -m "feat: support multi-dependency scheduling and payload compatibility"
```

### Task 6: 归档接口与同路径复用语义

**Files:**
- Modify: `whisper-stt/whisper_stt_service/repository.py`
- Modify: `whisper-stt/whisper_stt_service/api.py`
- Create: `whisper-stt/tests/unit/test_repository_archive.py`
- Create: `whisper-stt/tests/unit/test_api_archive.py`

- [ ] **Step 1: 先写失败测试（可归档/不可归档/归档后可重新提交）**

```python
def test_archive_moves_job_and_tasks_and_releases_video_path(tmp_path: Path) -> None:
    # 创建 job -> 归档 -> 校验主表删除、归档表存在、同路径可重新 enqueue
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q whisper-stt/tests/unit/test_repository_archive.py whisper-stt/tests/unit/test_api_archive.py`
Expected: FAIL。

- [ ] **Step 3: 在 repository 中实现事务化归档**

```python
def archive_job(self, job_id: str, reason: str) -> dict:
    # 校验归档前置状态
    # INSERT INTO jobs_archive(job_id, video_path, source_language, status, output_ja_path, output_zh_path, dag_json, job_config_json, created_at, updated_at, finished_at, archived_at, archive_reason)
    # SELECT job_id, video_path, source_language, status, output_ja_path, output_zh_path, dag_json, job_config_json, created_at, updated_at, finished_at, ?, ? FROM jobs WHERE job_id=?
    # INSERT INTO tasks_archive(task_id, job_id, stage, status, depends_on_task_id, task_config_json, attempt, max_retries, timeout_sec, lease_owner, lease_expires_at, claimed_at, started_at, finished_at, last_error, log_dir, log_file, created_at, updated_at, archived_at, archive_reason)
    # SELECT task_id, job_id, stage, status, depends_on_task_id, task_config_json, attempt, max_retries, timeout_sec, lease_owner, lease_expires_at, claimed_at, started_at, finished_at, last_error, log_dir, log_file, created_at, updated_at, ?, ? FROM tasks WHERE job_id=?
    # DELETE FROM tasks WHERE job_id=?
    # DELETE FROM jobs WHERE job_id=?
```

- [ ] **Step 4: 新增 `POST /jobs/{job_id}/archive` 并返回归档结果**

```python
class ArchiveJobReq(BaseModel):
    reason: str = "manual_archive"

@app.post("/jobs/{job_id}/archive")
def archive_job(job_id: str, req: ArchiveJobReq):
    return repo_impl.archive_job(job_id=job_id, reason=req.reason)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest -q whisper-stt/tests/unit/test_repository_archive.py whisper-stt/tests/unit/test_api_archive.py`
Expected: PASS。

- [ ] **Step 6: 提交归档任务**

```bash
git add whisper_stt_service/repository.py whisper_stt_service/api.py tests/unit/test_repository_archive.py tests/unit/test_api_archive.py
git commit -m "feat: add transactional job archive API"
```

### Task 7: E2E 显式 DAG 脚本与 5 分钟无错日志验收

**Files:**
- Create: `whisper-stt/tests/e2e/run_e2e_explicit_dag_flow.py`
- Create: `whisper-stt/tests/e2e/verify_e2e_logs.py`
- Modify: `whisper-stt/tests/unit/test_e2e_driver.py`
- Use existing dataset: `whisper-stt/tests/e2e/video_paths.txt`（复制到 worktree 后直接使用）

- [ ] **Step 1: 先写失败测试，锁定新 E2E 脚本的输入与最短监控时长参数**

```python
from tests.e2e.run_e2e_explicit_dag_flow import load_video_paths, parse_args

def test_explicit_e2e_args_defaults() -> None:
    args = parse_args([])
    assert args.min_monitor_sec == 300
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -q whisper-stt/tests/unit/test_e2e_driver.py`
Expected: FAIL。

- [ ] **Step 3: 实现显式 DAG E2E 脚本（使用当前数据集）**

```python
payload = {
    "video_path": video,
    "language": "ja",
    "dag": {
        "version": 1,
        "stages": [
            {"stage": "extract", "depends_on": []},
            {"stage": "stt", "depends_on": ["extract"]},
            {"stage": "translate", "depends_on": ["stt"]},
        ],
    },
    "job_config": {
        "stt": {"beam_size": 3, "best_of": 3},
        "translate": {"chunk_minutes": 20, "retry": 8},
    },
}

# 至少监控 300 秒；即使任务提前完成也继续轮询并输出监控日志
```

- [ ] **Step 4: 实现日志验收脚本，校验 3 类日志均无错误**

```python
def assert_no_error_keywords(path: Path, *, forbidden: Sequence[str]) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    for word in forbidden:
        if word in text:
            raise AssertionError(f"found forbidden keyword '{word}' in {path}")

# 校验对象：
# 1) task logs: tmp/logs/**/task.log
# 2) monitor log: tmp/e2e/explicit_dag_monitor.log
# 3) server log: tmp/e2e/explicit_dag_server.log
```

- [ ] **Step 5: 执行 E2E（5 分钟）并跑日志校验**

Run: `uv run python whisper-stt/tests/e2e/run_e2e_explicit_dag_flow.py --min-monitor-sec 300 --monitor-log tmp/e2e/explicit_dag_monitor.log --server-log tmp/e2e/explicit_dag_server.log`

Expected: 运行时长 `>= 300` 秒，全部 job 最终 `succeeded`。

Run: `uv run python whisper-stt/tests/e2e/verify_e2e_logs.py --task-log-root tmp/logs --monitor-log tmp/e2e/explicit_dag_monitor.log --server-log tmp/e2e/explicit_dag_server.log`

Expected: 输出 `E2E log verification passed`。

- [ ] **Step 6: 提交 E2E 任务**

```bash
git add tests/e2e/run_e2e_explicit_dag_flow.py tests/e2e/verify_e2e_logs.py tests/unit/test_e2e_driver.py
git commit -m "test: add explicit DAG e2e flow with 5-minute no-error log gate"
```

### Task 8: 全量回归、README Roadmap 标注完成、交付收口

**Files:**
- Modify: `whisper-stt/README.md`
- Modify: `whisper-stt/README.zh-CN.md`
- Optional Modify: `whisper-stt/tests/e2e/run_e2e_real_flow.py`（仅在需要提取共用函数时）

- [ ] **Step 1: 跑单测与 API 回归**

Run: `uv run pytest -q whisper-stt/tests/unit`
Expected: PASS。

- [ ] **Step 2: 跑显式 DAG E2E 与日志验收（最终验收门）**

Run: `uv run python whisper-stt/tests/e2e/run_e2e_explicit_dag_flow.py --min-monitor-sec 300 --monitor-log tmp/e2e/explicit_dag_monitor.log --server-log tmp/e2e/explicit_dag_server.log`

Run: `uv run python whisper-stt/tests/e2e/verify_e2e_logs.py --task-log-root tmp/logs --monitor-log tmp/e2e/explicit_dag_monitor.log --server-log tmp/e2e/explicit_dag_server.log`

Expected: 通过“5 分钟 + task/monitor/server 日志无错误”标准。

- [ ] **Step 3: README Roadmap 标注完成（实现完成后必须执行）**

```markdown
## Roadmap

### Implemented / 已完成
- Job DAG 规划模型（含显式依赖）
- job_config 按 stage 覆盖与 task_config 快照固化
- Job 归档接口与 path 复用机制
- 显式 DAG E2E（5 分钟无错日志验收）
```

- [ ] **Step 4: 变更汇总提交**

```bash
git add whisper_stt_service tests README.md README.zh-CN.md
git commit -m "docs: mark roadmap completed for DAG planning delivery"
```

- [ ] **Step 5: 交付记录（主仓 docs）**

```bash
git add /home/base/repo/video-stt-whisper-server/docs/superpowers/
git commit -m "docs: add job DAG implementation plan"
```

Expected: 主仓文档与 child repo 实现分离，符合 AGENTS 规则。

---

## Definition of Done (DoD)

- `POST /jobs` 同时支持默认 DAG（未传 `dag`）和显式 DAG（传 `dag` + `job_config`）。
- `jobs`/`tasks` 新字段与 `jobs_archive`/`tasks_archive` 在增量迁移后可用。
- `claim_next` 在多依赖场景下仅在“全部上游 succeeded”时放行。
- `POST /jobs/{job_id}/archive` 满足允许/拒绝规则并释放 `video_path` 占用。
- 显式 DAG E2E 使用当前 `tests/e2e/video_paths.txt` 数据集，监控时长 `>= 5` 分钟。
- `task logs`、`monitor log`、`server 主日志` 三类日志均无错误关键字，且无 `task_failed` 事件。

## 风险与缓解

- SQLite 历史库结构不一致：通过 `PRAGMA table_info + ALTER TABLE` 增量补齐。
- 依赖载荷兼容（NULL/字符串/JSON 数组）复杂：集中使用单一 decode/encode 函数并单测覆盖。
- E2E 长耗时导致 CI 不稳定：将 5 分钟无错门作为可选 nightly/手工门，PR 默认跑单测 + 轻量接口测。
- `config.ini` / `video_paths.txt` 被忽略：在 worktree 初始化步骤显式复制，避免“本地可跑、worktree 不可跑”。

## 执行顺序建议

1. 先落 schema + 校验层（Task 2~3）
2. 再改 enqueue/claim/archive 核心语义（Task 4~6）
3. 最后补 E2E 与 README roadmap 收口（Task 7~8）

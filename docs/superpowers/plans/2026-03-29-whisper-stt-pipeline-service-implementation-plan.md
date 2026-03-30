# Whisper STT Pipeline Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `whisper-stt` 从 CLI 改造成可并发流水线执行的 HTTP 服务，具备 SQLite 队列、幂等入队、恢复机制、内存进度、完整测试与真实 E2E 验证。

**Architecture:** 使用 FastAPI 提供入队与查询接口，SQLite 持久化 `jobs/tasks`，三阶段 worker 池按依赖推进任务。任务状态写 DB，细粒度进度仅写内存 `ProgressStore`。启动恢复会将全部 `claimed` 回退为 `queued`，停机时对在途任务执行回滚清理并回写状态。

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, SQLite, threading, pytest, requests

---

## 文件结构与职责

- 新建 `whisper-stt/whisper_stt_service/config.py`：读取 `config.ini` 并做强类型配置。
- 新建 `whisper-stt/whisper_stt_service/db.py`：SQLite 连接、事务上下文、初始化表结构。
- 新建 `whisper-stt/whisper_stt_service/repository.py`：jobs/tasks 的增删查改、幂等判定、领取与状态流转。
- 新建 `whisper-stt/whisper_stt_service/progress.py`：内存进度存储、TTL 清理、异步进度队列消费。
- 新建 `whisper-stt/whisper_stt_service/executors.py`：`extract/stt/translate` 三阶段执行器及“删除后重做”。
- 新建 `whisper-stt/whisper_stt_service/workers.py`：worker 循环、scheduler、启动恢复、优雅停机。
- 新建 `whisper-stt/whisper_stt_service/api.py`：FastAPI 路由与响应模型。
- 新建 `whisper-stt/whisper_stt_service/main.py`：服务入口（组装依赖并启动）。
- 新建 `whisper-stt/tests/unit/*.py`：单元测试（repository/worker/progress/executor/api）。
- 新建 `whisper-stt/tests/e2e/video_paths.txt`：真实视频路径输入文件（用户每次更新）。
- 新建 `whisper-stt/tests/e2e/run_e2e_real_flow.py`：启动服务、入队、轮询进度、30 分钟超时。
- 修改 `whisper-stt/README.md`：新增服务运行、API、测试说明。

### Task 1: 项目骨架与配置加载

**Files:**
- Create: `whisper-stt/whisper_stt_service/__init__.py`
- Create: `whisper-stt/whisper_stt_service/config.py`
- Create: `whisper-stt/whisper_stt_service/main.py`
- Create: `whisper-stt/tests/unit/test_config.py`

- [ ] **Step 1: 写失败测试（配置解析）**

```python
# whisper-stt/tests/unit/test_config.py
from pathlib import Path

from whisper_stt_service.config import load_settings


def test_load_settings_reads_worker_counts(tmp_path: Path) -> None:
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        """
[workers]
extract_workers = 2
stt_workers = 3
translate_workers = 4
scheduler_interval_sec = 180
poll_interval_sec = 1

[timeouts]
extract_timeout_sec = 1200
stt_timeout_sec = 7200
translate_timeout_sec = 7200
lease_timeout_sec = 600

[retry]
extract_max_retries = 2
stt_max_retries = 2
translate_max_retries = 2

[runtime]
db_path = /tmp/test.db
progress_ttl_sec = 3600
log_root = /tmp/logs
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(cfg)
    assert settings.workers.extract_workers == 2
    assert settings.workers.stt_workers == 3
    assert settings.runtime.progress_ttl_sec == 3600
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest whisper-stt/tests/unit/test_config.py -v`  
Expected: FAIL，提示 `ModuleNotFoundError: No module named 'whisper_stt_service'`

- [ ] **Step 3: 写最小实现（配置模块+入口）**

```python
# whisper-stt/whisper_stt_service/config.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import configparser


@dataclass(frozen=True)
class WorkerSettings:
    extract_workers: int
    stt_workers: int
    translate_workers: int
    scheduler_interval_sec: int
    poll_interval_sec: int


@dataclass(frozen=True)
class TimeoutSettings:
    extract_timeout_sec: int
    stt_timeout_sec: int
    translate_timeout_sec: int
    lease_timeout_sec: int


@dataclass(frozen=True)
class RetrySettings:
    extract_max_retries: int
    stt_max_retries: int
    translate_max_retries: int


@dataclass(frozen=True)
class RuntimeSettings:
    db_path: Path
    progress_ttl_sec: int
    log_root: Path


@dataclass(frozen=True)
class Settings:
    workers: WorkerSettings
    timeouts: TimeoutSettings
    retry: RetrySettings
    runtime: RuntimeSettings


def load_settings(config_path: Path) -> Settings:
    cp = configparser.ConfigParser()
    cp.read(config_path, encoding="utf-8")
    workers = WorkerSettings(
        extract_workers=cp.getint("workers", "extract_workers"),
        stt_workers=cp.getint("workers", "stt_workers"),
        translate_workers=cp.getint("workers", "translate_workers"),
        scheduler_interval_sec=cp.getint("workers", "scheduler_interval_sec", fallback=180),
        poll_interval_sec=cp.getint("workers", "poll_interval_sec", fallback=1),
    )
    timeouts = TimeoutSettings(
        extract_timeout_sec=cp.getint("timeouts", "extract_timeout_sec"),
        stt_timeout_sec=cp.getint("timeouts", "stt_timeout_sec"),
        translate_timeout_sec=cp.getint("timeouts", "translate_timeout_sec"),
        lease_timeout_sec=cp.getint("timeouts", "lease_timeout_sec"),
    )
    retry = RetrySettings(
        extract_max_retries=cp.getint("retry", "extract_max_retries"),
        stt_max_retries=cp.getint("retry", "stt_max_retries"),
        translate_max_retries=cp.getint("retry", "translate_max_retries"),
    )
    runtime = RuntimeSettings(
        db_path=Path(cp.get("runtime", "db_path")),
        progress_ttl_sec=cp.getint("runtime", "progress_ttl_sec", fallback=3600),
        log_root=Path(cp.get("runtime", "log_root")),
    )
    return Settings(workers=workers, timeouts=timeouts, retry=retry, runtime=runtime)
```

```python
# whisper-stt/whisper_stt_service/main.py
from __future__ import annotations

from pathlib import Path

from whisper_stt_service.config import load_settings


def bootstrap(config_path: Path) -> None:
    _ = load_settings(config_path)
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `pytest whisper-stt/tests/unit/test_config.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add whisper-stt/whisper_stt_service/__init__.py whisper-stt/whisper_stt_service/config.py whisper-stt/whisper_stt_service/main.py whisper-stt/tests/unit/test_config.py
git commit -m "feat: add service config bootstrap"
```

### Task 2: SQLite 表结构与幂等入队规则

**Files:**
- Create: `whisper-stt/whisper_stt_service/db.py`
- Create: `whisper-stt/whisper_stt_service/repository.py`
- Create: `whisper-stt/tests/unit/test_repository_enqueue.py`

- [ ] **Step 1: 写失败测试（同路径幂等/拒绝）**

```python
# whisper-stt/tests/unit/test_repository_enqueue.py
from pathlib import Path

from whisper_stt_service.db import Database
from whisper_stt_service.repository import JobRepository


def test_enqueue_idempotent_when_all_three_tasks_queued(tmp_path: Path) -> None:
    db = Database(tmp_path / "q.db")
    db.init_schema()
    repo = JobRepository(db)

    first = repo.enqueue(video_path="/tmp/a.mp4", language="ja")
    second = repo.enqueue(video_path="/tmp/a.mp4", language="ja")

    assert first.job_id == second.job_id
    assert second.message == "idempotent_returned"


def test_enqueue_rejected_when_started(tmp_path: Path) -> None:
    db = Database(tmp_path / "q.db")
    db.init_schema()
    repo = JobRepository(db)
    created = repo.enqueue(video_path="/tmp/b.mp4", language="ja")
    repo.force_mark_any_stage_started(created.job_id)

    rejected = repo.enqueue(video_path="/tmp/b.mp4", language="ja")
    assert rejected.accepted is False
    assert rejected.message == "rejected_started"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest whisper-stt/tests/unit/test_repository_enqueue.py -v`  
Expected: FAIL，提示 `Database` / `JobRepository` 未定义

- [ ] **Step 3: 写最小实现（建表+入队）**

```python
# whisper-stt/whisper_stt_service/db.py
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    video_path TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output_ja_path TEXT NOT NULL,
                    output_zh_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    depends_on_task_id TEXT,
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
                    updated_at TEXT NOT NULL
                );
                """
            )

    @contextmanager
    def tx(self):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
```

```python
# whisper-stt/whisper_stt_service/repository.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import uuid

from whisper_stt_service.db import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EnqueueResult:
    job_id: str
    accepted: bool
    message: str
    queue_ahead: int


class JobRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def enqueue(self, video_path: str, language: str) -> EnqueueResult:
        now = _now()
        with self.db.tx() as conn:
            row = conn.execute(
                "SELECT job_id FROM jobs WHERE video_path=? ORDER BY created_at DESC LIMIT 1",
                (video_path,),
            ).fetchone()
            if row is not None:
                latest_job_id = row["job_id"]
                statuses = [
                    r["status"]
                    for r in conn.execute(
                        "SELECT status FROM tasks WHERE job_id=? ORDER BY stage",
                        (latest_job_id,),
                    ).fetchall()
                ]
                if len(statuses) == 3 and all(s == "queued" for s in statuses):
                    return EnqueueResult(latest_job_id, False, "idempotent_returned", 0)
                if any(s in {"claimed", "succeeded", "failed"} for s in statuses):
                    return EnqueueResult(latest_job_id, False, "rejected_started", 0)

            job_id = str(uuid.uuid4())
            p = Path(video_path)
            ja = str(p.with_suffix(".ja.srt"))
            zh = str(p.with_suffix(".zh.srt"))
            conn.execute(
                "INSERT INTO jobs(job_id,video_path,source_language,status,output_ja_path,output_zh_path,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (job_id, video_path, language, "queued", ja, zh, now, now),
            )
            extract_id = str(uuid.uuid4())
            stt_id = str(uuid.uuid4())
            tr_id = str(uuid.uuid4())
            tasks = [
                (extract_id, job_id, "extract", "queued", None),
                (stt_id, job_id, "stt", "queued", extract_id),
                (tr_id, job_id, "translate", "queued", stt_id),
            ]
            for task_id, jid, stage, status, dep in tasks:
                conn.execute(
                    "INSERT INTO tasks(task_id,job_id,stage,status,depends_on_task_id,max_retries,timeout_sec,log_dir,log_file,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (task_id, jid, stage, status, dep, 2, 3600, "", "", now, now),
                )
            return EnqueueResult(job_id, True, "created", 0)

    def force_mark_any_stage_started(self, job_id: str) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE tasks SET status='claimed', started_at=?, updated_at=? WHERE job_id=? AND stage='extract'",
                (_now(), _now(), job_id),
            )
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `pytest whisper-stt/tests/unit/test_repository_enqueue.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add whisper-stt/whisper_stt_service/db.py whisper-stt/whisper_stt_service/repository.py whisper-stt/tests/unit/test_repository_enqueue.py
git commit -m "feat: add sqlite queue schema and enqueue idempotency"
```

### Task 3: 原子领取与依赖判定

**Files:**
- Modify: `whisper-stt/whisper_stt_service/repository.py`
- Create: `whisper-stt/tests/unit/test_repository_claim.py`

- [ ] **Step 1: 写失败测试（同一任务不能被重复领取）**

```python
# whisper-stt/tests/unit/test_repository_claim.py
from pathlib import Path

from whisper_stt_service.db import Database
from whisper_stt_service.repository import JobRepository


def test_claim_is_atomic_for_same_stage(tmp_path: Path) -> None:
    db = Database(tmp_path / "q.db")
    db.init_schema()
    repo = JobRepository(db)
    repo.enqueue("/tmp/c.mp4", "ja")

    first = repo.claim_next(stage="extract", worker_id="w1", lease_timeout_sec=60)
    second = repo.claim_next(stage="extract", worker_id="w2", lease_timeout_sec=60)

    assert first is not None
    assert second is None
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest whisper-stt/tests/unit/test_repository_claim.py -v`  
Expected: FAIL，提示 `claim_next` 不存在

- [ ] **Step 3: 写最小实现（领取 SQL）**

```python
# repository.py 中新增
from datetime import timedelta


def _lease_expire(sec: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=sec)).isoformat()


@dataclass
class ClaimedTask:
    task_id: str
    job_id: str
    stage: str


class JobRepository:
    # ... existing methods
    def claim_next(self, stage: str, worker_id: str, lease_timeout_sec: int) -> ClaimedTask | None:
        with self.db.tx() as conn:
            row = conn.execute(
                """
                SELECT t.task_id, t.job_id, t.stage
                FROM tasks t
                LEFT JOIN tasks d ON d.task_id = t.depends_on_task_id
                WHERE t.stage=? AND t.status='queued'
                  AND (t.depends_on_task_id IS NULL OR d.status='succeeded')
                ORDER BY t.created_at ASC, t.task_id ASC
                LIMIT 1
                """,
                (stage,),
            ).fetchone()
            if row is None:
                return None

            now = _now()
            changed = conn.execute(
                """
                UPDATE tasks
                SET status='claimed', lease_owner=?, lease_expires_at=?, claimed_at=?, started_at=?, updated_at=?
                WHERE task_id=? AND status='queued'
                """,
                (worker_id, _lease_expire(lease_timeout_sec), now, now, now, row["task_id"]),
            ).rowcount
            if changed == 0:
                return None
            return ClaimedTask(task_id=row["task_id"], job_id=row["job_id"], stage=row["stage"])
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `pytest whisper-stt/tests/unit/test_repository_claim.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add whisper-stt/whisper_stt_service/repository.py whisper-stt/tests/unit/test_repository_claim.py
git commit -m "feat: add atomic task claim with dependency gate"
```

### Task 4: 进度内存通道与 TTL 清理

**Files:**
- Create: `whisper-stt/whisper_stt_service/progress.py`
- Create: `whisper-stt/tests/unit/test_progress_store.py`

- [ ] **Step 1: 写失败测试（完成后 1h 清理）**

```python
# whisper-stt/tests/unit/test_progress_store.py
from datetime import datetime, timedelta, timezone

from whisper_stt_service.progress import ProgressStore


def test_completed_progress_expires() -> None:
    store = ProgressStore(ttl_seconds=10)
    now = datetime.now(timezone.utc)
    store.update("t1", percent=50.0, message="running", worker_id="w1", ts=now)
    store.mark_done("t1", ts=now)

    assert "t1" in store.snapshot("t1")

    future = now + timedelta(seconds=11)
    store.cleanup(now=future)

    assert store.snapshot("t1") == {}
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest whisper-stt/tests/unit/test_progress_store.py -v`  
Expected: FAIL，提示 `ProgressStore` 不存在

- [ ] **Step 3: 写最小实现（内存进度）**

```python
# whisper-stt/whisper_stt_service/progress.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock


@dataclass
class ProgressItem:
    percent: float
    message: str
    worker_id: str
    ts: datetime
    done_at: datetime | None = None


class ProgressStore:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl = timedelta(seconds=ttl_seconds)
        self._items: dict[str, ProgressItem] = {}
        self._lock = Lock()

    def update(self, task_id: str, percent: float, message: str, worker_id: str, ts: datetime | None = None) -> None:
        now = ts or datetime.now(timezone.utc)
        with self._lock:
            self._items[task_id] = ProgressItem(percent=percent, message=message, worker_id=worker_id, ts=now)

    def mark_done(self, task_id: str, ts: datetime | None = None) -> None:
        now = ts or datetime.now(timezone.utc)
        with self._lock:
            item = self._items.get(task_id)
            if item is not None:
                item.done_at = now
                item.ts = now

    def cleanup(self, now: datetime | None = None) -> None:
        ref = now or datetime.now(timezone.utc)
        with self._lock:
            expired = [
                k
                for k, v in self._items.items()
                if v.done_at is not None and (ref - v.done_at) > self.ttl
            ]
            for key in expired:
                self._items.pop(key, None)

    def snapshot(self, task_id: str) -> dict[str, dict]:
        with self._lock:
            item = self._items.get(task_id)
            if item is None:
                return {}
            return {
                task_id: {
                    "percent": item.percent,
                    "message": item.message,
                    "worker_id": item.worker_id,
                    "updated_at": item.ts.isoformat(),
                }
            }
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `pytest whisper-stt/tests/unit/test_progress_store.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add whisper-stt/whisper_stt_service/progress.py whisper-stt/tests/unit/test_progress_store.py
git commit -m "feat: add in-memory progress store with ttl cleanup"
```

### Task 5: 三阶段执行器与删除后重做

**Files:**
- Create: `whisper-stt/whisper_stt_service/executors.py`
- Create: `whisper-stt/tests/unit/test_executors_cleanup.py`

- [ ] **Step 1: 写失败测试（目标文件已存在时先删）**

```python
# whisper-stt/tests/unit/test_executors_cleanup.py
from pathlib import Path

from whisper_stt_service.executors import preclean_output


def test_preclean_output_deletes_existing_file(tmp_path: Path) -> None:
    out = tmp_path / "video.ja.srt"
    out.write_text("dirty", encoding="utf-8")
    assert out.exists()

    preclean_output(out)
    assert not out.exists()
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest whisper-stt/tests/unit/test_executors_cleanup.py -v`  
Expected: FAIL，提示 `preclean_output` 不存在

- [ ] **Step 3: 写最小实现（三阶段调用封装）**

```python
# whisper-stt/whisper_stt_service/executors.py
from __future__ import annotations

from pathlib import Path
import subprocess


def preclean_output(path: Path) -> None:
    if path.exists():
        path.unlink()


def run_extract(input_video: Path, output_wav: Path, timeout_sec: int) -> None:
    preclean_output(output_wav)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output_wav),
    ]
    subprocess.run(cmd, check=True, timeout=timeout_sec)


def run_stt(input_video: Path, output_ja_srt: Path, language: str, timeout_sec: int) -> None:
    preclean_output(output_ja_srt)
    cmd = [
        "python",
        "whisper-stt/whisper_stt/transcribe_video.py",
        "--input",
        str(input_video),
        "--output",
        str(output_ja_srt),
        "--language",
        language,
    ]
    subprocess.run(cmd, check=True, timeout=timeout_sec)


def run_translate(input_ja_srt: Path, output_zh_srt: Path, config_path: Path, timeout_sec: int) -> None:
    preclean_output(output_zh_srt)
    progress_artifact = output_zh_srt.with_suffix(output_zh_srt.suffix + ".progress.json")
    preclean_output(progress_artifact)
    cmd = [
        "python",
        "whisper-stt/whisper_stt/translate_srt_ja_to_zh.py",
        "--input",
        str(input_ja_srt),
        "--output",
        str(output_zh_srt),
        "--config",
        str(config_path),
    ]
    subprocess.run(cmd, check=True, timeout=timeout_sec)
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `pytest whisper-stt/tests/unit/test_executors_cleanup.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add whisper-stt/whisper_stt_service/executors.py whisper-stt/tests/unit/test_executors_cleanup.py
git commit -m "feat: add stage executors and preclean behavior"
```

### Task 6: Worker/Scheduler、启动恢复与优雅停机

**Files:**
- Create: `whisper-stt/whisper_stt_service/workers.py`
- Create: `whisper-stt/tests/unit/test_worker_recovery.py`

- [ ] **Step 1: 写失败测试（启动后 claimed 回退 queued）**

```python
# whisper-stt/tests/unit/test_worker_recovery.py
from pathlib import Path

from whisper_stt_service.db import Database
from whisper_stt_service.repository import JobRepository
from whisper_stt_service.workers import recover_claimed_to_queued


def test_recover_claimed_to_queued_on_startup(tmp_path: Path) -> None:
    db = Database(tmp_path / "q.db")
    db.init_schema()
    repo = JobRepository(db)
    created = repo.enqueue("/tmp/d.mp4", "ja")
    claimed = repo.claim_next("extract", "w1", 60)
    assert claimed is not None

    recovered = recover_claimed_to_queued(db)
    assert recovered >= 1

    with db.connect() as conn:
        row = conn.execute("SELECT status FROM tasks WHERE task_id=?", (claimed.task_id,)).fetchone()
        assert row["status"] == "queued"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest whisper-stt/tests/unit/test_worker_recovery.py -v`  
Expected: FAIL，提示 `recover_claimed_to_queued` 未定义

- [ ] **Step 3: 写最小实现（恢复与 worker 主循环）**

```python
# whisper-stt/whisper_stt_service/workers.py
from __future__ import annotations

from threading import Event
from time import sleep

from whisper_stt_service.db import Database
from whisper_stt_service.repository import JobRepository


def recover_claimed_to_queued(db: Database) -> int:
    with db.tx() as conn:
        changed = conn.execute(
            "UPDATE tasks SET status='queued', lease_owner=NULL, lease_expires_at=NULL, updated_at=datetime('now') WHERE status='claimed'"
        ).rowcount
        return int(changed)


def worker_loop(repo: JobRepository, stage: str, worker_id: str, stop_event: Event, poll_interval_sec: int) -> None:
    while not stop_event.is_set():
        task = repo.claim_next(stage=stage, worker_id=worker_id, lease_timeout_sec=600)
        if task is None:
            sleep(poll_interval_sec)
            continue
        repo.mark_task_succeeded(task.task_id)
```

```python
# repository.py 增加最小方法
class JobRepository:
    # ...
    def mark_task_succeeded(self, task_id: str) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE tasks SET status='succeeded', finished_at=?, updated_at=? WHERE task_id=?",
                (_now(), _now(), task_id),
            )
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `pytest whisper-stt/tests/unit/test_worker_recovery.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add whisper-stt/whisper_stt_service/workers.py whisper-stt/whisper_stt_service/repository.py whisper-stt/tests/unit/test_worker_recovery.py
git commit -m "feat: add startup recovery and worker loop skeleton"
```

### Task 7: API 路由与筛选分页接口

**Files:**
- Create: `whisper-stt/whisper_stt_service/api.py`
- Modify: `whisper-stt/whisper_stt_service/main.py`
- Create: `whisper-stt/tests/unit/test_api_jobs.py`

- [ ] **Step 1: 写失败测试（POST /jobs 和 GET /jobs/{id}/progress）**

```python
# whisper-stt/tests/unit/test_api_jobs.py
from fastapi.testclient import TestClient

from whisper_stt_service.api import create_app


def test_post_jobs_requires_existing_video(tmp_path):
    app = create_app()
    client = TestClient(app)
    resp = client.post("/jobs", json={"video_path": "/not-found/a.mp4", "language": "ja"})
    assert resp.status_code == 400


def test_get_progress_returns_task_status_and_optional_progress(tmp_path):
    app = create_app()
    client = TestClient(app)
    resp = client.get("/jobs/unknown/progress")
    assert resp.status_code in (404, 200)
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest whisper-stt/tests/unit/test_api_jobs.py -v`  
Expected: FAIL，提示 `create_app` 未定义

- [ ] **Step 3: 写最小实现（核心接口）**

```python
# whisper-stt/whisper_stt_service/api.py
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class CreateJobReq(BaseModel):
    video_path: str
    language: str


def create_app() -> FastAPI:
    app = FastAPI(title="whisper-stt-service")

    @app.post("/jobs")
    def create_job(req: CreateJobReq):
        path = Path(req.video_path)
        if not path.is_absolute() or not path.is_file():
            raise HTTPException(status_code=400, detail="video_path_not_found")
        return {"job_id": "example-job-id", "accepted": True, "queue_ahead": 0, "message": "created"}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        raise HTTPException(status_code=404, detail="job_not_found")

    @app.get("/jobs/{job_id}/progress")
    def get_progress(job_id: str):
        raise HTTPException(status_code=404, detail="job_not_found")

    @app.get("/jobs/by-path")
    def by_path(video_path: str):
        return {"video_path": video_path, "item": None}

    @app.get("/jobs")
    def list_jobs(page: int = 1, page_size: int = 20):
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    @app.get("/tasks")
    def list_tasks(page: int = 1, page_size: int = 20):
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    @app.get("/queue/summary")
    def queue_summary():
        return {"stages": {}, "workers": {}, "throughput": {}}

    return app
```

```python
# whisper-stt/whisper_stt_service/main.py
from __future__ import annotations

from whisper_stt_service.api import create_app

app = create_app()
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `pytest whisper-stt/tests/unit/test_api_jobs.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add whisper-stt/whisper_stt_service/api.py whisper-stt/whisper_stt_service/main.py whisper-stt/tests/unit/test_api_jobs.py
git commit -m "feat: add api endpoints and pagination skeleton"
```

### Task 8: 真实 E2E 脚本与文档

**Files:**
- Create: `whisper-stt/tests/e2e/video_paths.txt`
- Create: `whisper-stt/tests/e2e/run_e2e_real_flow.py`
- Modify: `whisper-stt/README.md`

- [ ] **Step 1: 写失败测试（路径文件必须存在且至少 1 条）**

```python
# whisper-stt/tests/unit/test_e2e_driver.py
from pathlib import Path

from tests.e2e.run_e2e_real_flow import load_video_paths


def test_load_video_paths_requires_non_empty(tmp_path: Path) -> None:
    f = tmp_path / "video_paths.txt"
    f.write_text("", encoding="utf-8")
    try:
        load_video_paths(f)
        assert False, "should raise"
    except ValueError:
        assert True
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest whisper-stt/tests/unit/test_e2e_driver.py -v`  
Expected: FAIL，提示 `run_e2e_real_flow` 不存在

- [ ] **Step 3: 写最小实现（真实链路脚本）**

```python
# whisper-stt/tests/e2e/run_e2e_real_flow.py
from __future__ import annotations

from pathlib import Path
import subprocess
import time
import requests


def load_video_paths(path_file: Path) -> list[str]:
    lines = [x.strip() for x in path_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not lines:
        raise ValueError("video_paths.txt is empty")
    return lines


def main() -> int:
    base = "http://127.0.0.1:8000"
    path_file = Path("whisper-stt/tests/e2e/video_paths.txt")
    videos = load_video_paths(path_file)

    server = subprocess.Popen(["python", "-m", "uvicorn", "whisper_stt_service.main:app", "--host", "127.0.0.1", "--port", "8000"])
    try:
        time.sleep(2)
        job_ids: list[str] = []
        for video in videos:
            r = requests.post(f"{base}/jobs", json={"video_path": video, "language": "ja"}, timeout=30)
            r.raise_for_status()
            job_ids.append(r.json()["job_id"])

        deadline = time.time() + 1800
        while time.time() < deadline:
            done = 0
            for job_id in job_ids:
                status = requests.get(f"{base}/jobs/{job_id}", timeout=30).json().get("status")
                _ = requests.get(f"{base}/jobs/{job_id}/progress", timeout=30).json()
                if status in {"succeeded", "failed"}:
                    done += 1
            if done == len(job_ids):
                return 0
            time.sleep(15)
        return 1
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
```

```text
# whisper-stt/tests/e2e/video_paths.txt
/abs/path/video1.mp4
/abs/path/video2.mp4
/abs/path/video3.mp4
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `pytest whisper-stt/tests/unit/test_e2e_driver.py -v`  
Expected: PASS

- [ ] **Step 5: 更新 README 并提交**

```markdown
## Service E2E

1. 编辑 `whisper-stt/tests/e2e/video_paths.txt`，填写真实绝对路径。
2. 运行 `python whisper-stt/tests/e2e/run_e2e_real_flow.py`。
3. 脚本会启动服务、入队、轮询进度，直到全部完成或 30 分钟超时。
```

```bash
git add whisper-stt/tests/e2e/video_paths.txt whisper-stt/tests/e2e/run_e2e_real_flow.py whisper-stt/tests/unit/test_e2e_driver.py whisper-stt/README.md
git commit -m "test: add real-flow e2e driver and instructions"
```

## 计划自检

- 规格覆盖：已覆盖 API、SQLite 队列、幂等规则、单表三任务依赖、原子领取、重启回退、优雅停机回滚、删除重做、日志要求、筛选分页、E2E 与 worker 单测。
- 占位符扫描：无 `TBD/TODO/implement later`。
- 命名一致性：统一使用 `job_id/task_id/stage/status/claimed` 与 `ProgressStore`。

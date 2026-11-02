# React 字幕流水线工作台：实施计划与并行开发契约

- 日期：2026-11-01（Asia/Shanghai）
- 目标 SPEC：[2026-11-01-react-web-console-spec.md](../specs/2026-11-01-react-web-console-spec.md)（唯一需求与行为权威）
- 本文件只补充**并行开发所需的契约冻结**：模块所有权、共享数据结构、构建/测试命令。
  行为细节一律以 SPEC 为准；与 SPEC 冲突时以 SPEC 为准并回写本文件。
- 状态：实施中（M1 → M2 → M3）

## 0. 仓库与分支

| 项 | 值 |
|---|---|
| 主仓库（文档/协调） | `/home/base/repo/video-stt-whisper-server` |
| 子仓库工作树（代码） | `.worktrees/react-web-console`，分支 `feat/react-web-console` |
| Python | 只用主项目 `.venv`：`/home/base/repo/video-stt-whisper-server/.venv/bin/python` |
| Node | 系统 node v24 / pnpm；前端依赖与 lockfile 落在 `web/` |
| 后端测试 | `cd .worktrees/react-web-console && <venv>/bin/python -m pytest -q`（基线 618 passed） |
| 前端测试 | `cd .worktrees/react-web-console/web && pnpm typecheck && pnpm lint && pnpm test && pnpm build` |

## 1. 并行开发规则（所有子代理必须遵守）

1. **只改自己名下的文件**。需要改边界外文件时，写进交付说明，由总调度集成，不要擅自改。
2. **不执行 git 写操作**（不 commit / 不 checkout / 不 stash / 不 reset）。总调度统一提交。
3. **MUSTDO：保留所有既有注解、docstring、中文注释**，不得因为重构删除或简化；新增代码同样写中文 docstring（说明契约与失败语义）。
4. 新增/修改的行为必须有 pytest 用例；不依赖真实 GPU / 真实 LLM / 真实媒体 / 网络。
5. 不得引入新 Python 运行时依赖（除非全局约定），不得创建 `.venv`。
6. 新增 Python 模块必须可在 `create_app` 之外单独测试（用局部 `FastAPI()` + 注入的假 repo/租约）。
7. 报告格式：`已完成 / 未完成 / 已验证（命令+结果）/ 未验证 / 遗留风险 / 触碰的文件`。

## 2. 冻结的共享契约

### 2.1 `[web]` 配置段（`core/config.py`）

```python
@dataclass(frozen=True)
class WebSettings:
    enabled: bool = False              # 默认关闭，保持纯 API 部署
    base_path: str = "/ui"             # 前端挂载前缀（无尾斜杠）
    dist_dir: str = ""                 # 空 = <repo>/web/dist；相对路径按配置文件目录解析
    media_roots: tuple[str, ...] = ()  # 服务器媒体根白名单（绝对路径字符串）
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "[::1]")
    allowed_origins: tuple[str, ...] = ()
    trusted_proxies: tuple[str, ...] = ()
    allow_shutdown: bool = False       # Web 启用部署默认禁止停机写接口
    auth_rate_limit_per_minute: int = 10
    progress_stale_seconds: int = 60
```

- `Settings.web: WebSettings`，`load_settings` 解析 `[web]`（键名：`enabled/base_path/dist_dir/media_roots/allowed_hosts/allowed_origins/trusted_proxies/allow_shutdown/auth_rate_limit_per_minute/progress_stale_seconds`）。
- 逗号分隔的多值解析沿用现有 `_parse_csv` 风格（空串 = 空元组）。
- `enabled=true` 且 dist 不存在 → 启动 fail-fast（`bootstrap` 侧），不得半可用。

### 2.2 三条固定预置（`core/presets.py`，已由总调度提供）

```python
PRESETS: tuple[Preset, ...]                 # 顺序固定：whisper-ja-zh, whisperx-ja-zh, qwen-ja-zh
DEFAULT_PRESET_ID = "whisper-ja-zh"
PRESET_REVISION = "1"                       # 预置结构版本，变更预置内容必须自增
def get_preset(preset_id: str) -> Preset | None
def resolve_preset(preset_id, language, dag, job_config) -> Preset   # 冲突抛 ValueError
```

失败码：`preset_not_found`、`preset_input_conflict`（preset 与 language/dag/job_config 同时出现）。

### 2.3 `GET /capabilities` 响应（冻结）

```jsonc
{
  "schema_version": "1",
  "service_version": "0.5.0",
  "web_base_path": "/ui",
  "server_time": "2026-11-01T23:59:00+00:00",
  "features": {"web": true, "logs": true, "artifacts": true, "archives": true,
               "batch": true, "shutdown_api": false, "media": true},
  "limits": {"page_size_max": 200, "media_page_size_max": 200, "media_entry_limit": 5000,
             "log_bytes_max": 262144, "log_default_bytes": 65536,
             "log_download_max_bytes": 10485760, "cues_page_size_max": 500,
             "batch_max_items": 50},
  "stages": [{"name": "stt", "asr": true, "available": true, "unavailable_reasons": [],
              "config_fields": [{"key": "batch_size", "type": "int", "unit": null,
                                 "min": 1, "max": null, "enum": null, "nullable": false,
                                 "job_override": true, "description": "..."}],
              "defaults": {"batch_size": 8, "..." : 0}}],
  "presets": [{"preset_id": "whisper-ja-zh", "name": "Whisper 转写与翻译",
               "description": "...", "asr_stage": "stt", "dag": {"version": 1, "stages": []},
               "preset_revision": "1", "config_revision": "cfg-0123456789ab",
               "available": true, "unavailable_reasons": [], "stages": ["extract","stt","translate"]}],
  "languages": [{"code": "ja", "label": "日语"}, {"code": "zh", "label": "中文"}]
}
```

- `defaults` 来自当前 settings + `JobRepository._build_effective_config` 同源逻辑（只读）。
- `available` 只表示静态前置（目录/配置/依赖），不加载模型、不联网、不探显存。

### 2.4 DTO（`api/dto.py`，冻结字段名）

`JobSummary`（`GET /jobs` items、`GET /archives/jobs` items 共用）：

```jsonc
{"job_id":"...","video_path":"...","video_name":"...","status":"queued|running|succeeded|failed",
 "source_language":"ja","preset_id":"whisper-ja-zh|null","preset_name":"...|null",
 "preset_inferred": false, "asr_stage": "stt", "current_stages": ["stt"],
 "stage_states": {"extract":"succeeded","stt":"running","translate":"queued"},
 "task_counts": {"queued":0,"claimed":0,"succeeded":0,"failed":0,"blocked":0,"cancelled":0},
 "cancelled_by_user": false, "warning_summary": {"available": false, "items": []},
 "error_summary": "unique_violation|null", "request_id": "|null",
 "created_at":"...","updated_at":"...","finished_at":null,
 "allowed_actions": {"retry":{"allowed":false,"reasons":["job_not_failed"]},"cancel":{...},"archive":{...}},
 "archived_at": null, "archive_reason": null}
```

`JobDetail` = `JobSummary` + `dag`、`job_config`（安全投影）、`tasks: TaskView[]`、
`progress: {available, tasks: {task_id: {...}}}`、`config_source: "frozen|legacy_fallback"`、
`output_availability: {status: "unknown|available|expired|missing", reason}`、
`stages: [{stage,status,attempt,max_retries,started_at,finished_at,duration_sec,error,worker,
           heartbeat_at,progress:{available,percent,message,updated_at,stale}}]`。

`TaskView`：

```jsonc
{"task_id":"...","job_id":"...","stage":"stt","status":"queued","attempt":0,"max_retries":2,
 "depends_on_task_id":"...|null","blocked_by":"...|null","error":"code|null",
 "started_at":null,"finished_at":null,"updated_at":"...","duration_sec":null,
 "lease_owner":"|null","lease_expires_at":"|null","progress":{...}}
```

`ArtifactView`（§6.4）、`LogPage`（§6.3）字段按 SPEC 原样。

`security_projection(raw_cfg)`：允许列表 + 密钥键（`token/password/secret/api_key` 等）一律剔除，
返回 `{"redacted": true, "fields": {...}}` 形态由实现决定，但**不得**原样透传未知嵌套字段。

### 2.5 统一错误响应（§8）

```jsonc
{"detail": "preset_not_found",
 "error": {"code": "preset_not_found", "message": "中文可读原因", "field_errors": [], "retryable": false},
 "request_id": "..."}
```

`detail` 必须保留旧字符串语义（旧脚本兼容）；缺少 `error`/`request_id` 时前端按旧行为降级。

### 2.6 路由模块清单（各代理只创建自己的模块，`app.py` 由总调度统一挂载）

| 模块 | 路由 |
|---|---|
| `api/routes/auth.py` | `GET /auth/config`、`GET /auth/check`（仅 web 启用时注册） |
| `api/routes/capabilities.py` | `GET /capabilities` |
| `api/routes/system.py` | `GET /system/status` |
| `api/routes/media.py` | `GET /media/roots`、`GET /media/entries` |
| `api/routes/planning.py` | `POST /jobs/validate` |
| `api/routes/logs.py` | `GET /tasks/{task_id}/logs`、`.../logs/download` |
| `api/routes/artifacts.py` | `GET /jobs/{job_id}/artifacts`、`.../{artifact_id}/content`、`.../cues` |
| `api/routes/archives.py` | `GET /archives/jobs`、`GET /archives/jobs/{job_id}` |

每个模块导出 `router = APIRouter()`；路由 internal 依赖通过 `request.app.state` 读取
（`repo` / `progress_store` / `runtime` / `settings` / `web_settings`）。
`/jobs/validate`（固定字面路由）必须先于 `/jobs/{job_id}` 注册——由总调度保证注册顺序。

### 2.7 前端

- `web/`：Vite + React 18 + TS + antd 5 + @tanstack/react-query 5 + react-router-dom 6。
- 目录：`src/app`（shell/路由/主题）、`src/api`（client + contracts + adapters）、
  `src/features/{overview,jobs,media,tasks,system,history,access}`、`src/components`。
- 所有网络调用只经 `src/api/client.ts`；Token 只存 `sessionStorage` + 内存，禁止 URL。
- 设计规范：`docs/superpowers/specs/2026-11-01-react-web-console-aesthetic-guidance.md`（GPT-6.1-Sol 出具）。

## 3. 分期与代理分工

| 波次 | 代理 | 范围 | 文件所有权 |
|---|---|---|---|
| W1 | `capability-agent` | F04：能力表、`/capabilities`、`/system/status`、预置前置检查 | `core/capabilities.py`、`service/system_status.py`、`api/routes/capabilities.py`、`api/routes/system.py`、`tests/unit/test_capabilities*.py` |
| W1 | `data-agent` | F03：DTO、`allowed_actions`、列表摘要、稳定排序、进度身份、`plan_job` 纯规划、m003 | `api/dto.py`、`repo/job_repository.py`、`repo/migrations/m003_web_console.py`+注册、`api/routes/jobs.py`、`api/routes/queue.py`、`core/progress.py`、`api/schemas.py` |
| W1 | `gate-agent` | F02：auth 路由、Host/Origin、web 门禁、静态托管、停机策略 | `api/routes/auth.py`、`api/web_gate.py`、`api/static_site.py`、`core/web_security.py`、`tests/unit/test_web_gate*.py` |
| W1 | `fe-foundation-agent` | F01：脚手架、主题、API 客户端、鉴权门、导航、错误/空态 | `web/**`（脚手架与公共层） |
| W1 | `aesthetic-agent`（GPT-6.1-Sol） | 美学规范文档 | 主仓库 `docs/superpowers/specs/2026-11-01-react-web-console-aesthetic-guidance.md` |
| W2 | `media-agent` | F05：目录浏览、预检、配置版本 | `service/media_browser.py`、`service/planning.py`、`api/routes/media.py`、`api/routes/planning.py` |
| W2 | `artifact-agent` | F07/F08/F09：日志、manifest、字幕、归档 | `service/log_reader.py`、`service/artifacts.py`、`repo/artifact_repository.py`、`api/routes/logs.py`、`api/routes/artifacts.py`、`api/routes/archives.py`、m004 |
| W2 | `fe-jobs-agent` | 概览/列表/新建/详情/任务页 | `web/src/features/{overview,jobs,media,tasks}` |
| W3 | `fe-m2-agent` | 日志/字幕/归档/系统页 | `web/src/features/{history,system}`, `web/src/features/jobs/tabs` |
| W3 | `batch-docs-agent` | F10/F11：多选批量、CI、README、运维文档 | `web/src/features/jobs/batch*`、`.github/workflows/ci.yml`、两份 README、`web/README.md` |
| W4 | `acceptance-*` | 独立验收（非实现者） | 只读 + 独立测试文件 |

## 4. M1 验收闸门（总调度自查，独立代理复验）

1. `pytest -q` 全绿（基线 618 + 新增）。
2. `curl`/TestClient 冒烟：四种 security 组合下 `/auth/config`、`/ui/` 静态页、受保护 API 行为符合 §4.1。
3. `pnpm typecheck/lint/test/build` 全绿，构建产物可被 FastAPI 托管。
4. SPEC §11.1 的契约用例（preset、冲突、422 收紧、allowed_actions、并发竞态）存在且通过。

## 5. 实施完成情况（2026-11-03 更新）

### 5.1 各期状态

| 期 | 范围 | 状态 | 证据 |
|---|---|---|---|
| M1 | F01–F06 | 完成 | 后端 `pytest` 1082 passed / 5 deselected（CPU、fake executor）；前端 `typecheck/lint/test/build` 通过（182 tests） |
| M2 | F07–F09 | 完成 | 日志/产物/归档路由已挂 `create_app`；`tests/integration/test_web_console_m2.py`（7 例）覆盖下载/字幕/日志/归档只读 |
| M3 | F10/F11 | 完成（真实媒体验收待 GPU 窗口） | 批量多选/逐项结果/unknown 查证；CI 增加 web job；中英文 README 与 `web/README.md` 已更新 |
| 验收 | 独立三方向 | **进行中** | 3 个未参与实现的代理分别覆盖契约/交互/安全，见 `docs/superpowers/executions/2026-11-02-react-web-console-acceptance-plan.md` |

### 5.2 相对本文冻结契约的偏差（都已落地并有证据）

1. **fenced manifest 接线**：`ArtifactRepository.upsert_publish` 原为"契约无调用方"。已在
   `service/artifacts.py::record_published_task_artifacts` + `runtime._record_manifest_after_publish`
   接入发布成功路径（两处：`publish_task_artifacts` 返回 True、`with_task_lease` 降级成功），
   登记失败只告警不影响任务终态（`tests/unit/test_artifact_publish_hook.py` 7 例）。
2. **清理 → expired 接线**：`runtime._mark_artifacts_expired` 只在 `shutil.rmtree` 成功后把
   `available → expired`；删除失败保留原状态（同上测试文件）。
3. **`/system/status` 与 `/capabilities` 口径统一**：烟测发现同一实例出现
   "qwen-ja-zh available=true 但 stt_qwen ready=false"。根因是 system 侧对**复合模型根**
   （whisperx `align/` 下只有语言子目录、FireRedVAD 的 `cmvn.ark/model.pth.tar`）套用了 readyz
   级严格检查。已改为目录存在性判定，并加回归用例
   `test_readiness_matches_capabilities_for_composite_model_roots` 把两条口径钉在一起。
4. **导航图标改为装饰性**：antd 图标自带 `aria-label`，菜单项可访问名被污染成 "dashboard 概览"；
   已统一 `aria-hidden`（`app/layout/navItems.tsx`）。
5. **E2E 复用系统 Chrome**：`web/playwright.config.ts` 用 `channel: "chrome"`，避免下载浏览器；
   `scripts/web_server.sh` 统一提供"真实配置 + 0 worker（不碰 GPU）/ real workers（真实验收）"两种实例。
6. **批量结果集合视图**：已补齐——列表页支持 `?jobs=a,b,c`（去重、上限 50、可清除标签），
   批量面板提供"在作业列表查看这 N 个 Job"；仍不虚构批量 Job 实体。
7. **历史页筛选范围**：只暴露状态/语言/路径/归档时间；后端支持的创建日期/preset/排序未上 UI。
8. **`copy_back` 无生产者**：manifest 字段支持读取，但当前发布链路不写，UI 如实显示"未记录"。

### 5.3 明确的未完成项

- **真实媒体端到端**（SPEC §11.3）：等用户通知 GPU 长测结束后，用 `/srv/media/jellyfin/JELLYFIN/JAV` 的
  2 部非 VR 影片按"选片 → 预检 → 提交 → 监控 → 字幕双栏 → 下载 → 回写"全流程验收；CPU 烟测不得替代。
- **CI 实跑**：新增的 `web` job 只在本地验证过同样的命令，尚未在 GitHub Actions 实际运行。
- **独立验收结论**：等待三个验收代理回报后写入 `executions/2026-11-02-react-web-console-acceptance.md`。

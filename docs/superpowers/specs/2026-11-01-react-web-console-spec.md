# 下一阶段 SPEC：React 字幕流水线工作台（可选 Token 鉴权）

- 日期：2026-11-01（Asia/Shanghai）
- 状态：**待评审，未实施**；本文件是下一阶段 Web 控制台的唯一需求与契约入口。
- 用户已确定：增加 React 前端；鉴权由现有 `[security]` 同时控制前后端，开启时仅要求完整 API Token，不引入用户名/密码；关闭时直接进入。提供简单目录/文件选择，流水线仅从现有三种预置中单选，不手动配置。
- 本轮修订：以可选 Token 鉴权取代固定无鉴权 profile；细化 §3.3 选片器、固定三条流水线及服务端 preset 契约，新增 §3.5 监控闭环，取消可组合 ASR/翻译开关/高级参数表单。文档不记录任何真实 Token。
- 本文建议默认：本机/可信内网、同源部署、服务端媒体目录选择、中文桌面工作台；未另行确认的产品取舍见 §13。
- 探查基线：主仓库 `7df416f962254914f1537a399e171c499093a352`；子仓库 `3185a9d303de9ad225464104d872929756946286`。探查开始时两仓 tracked 工作区干净。
- 本次仅静态探查与文档设计：未启动/重启服务、未提交真实作业、未访问真实密钥、未运行模型或测试。以下“已有”指源码实现，不代表本轮运行验证。

## 1. 目标、范围与非目标

把现有 CLI/API 使用方式补齐为：**选片 → 配置流水线 → 预检 → 提交 → 监控 → 排障/重试 → 预览与下载字幕 → 历史追溯**。不替换 worker、SQLite、DAG、模型执行器及产物 fencing。

### 1.1 本阶段必须交付（M1–M3）

1. React + TypeScript 单页应用；由同一 `[security]` 派生是否展示 Token 验证页，输入完整 Token 后访问；无注册、用户名/密码、用户或角色体系。
2. 概览、作业列表、新建作业、作业详情、任务排障、归档历史、系统状态七类页面。
3. 仅提供三条完整预置流水线：`extract→stt→translate`、`extract→stt_whisperx→translate`、`extract→stt_qwen→translate`。选择其一，阶段与参数只读；不提供 DAG 编辑器、翻译开关或手动参数表单。后端既有可组合 API 保留，不能据此在 UI 扩出六种组合。
4. 简单的服务器目录/文件选择器：根目录、面包屑、返回上级、文件列表、勾选、确认；不把浏览器本地路径误认为服务器路径。
5. 稳定的能力/参数元数据、提交预检、脱敏响应、操作资格、日志读取、字幕预览/下载、归档读取接口。
6. 单一发行产物的静态前端托管、测试/CI、Token 开启/关闭两种部署说明。

### 1.2 本阶段明确不做

- 多用户、权限、云端 ASR、远程 URL 拉片、公开互联网部署。
- 浏览器上传数 GB 视频、在线剪辑/字幕编辑、任意 shell、任意文件管理、模型下载/安装。
- 运行中强制取消、暂停恢复、任意阶段重跑、修改已入队配置、全局配置在线写入。
- 独立翻译已有 SRT：当前 DAG 不支持 translate-only，不能仅在 UI 暴露按钮冒充已支持。
- Docker/Compose、MCP、Agent Skill、告警平台、GPU 资源调度不与 Web 首期绑定；扩展待办见 §12。

## 2. 已有系统与证据

以下链接相对本文；定位以本次子仓库提交为准。

| 领域 | 当前事实 / 对前端的约束 | 源码证据 |
|---|---|---|
| 请求 | 创建只收 `video_path/language/dag/job_config`，后两项还是自由 dict，无响应 DTO | [schemas.py:8–14](../../../whisper-stt/whisper_stt_service/api/schemas.py#L8-L14) |
| 接口 | 已有作业 CRUD 的部分操作、任务筛选与内存进度；无日志/文件下载/媒体浏览接口 | [jobs.py:21–206](../../../whisper-stt/whisper_stt_service/api/routes/jobs.py#L21-L206) |
| 阶段 | 实际是五个注册阶段、三选一 ASR；Qwen 部署模型目录/device/dtype 不允许 job 覆盖 | [stages.py:5–89](../../../whisper-stt/whisper_stt_service/core/stages.py#L5-L89) |
| DAG | 默认仍是 `extract→stt→translate`；必须恰好一个 ASR 且依赖 extract；translate 可省略但必须依赖该 ASR | [dag.py:19–29](../../../whisper-stt/whisper_stt_service/core/dag.py#L19-L29)、[dag.py:96–116](../../../whisper-stt/whisper_stt_service/core/dag.py#L96-L116) |
| 参数 | 按阶段白名单、类型/范围校验；不是所有 INI 配置都可经 job 覆盖 | [dag.py:133–280](../../../whisper-stt/whisper_stt_service/core/dag.py#L133-L280) |
| 冻结/去重 | 入队冻结 effective_config/io；同路径全 queued 返回原 job，已有 claimed/succeeded/failed 则拒绝创建 | [job_repository.py:491–541](../../../whisper-stt/whisper_stt_service/repo/job_repository.py#L491-L541)、[589–602](../../../whisper-stt/whisper_stt_service/repo/job_repository.py#L589-L602) |
| 状态 | Job 为 queued/running/succeeded/failed；Task 为 queued/claimed/succeeded/failed/blocked/cancelled；全部 cancelled 的 Job 仍为 failed | [job_repository.py:1179–1217](../../../whisper-stt/whisper_stt_service/repo/job_repository.py#L1179-L1217) |
| 重试 | 只对 failed job；只重置 failed/blocked，保留 succeeded，attempt 重置 0，不是整条重跑 | [job_repository.py:2321–2382](../../../whisper-stt/whisper_stt_service/repo/job_repository.py#L2321-L2382) |
| 取消 | 只处理未开始的队列任务，不支持运行中取消；事务内再判资格 | [job_repository.py:2384–2452](../../../whisper-stt/whisper_stt_service/repo/job_repository.py#L2384-L2452) |
| 归档 | 实际迁移到 archive 表并删除活动表记录；当前普通列表/详情查不到归档；全 queued 或 succeeded/failed 可归档 | [job_repository.py:1854–1866](../../../whisper-stt/whisper_stt_service/repo/job_repository.py#L1854-L1866)、[1919–2000](../../../whisper-stt/whisper_stt_service/repo/job_repository.py#L1919-L2000) |
| 列表 | Job 返回 DB 行和 JSON 字符串，Task 列表也是 DB 行，缺稳定浏览器投影 | [job_repository.py:2002–2122](../../../whisper-stt/whisper_stt_service/repo/job_repository.py#L2002-L2122) |
| 进度 | percent/message/worker_id/updated_at，线程内存+TTL，不是持久化历史 | [progress.py:10–84](../../../whisper-stt/whisper_stt_service/core/progress.py#L10-L84) |
| 观测 | 队列含 worker、shutdown、5 分钟吞吐；readyz 只检查通用模型路径等，不证明每个 ASR 可用 | [queue.py:67–96](../../../whisper-stt/whisper_stt_service/api/routes/queue.py#L67-L96)、[observability.py:468–557](../../../whisper-stt/whisper_stt_service/api/observability.py#L468-L557) |
| 安全 | token 非空时所有 API 受保护；空 token 才关闭鉴权；默认 require_token=true | [app.py:235–274](../../../whisper-stt/whisper_stt_service/api/app.py#L235-L274)、[security.py:67–82](../../../whisper-stt/whisper_stt_service/core/security.py#L67-L82) |
| 路径 | 现有扩展名白名单，allowed_video_roots 为空原本表示不限，不能照搬为空时浏览整台服务器 | [security.py:21–24](../../../whisper-stt/whisper_stt_service/core/security.py#L21-L24)、[67–82](../../../whisper-stt/whisper_stt_service/core/security.py#L67-L82) |
| 停机 | 已有 drain 请求/状态，不是暂停；停止进程后网页无法远程启动它 | [admin.py:14–31](../../../whisper-stt/whisper_stt_service/api/routes/admin.py#L14-L31) |
| Roadmap | Web 控制台仍是规划项；README 的 ASR 概览落后于注册表，以源码为准 | [README.zh-CN.md:25–29](../../../whisper-stt/README.zh-CN.md#L25-L29)、[376–383](../../../whisper-stt/README.zh-CN.md#L376-L383) |

## 3. 产品结构与交互设计

### 3.1 整体布局

- 左侧约 208px 导航：概览 / 作业 / 新建作业 / 任务排障 / 归档历史 / 系统状态。
- 顶栏：产品名“字幕流水线”、服务连接状态、刷新时间、当前鉴权模式、主操作“新建作业”；Token 模式提供“退出/清除本机 Token”，无鉴权模式显示风险提示。
- 主内容最大宽度约 1440px，表格优先；浅色默认，可选深色。状态必须文字+图标，不只靠颜色。
- 日文/中文正文使用可读字体，ID/路径/日志使用等宽字体；长路径截断但支持展开/复制。
- 1280px 桌面优先；768px 以下折叠菜单、表格横向滚动，仍可提交、查状态、下载字幕。
- 路由与筛选写入 URL，可刷新/分享；按钮 loading、防双击；键盘可操作、表单关联标签、错误焦点定位。

### 3.2 页面和数据依赖

| 页面 | 路由 | 大致设计 / 主要操作 | 依赖 |
|---|---|---|---|
| Token 验证 | `/ui/access` | 单个完整 Token 输入框（默认隐藏，可显隐）、验证按钮、错误提示；无用户名/密码；保留待访问站内路径 | auth/config、auth/check |
| 概览 | `/ui/` | 顶部连接/就绪告警；Job 状态计数卡；阶段队列、活跃 worker、5 分钟完成数；最近 10 条作业、失败入口 | queue summary（扩展 Job 计数）、jobs、healthz、readyz |
| 作业列表 | `/ui/jobs` | 搜索文件名/路径，状态/语言/日期/失败任务筛选；分页、创建/更新时间排序；列：文件、ID、ASR、当前阶段、状态、更新时间、操作 | jobs（扩展摘要） |
| 新建 | `/ui/jobs/new` | 三步表单：目录/文件选择 → 三条预置流水线单选 → 预检与确认；右侧只读展示阶段链和服务端参数摘要 | capabilities、media、validate、POST jobs |
| 详情 | `/ui/jobs/:jobId` | 顶部文件/状态/操作；阶段卡按依赖拓扑排列；下方标签：任务、日志、字幕与产物、冻结参数 | detail/progress、logs、artifacts |
| 任务排障 | `/ui/tasks` | 按 stage/status/job/worker/更新时间筛选；显示 attempt、错误摘要、租约；点任务进详情对应 tab | tasks（稳定 DTO） |
| 归档历史 | `/ui/history` | 只读分页、归档原因/时间、原状态；详情仍可看日志/可用产物；无恢复按钮 | archives 新接口 |
| 系统状态 | `/ui/system` | 存活/就绪、每 ASR 前置条件、worker/缓存概况（只展示有数据的项）、清理策略、版本与部署能力 | capabilities、system/status、现有探针 |

### 3.3 新建作业细则

#### 3.3.1 简单目录/文件选择器

1. 点击“选择影片”打开弹窗：顶部为媒体根目录下拉框、当前路径面包屑、返回上级、刷新；中间为目录/视频列表；底部为已选文件与“取消/确认选择”。这是浏览服务器文件，不上传视频。
2. 单击目录名进入下一层，单击面包屑返回对应层；在根目录时禁用“返回上级”。视频行显示文件名、大小、修改时间；文件名旁勾选后点击确认，双击文件可快捷确认单片。
3. 提供当前目录文件名筛选、分页/加载更多；不做整个媒体库递归搜索。筛选必须由服务端应用于当前目录全部候选后再分页，不能只筛当前页。目录始终可进入，非支持视频不作为可选项。
4. 选择器只有浏览与选择，不提供删除/重命名/创建目录。仅显示管理员配置的媒体根，空根配置显示“尚未配置媒体目录”，不能回退到浏览服务器 `/`。
5. 确认后回到新建页，显示文件名、服务器路径、大小，可“重新选择”或移除。取消弹窗保留打开前已确认选择；切换目录不自动丢失已选项，也不把已选目录当作待运行文件。
6. 目录表示导航位置，不表示“处理该目录全部影片”。本阶段不做隐式递归提交。M1 支持单片；M3 增加跨目录文件多选、已选数量/清空/逐项移除，每批最多 50 个；所有批量提交必须展示明确文件清单。
7. 目录加载中保留面包屑与 loading；空目录、无匹配、根离线/权限不足、文件已删除分别提示并支持刷新。翻页响应不能覆盖后来切换的目录。选择完成到提交之间再次校验文件存在、类型与范围。
8. 不要求用户手工填写绝对路径；不提供额外“原始路径提交”主流程。路径展示只读，必要的定位仍通过根目录/面包屑完成。

#### 3.3.2 三条预置流水线单选

| preset_id（稳定标识） | 页面名称 | 只读阶段链 |
|---|---|---|
| `whisper-ja-zh` | Whisper 转写与翻译 | 抽取音频 → Faster-Whisper → 中文字幕翻译 |
| `whisperx-ja-zh` | WhisperX 转写与翻译 | 抽取音频 → WhisperX → 中文字幕翻译 |
| `qwen-ja-zh` | Qwen3-ASR 转写与翻译 | 抽取音频 → 本地 Qwen3-ASR → 中文字幕翻译 |

1. 以三张单选卡或单选列表展示，只能选一条；卡片显示简述、阶段链、就绪/不可用原因。禁止手动增删节点、连线、编辑 JSON 或切换翻译开关。
2. 流水线参数来自服务端现有配置/受控预置，只读展示；不要求用户填写 batch、超时、重试、模型路径或回写目录。源语言固定日语、目标中文，与当前任务口径一致。
3. 默认选 Whisper（延续当前默认）；若不可用则要求用户从其余可用项显式选择，不静默切换引擎。选择器始终展示三条，不因依赖缺失就把条目隐藏。
4. 预检及创建提交 `preset_id` 与可选 `expected_config_revision`；服务端解析预置并冻结 DAG/effective_config，前端不自行拼装 DAG。旧脚本的 dag/job_config 模式继续兼容，详见 §5/§6。
5. 确认页显示影片、流水线名称、三个阶段、只读生效配置、字幕回写位置/覆盖风险、相同路径已有作业及处置建议。预检不是资源预留，创建时仍完整校验。
6. `accepted=false` 不算创建成功：`idempotent_returned` 引导查看原 job，`rejected_started` 引导查看/重试/显式归档。不得自动归档历史绕过去重。
7. 提交成功直接进入详情开始监控；HTTP 超时显示“结果未知”，先按路径查证，不自动重复 POST。M3 多选逐项展示 accepted/reused/rejected/unknown，并且只补未确认项。

### 3.4 详情、状态与操作语义

- 阶段卡：阶段名、真实状态、attempt/max_retries、开始/结束时间、耗时、错误、worker、心跳/进度更新时间；blocked 展示阻断上游。
- percent 只表示当前阶段上报的进度，不等于整片总耗时完成率。无快照显示“暂无进度”；重启、TTL、重试后可消失，不能显示假 0% 或假 100%。
- 首期不显示预测 ETA，也不对 extract/ASR/translate 做等权伪总进度。attempt 不是不可重置的历史次数。
- 全部任务 cancelled 可显示“已取消”辅助标签，但保留 API 原 status=failed；状态筛选及指标不暗改枚举。
- 重试：确认框明确只重跑失败/阻断部分、参数不变、成功产物保留。变参需新建作业，先处理同路径占用；不是“编辑后续跑”。
- 取消：仅“取消尚未开始的作业”；运行中按钮禁用并说明，不把 drain 停机当取消。
- 归档：二次确认，说明“移出活动队列、释放路径占用，不等于删除媒体/产物”。queued 归档是放弃执行，需显著警告。
- 所有操作以服务端 `allowed_actions` 为准；点击时服务端事务内复核，409 刷新页面并显示冲突原因。
- 字幕 tab：JA/ZH 双栏按 cue 序号与时间展示、搜索、分页；不按相同行数强行宣称已对齐。文本用纯文本渲染，不插入 HTML。
- 本阶段不提供视频在线播放；M2 开放已发布字幕下载和字幕 tab。M2 日志 tab 支持阶段选择、增量加载、自动跟随/暂停、复制 request_id、下载限额内脱敏日志；M1 对应 tab 仅显示未交付说明。

### 3.5 提交后的监控闭环

监控不是只列一个“运行中”，而是覆盖排队、各阶段执行、异常、最终产物与历史：

| 场景 | 用户看到什么 | 刷新 / 后续动作 |
|---|---|---|
| 提交成功 | 自动进入作业详情，显示所选流水线、影片、Job ID 与阶段卡 | 当前详情每 2s 刷新；可回作业列表，离开页面不影响执行 |
| 排队 | Job 状态、各阶段待执行/等待上游；显示队列统计及可用排队信息 | 不把 queue_ahead 当稳定排名或预计等待时长；仅未开始作业可取消 |
| 抽音频/ASR/翻译 | 高亮当前阶段，阶段进度、执行器消息、开始时间、已耗时、worker、最近上报时间 | 未上报显示“暂无进度”；有批次/片段计数则展示 completed/total，无数据不编造 |
| 阶段切换 | 已完成阶段显示完成时间/耗时，下阶段转执行或等待；三阶段完成数例如 1/3 | 完成阶段数不是等权总进度百分比，不提供虚假 ETA |
| 疑似卡住 | 独立标记“进度长时间未更新”，保留数据库真实状态；区分网络断连/进度陈旧/租约过期 | 进度上报超过 60s 未更新仅作提示，可配置；若仅有 lease_expires_at，不伪称最后心跳时间；不自动重试或认定失败 |
| 失败/上游阻断 | 哪个阶段失败、错误摘要、attempt/重试预算、request_id；下游说明被哪个阶段阻断 | M1 看结构化错误，M2 一键进入对应阶段日志；符合条件才可原参数重试 |
| 完成但有警告 | 成功状态与“保留原文/覆盖率不足等实际已记录警告”分开展示 | 从结构化 warning_summary 提供计数/原因/来源；旧任务无摘要显示 unknown，不等于没有警告，不凭前端模糊解析日志判定 |
| 正常完成 | 三阶段完成、总耗时和各阶段耗时；M2 展示 JA/ZH 字幕、下载与回写校验状态 | 终态停止 2s 轮询；进入产物 tab 或手动刷新时重新确认可用性/是否已清理 |
| 服务断开/重启 | 顶部离线/重连提示、最后成功刷新时间，旧数据显示为陈旧 | 退避重连；恢复后重新取 Job/Task 状态，不能将重启后消失的内存进度填成 0% |

- **全局视角**：概览显示 Job 的排队/运行/成功/失败数量、各阶段 Task 队列、活跃 worker、近 5 分钟吞吐、服务就绪；Task 数不能冒充影片数。
- **列表视角**：按状态/流水线/文件名筛选；每行显示当前阶段、开始/更新时间、错误摘要，进入详情无需再找 Job ID。旧任务可从 DAG 派生三类流水线；自定义历史 DAG 标“历史自定义”，不放入新建选项。
- **详情视角**：概况和阶段卡始终可见；日志/字幕/只读配置在 tab 内。日志仅打开时轮询，支持暂停跟随，不把“暂停日志滚动”叫作“暂停作业”。
- **系统视角**：展示模型/各 ASR 前置、磁盘与清理策略；显存或探针不可用明确 unknown，不能据此假定没有 GPU 或保证不会 OOM。
- **批量视角（M3）**：逐片创建独立 Job；结果表显示每个文件的 Job 链接与提交结果，再跳列表按此次 Job 集合查看；不虚构一个有独立后端状态的批量 Job。运行监控仍使用列表分页摘要，不为每部后台展开 2s 轮询。
- **持久性边界**：Job/Task 状态、时间、错误、冻结流水线可重启后恢复；即时百分比是内存快照。结构化 warning_summary 为本阶段需补的持久摘要，完整执行事件历史仍在 P2。

## 4. 技术与部署设计

- 子仓库新增 `web/`：React + TypeScript + Vite；React Router 管路由、TanStack Query 管服务端数据、Ant Design 管表格/表单/抽屉。锁版本与 lockfile 进入 CI；不在本轮安装依赖。
- 表单校验可用 Zod/React Hook Form，但后端仍是唯一业务约束来源；元数据来自 §6，不在 TS 复制完整 stages/配置白名单。
- 页面按 `features/jobs|media|tasks|system` 拆分；统一 fetch 客户端处理超时、HTTP 错误、request_id、AbortSignal，不自动重试变更请求。
- DTO 类型从构建时生成的 OpenAPI/schema 导出；生产 `/openapi.json` 可继续关闭。客户端不读 INI、不直连 SQLite、不访问 artifact 文件系统。
- **生产同进程/同源**：FastAPI 在 `/ui/` 托管构建产物；根 API 路径保持不变，不额外引入 BFF 或第二份队列服务。`/` 可 307 到 `/ui/`。
- SPA fallback 只匹配 `/ui/**` 的页面导航，不吞 API 404，不把不存在的 JS/CSS 返回 HTML；缓存：hash assets 长缓存、index.html 不缓存。
- 开发时 Vite 代理明确列出的后端 API 路径；生产不依赖 Node 进程。不要用全路径 catch-all 代理破坏前端路由。
- 打包需确保静态资源随 Python 发行/部署可获得；web_enabled=false 保持纯 API 模式；web_enabled=true 但无 dist 应 fail-fast 报构建缺失，不出现半可用页面。
- worker/内存进度仍按当前单 runtime 架构运行，不借 Web 引入多 uvicorn worker；未来拆服务需单独设计。

### 4.1 同一 security 配置驱动前后端鉴权

**唯一事实源是服务启动时解析的现有 `[security]`，不新增一个独立前端鉴权开关。** 现有语义是 token 非空即校验，require_token 是启动时要求必须配置 Token，而不单独充当关闭开关；保持兼容，具体如下：

| require_token | api_token | 服务端及前端结果 |
|---|---|---|
| true | 合法非空值 | 开启 Token 鉴权，前端显示完整 Token 输入页 |
| true | 空值 | fail-closed，服务拒绝启动，不允许页面退化为无鉴权 |
| false | 合法非空值 | 仍开启 Token 鉴权（保留现有行为），前端仍要求 Token |
| false | 空值 | 关闭鉴权，前端直接进入工作台 |

占位值拒绝等现有启动校验继续生效；不在 SPEC 内存放用户真实 Token。配置修改按现有启动配置装配/重启生效，不承诺热更新。若要无鉴权须同时 require_token=false 且清空 api_token。

1. **公开启动面**：仅 `/ui/` 页面/静态资源、根跳转及 `GET /auth/config` 可无 Token 访问。该接口只返回 `auth_required/auth_scheme`，绝不返回 Token、部分 Token、长度、哈希、配置内容或媒体信息。既有 docs/metrics 关闭时的 404 语义不变。
2. **前端入口**：先取 auth/config；失败显示“无法确定访问模式”并重试，不默认放行。auth_required=false 直接进入；为 true 时，未有凭据则跳 `/ui/access`；已有本标签页凭据先验证再加载业务数据，防止业务数据闪现。
3. **Token 验证页**：仅一个完整 Token 输入框与“验证并进入”按钮，支持显隐；不提供用户名、密码、注册、找回密码或前缀匹配。后端用 `X-API-Token` 完整常量时间比较，不把前端判断当作验证；错误只提示 Token 无效，不回显输入或正确值。
4. **验证与请求**：`GET /auth/check` 经同一鉴权中间件校验，通过返回 `{authenticated:true}`，失败 401；无鉴权模式返回 `{authenticated:true,auth_required:false}`。成功后才访问业务 API；前端全部业务请求统一带 `X-API-Token`，不可写到 URL/query、HTML、bundle、日志或错误上报。
5. **凭据寿命**：建议默认只放当前标签页 sessionStorage 与内存（不放 localStorage、不建立用户/服务端 session）；刷新可恢复，关闭标签页后由浏览器会话机制清除，不承诺浏览器恢复会话时必然销毁。退出时主动清空凭据、表单、Query 缓存、正在进行的请求，回验证页；这是本地退出，不是全局 Token 吊销。仅同源脚本运行，额外防 XSS；不把浏览器存储称为加密保险箱。
6. **失效与轮换**：任一业务请求 401 即清凭据/缓存、取消轮询并回验证页，保留经校验的站内目标路径；不无限重试、不自动重放 POST。403（越界/策略）与 503（未就绪）不当成 Token 失效。Token 轮换并重启后原值失效，客户端重新输入；验证失败可按来源有界限流返回 429，验证响应 no-store。
7. **下载也鉴权**：字幕/日志下载用携带同一 header 的 fetch 取得 Blob 后保存，结束时撤销 object URL；不直接用无法附 header 的普通链接，不在下载 URL 放 Token。日志、媒体、归档、预检、healthz/readyz/metrics/admin 均继续受后端统一保护，禁止仅隐藏菜单却放开 API。
8. **路径与网络**：默认 127.0.0.1，Web 必须有非空媒体根白名单，artifact/log 根独立受限。无鉴权模式持续提示“所有可访问者均可操作”；Token 模式也没有多用户隔离。可信内网反代建议 TLS，非 loopback 传输 Token 必须使用 TLS 或等价受控加密通道，禁止明文暴露公网。
9. **Host/Origin**：不开通配 CORS；新增 `[web] allowed_hosts/allowed_origins/trusted_proxies`。默认 Host 仅 localhost/127.0.0.1/[::1]（端口按部署校验），Origin 仅明确配置的同源 scheme+host+port，trusted_proxies 为空；缺配置不能退化为通配。未知 Host、跨源变更、`Origin: null` 拒绝；缺 Origin 兼容 CLI，不代表可信身份。非 loopback 显式配置 Host/Origin，并通过防火墙/受限反代/隔离网段限制可达范围；只信任受配置代理提供的 forwarded 信息。
10. **管理策略**：`web.allow_shutdown=false` 时，Web 启用部署的停机写 API 在服务端拒绝（有效 Token 也不能越过此策略），不只是隐藏按钮；API-only 旧部署不变。若人工启用，需高危确认并说明无法从已经退出的服务启动它。
11. **脱敏与离线**：配置响应采用允许列表，未知字段不返回；日志/错误去除凭据/带密码 URL。已发布字幕正文不因脱敏而改写，下载保留原字节/hash；自然语言秘密不在自动识别保证内。ASR 音频/权重保持本地，翻译仅发字幕文本，前端不引入外部遥测/CDN。

## 5. 已有 API：复用范围与必要扩展

以下均为真实存在的路径，不改名、不强制迁移旧脚本。

| 方法与路径 | 用途 | 本阶段变化 |
|---|---|---|
| `POST /jobs` | 创建一个作业 | 保留请求/返回字段；补严格模型、错误定位、提交竞态校验；不把 accepted=false 改成成功 |
| `GET /jobs` | 分页/筛选 | 增加 ASR/当前阶段/任务计数/取消辅助标记/allowed_actions；保留旧字段；稳定同时间排序 |
| `GET /jobs/by-path` | 查询相同路径最近作业 | 保留；用于重复提交与结果未知查证，不代替最终入队事务 |
| `GET /jobs/{job_id}` | 详情与冻结配置 | 增加操作资格、输出可用性摘要；配置安全投影；旧记录标注配置来源 frozen/legacy_fallback |
| `GET /jobs/{job_id}/progress` | 详情+进度 | 保留兼容结构；新增进度可用/时间/attempt 身份，避免重试旧快照混入 |
| `POST /jobs/{job_id}/retry` | 原地失败重试 | 不变更范围；清理或隔离旧进度，事务内复核资格 |
| `POST /jobs/{job_id}/cancel` | 取消未开始任务 | 维持当前限制，不承诺运行中取消 |
| `POST /jobs/{job_id}/archive` | 归档释放路径 | 保留迁移语义；M1 成功回活动列表并提示；M2 才返回可用历史详情入口并跳转 |
| `GET /tasks` | 任务分页 | 保留旧字段，追加解析后的安全 task_config/摘要；不让 React 解析 DB JSON 与依赖编码 |
| `GET /queue/summary` | 阶段队列、worker、吞吐、停机 | 补 Job 总数/状态计数（不是 task 数）；缺数据用 available=false |
| `GET /healthz`、`GET /readyz` | 存活/通用就绪 | 复用；503 的结构化原因必须可读，不因非 2xx 丢掉响应体 |
| `GET /metrics` | Prometheus | 保留，网页不解析 Prometheus 文本当业务 API |
| `POST /admin/shutdown`、`GET /admin/shutdown/status` | drain | 按 §4.1 的 Web profile 策略控制写接口；无“重启”伪按钮 |

兼容原则：新增字段为主；保留既有合法请求、成功结构、accepted/message 与状态机语义。已知 DAG/job_config 业务校验错误继续返回 400，Pydantic 请求结构错误仍 422；不把所有错误一律改 422。筛选的非法枚举/无时区或无法解析日期从原宽松行为收紧为 422，这属于有意兼容例外，Web 与 API-only 均生效，须发布说明并测试。CreateJobReq/OpenAPI 新增可选 `preset_id: str | None = None` 与 `expected_config_revision: str | None = None`；language 改为仅 legacy 模式必填，preset 模式由服务端固定 ja。preset_id 非空时禁止同时提供 language/dag/job_config（包括显式空对象），冲突 400 preset_input_conflict；未知 preset 返回 400 preset_not_found。省略 preset_id 时按旧字段/旧默认 DAG 处理，保留合法旧请求行为。验证请求与创建使用同一个解析器，preset 模式服务端选取三条之一并冻结预置版本与配置摘要。严禁泄漏的字段即使历史存在也必须安全投影，并在变更说明登记。对旧脚本合法输入与上述有意收紧分别做契约测试，不笼统承诺所有旧非法输入兼容。

## 6. 必须补齐的 API 契约

共 14 条新增 method+path 路由、13 类能力（归档列表/详情合为一类）；全部是设计目标，**当前尚不存在**。固定字面路由如 `/jobs/validate` 必须在动态 job_id 路由前注册。

### 6.0 鉴权启动与验证

- `GET /auth/config`：公开，返回 `{auth_required:boolean,auth_scheme:"api_token"|"none"}`，从后端实际 security policy 派生，不读取另一个前端开关。no-store；不返回任何凭据/业务信息。关闭 Web 时可不注册这两个新接口，不改变 API-only 入口。
- `GET /auth/check`：采用现有 `X-API-Token` 中间件，返回 `{authenticated:true,auth_required:boolean}`；错误 Token/缺 Token 在开启鉴权时 401，校验失败可 429 限流。无副作用、不加载模型、与 readyz 无关，不能因模型未就绪就误判 Token 错误。no-store，错误响应不回显请求头。
- 静态页与 auth/config 是精确的公开例外，禁止把整个 `/auth/*` 或 `/ui/*` 之外的业务路径无条件豁免。新增下载 API 仍走同一中间件；完整流程见 §4.1。

### 6.1 能力与系统

- `GET /capabilities`
  - 返回 `schema_version/service_version/web_base_path/server_time/features/limits/stages/presets/languages`。
  - 每 stage 提供 `name/asr/available/unavailable_reasons/config_fields/defaults`；field 提供 `key/type/unit/min/max/enum/nullable/job_override/description`。
  - defaults 必须来自当前 settings 与同一 effective-config 构建逻辑；字段元数据仅供只读说明，不渲染编辑表单。presets 恰好三项（§3.3.2），每项含 preset_id/name/description/dag/preset_revision/config_revision/available/unavailable_reasons；源语言/参数/部署字段只读，密钥完全不返回。任一 extract/所选 ASR/translate 前置不满足，该完整预置即不可用。
  - 重构 Python 注册表/校验元数据为单一事实源，现有校验调用它；不手写第二套前端参数规则。
  - `available` 仅指依赖/目录/配置静态前置条件，不保证实时显存足够；不得为探针加载模型或发外网请求。
- `GET /system/status`
  - 返回 `timestamp/uptime_sec/readiness_by_stage/storage/cleanup/shutdown/features`。整合现有探针/队列，不另建监控系统。
  - storage 至少含 artifact/log 根所在分区剩余字节；相同分区不重复求和。GPU 信息可为 `{available:false,reason}`，不可填 0 冒充测量。
  - 翻译只显示“已配置/缺配置”，无网络调用时不显示“供应商连接正常”。

### 6.2 媒体选择与预检

- `GET /media/roots`：返回 `{items:[{root_id,label,available,reason}]}`，不允许客户端自行注册根。
- `GET /media/entries?root_id=...&relative_path=...&q=...&cursor=...&page_size=100`
  - 返回 `{items:[{name,relative_path,kind,size_bytes,mtime,canonical_video_path}],next_cursor,skipped_count}`；视频项必须含 canonical_video_path，目录项该字段为 null；默认 100、上限 200；目录优先且稳定按名称排序。
  - q 为当前目录视频文件名子串筛选，先筛选后分页，目录仍保留以便导航；游标绑定 root_id/relative_path/q/目录版本。目录变化返回可恢复的 cursor_expired，前端重新加载。仅一层；隐藏文件/越界链接不列出，并给 skipped_count（不泄漏路径）。目录枚举耗时/条目有上限，超限提示范围过大而不是隐式省略，实施计划冻结具体限额。
  - 服务端 strict resolve、根包含判定、文件类型/扩展名/符号链接复核；未知 root 返回 404、越界 403。不得使用字符串 startswith 判断目录包含。
- `POST /jobs/validate`：请求与 CreateJobReq 一致；不落 Job/Task、不占队列、不启动模型。
  - 返回 `{valid,normalized_request,effective_config,config_revision,existing_job,checks,warnings,errors}`；错误含 `code/field/stage`。
  - 检查媒体存在/普通文件/路径、DAG/参数、ASR 前置、copy_back 边界与目标冲突、磁盘最低水位；必要媒体信息用有界 ffprobe（超时/并发上限，非 shell 拼接）。
  - Web 预检请求为 `{video_path,preset_id,expected_config_revision?}`，video_path 来自目录选择返回的 canonical_video_path；前端不提交 dag/job_config/language，也不把只读 effective_config 回传为覆盖值。服务端返回 normalized_request 保持 preset 模式，并另给只读 resolved_dag/effective_config 摘要；创建仍由服务端同一解析器决定配置，不信任前端回传摘要。旧脚本手输路径仍受同一边界校验，但网页不提供手填路径主流程。
  - valid=false 用 200 表示完成预检但未通过，结构错误用 422；I/O/ffprobe 超时用显式检查失败，不隐式忽略。
  - 预检返回配置版本；创建可选携带 `expected_config_revision`，若设置且服务端配置变化返回 409 config_changed，要求重看摘要。旧客户端可不传。
  - 预检期间不写生产媒体；回写权限可声明“静态检查/未实写验证”，最终仍由执行器判定。预检与创建共享纯规划逻辑，不复制入队代码。

### 6.3 日志

- `GET /tasks/{task_id}/logs?cursor=...&limit_bytes=65536`
  - 返回 `{task_id,items,next_cursor,eof,truncated,source_reset}`；item 至少 `text`，能解析时附 timestamp/level/event，不把不规范旧行丢掉。
  - opaque cursor 绑定文件身份/偏移；默认尾部 64 KiB、单次上限 256 KiB；截断/轮转需明确标记，字节边界不破坏 UTF-8。
  - 从 DB task_id 找日志，兼容活动/归档表；不接收 path，不提供目录静态托管。路径只允许在 log_root 下并防 symlink 替换。
  - 未生成日志返回空列表+原因；task 不存在 404；文件不可读显式错误。日志必须脱敏、纯文本渲染，禁止前端 `dangerouslySetInnerHTML`。
- `GET /tasks/{task_id}/logs/download`：下载脱敏文本；默认最大 10 MiB，超出返回 413 log_too_large 并提示分段读，不静默只给尾巴。不直接返回原始文件。

### 6.4 产物与字幕

- `GET /jobs/{job_id}/artifacts`：兼容活动与归档 Job，返回 `{items:[{artifact_id,kind,stage,filename,status,provenance,size_bytes,sha256,published_at,expires_at,downloadable,validation,copy_back}]}`。
  - status 为 `pending/available/expired/missing`，provenance 独立为 `fenced/legacy/unknown`；历史发布时间不可证实则 null，sha256/validation 未计算必须 null/unknown，不能用存在/非空冒充字幕内容已验收。
  - 只枚举 fenced 发布的正式产物，不暴露 staging、检查点原文、任意文件；默认只可下载 JA/ZH SRT，音频下载本阶段关闭。
  - copy_back 单独表示目标存在/哈希验证状态及采样时间，不因任务 succeeded 就推断回写仍在。原文件清理后不自动改指向回写文件。
- `GET /jobs/{job_id}/artifacts/{artifact_id}/content`
  - attachment 下载正式字幕，设置安全 filename、Content-Type、Content-Length、ETag 与 nosniff；artifact_id 由服务端映射，不能等于任意相对路径。
  - 未发布 409 artifact_not_ready；已知清理 410 artifact_expired；意外丢失 404 artifact_missing；禁止下载目录、链接越界文件。
- `GET /jobs/{job_id}/artifacts/{artifact_id}/cues?page=1&page_size=100&q=...`
  - 返回 `{items:[{index,start_ms,end_ms,text}],total,page,page_size,validation,sha256}`，单页上限 500；只对正式字幕解析，非法 SRT 返回 422 invalid_subtitle。
  - 解析结果绑定发布哈希并缓存；只读，不提供修改/覆盖。JA/ZH 对照按 index/time 展示差异，不按数组偏移配对。

### 6.5 归档读取

- `GET /archives/jobs`：沿用 Job 列表分页/路径/状态/语言/日期筛选，增加 archived_from/archived_to，返回 archive_reason/archived_at。
- `GET /archives/jobs/{job_id}`：返回与活动详情一致的安全 DTO，另加 archived_at/archive_reason/readonly=true；allowed_actions 全 false。
- 这两条算一类接口；日志和 artifact 服务按 ID 同时查活动/归档，不复制两套读取实现。普通 `/jobs/{id}` 的 404 行为保持兼容。

## 7. 数据契约与持久化缺口

1. **DTO 层**：定义 JobSummary、JobDetail、TaskView、AllowedActions、CapabilityField、ArtifactView、LogPage；禁止把 SELECT * 直接作为新 UI 契约。旧 JSON 字符串字段仅为兼容保留字段名，内容须先解析、按允许列表投影后重新序列化；不能只用正则遮盖后透传未知嵌套字段。新页面使用同源安全投影的解析字段。M1 的输出可用性一律 unknown、仅展示服务器路径，不提供基于文件存在的下载/expired 推断；M2 再接 manifest。
2. `allowed_actions` 至少含 retry/cancel/archive 与 disabled_reasons；复用仓储事务规则。全 cancelled 的 failed Job 不可 retry；不能仅按 job.status=failed 显示可重试。
3. 详情输出 DAG 原边与阻断原因，前端不解析 depends_on_task_id 的内部序列化。列表增加 current_stages/asr_stage/preset_id/preset_name/task_counts/cancelled_by_user/warning_summary 等摘要，避免每行再请求详情的 N+1。增加 preset_id 筛选；M3 增加最多 50 个 job_ids 筛选用于批次结果集合查看（集合与其他筛选取交集）。不把历史自定义 DAG 错归类为三条预置之一。
4. 列表补稳定 tie-breaker（时间+job_id），日期入参使用带时区 RFC3339 并转换 UTC；非法枚举/日期返回字段化 422，不默默接受无效筛选。
5. **进度身份**：至少带 attempt+lease 身份或新增不可重置 run_generation；retry/重新领取时清除旧快照，terminal UI 以 DB 为准。服务重启不伪造历史进度。
6. **产物 manifest**：增加发布记录（artifact_id/job_id/task_id/kind/正式路径/发布身份/大小/hash/验证摘要/发布时间/清理时间与原因）。计算 hash/校验在发布流程完成，不在 2s 轮询重复读大文件。
7. manifest 必须接入现有租约 fencing，旧 attempt 不可登记/覆盖新产物；文件 rename 与 DB 不是真正跨资源原子事务，复用当前发布锁并加启动/读取 reconciliation。任何不一致标 missing/unknown，不宣称完全原子。
8. **清理可解释性**：清理器记录删除意图/结果，已成功删除才标 expired；失败保留错误与实际状态。TTL 页面展示来源，日志保留策略与 artifact TTL 分开。manifest 不因归档丢失，不新增强制级联删除破坏历史。
9. **历史兼容**：旧 Job 无 manifest 时，只从冻结 io/既有标准路径严格校验后懒生成记录，禁止递归猜测最新文件；没有可信发布身份的旧产物标 legacy，不能伪称 fenced/hash 已验证。
10. 日志按 task_id 已可找到，但 attempt 会重置，完整“第几轮人工重试/每次日志独立文件”的历史审计不是现成能力。MVP 使用日志事件和源身份；完整执行历史列为扩展，不能用当前 attempt 充当累计次数。
11. **预置身份（M1）**：Job 创建时持久化 preset_id/preset_revision/preset_name 与已冻结 DAG/配置，归档同步保留；预置日后变化不回写旧任务。旧记录只可按准确 DAG 结构展示推导名称且标 inferred，不伪造曾使用某个预置版本。preset/config_revision 是不含秘密的 opaque 版本，预检到入队用同一配置快照比较，不以公开秘密值哈希暴露凭据。
12. **监控摘要（M2）**：从执行器结构化结果/事件收集 warning_summary（available/items[{code,count,stage,source}]）、实际可获得的进度计数。发布时绑定当前执行身份并持久化，重试不混用旧 attempt 的警告；不从任意日志正则猜测质量结论。M1/旧任务无来源时返回 available=false/unknown，前端不称“无警告”。
13. 数据库 migration 必须兼容已有 jobs/tasks 与 archive 表，先备份并测试升级/回滚策略；禁止重建数据库或迁移时改写既有字幕。

## 8. 通用错误与刷新约定

- 新接口错误统一 `{detail:code,error:{code,message,field_errors,retryable},request_id}`；保留现有 detail，兼容已有 string/list detail，错误信息不可含密钥。
- 400 业务输入错误；403 越界/禁用操作；404 不存在；409 状态/版本冲突；410 已清理；413 大小超限；422 schema/字幕结构错误；429 限流；503 未就绪。
- 浏览器错误 toast 展示中文原因+request_id+建议；详情保留上下文，不把失败全变成“网络异常”。404、空队列、尚无日志、已清理字幕各有独立空态。
- 活动作业详情/进度 2s；列表/队列 5s；系统状态/readyz 30s（readyz 有真实写探测，不得高频调用）。终态详情停止进度轮询，日志仅在打开 tab 时增量读。
- 页面不可见停止轮询；网络错误指数退避最高 30s，恢复后刷新；请求串行/取消旧请求，避免慢响应覆盖新筛选；已显示数据标“过期”而非假装最新。
- M1 不引入 SSE/WebSocket。先证明轮询负载可控，若未来推送须有断线重连/序号/补读/退回轮询，不作为核心可用性前提。
- 单个浏览器只轮询当前页，不轮询全部历史；后端日志/预检/目录浏览有并发与响应体上限。服务端明确限制资源耗费，关闭鉴权不是允许无界请求。

## 9. 功能缺口总清单与实施文件边界

| 编号 | 必补功能 | 主要实施位置（子仓库；新增名为建议） | 分期 |
|---|---|---|---|
| F01 | React 脚手架、导航、公共组件、API 客户端、错误/空态、响应式 | 新增 `web/` | M1 |
| F02 | 共用 security 的 Token 页面/公开模式查询/完整 Token 校验/401清理、Host/Origin、停机策略、静态托管 | 现有 [app.py](../../../whisper-stt/whisper_stt_service/api/app.py)、[core/config.py](../../../whisper-stt/whisper_stt_service/core/config.py)、[bootstrap.py](../../../whisper-stt/whisper_stt_service/service/bootstrap.py) | M1 |
| F03 | DTO、脱敏、allowed_actions、列表摘要/稳定排序、进度身份 | 现有 [schemas.py](../../../whisper-stt/whisper_stt_service/api/schemas.py)、[jobs.py](../../../whisper-stt/whisper_stt_service/api/routes/jobs.py)、[job_repository.py](../../../whisper-stt/whisper_stt_service/repo/job_repository.py)、[progress.py](../../../whisper-stt/whisper_stt_service/core/progress.py) | M1 |
| F04 | 三条固定预置及服务端解析/身份冻结、只读阶段参数能力表/系统状态、每预置前置检查 | [core/stages.py](../../../whisper-stt/whisper_stt_service/core/stages.py)、[core/dag.py](../../../whisper-stt/whisper_stt_service/core/dag.py)；新增 capability/system route + service | M1 |
| F05 | 受限目录浏览、预检与配置版本、copy_back 风险展示 | 新增 media/planning service 与 routes；复用 [core/security.py](../../../whisper-stt/whisper_stt_service/core/security.py) | M1 |
| F06 | 概览/列表/新建/详情/任务页，既有 retry/cancel/archive 操作 | 新增 web features；扩展 [queue.py](../../../whisper-stt/whisper_stt_service/api/routes/queue.py) | M1 |
| F07 | 有界增量日志/脱敏下载、文件安全读取 | 新增 log service/routes；复用 DB 日志索引 | M2 |
| F08 | manifest、字幕结构校验、预览/鉴权下载、清理状态与 legacy 兼容、结构化警告摘要 | [service/runtime.py](../../../whisper-stt/whisper_stt_service/service/runtime.py)、[repo/migrations](../../../whisper-stt/whisper_stt_service/repo/migrations/__init__.py)；新增 artifact service/routes | M2 |
| F09 | 归档分页/详情、history 页面，归档日志/产物共享读取 | 扩展 repository；新增 archives route / history feature | M2 |
| F10 | 多片逐项提交/结果未知恢复/仅补未确认项 | web 新建页与批次结果视图；不新增整批原子语义 | M3 |
| F11 | 单发行包静态资源、前后端 CI、浏览器测试、运维与回归文档 | [pyproject.toml](../../../whisper-stt/pyproject.toml)、[CI](../../../whisper-stt/.github/workflows/ci.yml)、新增 web test/build；两份 README | 各期，M3 收口 |

不修改已发布产物，不把后端全仓重构当作前端前置；阶段注册/校验必要的元数据归一单独提交并回归。实现与测试在子仓库；本 SPEC、计划与验收记录仍仅在主仓库 docs。

## 10. 分期与发布闸门

### M1：能够提交、监控、做正确的既有控制

交付 F01–F06，形成基础工作台；capabilities.features 显式返回 logs/artifacts/archives 的交付开关。M2 未交付前：输出可用性为 unknown，字幕/日志/历史入口明确标记不可用，不请求尚未存在的接口；归档成功跳回活动列表并显示成功提示，不跳转未实现的历史页。M1 是内部里程碑，**不能标记整个 Web roadmap 完成**。

### M2：能够排障与交付产物

交付 F07–F09；用户不必 SSH 即可查脱敏日志、看/下载已发布字幕、查询归档。清理/历史/重试语义正确，此时达到单片完整闭环。

### M3：批量易用性与正式发布

交付 F10，完成 F11、完整测试及真实媒体验收；完善可访问性/弱网状态。正式版本号发布时另定，不预先声称 v0.6.0 已实现。

M3 验收后才更新 [中文 README Roadmap](../../../whisper-stt/README.zh-CN.md#L376-L383) 与 [英文 README](../../../whisper-stt/README.md) 的 Web 控制台为完成；Docker/多用户等未实施项仍保留未完成。本次规划不改完成标记。

## 11. 验收标准（实施前冻结种子/输入/判据）

### 11.1 后端契约与兼容（CPU/fake executor）

- Web 恰好三条固定预置，每条映射到正确 extract/ASR/translate 链；网页无手动参数/DAG/翻译开关。未知 preset、preset 混传 language/dag/job_config 全部拒绝；服务端冻结与只读摘要一致。legacy API 仍支持原有合法的三 ASR×是否 translate 组合；空/双 ASR、无 extract、错误依赖、越界参数仍拒绝且定位字段。
- 旧 POST/查询/归档/重试/取消脚本兼容；accepted=false、400/409/422/503 等响应在页面含清晰原因与 request_id。
- 取消与 claim 竞态、归档与运行竞态、retry 与旧 progress 竞态、配置预检到提交变化均有确定性测试；不能只测按钮禁用。
- 全 cancelled Job 的失败原状态/辅助文案/retry 禁用一致；归档后活动 404、历史可读，产物与日志可定位。
- 媒体/日志/产物接口覆盖 `../`、编码穿越、绝对路径注入、未知 ID、symlink 逃逸/替换、隐藏文件、大目录与日志轮转。
- manifest/fencing/reconciliation/legacy/清理失败覆盖：旧 attempt 不可发布，已清理 410，意外丢失 404，未发布 409，非法 SRT 422。预览/下载 sha256 与正式产物一致。
- 将 canary secret 注入配置凭据、异常、日志、旧 JSON 未知嵌套字段，确认浏览器可见 API/日志/HTML/bundle 不泄漏；不以只检查配置页代替全响应扫描。字幕正文不作为凭据脱敏输入，另测下载原字节/hash 不变，避免用修改原字幕换取扫描通过。
- §4.1 四种 security 组合覆盖启动/前端模式/后端一致性；有效完整 Token 通过，空值/错误值/正确前缀或后缀/伪造本地“已验证”状态均不能访问业务接口。静态资源与 auth/config 公开但不泄漏业务；auth/check 不依赖模型/DB 就绪，错误 Token 仍 401。
- 手工绕过前端直接请求媒体/日志/产物/下载/归档/预检/health/metrics/admin，在 Token 模式未提供正确 header 均被拒；关闭鉴权时直接进入。旧 API-only Token 模式仍可用；默认 loopback/根白名单/Host/Origin/停机限制通过；不调用在线翻译探活。

### 11.2 前端与浏览器

- 单元测试：DTO adapter、错误兼容、三条预置单选与纯只读参数、操作资格、状态投影、unknown 提交结果恢复、Token 模式与凭据清理；不以 UI 只做前缀验证代替完整后端校验。
- 选片器浏览器测试：进入目录/上级/面包屑、跨页文件名筛选、单选确认/取消、根离线/权限不足/空目录/文件删除、重新选择；M3 验证跨目录多选去重与显式文件清单，不递归提交整个目录。
- 鉴权浏览器测试：启动模式加载、完整 Token 正误、刷新恢复、直接深链接/安全站内返回、退出清空缓存/中止请求、服务重启轮换后 401 回验证页；403/503 不误踢出，不能在验证前闪现旧业务数据。Token 不出现在 URL、bundle、下载链接或日志，下载仍能携带 header。
- 监控测试：阶段切换、缺进度、超过阈值陈旧但仍运行、网络断线与真实失败区分、成功带警告、重试不显示旧轮次进度/警告、终态停止轮询及产物 tab 重查过期。
- Playwright + fake executor：服务器选片→预检→提交→完成→字幕双栏→下载，另覆盖失败→日志→重试、queued 取消、归档→历史查询。
- 浏览器刷新深链接可用；API 404 不是 index.html；JS 404 正确失败；offline/503/409/410/空日志均有专用状态。
- 1280/768/375px 基础流程可操作，键盘焦点/表单标签/状态非纯颜色；日志与字幕恶意 HTML 不执行。
- 前端依赖安装锁定、typecheck、lint、unit、build、浏览器 E2E 纳入 CI；后端既有测试仍通过，新增测试不依赖真实 GPU/LLM。

### 11.3 性能与真实交付（目标，不是现测结果）

- **2026-11-01 修订：删除“10,000 Job/30,000 Task 夹具 + 20 行列表 p95 ≤500ms”目标**。本机不存在该规模场景，不建大夹具、不设 p95 门槛、不需要测量脚本。仍然要求实现层面不引入 N+1（列表一次查询带摘要、不逐行请求详情），但这是设计约束，不作为独立性能验收项。
- 5 个并发浏览器详情持续 10 分钟：无重叠无限轮询/持续内存增长、无 worker 饥饿；日志请求每次不超限；readyz 不按详情频率执行。
- 静态 Web 首屏不依赖外网资源；服务重启后提示并恢复刷新，不把旧进度当新执行；只改变部署构建，不擅自重启真实在途作业。
- 经用户选择至少一部测试媒体，由网页走完整流程；先用 fake/小片，再批准真实模型与可能计费翻译。记录输入 hash、代码/config 指纹、Job ID。
- 最终检查 SRT 结构/时间/条目、source→translation ID 一致性、正式产物与下载 hash、copy_back hash；有降级保留原文必须显式告警。退出码/Job succeeded/文件非空均不是单独通过判据。
- ASR 不出网、浏览器无外部遥测；日志中不出现密钥；未覆盖的 GPU 峰值/崩溃恢复等边界单列，不能自动沿用历史验收结论。

## 12. 扩展待办（不阻塞 M3；不是已经存在的能力）

| 优先级 | 功能 | 必须先补的后端契约 |
|---|---|---|
| P2 | 大视频上传 | 分片/配额/磁盘水位/校验/续传/取消/过期回收；最终仍只保存服务器端并走路径策略 |
| P2 | 翻译已有 SRT | 新输入类型与 DAG 语义、SRT 导入/校验、输出路径、检查点身份；不能破坏唯一 ASR 的旧视频模式 |
| P2 | 运行中取消 | 可持久取消信号、执行器安全点、子进程/GPU 释放、租约 fencing、检查点/部分产物保留与终态定义 |
| P2 | 从指定阶段重跑/复制变参 | 输入 hash/配置指纹决定无效化闭包、新 Job 血缘、产物只读引用/复制、显式 copy_back 覆盖策略 |
| P2 | 全局配置在线编辑/模板管理 | 可编辑字段白名单、密钥只写、版本冲突、持久化/校验、重启边界、作业冻结不受影响 |
| P2 | 独立执行历史/事件流 | 不可重置的执行轮次、事件 ID/保留策略、断线补读；再考虑 SSE |
| P2 | 视频与字幕联动播放/字幕编辑 | Range 流媒体、安全转码、格式兼容；编辑副本/版本/发布审核，不覆盖流水线原产物 |
| P2 | 磁盘清理管理/恢复归档 | 只读用量先行；预览删除清单、引用检查、幂等清理、恢复后的路径占用冲突，不能直接 unlink 任意路径 |
| P3 | Compose/模型管理/GPU 调度/告警 | 本地模型挂载、单 runtime、资源整机口径、持久卷迁移、健康/告警契约；单独 SPEC |
| 不在本路线 | 多用户/角色/配额 | 本期仅共享 API Token 或关闭鉴权，不提供用户名/密码/账号体系；多用户须另立安全设计 |

## 13. 待评审决策与建议默认值

这些不是对既有实现的事实描述；若无额外需求，建议按右列实施，变更需更新本 SPEC。

| 决策 | 建议默认 |
|---|---|
| 部署范围 | 本机/可信内网，支持 Token 开/关；非 loopback 传 Token 须 TLS/受控加密通道，不做公网产品 |
| UI 与语言 | 中文、桌面优先、React+TS+Ant Design；可读英文技术名，不先做全量 i18n |
| 输入（已确定） | 简单服务器目录/文件选择器，不要求手填路径；上传留 P2 |
| 流水线（已确定） | 恰好三条完整预置单选，默认 Whisper；无参数/DAG 编辑或翻译开关；不可用时明确提示 |
| 翻译 | 三条均保留当前日→中；UI 提示字幕文本可能发给配置的 LLM，不外发音频 |
| 参数与模板 | 服务端受控预置/现有配置决定，网页只读，不提供自定义模板编辑 |
| 作业控制 | 原样保留失败重试/未开始取消/归档；不改运行中取消语义 |
| 鉴权（已确定） | 前后端共用现有 security；开启时完整 Token 页+X-API-Token，无用户名/密码；关时直入 |
| 管理策略 | 无多用户角色；停机写操作在 Web 启用部署默认关闭，全局配置只读 |
| 刷新 | 有界轮询，不先做推送 |
| 正式完成边界 | M1+M2+M3 全部验收后才勾 Web roadmap；扩展待办另立 SPEC |

## 14. 本次交付与未验证项

- 已完成：源码/文档静态探查、页面设计、复用接口盘点、新增接口契约、功能缺口/分期/验收规划。
- 未实施：所有 React 页面、后端新增接口、DTO/安全/manifest/部署修改。
- 未验证：在线服务实际路由/配置、浏览器效果、性能、模型与真实媒体链路；本文不声称这些验收已通过。
- 下一步：评审 §4.1 与 §13；通过后按 M1/M2/M3 拆文件级实施计划，再开始功能开发。

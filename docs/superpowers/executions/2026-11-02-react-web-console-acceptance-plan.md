# React 工作台验收计划（种子与判据，验收前冻结）

- 日期：2026-11-02（Asia/Shanghai）
- 对象：`feat/react-web-console` 分支（子仓库工作树 `.worktrees/react-web-console`）
- 需求权威：[React 工作台 SPEC](../specs/2026-11-01-react-web-console-spec.md)（§11 为验收标准来源）
- 本文件在验收**开始前**冻结：样本、命令、判据、证据格式、未覆盖项。
  验收过程中不得因为"跑不过就放宽判据"而修改本文件；确需修订必须写明原因与影响面。

## 0. 角色与独立性（硬约束）

| 角色 | 要求 |
|---|---|
| 实现者 | 参与编写的代理/会话，**不得**担任本轮验收人 |
| 验收人 | 由总调度另派**未参与实现**的独立子代理执行；至少 3 个方向：后端契约、前端浏览器、安全边界 |
| 复核人 | 总调度只做证据汇总与冲突裁定，不替代验收人下结论 |
| 取证方式 | 只认"命令 + 真实输出 + 文件行号"；不认"我看过代码觉得没问题" |

验收人回报必须包含：通过项（命令+输出摘要）、失败项（复现命令+报错）、未覆盖项、以及
"是否发现实现与 SPEC 不一致"的逐条结论。

## 1. 环境与冻结输入

| 项 | 值 |
|---|---|
| Python | `/home/base/repo/video-stt-whisper-server/.venv/bin/python`（3.10），禁止新建 venv |
| 工作目录 | `/home/base/repo/video-stt-whisper-server/.worktrees/react-web-console` |
| 后端测试 | `python -m pytest -q`（默认跳过 manual/e2e，CPU-only，不联网） |
| 前端测试 | `cd web && pnpm typecheck && pnpm lint && pnpm test && pnpm build` |
| 浏览器 | Chromium（Playwright）；无网环境允许跳过 E2E 并以"未覆盖"记录，不得记为通过 |
| 测试媒体 | **不启用真实媒体/真实模型**；统一用 fake executor + 临时目录假视频（0 字节文件 + 白名单扩展名） |
| Token | 只使用测试用随机串（如 `test-token-<random>`），不得使用用户真实 Token，不得写入仓库 |
| 基线 | 开工前 `main@3185a9d`：`618 passed`；验收时新增用例数须在报告中给出 |

**代码指纹**：验收人必须记录 `git -C .worktrees/react-web-console rev-parse HEAD` 与
`git status --short`；工作区有未提交改动时，验收结论注明"基于工作区快照，未提交"。

### 1.1 GPU 占用窗口约束（2026-11-03 用户指示）

本机现有另一条**真实媒体长测**正在占用 GPU。在用户明确通知"长测已停"之前：

- 本轮所有验收**只做 CPU 烟测**：fake executor、0 字节假媒体、`TestClient` / Playwright；
  禁止启动 faster-whisper / WhisperX / Qwen3-ASR / 在线翻译 LLM，禁止任何会加载模型或做真实解码的用例；
- 临时实例的 `runtime.model_path` 必须指向**不存在**的目录（能力接口会如实返回 `model_path_missing`），
  这样即使误提交作业也只会快速失败，不会触达 GPU；
- 真实媒体端到端（SPEC §11.3「经用户选择至少一部测试媒体」）**推迟**到用户通知后执行；
  其结论不得用 CPU 烟测替代，也不得沿用历史阶段的验收结论。


## 2. M1 判据（能提交、能监控、控制正确）

### 2.1 后端契约（CPU / fake executor）

| 编号 | 判据 | 反例（不得通过） |
|---|---|---|
| B1 | `/capabilities` 恰好返回三条预置，顺序 `whisper-ja-zh → whisperx-ja-zh → qwen-ja-zh`，每条 DAG 唯一 ASR 且依赖 extract、translate 依赖该 ASR | 返回 2 条 / 4 条、允许自定义 DAG、缺 `available` 字段 |
| B2 | `preset_id` 未知 → 400 `preset_not_found`；与 `language/dag/job_config` 任一同时出现（含 `{}`）→ 400 `preset_input_conflict` | 静默忽略冲突字段、返回 422 或 500 |
| B3 | 预置模式创建成功时，服务端冻结的 DAG/配置与 `/capabilities` 返回的该预置摘要一致（同一次请求内比对），响应含 `preset_id/preset_name/config_revision` | 前端可覆盖参数、冻结摘要与能力表不一致 |
| B4 | 旧 legacy 请求（`video_path+language`、显式 `dag`、`job_config`）行为不变：合法组合成功、accepted/message 语义不变 | 旧脚本 4xx、accepted=false 被当成功 |
| B5 | `GET /jobs` 每行含 `asr_stage/current_stages/task_counts/allowed_actions/preset_id`，且**不为每行再请求详情**（单次请求 SQL 次数有上界，用 repo 调用计数或日志断言） | N+1、字段缺失、把 Task 数当 Job 数 |
| B6 | `allowed_actions` 与状态机一致：全 cancelled 的 failed Job `retry.allowed=false`；running Job `cancel.allowed=false`；archived 全 false；每条 false 都有 reason | 仅按 `job.status` 判断、无 reason 字符串 |
| B7 | 进度身份：任务重试/重新领取后，旧快照不得以 0%/旧百分比出现（`progress.available=false` + reason），且 `stale` 只在超阈值时为 true、不改 job 状态 | 显示假 0%、把陈旧当失败 |
| B8 | 400/409/422 响应同时含 `detail`（旧语义）与 `error{code,message,field_errors,retryable}` + `request_id`；`422` 的 `detail` 仍是列表 | 只有新结构（旧脚本崩）、或只有 detail（新前端拿不到码） |
| B9 | 日期/枚举筛选非法值 → 422 且 `field_errors` 指向字段（这是 SPEC 允许的有意收紧），合法 RFC3339 带时区值生效 | 静默忽略非法筛选 |
| B10 | 归档后 `GET /jobs/{id}` 404、`GET /archives/jobs/{id}` 可读、其日志/产物按 SPEC 语义可定位（M2 判据） | 归档队列/详情仍能从活动列表查到 |

### 2.2 安全与部署（§4.1 四种组合）

| 编号 | 判据 |
|---|---|
| S1 | `require_token=true` + 合法 token：`/ui/` 与 `/auth/config` 匿名可取；任意业务 API 无 header → 401；正确 token → 200 |
| S2 | `require_token=true` + 空 token：启动拒绝（fail-closed），不出现"退化为无鉴权"的服务 |
| S3 | `require_token=false` + 非空 token：仍要求 Token（前端仍进验证页） |
| S4 | `require_token=false` + 空 token：前端直接进入；`/auth/config` 返回 `auth_required=false` |
| S5 | `auth/config` 响应体不含 token、长度、哈希、配置内容；`no-store` |
| S6 | 前缀/后缀/大小写伪造的"接近 token"一律 401；前端本地伪造"已验证"状态无法访问业务接口（必须用真实 HTTP 请求证明） |
| S7 | 未配置 `allowed_hosts` 时非 loopback Host → 403 `host_not_allowed`；`Origin: null` / 跨源变更 → 403 `origin_not_allowed`；缺 Origin 的 CLI POST 仍可用 |
| S8 | `web.allow_shutdown=false` 时 `POST /admin/shutdown` 即使带有效 Token 也 403 `shutdown_disabled_by_policy`；`web.enabled=false` 时旧行为不变 |
| S9 | 匿名访问 `/media/*`、`/tasks/*/logs*`、`/jobs/*/artifacts*`、`/archives/*`、`/jobs/validate`、`/healthz`、`/readyz`、`/metrics` 全部 401（Token 模式） |
| S10 | `web.enabled=true` 但 dist 缺失 → 启动 fail-fast（非零退出 + 明确提示），不出现半可用页面 |
| S11 | 静态资源：`/ui/assets/<hash>.js` 长缓存；`/ui/jobs` 返回 `index.html` 且 `no-store`；`/ui/nope.js` 返回 404 而非 HTML；`/jobs/not-exist` 返回 JSON 404 而非 index.html |

### 2.3 前端（浏览器 / jsdom）

| 编号 | 判据 |
|---|---|
| F1 | `pnpm typecheck/lint/test/build` 全绿；构建产物无外网 URL（字体/CDN/统计） |
| F2 | 无 Token 模式：打开 `/ui/` 直接进入，不闪验证页 |
| F3 | Token 模式：未验证前**不显示任何业务数据**（深链接 `/ui/jobs` 也先验证）；验证失败只提示"Token 无效"且不回显输入 |
| F4 | 刷新后（同标签页）用 sessionStorage 凭据恢复；退出后 token/缓存/在途请求清空并回验证页 |
| F5 | 业务请求 401 → 清凭据回验证页并保留站内目标路径；403/503 **不**踢出 |
| F6 | 三条预置单选：只能选一条、默认 Whisper、不可用项显示原因但**不隐藏**；页面无参数编辑/DAG 编辑/翻译开关控件 |
| F7 | 选片器：进入目录/返回上级/面包屑、根目录禁用上级、跨页文件名筛选（服务端筛选后再分页）、单选确认/取消保留已选、`/` 不可浏览、空根提示"尚未配置媒体目录" |
| F8 | 详情：阶段卡按拓扑、`暂无进度` 而非 0%、终态停止 2s 轮询、重试确认文案说明"只重跑失败/阻断部分、参数不变" |
| F9 | 状态可访问性：状态为"文字+图标"，非纯颜色；表格/表单键盘可操作 |
| F10 | 1280/768/375 三档基础流程（提交、查状态、下载字幕 M2）可操作 |

## 3. M2 判据（排障与产物）

| 编号 | 判据 |
|---|---|
| L1 | 日志分页：尾部 64 KiB 默认、单次上限 256 KiB、`cursor`/`eof`/`truncated`/`source_reset` 语义正确；UTF-8 边界不破字 |
| L2 | 日志只按 `task_id` 读取，不接受 path；`../`、编码穿越、symlink 逃逸全部被拒；未知 task 404；未生成日志返回空+原因 |
| L3 | 日志脱敏（`canary` 注入的假 token 不出现），下载限额 10 MiB，超限 413 `log_too_large` |
| A1 | 产物 manifest：旧 attempt 不可登记/覆盖新产物；`pending/available/expired/missing` 与 `provenance fenced/legacy/unknown` 四种组合可达 |
| A2 | 下载：未发布 409、已清理 410、意外丢失 404；`Content-Disposition` 文件名安全；sha256 与正式产物一致 |
| A3 | 字幕预览：按 index/time 展示，非法 SRT → 422；JA/ZH 不按数组偏移强行配对；正文为纯文本渲染 |
| H1 | 归档列表分页/筛选（含 archived_from/to、reason）、详情 `readonly=true` 且 `allowed_actions` 全 false |
| H2 | 归档后日志/产物仍可按 ID 读取（与活动共用一套读取实现，不复制两套） |

## 4. M3 判据（批量与发布配套）

| 编号 | 判据 |
|---|---|
| M3-1 | 跨目录多选去重、上限 50、提交前展示明确文件清单；逐片独立 Job |
| M3-2 | 逐项结果 `accepted/reused/rejected/unknown` 可区分；`unknown` 只能用 by-path 查证后补提交，不自动重复 POST |
| M3-3 | `unknown` 提交结果恢复有单测（模拟超时+查证命中/未命中两条路径） |
| M3-4 | CI 含前端 job（install/typecheck/lint/test/build），后端既有 job 不退化 |
| M3-5 | README（中英）Roadmap 的 Web 控制台按 SPEC §10 要求处理；未实施项保留未完成标记 |
| M3-6 | 运维文档：Token 开/关两种部署说明、构建步骤、非 loopback 的 TLS 要求、`[web]` 全键说明 |

## 5. 性能与并发（按 2026-11-01 修订后的 §11.3）

- **不执行** 10,000 Job / 30,000 Task 夹具，不设 p95 门槛（用户已明确本机无此场景）。
- 仍验：5 个并发的作业详情页 10 分钟，无重复无限轮询、无持续内存增长；
  单次日志请求不超限；`readyz` 不被详情页按 2s 频率调用（用访问日志计数证明）。
- 仍验（设计约束而非性能项）：列表单页 SQL 次数有界，不逐行请求详情。

## 6. 明确"不算通过"的证据

- 只跑了 `curl` 手工点几下、没断言。
- 只测"按钮禁用"，没测服务端事务内复核（SPEC §11.1 明确要求确定性竞态用例）。
- Job `succeeded` 或退出码 0、文件非空当作产物正确（M2 起必须看字幕结构与 hash）。
- 前端单测里"前缀匹配通过"冒充 Token 校验通过。
- 把"未覆盖"记成"通过"。

## 7. 未覆盖项（默认不验，需人另定）

- 真实 GPU / 真实 ASR 模型 / 真实翻译 LLM 的完整链路（沿用既有阶段验收结论，不自动外推）。
- 真实浏览器矩阵（Firefox/Safari）、真实 TLS 反代、真实公网暴露。
- 多用户/角色/配额（本期不存在）。
- 运行中取消、上传、SRT 独立翻译（SPEC §1.2 明确不做）。

## 8. 证据归档

- 实现者与验收者的原始回报、命令输出摘要、失败复现步骤，统一追加到
  `docs/superpowers/executions/2026-11-02-react-web-console-acceptance.md`。
- 每条结论必须能追溯到：判据编号 → 命令 → 输出片段 → 代码位置（file:line）。

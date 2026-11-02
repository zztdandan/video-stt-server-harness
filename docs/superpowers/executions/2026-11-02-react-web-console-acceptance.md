# React 工作台验收记录（独立验收，CPU 口径）

- 日期：2026-11-03（Asia/Shanghai）
- 判据来源（验收前冻结）：[验收计划](./2026-11-02-react-web-console-acceptance-plan.md)、[SPEC](../specs/2026-11-01-react-web-console-spec.md)
- 实现分支：子仓库 `.worktrees/react-web-console`（`feat/react-web-console`）
- 验收人：3 个**未参与实现**的独立代理（A 后端契约 / B 前端浏览器 / C 安全部署）

## 0. 环境与边界（先写死再开跑）

| 项 | 值 |
|---|---|
| GPU | **另一条真实媒体长测占用中**：本轮全程 0 worker 实例，不加载模型、不做真实推理/解码 |
| 后端测试 | `/home/base/repo/video-stt-whisper-server/.venv/bin/python -m pytest -q`（CPU / fake executor） |
| 前端测试 | `cd web && pnpm typecheck && pnpm lint && pnpm test && pnpm build` |
| 浏览器 | Playwright，`channel: "chrome"`（复用系统 Chrome，不下载浏览器） |
| 实例 | `scripts/web_server.sh`：读生产 `config.ini` 的真实模型路径，db/log/artifact 落临时目录，`WORKERS=0` |
| Token | 只用随机测试串；生产 Token 全程未读取、未写入仓库 |
| 指纹 | 验收时代码快照：`68a8b29`（验收期间实现主体 `000f47b`、集合视图 `68a8b29`）；验收后修复提交见 §5 |

## 1. 总览

| 方向 | 判据数 | 结果 | 备注 |
|---|---|---|---|
| A 后端契约/兼容 | B1–B10、L1–L3、A1–A2、H1–H2 | **PASS 16 / FAIL 1 / PARTIAL 1** | B7 进度身份、B9 筛选收紧：**已修**（§5.1/§5.2） |
| B 前端浏览器/交互 | F1–F10、M2 UI、M3 UI | **全部 PASS** | D1 窄屏布局溢出：**已修**（§5.3） |
| C 安全/部署 | S1–S11、限流、泄露扫描 | **全部 PASS** | 1 条部署注记（proxy headers）：**已修**（§5.4） |

新增验收测试：`tests/acceptance/`（58 例）、`tests/acceptance_security/`（93 例）、
`web/e2e/acceptance/*.spec.ts`（28 例）。

## 2. 验收 A：后端契约与兼容

命令与计数（验收时）：

```text
pytest -q tests/acceptance                     -> 56 passed, 2 xfailed
pytest -q                                     -> 1138 passed, 98 deselected, 2 xfailed
ruff check tests/acceptance                   -> All checks passed
```

| 判据 | 结论 | 证据要点 |
|---|---|---|
| B1 三预置/能力表 | PASS | 恰好 3 条且顺序固定；每条 DAG 唯一 ASR、依赖 extract；`config_fields` 与 `STAGE_CONFIG_KEYS` 逐阶段全等 |
| B2 预置错误码与顺序 | PASS | 未知/混传（含 `{}`）→ 400，字段定位 `preset_id`；结构错误先于路径存在性 |
| B3 冻结一致性 | PASS | `/jobs/validate`、创建响应、`/capabilities` 的 `config_revision`/DAG/逐阶段配置全等；详情无 `config_revision`（合同未冻结） |
| B4 legacy 兼容 | PASS | `video_path+language`、显式 DAG 组合、显式 `job_config` 全部可用；`accepted=false` 语义不变 |
| B5 列表摘要/无 N+1 | PASS | 6 个 job 仅 2 次 DB 连接；替换 `get_job_detail` 为抛异常后列表仍正常 |
| B6 allowed_actions | PASS | queued/running/failed/全 cancelled/archived 五态矩阵；false 均有 reason |
| **B7 进度身份** | **FAIL → 已修** | retry 后旧 worker 迟到事件曾以 37% 出现（见 §5.1） |
| B8 错误体 | PASS | 400/409/422 均含 `detail` + `error{code,message,field_errors,retryable}` + `request_id` |
| **B9 筛选收紧** | **PARTIAL → 已修** | `GET /jobs?language=fr` 曾返回 200 空列表（见 §5.2） |
| B10 归档读取 | PASS | 活动 404、归档可读、`readonly=true`、`allowed_actions` 全 false |
| L1–L3 日志 | PASS | 尾读 64 KiB/上限 256 KiB、游标 `source_reset`、UTF-8 边界无 U+FFFD、脱敏、413 |
| A1–A2 产物 | PASS | 旧 generation 被拒、409/410/404/422、下载 hash 与 manifest 一致 |
| H1–H2 归档 | PASS | 筛选与分页稳定、归档日志/产物按 ID 可读 |

## 3. 验收 B：前端浏览器与交互

命令与计数（最终 dist 复跑）：

```text
cd web
E2E_BASE_URL=http://127.0.0.1:18130 ACC_B_TOKEN=<随机测试串> \
  pnpm exec playwright test e2e/acceptance --project=chromium-desktop
-> 28 passed (1.2m)
```

| 判据 | 结论 | 证据要点 |
|---|---|---|
| F1 构建/外链 | PASS | dist 无外部 script/link/`@font-face`/统计脚本；浏览器请求全同源 |
| F2/F3 鉴权入口 | PASS | 无 Token 直入；深链接先验证、验证前零业务请求；错误 Token 不回显 |
| F4/F5 凭据寿命 | PASS | 刷新先 `/auth/check` 后恢复；退出清凭据；401 带 `next` 回验证页；403/503 不踢出 |
| F6 三预置 | PASS | 默认 Whisper、单选、不可用显示原因不隐藏、无参数/DAG/翻译开关 |
| F7 选片器 | PASS | 目录/上级/面包屑、空根提示、服务端先筛后分页、取消保留 |
| F8 详情 | PASS | 阶段拓扑、无快照"暂无进度"、2s 轮询且终态停止、重试确认文案 |
| F9 可访问性 | PASS | 状态文字+图标、label 关联、跳过导航、键盘可达 |
| F10 响应式 | PASS（修复后） | 1280/768/375 均可提交/查状态/下载；**D1 溢出已修**（§5.3） |
| M2 UI | PASS | 历史只读/抽屉、日志增量与轮转、双栏按 index、下载门禁、409/410/404 提示 |
| M3 UI | PASS | 上限 50、显式清单、accepted/reused/rejected/unknown、unknown 先查证、accepted 无重试 |

负向对照：临时注入 6 类缺陷（F3/F6/F7/F8/M2/M3）→ 6 failed，证明断言可失败（脚本已删）。

## 4. 验收 C：安全与部署

命令与计数：

```text
ACC_SECURITY_RUN=1 python -m pytest tests/acceptance_security -q   -> 93 passed
```

| 判据 | 结论 | 证据要点 |
|---|---|---|
| S1–S4 security 组合 | PASS | 四种组合启动形态与 `/auth/config` 一致；空 token+require → rc=1 `api_token_missing`、端口不监听 |
| S5 auth/config 泄露 | PASS | 响应恰两字段、no-store、无 token/长度/哈希 |
| S6 伪造与绕过 | PASS | 11 种变体全 401；`Authorization`/Cookie/query 无效；无通配 CORS |
| S7 Host/Origin | PASS | 未知 Host 403 **先于** 401；`Origin: null`/跨源 403；缺 Origin CLI 放行；空 `allowed_hosts` 拒绝全部 |
| S8 停机策略 | PASS | `allow_shutdown=false` 时有效 Token 仍 403 且无副作用；`web.enabled=false` 旧行为不变 |
| S9 静态托管 | PASS | assets 长缓存、页面 no-store、缺失 JS 404 非 HTML、API 404 JSON、nosniff |
| S10 fail-fast | PASS | 空/缺失/半成品 dist → rc=1 且原因落日志、端口不监听 |
| S11 路径/注入 | PASS | 媒体穿越/编码穿越/symlink 逃逸被拒；日志只按 task_id；产物按双 ID |
| 限流 | PASS | 失败超限 429、成功清零；不可信直连伪造 XFF 不换桶 |
| canary 泄露 | PASS | 公开页/全 bundle/错误体/响应头/日志均无 canary |

## 5. 验收发现 → 修复（全部有回归用例）

### 5.1 B7 进度身份（retry 后旧进度可见）— 已修
- 现象：retry+re-claim 后，旧 worker 迟到事件仍以 37% 出现。
- 根因：进度事件无 claim 身份；`retry_job` 把 `attempt` 重置为 0（ABA）。
- 修复：`core/claim_identity.py::build_claim_id`（`claim:v1:<attempt>:<owner>:<claimed_at>`）；
  runtime 用 `_ClaimBoundProgressQueue` 给事件注入 claim；`ProgressStore` 记录并返回；
  DTO 与当前任务身份不一致 → `available=false, reason="stale_claim", stale=false`。
  claim 纪元取 `claimed_at`（心跳不改写），并有 `test_claim_identity_stable_across_heartbeat` 证明不误杀。
- 回归：`tests/unit/test_progress_claim_identity.py`（15 例）+ 验收用例由 xfail 转正常断言。

### 5.2 B9 筛选收紧不一致 — 已修
- 现象：`GET /jobs?language=fr` 返回 200 空列表；`/tasks?stage|status` 同样宽松。
- 修复：`job_repository.list_jobs` 增 `language` 白名单；`list_tasks` 增 `stage`（注册表）/`status`（任务状态机）白名单，非法 → `invalid_filter` 422 + 字段定位。
- 回归：验收用例扩展为同时断言 `/jobs`、`/tasks` 的非法值与合法值。

### 5.3 D1 窄屏布局溢出 — 已修
- 现象：详情页 375px `scrollWidth=713`、768px 溢出 9px；根因是 `page-header__extra` 固定宽度 +
  `CopyableText` 的内联 `maxWidth` 优先级高于 CSS `max-width:100%` + antd Space 取内容宽度。
- 修复：`CopyableText` 数值上限改 `min(100%, Npx)`；`.page-header__desc` 改 `min(68ch, 100%)`；
  标题/描述区的 antd Space 允许收缩；`.page-header__extra` 可换行、窄屏独占一行。
- 回归：`web/e2e/harness.spec.ts` 新增"详情页 1280/768/375 无整页横向溢出"，实测通过。
- 附带修复：归档历史表列宽之和超过容器导致"操作"列被挤出、`归档原因` 被压成竖排；已收敛列宽、
  原因列单行省略 + tooltip、时区名收进 tooltip（保留"本地"+可展开 UTC）。

### 5.4 部署注记：uvicorn 默认信任 loopback 的 X-Forwarded-For — 已修
- 现象：`proxy_headers=True`（默认）在应用前改写 `request.client`，使 `[web] trusted_proxies`
  为空时的"不信任转发头"在**限流分桶**上失效（鉴权不受影响，仅 loopback 可利用）。
- 修复：`launcher.read_proxy_settings` 读取 `[web] trusted_proxies`：为空 → `proxy_headers=False`；
  非空 → 打开并限定 `forwarded_allow_ips`。冒烟脚本直连实例加 `--no-proxy-headers`；
  `config.example.ini` 补注释。
- 回归：`tests/unit/test_launcher_proxy_settings.py`（3 例）。

## 6. 修复后的总账（干净全量）

| 门禁 | 结果 |
|---|---|
| 后端 `pytest -q` | **1158 passed / 98 deselected / 0 failed**（验收用例 58 含在内；安全 93 默认 deselect） |
| 安全专项 | `ACC_SECURITY_RUN=1 pytest tests/acceptance_security -q` → **93 passed** |
| 前端 `typecheck/lint/test/build` | 通过；**189 passed**（27 文件） |
| 浏览器 E2E（验收 B 套件，最终 dist） | **28 passed** |
| 浏览器 E2E（基础设施 + 布局回归） | **4 passed** |

证据文件：`tmp/shots2/*.png`（11 张逐页截图）、`tmp/accB/acceptance-B-report.md`、
`tests/acceptance_security/REPORT.md`、`tmp/accB/final-run.log`。

## 7. 明确未覆盖（不得据此推断已通过）

- **真实媒体端到端**：本轮 GPU 被长测占用，未跑真实 ASR/翻译；待用户通知后按
  `scripts/e2e_real_run.py` 用 `/srv/media/jellyfin/JELLYFIN/JAV` 的 2 部非 VR 影片验收。
- TLS 反代 / 非 loopback 部署 / 多跳 `trusted_proxies`；Firefox/Safari；真实 Token 轮换与重启 401。
- 多进程/多 runtime 共享同一 DB 的并发压测；`provenance=unknown` 的公开可达路径。
- **`warning_summary` 结构化生产者缺失（SPEC §7.12 未完成）**：`jobs.warning_summary_json` 列、DTO 读取与
  "available=false 不称'无警告'"的口径已就绪，但**没有任何写入方**——执行器确实返回了结构化计数
  （`stt_qwen` 的 `coverage/align_missing_chunks/empty_chunks/punct_only_lines`、`stt` 的 `timestamp_stats` 等），
  但尚未在 `publish_task_artifacts` 同一事务内聚合成 `{code,count,stage,source}` 并持久化。
  因此当前所有作业（含旧作业）都显示 `available=false`，这是**如实反映无数据**，不是前端丢失。
  设计要点（后续实施）：纯函数从阶段结果提取（禁止日志正则）；写入口与发布同一 fencing 事务；
  按 stage 合并、重试时替换该 stage 的旧条目；阈值为显式常量（如 coverage < min_coverage）。
- CI：新增的 `web` job 与既有两个 Python job 尚未在 GitHub Actions 实跑。

## 8. 结论

- M1–M3 的**代码与契约**已实现并通过 CPU 口径的独立三方向验收；验收中发现的 1 个 FAIL（B7）、
  1 个 PARTIAL（B9）、1 个交互缺陷（D1）与 1 条部署注记均已在实现侧修复并加回归用例。
- **本轮不宣称"真实媒体已验收"**：该结论只能在 GPU 窗口空闲、用 2 部真实影片跑完整链路后给出。
- 发布版本号、README Roadmap 的"完成"标记与 tag/push 仍待用户在真实媒体验收后确认。

## 附录 A：真实端到端脚本的 CPU 冒烟（2026-11-03 03:1x）

在 GPU 仍被长测占用期间，用 **0 worker** 实例对 `scripts/e2e_real_run.py` 做了完整链路冒烟
（不加载模型、不推理，作业只会停在 `queued`）：

| 场景 | 结果 |
|---|---|
| 预检 `POST /jobs/validate` | 通过（`valid=true`，8 项 checks 全 true/null） |
| 提交 `POST /jobs` | `accepted=true`，拿到 job_id |
| 轮询到终态 | 0 worker 下不会推进，`--timeout-sec 15` 到期后按设计报 `wait_terminal_failed`，**保留** `validate_ok/accepted/job_id` |
| 重复提交同一路径 | `accepted=false, message=idempotent_returned`，脚本判为"未接受"并给 existing_job（符合预期，未自动重发） |
| 归档后重提 | 归档成功 → 再次提交 accepted=true（路径占用已释放） |

冒烟暴露并修掉的脚本缺陷：超时/异常时曾丢失已取得的证据（`validate_ok/accepted/job_id` 被新对象覆盖），已改为保留部分结果。

### A.1 环境事实（影响真实验收配置，非代码缺陷）

- 本机 `/srv/media/jellyfin` 是 **CIFS 只读挂载**（`ro,nosuid,nodev,vers=3.0`）；
  实测 `touch` 返回 `Read-only file system`。
- 生产 `config.ini`：`[security] allowed_copy_back_roots` 为空、`[translation] copy_back` 缺省
  `__video_dir__` → 预检会（正确地）报 `copy_back_not_writable`，网页提交被拦。
- 真实端到端将用 `scripts/web_server.sh` 的 `COPY_BACK_DIR=<可写目录>` 覆盖
  `[translation] copy_back` 与 `[security] allowed_copy_back_roots`，从而让预检通过、
  并能校验 copy_back 的 hash；这只是测试实例配置，不改生产 `config.ini`。
- 若希望**生产**网页提交也能通过，需要把 `[translation] copy_back` 指到可写目录，
  并按需把该目录加入 `[security] allowed_copy_back_roots`（属于部署决策，待用户确认）。

### A.2 产物判据逻辑的独立冒烟（不跑模型）

用已 seed 的 succeeded 作业（12 条 JA/ZH 字幕）驱动 `scripts/e2e_real_run.py` 的判据代码：

| 检查 | 结果 |
|---|---|
| 下载 `content` | 200，字节与文件一致 |
| `sha256_match` | **True**（JA、ZH 各一次） |
| `cues` 解析 | 12 条、`timeline_ok=True` |
| JA/ZH index 对齐 | 12/12，`zh_missing_in_ja=0` |
| 缺 copy_back 记录 | 如实标 `copy_back_unverified` |

再用 stub 替换"提交/等待"网络动作（判据代码不 stub），`run_video` 成功路径返回
`passed=True`、三阶段 succeeded、四项检查齐全——说明真实跑完后判定不会误判。

### A.3 真实跑批命令（GPU 空闲时执行）

```bash
cd .worktrees/react-web-console
# 1) 起真实实例：生产配置 + 真实 worker（会吃 GPU）+ 可写 copy_back
PORT=18127 \
WORK_DIR=$PWD/tmp/real-e2e \
COPY_BACK_DIR=$PWD/tmp/real-e2e/copyback \
WITH_TOKEN=1 E2E_TOKEN=<随机测试 token> \
WORKERS=real bash scripts/web_server.sh

# 2) 两部非 VR 影片（可替换）
E2E_TOKEN=<同一个 token> python scripts/e2e_real_run.py \
  --base-url http://127.0.0.1:18127 --preset whisper-ja-zh \
  --video "/srv/media/jellyfin/JELLYFIN/JAV/N/奈/奈美_なみ 26歳 コーヒーショップ勤務/NTR-102 绝对会为这情况兴奋吧 难/NTR-102-U.mp4" \
  --video "/srv/media/jellyfin/JELLYFIN/JAV/W/五/五日市芽依/MIAB-196 合宿轮奸：憧憬的女子经理/MIAB-196.mp4" \
  --timeout-sec 21600 --out tmp/real-e2e/report.json
```

判据不通过时的处置：**不自动重试、不自动归档**；先看 `report.json` 的 `errors`/`checks`，
按 SPEC 的"失败→日志→符合条件才重试"流程处理，并把结论追加到本文件。

### A.4 长跑可恢复：账本 + `--resume`

真实跑批可能持续数小时，脚本已按"append-only 账本"实现续跑：

- 每完成一部片，结果追加到 `<out>.jsonl`（一片一行，含 `passed`、job_id、checks）；
- `--resume` 时读取账本，`(video, preset)` 已通过的组合**直接跳过**（不发起任何请求）；
- 失败/未完成项会重新执行；账本损坏行被跳过，不中断跑批。

冒烟验证：预写两条"已通过"账本后，用不可达 base-url 跑 `--resume`，两部片均被跳过、
退出码 0、`summary.passed=2` —— 证明续跑不依赖网络。
（冒烟同时暴露并修掉一个实现缺陷：`passed` 是 property 不在 `__dict__`，账本最初读不到已通过项。）

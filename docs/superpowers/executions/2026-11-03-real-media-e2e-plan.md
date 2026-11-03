# 真实媒体端到端验收计划（冻结口径，跑前写死）

> 目的：用 2 部**非 VR** 真实影片，验证"预检 → 提交 → 监控 → 字幕双栏 → 下载 → 回写校验"的完整链路。
> 判据以**产物**为准，不以退出码、`succeeded` 或"跑通"为准。执行者（总调度）与验收者（独立代理 T）分离：
> 验收方**不改产品代码**、不看执行者的中间结论，只按本文件逐条取证。

## 1. 前置（不满足则不开跑）

| 项 | 条件 | 取证方式 |
|---|---|---|
| GPU 空闲 | `nvidia-smi` 可用；`memory.free >= 12 GiB`；`utilization.gpu <= 20%` | `python scripts/preflight_real_e2e.py` |
| 无长测 | 无 `fullrun_atmp.py` 进程占用 | 同上（`pgrep -f` 由脚本内部实现，排除自身） |
| 媒体可读 | 两部影片存在且大小 > 100 MiB | 同上 |
| 回写目录可写 | `COPY_BACK_DIR` 可写（媒体根是只读 CIFS） | 同上 |
| 代码冻结 | 记录子仓 `git rev-parse HEAD` 与 `git status --short`；dist 重建后时间晚于 `web/src` 最近修改 | 同上 |
| 端口 | 18127 未被监听 | 同上 |
| 配置 | 临时派生配置通过 `load_settings`（不改生产 config.ini） | 同上 |

## 2. 选片（默认，可替换）

| # | 影片 | 时长 | 说明 |
|---|---|---|---|
| A | `N/奈/…/NTR-102 绝对会为这情况兴奋吧 难/NTR-102-U.mp4` | 63.2 min | 短片，先跑 |
| B | `W/五/五日市芽依/MIAB-196 合宿轮奸：憧憬的女子经理/MIAB-196.mp4` | 124.9 min | 长片，验证长音频切片 |

## 3. 执行步骤（固定顺序）

1. 运行预检脚本，全部 OK 后记录输出（`tmp/real-e2e/preflight.json`）。
2. 起真实实例：
   ```bash
   cd .worktrees/react-web-console
   PORT=18127 WORK_DIR=$PWD/tmp/real-e2e \
   COPY_BACK_DIR=$PWD/tmp/real-e2e/copyback \
   WITH_TOKEN=1 E2E_TOKEN=<随机测试 token> WORKERS=real \
   bash scripts/web_server.sh
   ```
   记录启动日志与 `/system/status`、`/capabilities` 快照。
3. 跑 A 片：`scripts/e2e_real_run.py`（`--preset whisper-ja-zh --timeout-sec 21600 --out tmp/real-e2e/report.json`）。
4. A 片 `passed=true` 后再跑 B 片（`--resume` 会跳过已通过项）。
5. 两部都完成后：**不归档**作业（保留证据），停止实例前导出 `/jobs`、`/jobs/{id}`、`/jobs/{id}/artifacts`、`/system/resources` 快照。

## 4. 判据（逐条 PASS/FAIL/PARTIAL）

| 编号 | 判据 | 取证 |
|---|---|---|
| E1 | 预检 `valid=true`，8 项 checks 全通过（无 `warn/fail`）；预检本身不创建作业 | `POST /jobs/validate` 响应 + 作业数前后一致 |
| E2 | 提交 `accepted=true` 且有 `job_id`；`stages` 与预设一致（extract/stt/translate） | 响应体 |
| E3 | 三阶段均 `succeeded`；每次 `attempt` 有记录（重试要能解释） | `/jobs/{id}` |
| E4 | JA/ZH SRT 均 `available`；**下载字节 sha256 == manifest sha256**；cues > 0；时间轴单调不重叠；ZH index ⊆ JA index 且缺失数可解释 | 下载后本地 `sha256sum` 与 manifest 对比 |
| E5 | 详情页"字幕与产物"双栏可读：JA/ZH 行数与接口一致；页面不报错 | 浏览器截图 + 请求日志 |
| E6 | 字幕下载响应带正确文件名与 `Content-Disposition`；内容与 E4 一致 | `curl -O` 后比对 |
| E7 | copy_back：`COPY_BACK_DIR` 下存在同名 ZH SRT 且 sha256 与下载一致；若无记录则如实标 `copy_back_unverified` | 文件系统 + report.json |
| E8 | 日志中无 Token/LLM key 明文（用 canary 扫描本次新增日志）；`request_id` 可关联 | 日志文本扫描 |
| E9 | 终态后详情页停止轮询；`冻结参数` 显示预设/版本；产物行显示"结构校验"结果 | 浏览器 + 请求计数（60s 窗口 ≤ 40 次） |
| E10 | 运行中 `/ui/resources` 显示 GPU 利用率 > 0 且能看到 worker 进程（WSL 单进程显存为"未知"属预期） | 截图 + 接口快照 |
| E11 | 详情页 60s 内业务请求 ≤ 40（每 2s 一次轮询 + 少量抖动），无 N+1 详情风暴 | Playwright 请求计数 |
| E12 | 证据齐全：每片 JSONL 账本、`report.json`、截图、日志摘录；结论绑定 commit 与 dist 哈希 | 文件清单 |

## 5. 失败处置

- **不自动重试、不自动归档**；先看 `report.json.checks` 与日志，区分产品缺陷 / 上游 LLM 错误 / 环境问题。
- 只有 `failed` 作业才允许 `retry`；`succeeded` 不得重试，只能归档（本验收**不归档**）。
- 任何一条 FAIL 都要给最小复现与影响面；PARTIAL 必须写明口径边界（例如 WSL 显存不可归因）。

## 6. 验收方（独立代理 T）要求

- 只读：不改产品代码、不改生产配置、不重启在跑实例；可用浏览器与 API。
- 逐条 E1–E12 给 PASS/FAIL/PARTIAL + 命令 + 关键输出 + file:line（涉及代码时）。
- 快照绑定：`git rev-parse HEAD`、`git status --short`、`web/dist` sha256、实例启动时间。
- 报告里必须写"本次结论只在 WORKERS=real、真实 GPU、真实 LLM 调用、0 worker 之外的端口 18127 上成立"。

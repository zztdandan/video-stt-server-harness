# whisper-stt 文档索引

- `01-project-memory.md`：本轮对话沉淀、约束与经验结论
- `02-operations-runbook.md`：标准执行步骤与交付核对清单
- `03-architecture-and-key-features.md`：架构拆分与关键功能说明
- `04-troubleshooting.md`：常见故障与恢复策略
- `05-api-reference.md`：**可选**文档，未纳入本轮交付范围（不是本轮缺口）；API 速查已由 `02` 第 6/7 节
  （接口、任务状态机、健康检查与指标）与 `04` 第 9 节（错误码速查）覆盖
- `research/vad-diarization-upgrade.md`：VAD 升级（FireRedVAD）+ 说话人分离 技术调研

## 规范与计划

- **[React 字幕流水线工作台 SPEC（2026-11-01，可选 Token 鉴权）](<superpowers/specs/2026-11-01-react-web-console-spec.md>)：待评审、未实施。** 简单服务器目录/文件选择、三条固定流水线单选、监控/日志/字幕闭环；前后端共用 security 配置，开启时输入完整 Token、关闭时直入（无用户名/密码）；已有 API 复用、14 条新增路由、功能缺口与 M1–M3 验收标准。上传/运行中取消等仍为扩展待办。**2026-11-01 修订：删除 10,000 Job/30,000 Task 夹具与列表 p95 目标（本机无此规模场景），保留"不引入 N+1"的设计约束，降低为设计约束而非性能验收项。**
- [React 工作台实施计划与并行开发契约](<superpowers/plans/2026-11-01-react-web-console-implementation-plan.md>)：模块所有权、`[web]` 配置段、三条预置、`/capabilities` 与 DTO 字段冻结、路由模块清单、波次分工与 M1 闸门。实现分支 `.worktrees/react-web-console`（`feat/react-web-console`）。
- [React 工作台验收计划（种子与判据，验收前冻结）](<superpowers/executions/2026-11-02-react-web-console-acceptance-plan.md>)：验收人独立性约束、冻结环境/指纹、M1–M3 判据编号（B/S/F/L/A/H/M3）、明确"不算通过"的证据、未覆盖项与证据归档要求。
- [React 工作台美学与视觉设计规范](<superpowers/specs/2026-11-01-react-web-console-aesthetic-guidance.md>)：**由 GPT-6.1-Sol 子代理出具**。12 节：颜色/字体/空间 token、可直接粘贴的 antd 5 深浅两套 `ThemeConfig`、布局与 9 类核心组件状态矩阵、动效与响应式、可访问性、Do/Don't、落地清单；全部对比度按 WCAG 2.1 实算，无外链/CDN/字体引用；明确禁止假 0% 进度与加权总进度。

- **⭐ `superpowers/specs/2026-11-01-stt-qwen-execution-spec.md`：stt_qwen 正式执行 SPEC（本次执行的唯一目标文档）**——VAD 定点切片参数（本轮 30±20/fallback+40→上界70s/batch10；目标 50±20/+30→上界80s/batch13，全部可配）、12 处代码改动、执行器契约、翻译链路两条前置修复、3 部未翻译影片标准三步验收口径。**§12 执行状态：1–7 全部完成，验收通过**
- **⭐ `superpowers/executions/2026-11-01-stt-qwen-acceptance.md`：stt_qwen 真实媒体验收记录（SPEC §9.3/§13）**——种子 20261101 抽 3 部未翻译片（SAN-484-U / ABF-394-U / CAWB-069-U）走标准三步全部 succeeded；逐项判据表、CPU 独立复算片边界、**验收暴露并修复的 2 个执行器缺陷**（显存门槛未区分冷启动/命中缓存、字级时间戳逃逸未夹取）、翻译链路容量取证（`reasoning.enabled=false` 关不掉思考，批次应降到 20~25）、未验证项
- `superpowers/specs/2026-10-22-whisper-stt-reliability-and-translation-hardening-spec.md`：可靠性与翻译链路加固 SPEC（含 2026-10-22 用户决策、批次拆分、验收标准）
- `superpowers/specs/2026-11-01-qwen3-asr-local-stage-design.md`：stt_qwen 早期设计稿——**参数部分已被上文执行 SPEC 取代**（`chunk_seconds=30`/`min_free_vram_gb=6.0` 等经实测修订），仅保留背景与架构取舍
- `superpowers/plans/2026-11-01-stt-qwen-vad-boundary-handoff.md`：FireRedVAD 定点切片交接说明——其 D2 的"固定网格 + 搜索窗"写法经实测有缺陷（切出 >180s 片），执行以 SPEC 的 prev 锚定为准
- `superpowers/executions/2026-11-01-qwen3-asr-local-pilot.md`：pilot 实测记录（同源对照 whisper-large-v3-turbo、切片粒度对速度与质量的影响、GPU 争用与落点核查）
- `superpowers/executions/2026-11-01-stt-qwen-vad-cut-eval.md`：定点切方案评估与**全部实测证据**（§1–§12：纯无语音片可跳过性、切点精度对照、锚定缺陷取证、坍缩根因三连探针、30s/50s 全长跑、翻译与发布）

## 版本与环境速记（v0.5.0 实现/P1/四次 CI 绿完成；annotated tag 指向 main 最终文档提交）

- 唯一 Python 环境：`/home/base/repo/video-stt-whisper-server/.venv`（Python 3.10）；子仓库与 `.worktrees/*` 不得创建 venv。
- 子仓库实现代码：`whisper-stt/`；工作树：`.worktrees/reliability-hardening`。
- 依赖与锁：主仓库 `pyproject.toml` / `uv.lock`，子仓库 `pyproject.toml`（0.5.0）/ `uv.lock`。
  2026-10-24 已将 child/root 锁的普通包源从宿主机 TUNA 镜像归一为公共 PyPI（`pypi.org/simple` /
  `files.pythonhosted.org`），torch/torchaudio 保持 explicit cu128；版本/哈希/依赖图等价。
  主仓库 root pyproject/uv.lock、.gitignore 已随 ee1cf98 提交；docs 随 ee1cf98/4ee839d 提交。
- CI：`whisper-stt/.github/workflows/ci.yml`（CPU-only，默认跳过 manual/e2e，含 secret 扫描与 lock 校验）；
  run 39981535390 @ bba96a0 锁校验失败（宿主机 TUNA 镜像）；run 39995654486 @ 66678d0 锁校验通过，
  但 2 个 clean-runner 用例失败（service.log 创建顺序、脚本 wav 校验晚于 ffprobe）；run
  39996457310 @ 2623545 **成功**。该提交让 service.log 立即创建、wav 契约先于 ffprobe；committed CI
  仍先跑 CPU 子集再跑完整套件。连续四个绿色提交：2623545 → 39996457310；5e67c7b → 39997343133；
  c88cc80 → 39997953791（39997946922 / 39997927908 同为 c88cc80 成功）；da43057 → 40000383321
  （restart 恢复集成用例确定性修复；该用例曾在 fd383c9 的一次 main push 偶发失败，同提交另有成功 run）。
- 密钥：`docs/hf-token.md` 已删除，HF token 用 `HF_TOKEN` 环境变量；供应商侧轮换仍需人工完成。
- 状态：v0.5.0 的七项 P1（copyback 真 sink、checkpoint 固定身份、finally compare-and-remove、
  stop/drain tuple-fenced rollback、promotion 异常收敛、atomic fenced 单写、worker boot nonce 防 ABA）
  已由官方实施代理修复，并经 Sol 用原真 SQLite/文件反例及跨 FS copyback、symlink 替换独立复验关闭。
  真实 2 小时 E2E、GPU 显存、供应商侧 token 轮换仍未验证；四次远端 CI 已绿。annotated `v0.5.0` tag
  已 push 并指向 `main` 上的最终文档提交（`git describe --tags --exact-match main`）。历史 `v0.4.0` tag 已补 push 到 b029d07。
- 主 docs（已随 ee1cf98/4ee839d 提交，最终定稿随根仓库后续提交）：`docs/00-index.md`–`docs/04-troubleshooting.md`、`docs/research/`、
  `docs/superpowers/specs/2026-10-22-whisper-stt-reliability-and-translation-hardening-spec.md`、
  `docs/superpowers/plans/2026-10-22-hardening-execution.md` 及本轮新增 spec/plan/execution 文件。
  具体发布核对清单见 `02-operations-runbook.md` 第 8 节。

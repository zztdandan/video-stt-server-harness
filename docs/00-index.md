# whisper-stt 文档索引

- `01-project-memory.md`：本轮对话沉淀、约束与经验结论
- `02-operations-runbook.md`：标准执行步骤与交付核对清单
- `03-architecture-and-key-features.md`：架构拆分与关键功能说明
- `04-troubleshooting.md`：常见故障与恢复策略
- `05-api-reference.md`：**可选**文档，未纳入本轮交付范围（不是本轮缺口）；API 速查已由 `02` 第 6/7 节
  （接口、任务状态机、健康检查与指标）与 `04` 第 9 节（错误码速查）覆盖
- `research/vad-diarization-upgrade.md`：VAD 升级（FireRedVAD）+ 说话人分离 技术调研

## 规范与计划

- `superpowers/specs/2026-10-22-whisper-stt-reliability-and-translation-hardening-spec.md`：可靠性与翻译链路加固 SPEC（含 2026-10-22 用户决策、批次拆分、验收标准）

## 版本与环境速记（v0.5.0 实现/P1/两次 CI 绿完成，tag 待父）

- 唯一 Python 环境：`/home/base/repo/video-stt-whisper-server/.venv`（Python 3.10）；子仓库与 `.worktrees/*` 不得创建 venv。
- 子仓库实现代码：`whisper-stt/`；工作树：`.worktrees/reliability-hardening`。
- 依赖与锁：主仓库 `pyproject.toml` / `uv.lock`，子仓库 `pyproject.toml`（0.5.0）/ `uv.lock`。
  2026-10-24 已将 child/root 锁的普通包源从宿主机 TUNA 镜像归一为公共 PyPI（`pypi.org/simple` /
  `files.pythonhosted.org`），torch/torchaudio 保持 explicit cu128；版本/哈希/依赖图等价。
  主仓库 root pyproject/uv.lock 此前已 staged，现有未暂存归一修订，父代理提交前需重新 add。
- CI：`whisper-stt/.github/workflows/ci.yml`（CPU-only，默认跳过 manual/e2e，含 secret 扫描与 lock 校验）；
  run 39981535390 @ bba96a0 锁校验失败（宿主机 TUNA 镜像）；run 39995654486 @ 66678d0 锁校验通过，
  但 2 个 clean-runner 用例失败（service.log 创建顺序、脚本 wav 校验晚于 ffprobe）；run
  39996457310 @ 2623545 **成功**。该提交让 service.log 立即创建、wav 契约先于 ffprobe；committed CI
  仍先跑 CPU 子集再跑完整套件。连续两个绿色提交：2623545 → 39996457310；5e67c7b → 39997343133。
  第二个提交 5e67c7b 的 run 39997343133 已成功。
- 密钥：`docs/hf-token.md` 已删除，HF token 用 `HF_TOKEN` 环境变量；供应商侧轮换仍需人工完成。
- 状态：v0.5.0 的七项 P1（copyback 真 sink、checkpoint 固定身份、finally compare-and-remove、
  stop/drain tuple-fenced rollback、promotion 异常收敛、atomic fenced 单写、worker boot nonce 防 ABA）
  已由官方实施代理修复，并经 Sol 用原真 SQLite/文件反例及跨 FS copyback、symlink 替换独立复验关闭。
  真实 2 小时 E2E、GPU 显存、供应商侧 token 轮换仍未验证；两次远端 CI 已绿，`v0.5.0` tag 待父创建。
- 主 docs 待跟踪：`docs/00-index.md`–`docs/04-troubleshooting.md`、`docs/research/`、
  `docs/superpowers/specs/2026-10-22-whisper-stt-reliability-and-translation-hardening-spec.md`、
  `docs/superpowers/plans/2026-10-22-hardening-execution.md` 及本轮新增 spec/plan/execution 文件。
  具体发布核对清单见 `02-operations-runbook.md` 第 8 节。

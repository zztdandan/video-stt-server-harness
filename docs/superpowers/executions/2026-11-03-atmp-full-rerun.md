# atmp 全量重做（音频提取 → stt_qwen → translate）计时台账

- **开始时间**：2026-11-03 01:34（Asia/Shanghai）
- **触发**：用户指令——对 `/srv/media/jellyfin/JELLYFIN/atmp` 全部电影从音频获取开始重做，
  清空既有 SRT，逐片逐阶段记录耗时与错误；要求不影响另一侧的前端开发与接口补齐。
- **机器可读账本**：`tmp/fullrun/ledger.jsonl`（每部一行，追加写，唯一事实源）
- **渲染报告**：`tmp/fullrun/report.md`（由账本重算，不含推测值）
- **驱动脚本**：`scripts/fullrun_atmp.py`（串行、可续跑、GPU 闸门）

---

## 1. 口径（开跑前写死）

| 项 | 取值 |
|---|---|
| 素材根 | `/srv/media/jellyfin/JELLYFIN/atmp`，一层子目录，**排除点目录**（含 SRT 隔离目录） |
| 素材范围 | **41 个常规视频文件**；按用户口径排除 VR 前缀 `KAVR-` / `MDVR-`（5 个文件） |
| DAG | `extract → stt_qwen → translate`（显式三步，不走默认 `stt`） |
| 提交方式 | 服务 API `POST /jobs`，鉴权头 `X-API-Token`，**不下发 job_config**（观测配置文件档位） |
| 并发 | **严格串行**：一部终态后才提交下一部（GPU 独占、对另一侧干扰最小） |
| 回拷 | `[translation] copy_back = __video_dir__`，产物落到视频同目录 `<stem>.ja.srt` / `<stem>.zh.srt` |
| 轮询 | 10s；单部超时 6h（超时即取消并记账，不按成功处理） |
| GPU 闸门 | 每部开跑前查空闲显存，< 12GiB 则等待（60s 一次），最长等 12h |
| 失败处理 | 只记账，不自动改配置/重跑；失败片在下一轮 `run` 时自动重试 |

### 关键配置（隔离实例 `tmp/fullrun/config.ini`，由 `whisper-stt/config.ini` 派生）

- 端口 **18001**，DB `tmp/fullrun/db/whisper_stt_service.db`，日志 `tmp/fullrun/logs`，产物 `tmp/fullrun/artifacts`；
  `artifact_cleanup_enabled = false`（保留产物以便事后审计）。
- `[stt_qwen]`：`nominal 30 / Δback 20 / Δfwd 20 / fallback_fwd 40`（片长上界 70s）、`batch_size 10`、
  `tokens_per_sec 16`、`min_free_vram_gb 12.0`、`max_segment_sec 30`、`strict_output false`。
- `[translation]`：`batch_size 50`、`parallel 4`、`timeout 240`、`reasoning_enabled false`、
  `checkpoint_enabled true`、`strict_ids false`；**`max_tokens` 20000 → 50000**
  （02:07 调整，见 §4.1）。
- `[workers]`：`extract 10 / stt_qwen 1 / translate 8`。
- 子仓库 `whisper-stt/` **未修改任何文件**（配置与运行数据全在主仓 `tmp/fullrun/` 下）。

## 2. 开跑前状态变更

### 2.1 既有 SRT 清空

- 清空前实测 **20 个 SRT / 10 部片**（含 `.qwen.ja/zh` 实验产物）。
- 处理方式：整体移到 `/srv/media/jellyfin/JELLYFIN/atmp/.srt_quarantine_20261103-012454/`，
  附 `manifest.json` + `manifest.tsv`（逐文件 bytes / sha256 / 相对路径），可整体回滚。
- 清除后复核：隔离目录之外的 SRT 数 = **0**。

### 2.2 服务与 GPU

- 旧 18000 实例原本未运行；本轮另起 18001 隔离实例，与另一侧前端联调环境互不可见。
- 开跑时 GPU 被外部占用 9.4GiB（空闲 6.6GiB），驱动按闸门等待；用户释放后 01:34 自动开跑。

## 3. 逐片计时

> 表格每部完成后更新；完整字段（每阶段 attempt、last_error、sha256、覆盖率）见 `tmp/fullrun/report.md`。

| # | 影片 | 时长 | 状态 | extract | stt_qwen | STT RTF | VAD | 片/批 | 峰值显存 | translate(墙钟) | 翻译API累计 | 重试 | 合计 | ja/zh 段 | 覆盖 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 300MIUM-1457-U | 73min | succeeded | 1.8m | 10.9m | 0.143 | 9.2s | 146/15 | 7.5G | 6.9m | 47min | 13 | 42.1m | 434/434 | 0.9968 |
| 2 | ABF-382-UC | 101min | succeeded | 1.5m | 18.7m | 0.179 | 10.6s | 200/20 | 9.2G | 6.2m | 29min | 10 | 34.9m | 335/335 | 0.9983 |

## 4. 异常与观察

### 4.1 翻译 parse 空转（上游 finish_reason=error，max_tokens 不是瓶颈）

- 现象：首片 translate 的 `1/1` 批次在 6 轮重试（每轮 100–200s）后报
  `unable to extract JSON value from response`，随后阶段重试从头再来。
- 归因（一次独立复现，同一切批与提示词，`max_tokens=50000`）：
  HTTP 200，但 **`finish_reason=error`**、`completion_tokens=11946`、
  `content` 仅 **56 字符**且截断在半个 JSON 键上；`reasoning_tokens=0`。
  → 上游把 1.2 万 token 的生成"算完丢了"，返回残片；**调大 max_tokens 不改变结果**。
- 处置：按用户要求把 `[translation] max_tokens` 上调到 **50000**（02:07 生效，
  该键不在 `as_job_config()` 冻结面内，服务每次跑翻译实时读配置文件）；
  同批次第 3 次尝试成功（136s），但**单样本不足以归因**，后续 40 部继续观测。
- 代价：首片 translate 的 API 累计耗时 **2843s（47.4min）**、13 次重试，
  而任务级墙钟只有 415s——重试是当前最大的隐性成本。

### 4.2 GPU 闸门两档化（驱动自身缺陷，已修）

- 现象：第 3 部开始卡在 "GPU 忙：空闲 1663MiB < 门槛 12288MiB"，永不开始。
- 归因：服务把 stt_qwen 权重**常驻显存**（实测约 12.7GiB，服务进程生命周期内不释放），
  空闲基线就只有 **1.6–2.0GiB**；驱动用"空闲 ≥12GiB"判断，等于把自己的缓存当成外人占卡。
- 修复：`--min-free-vram-gb` 只在**冷启动**（服务进程尚未加载过模型）生效；是否已加载
  用 `/metrics` 的 `whisper_stt_model_cache_misses_total ≥ 1` 判定，已加载则只按
  `--gate-floor-gb`（1.0GiB）判"是否有外部进程又抢卡"。
- 影响：前 2 部的计时不受影响；第 3 部起正常。

## 5. 结论与建议

（跑完后补：每音频小时成本、阶段占比、失败面、对配置的建议）

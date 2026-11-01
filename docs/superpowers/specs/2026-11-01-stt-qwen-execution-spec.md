# stt_qwen 正式执行 SPEC（VAD 定点切片 × Qwen3-ASR 本地阶段）

- **状态**：**正式执行目标文档**（取代 2026-11-01 早期设计稿与 handoff 中冲突的参数）
- **日期**：2026-11-01
- **适用范围**：`whisper-stt` 子仓库（`/home/base/repo/video-stt-whisper-server/whisper-stt`）
- **前置阅读**（证据来源，非必读但可追溯）：
  - `docs/superpowers/executions/2026-11-01-qwen3-asr-local-pilot.md`
  - `docs/superpowers/executions/2026-11-01-stt-qwen-vad-cut-eval.md`（§1–§12，含全部实测）

---

## 0. 一句话

新增与现有 `stt` **并列**的本地离线 ASR 阶段 `stt_qwen`：用 FireRedVAD 在"名义片长 ± 窗口"内寻找**真实语音边界**定点切片（不逐句切、不固定网格），按批喂给本地 Qwen3-ASR-1.7B，输出标准 `asr/<stem>.ja.srt`；**旧 `stt` 与其配置、产物契约零改动**。切片参数全部可配，本轮落地用**已实测通过的保守档**，目标档留作后续调优。

**翻译（translate）不是本文档的主流程**：沿用现有实现，只修掉两个会阻塞标准三步链路的缺陷（见 §7）。

---

## 1. 目标与非目标

### 1.1 目标

1. `stt_qwen` 成为可通过显式 DAG 选择的合法阶段，与 `stt`、`stt_whisperx` 互斥（DAG 内恰好一个 ASR）。
2. 运行期**全离线**：模型权重、VAD 权重均从本地绝对路径加载，禁止运行期联网下载。
3. 产物契约不变：`artifacts/<job_id>/asr/<stem>.ja.srt`，`translate` 无需改动。
4. 切片策略：**VAD 定点吸附 + prev 锚定 + 两级搜索窗 + 硬切上界**，参数全部可配。
5. 关键内容**绝不静默丢失**：空对齐、无语音片、硬切、fallback 全部计数并进日志/指标。
6. 达到实测吞吐量级：**每音频小时约 270s 推理**（50s 档实测），单部 2h 片约 9 分钟。

### 1.2 非目标

- 不改默认 DAG（仍 `extract -> stt -> translate`）。
- 不删除、不重命名、不改 `stt` / `stt_whisperx` 的行为。
- 不做说话人分离（diarization）；不落 word-level 公开产物。
- 不重做翻译逻辑（只做 §7 的最小修复）。
- 不引入 vLLM / flash-attn（当前吞吐已够）。
- 不追求"坍缩率-片长曲线"（用户已决定：70s 很短，不做该实验）。

---

## 2. 已确立的实测事实（不得再推翻，除非有新实测）

| # | 事实 | 证据 |
|---|---|---|
| F1 | 要时间戳时片长上限 **180s**；超限会被包内 `split_audio_into_chunks` 二次切分、废掉 VAD 定点 | `qwen_asr/inference/qwen3_asr.py:366`、`utils.py:34-35` |
| F2 | **长片坍缩**：180s 单次 → 1 字；同段切 7×26s → 41 字（41 倍） | eval §9.3 探针 |
| F3 | 坍缩是**退化生成打到 `max_new_tokens`**；耗时与上限线性（64→3.7s、512→21.7s、2048→85.9s） | eval §9.3 |
| F4 | 定点切精度远优于能量切/固定网格：切点语音概率 0.054 vs 0.092 vs 0.346；到语音边界距离 0.00s vs 0.25s vs 0.54s | eval §3.2 |
| F5 | **grid 锚定会切出超 180s 的片**（5/10，最长 182.14s）；prev 锚定 0/10 | eval §3.3 |
| F6 | 候选取"窗内最靠后"会把片长漂到窗上沿（30±20 实测均值 ~45s）；取"最接近名义目标"才落在 30s 中位 | eval §10 前一轮 |
| F7 | 30s 档全长产物：384 段/3240 字/覆盖 100%/清洗后 0 超长段 | eval §10.1 |
| F8 | 50s 档三部实测：494 片/39 批/推理 1844.8s/RTF 0.075/峰值显存 10.4–11.9GB/覆盖 ≥99.5% | eval §11 |
| F9 | 硬切上界被严格触达（50 档最长片正好 80.0s），链路真实可用 | eval §11 |
| F10 | 时间戳清洗必须复用服务端 `clean_segment_timeline`，否则出现 12 个 30–115s 超长段 | eval §10、`common.py:171` |
| F11 | 纯无语音片可跳过收益≈0（30s 网格 0/60、180s 网格 0/10） | eval §2 |
| F12 | `time_stamps` 可能为 `None`，必须回退片边界并计数，否则崩溃 | eval §9/§10 |
| F13 | 翻译 CLI 把 HTTP 超时当任务 deadline（240s）→ 606 行被取消；且请求无 `max_tokens` → 大批次输出被截断 → `parse` 错误重试（单批 303s） | 本轮 translate 实测日志 |
| F14 | **`reasoning.enabled=false` 关不掉思考**（更正 F13 与 §7-T2 的旧结论）：同一批 40 条仍产生 7185 个 reasoning token（不传该字段 12676、`effort=low` 6148、`max_tokens=0` 5732）；`batch_size=100` 时 completion 13773–22974、`finish_reason=error`、内容截断在半个字符串上，`batch_size=25` 时 16.6s 稳定成功 | 验收记录 §6.3 单变量对照 |

---

## 3. 切片算法（唯一事实源）

### 3.1 算法定义

```
输入：wav（16k mono pcm_s16le）、duration、VAD 语音段列表 segments[(start,end)]、参数（§4）
输出：cuts[]（严格递增）、每片 speech_ratio、每片的 policy 计数

target = prev_cut + nominal_seconds        # prev 锚定（禁止 k*nominal 网格，见 F5）
第 1 级（正常窗）：候选 = { o | o ∈ {语音段 end} 且 max(prev+min_chunk, target-Δback) ≤ o ≤ target+Δfwd }
                命中 → cut = argmin|o - target|，policy=vad_offset
第 2 级（fallback）：候选 = { o | max(prev+min_chunk, target-Δback) ≤ o ≤ target+fallback_fwd }
                命中 → cut = argmin|o - target|，policy=vad_offset_extended
第 3 级（硬切）：cut = min(target + fallback_fwd, duration)，policy=hard_cut  ← 必计数
```

### 3.2 不可违背的不变量

| # | 不变量 | 违反后果 |
|---|---|---|
| I1 | 每片长度 ≤ `nominal_seconds + fallback_forward_seconds`，且**绝对 ≤ 180s** | 包内二次切分（F1） |
| I2 | 切点严格递增，且相邻间隔 ≥ `min_chunk_seconds` | 碎片片/死循环 |
| I3 | 候选切点必须取**最接近 target** 者，不得取 max/min | 片长漂移（F6） |
| I4 | 名义目标必须锚定**上一刀**，不得用固定网格 | 超限片（F5） |
| I5 | 硬切/fallback/空对齐必须**计数**并进日志与 report | 静默降级 |
| I6 | 片尾切点 ≤ 音频时长；SRT 末条结束 ≤ 音频时长 | 时间轴越界 |

### 3.3 参数语义注意

- `fallback_forward_seconds` 是**片长上界**的直接来源：上界 = `nominal + fallback_forward`。
- 本轮落地：30 + 40 = **70s**；目标档：50 + 30 = **80s**。两者都远低于 180s 硬上限，**不是**同一参数。

---

## 4. 参数表（全部可配）

### 4.1 本轮落地值（本次执行使用，已实测通过）

| 键 | 值 | 说明 |
|---|---|---|
| `nominal_seconds` | **30** | 名义片长 |
| `delta_back_seconds` | **20** | 正常窗后向 |
| `delta_forward_seconds` | **20** | 正常窗前向 |
| `fallback_forward_seconds` | **40** | fallback 前向上限 → **片长上界 70s** |
| `min_chunk_seconds` | **10** | 最小片长 |
| `hard_cut_on_miss` | **true** | 扩窗仍无边界即硬切到上界并计数 |
| `batch_size` | **10** | 每次 API 调用的片数 |
| `tokens_per_sec` | 16 | `max_new_tokens = clamp(⌈max_chunk_sec × 16⌉, 256, 2048)` |
| `max_segment_sec` | 30 | SRT 单段上限（复用清洗函数） |

### 4.2 目标值（后续调优候选，写入配置默认值需再验收）

| 键 | 值 | 说明 |
|---|---|---|
| `nominal_seconds` | **50** | 少切点、少批次 |
| `fallback_forward_seconds` | **30** | → **片长上界 80s** |
| `batch_size` | **13** | 三部实测 10.4–11.9GB、RTF 0.075 |

> 两套值必须都能通过配置切换，代码里**不得硬编码**任一套。

### 4.3 其余配置（`[stt_qwen]` 段）

| 键 | 默认 | 说明 |
|---|---|---|
| `model_dir` | `models/qwen3-asr/Qwen3-ASR-1.7B` | 本地权重（必须为绝对路径或相对 config 解析后的绝对路径） |
| `aligner_dir` | `models/qwen3-asr/Qwen3-ForcedAligner-0.6B` | 本地对齐模型 |
| `vad_model_dir` | `models/vad/fireredvad/VAD` | FireRedVAD 权重目录（含 `model.pth.tar`/`cmvn.ark`） |
| `vad_speech_threshold` | `0.4` | FireRedVAD 判定阈值（与官方默认一致） |
| `vad_use_gpu` | `true` | VAD 推理设备（588K 参数，30 分钟约 4s） |
| `device` | `cuda:0` | 固定设备，不做 auto（便于 fail-fast） |
| `dtype` | `bfloat16` | 与实测一致 |
| `require_cuda` | `true` | CUDA 不可用即失败 |
| `min_free_vram_gb` | `12.0` | 加载前空闲显存门槛（实测峰值 9.6–11.9GB） |
| `align_missing_fallback` | `chunk_boundary` | `time_stamps=None` 时回退片边界单行并计数 |
| `max_segment_sec` | `30` | 清洗单段上限 |
| `tokens_per_sec` | `16` | 见 4.1 |

### 4.4 阶段级运行参数（与既有阶段同构）

| 键 | 默认 | 说明 |
|---|---|---|
| `[workers] stt_qwen_workers` | **1** | GPU 串行，避免自抢 |
| `[timeouts] stt_qwen_timeout_sec` | **5400** | 2h 片实测 8–16 分钟，余量充足 |
| `[retry] stt_qwen_max_retries` | **2** | 沿用既有语义 |
| `[runtime] model_cache_size` | 保持 2 | 若与 whisper 模型共存需评估调大（见 §10 风险） |

---

## 5. 代码改动清单（文件级，最小集）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `whisper_stt_service/core/stages.py` | `SUPPORTED_STAGES` 加 `stt_qwen`；`STAGE_CONFIG_KEYS["stt_qwen"]`（仅允许 §4 中标注"可按 job 覆盖"的键：`timeout_sec`/`max_retries`/`nominal_seconds`/`delta_*`/`fallback_forward_seconds`/`min_chunk_seconds`/`batch_size`/`max_segment_sec`；**禁止**覆盖 `model_dir`/`aligner_dir`/`vad_model_dir`/`device`） |
| 2 | `whisper_stt_service/core/dag.py:13` | `ASR_STAGES` 加 `stt_qwen`（唯一 ASR 语义自动生效） |
| 3 | `whisper_stt_service/executor/qwen_boundary.py`（新增） | **纯函数**：`pick_cuts(duration, nominal, delta_back, delta_fwd, fallback_fwd, min_chunk, hard_cut_on_miss, speech_ends) -> (cuts, meta)`；无模型依赖，可单测 |
| 4 | `whisper_stt_service/executor/stt_qwen.py`（新增） | `run_stt_qwen(...)`：读 wav → FireRedVAD（一次前向取 probs 与 segments）→ `pick_cuts` → 切片 → 批处理 ASR → 时间戳合成 → 清洗 → 原子写 SRT → 进度/计数 |
| 5 | `whisper_stt_service/executor/__init__.py`、`executors.py` | 导出 `run_stt_qwen`、`pick_cuts`，保持包根兼容导出面 |
| 6 | `whisper_stt_service/core/config.py` | 三个 dataclass 增字段 + 读取（`fallback=` 写法）；`REQUIRED_CONFIG_OPTIONS` 增键（注意：该项**只写 error 日志、不阻断启动**，见 `bootstrap.py:53`，故不能当校验保障） |
| 7 | `whisper_stt_service/service/bootstrap.py:74 / :241 / :247` | `_build_stage_effective_defaults` 增 `stt_qwen`；`stage_max_retries`/`stage_timeouts` 字典增键 |
| 8 | `whisper_stt_service/service/runtime.py:336 / :571 / :1110 / :1137 / :2262` | worker 池、阶段分派、`_build_staging`、`effective_config` 组装；新增 `_execute_stt_qwen(...)`（照 `:1721` 的 `_execute_stt_whisperx` 体例） |
| 9 | `whisper_stt_service/repo/job_repository.py:391` | **必须**把 `stt_qwen` 加入 `{"stt","stt_whisperx"}` 集合——否则 `input_path` 会落到原视频而非 16k wav（静默用错输入） |
| 10 | `whisper_stt_service/service/model_cache.py` | 新增 `get_qwen_asr_bundle(...)`：key 覆盖 模型目录/对齐目录/device/dtype/batch 相关参数；沿用 `make_cache_key` |
| 11 | `config.example.ini` / `config.ini` | 新增 `[stt_qwen]` 段与 §4.4 三项；`stt_qwen_workers=1` |
| 12 | 测试 | 见 §9 |

**实现来源**：`whisper-stt/tmp/research/pilot/prototype_stt_qwen_vad.py`（scratch，已跑通 ADN + 三部片）。**不得**把 scratch 脚本直接当产品代码交付，必须抽成 3/4 两项；原型中的注释与计数逻辑一并迁移（AGENTS：不得删除注释）。

---

## 6. 执行器契约

### 6.1 输入/输出

- 输入：`artifacts/<job_id>/audio/<stem>.16k.wav`（缺失或 0 字节 → `missing_audio_artifact`）
- 输出：`artifacts/<job_id>/asr/<stem>.ja.srt`（同目录临时文件 + `os.replace` 原子写）
- 中间：不落切片音频文件（内存中按 `(np.ndarray, sr)` 传给模型），仅落 `*.report.json` 片段到日志目录（可选）

### 6.2 必须实现的行为

1. **增量落盘**：每批成功后重写 SRT（崩溃不丢已算内容）；异常路径 `finally` 也要写。
2. **空对齐兜底**：`time_stamps is None` → 该片用片边界单行，`align_missing_chunks += 1`。
3. **空文本片**：`text.strip()==""` → 不产出行，计 `empty_chunks`。
4. **进度**：按批上报 `(已完成片数/总片数)`，沿用 `progress_queue`。
5. **GPU 落点校验**：加载后遍历参数，若非全在 `cuda` → 立即失败 `stt_qwen_not_on_gpu`。
6. **显存门槛**：加载前 `torch.cuda.mem_get_info()` 检查空闲 ≥ `min_free_vram_gb`，不足 → `stt_qwen_insufficient_vram`。
7. **时间戳清洗**：写盘前调用 `clean_segment_timeline`（`common.py:171`，与 `stt.py:496` 同一函数），传 `max_segment_sec`，`adjusted>0` 打 WARNING 并写日志/指标。
8. **结果校验**（写盘前）：末条结束时间 / 音频时长 < `min_coverage`（默认 0.98）→ 记 `stt_qwen_output_incomplete`（默认**告警不失败**，可配 `strict_output`）。

### 6.3 错误码（进 `error` 字段，可被监控消费）

`stt_qwen_model_missing`、`stt_qwen_aligner_missing`、`stt_qwen_vad_missing`、`stt_qwen_cuda_unavailable`、`stt_qwen_not_on_gpu`、`stt_qwen_insufficient_vram`、`stt_qwen_config_invalid`（片长上界 > 180 或 min > nominal 等）、`stt_qwen_output_incomplete`、`missing_audio_artifact`。

### 6.4 可观测性

- 日志字段沿用 SPEC G 的 11 字段；`effective_config` 固化：模型/对齐/VAD 路径、device、dtype、`nominal/delta_*/fallback_forward/min_chunk/batch_size/tokens_per_sec`、`max_new_tokens`、片数、批数、`model_cache_hit/key`。
- 逐片日志（可采样）：`chunk_index`、`start/end`、`speech_ratio`、`policy`、`chars`。
- 指标：`stt_qwen_chunks_total{policy=vad_offset|vad_offset_extended|hard_cut}`、`stt_qwen_align_missing_total`、`stt_qwen_cleanup_adjusted_total`、`stt_qwen_rtf`、沿用 `task_duration_seconds{stage=stt_qwen}`。

---

## 7. 前置修复：翻译链路（非主流程，但阻塞标准三步）

标准三步包含 `translate`，以下两条**必须先修**，否则实测跑不通：

| # | 文件 | 问题（实测） | 修法 |
|---|---|---|---|
| T1 | `whisper_stt/translate_srt_ja_to_zh.py:459-463` | `timeout_sec` 取 `[translation] timeout=240`（HTTP 超时）→ 任务 deadline 也被设成 240s，606 行片被 `translate_timeout` 取消 | 任务 deadline 改取 `[timeouts] translate_timeout_sec`（7200），`--timeout` 仅作单次 HTTP 超时；或新增独立 `--deadline` |
| T2 | `whisper_stt_service/executor/translate.py:274-283`（请求体） | 请求体只有 `model/temperature/messages`：① 无 `max_tokens` → 大批次输出被截断 → `parse` 错误重试（实测单批 303s）；② 无 `reasoning` → 推理写进正文/无法关思考 | ① 加 `max_tokens`（可配，默认 16000）；② 加 `reasoning: {"enabled": false}`（用户已授权）。**2026-11-01 验收更正**：该参数**只减不关**（实测仍产生 7185 个 reasoning token，见 F14），因此它不能替代"把 batch_size 降下来"这条主要手段 |

**最终决定（2026-11-01，用户拍板）**：`[translation] batch_size = 50`、`max_tokens = 20000`、`reasoning: {"enabled": false}` **仍下发**。依据：100 条实测 completion 13773–22974 且 `finish_reason=error`；25 条 16.6s 稳定成功；50 为折中值。**该折中值未做回归验证**（用户明确要求不再重跑影片）。已同步到 `config.ini`、`config.example.ini`、`executor/common.py` 默认值与 `core/config.py` 的 `TranslationSettings`，并新增用例把「模板值 = 代码默认值」与「配置值真的进请求体」两件事钉死。

附带（非阻塞，但建议）：`parallel` 2→3；`batch_size` **实测最优为 20~25**（原文写 200→150，幅度不够：2026-11-01 验收实测 `batch_size=100` 单批尝试中位 194.9s、最大 313.7s 且大量 `parse` 失败；25 条则 16.6s 且稳定，见验收记录 §6.3）。**注意降 batch 不会缩短总时长**（总 token 量不变），它降低的是单批失败面与重试成本。

---

## 8. 配置与开关

- 所有 §4 参数必须可通过 `config.ini` 与 `job_config.stt_qwen` 覆盖（除 §5-3 明确禁止的路径类键）。
- 切换两套档位只改配置，不改代码；`config.example.ini` 里默认写**本轮落地值**，并在注释中给出目标档。
- 运行期禁止联网下载：所有路径必须存在，缺失即 fail-fast。

---

## 9. 测试计划

### 9.1 单元测试（不加载模型）

- `pick_cuts` 合成用例（必须先跑，再烧真数据）：
  1. 密集边界（每 3s）→ 全部落正常窗，片长 ∈ [nominal-Δback, nominal+Δfwd]
  2. 稀疏边界（每 25s）→ 命中最近边界，片长稳定
  3. 极稀疏（每 120s）→ 走 extended，片长 ≤ 上界
  4. 无边界 → 全 `hard_cut`，片长 ≤ 上界且首尾正确
  5. 边界全在窗口外 → 不得超出上界
  6. 断言：严格递增、间隔 ≥ min_chunk、末片 ≤ duration
- `STAGE_CONFIG_KEYS` 白名单：允许键通过、路径类键被拒（`job_config_key_not_supported`）。
- `_build_stage_io("stt_qwen")` 返回 `input_path=wav`、`output_path=asr/<stem>.ja.srt`（防 io 兜底陷阱）。
- 清洗：构造 886s/乱序/零长/重叠 fake segments，断言单调、≤30s、条数与文本不变。
- 配置：缺 `[stt_qwen]` 段走 fallback 不抛；`nominal+fallback_forward > 180` 必须被拒（`stt_qwen_config_invalid`）。

### 9.2 集成测试（fake executor）

沿用 `tests/integration/test_runtime_fake_executors.py`：注册假 `stt_qwen`，验证 worker 池、租约心跳、staging/promotion、重试、copy_back——不加载真实模型。

### 9.3 真实媒体验收（本次执行的唯一验收口径）

- **素材**：从 `/srv/media/jellyfin/JELLYFIN/atmp/` **随机选 3 部未翻译过**的影片（排除 VR：`KAVR-*`/`MDVR-*`；排除已有字幕的目录），记录随机种子。
- **执行方式**：**必须走标准三步**（服务 API：`POST /jobs`，DAG = `extract → stt_qwen → translate`），**禁止用临时脚本冒充落地**。
- **配置**：§4.1 本轮落地值（30/±20/fallback+40/batch10）。
- **必须记录的指标**（每部）：
  | 指标 | 判据 |
  |---|---|
  | 任务状态 | `succeeded`（attempt 0 优先） |
  | 片数 / 批数 | 与理论值量级一致（±20%） |
  | 片长分布 | min ≥ 10s、max ≤ 70s、**0 片 > 70s** |
  | fallback/hard_cut 计数 | 分别记录（不得为隐藏值） |
  | 推理耗时 / RTF | 记录；参考 50 档 0.075 |
  | 峰值显存 | ≤ 12GB（本轮档）|
  | 覆盖终点 | ≥ 98% 音频时长（否则告警）|
  | SRT 结构 | 最长段 ≤ 30s、>30s 段 = 0、单调、空文本 0 |
  | 清洗 adjusted | 计数并记录 `max_original_sec` |
  | ja/zh 段数 | 相等；`checkpoint` 键集合 = 段数；zh 残留假名 = 0 |
  | copy_back | 视频同目录 ja/zh sha256 与本地产物一致 |

- **发布**：产物回拷到视频目录（`copy_back=__video_dir__`）。若文件名会覆盖既有字幕，**必须先经用户批准**。
- **记录**：结果写入 `docs/superpowers/executions/2026-11-01-stt-qwen-acceptance.md`。

---

## 10. 风险与未验证项（执行时必须保留这些标注）

1. **GPU 争用**：batch 13 时整卡口径峰值曾达 15.7GB/16.4GB（余量 ~0.7GB）。本轮用 batch 10（峰值 9.6–10.4GB）更安全；**必须独占**，与其它任务并发会 OOM。
2. **坍缩机制未定性**：只知与片长强相关（180s 高发、30s 未见）；触发条件未知。本轮用 30s 档已有 233 片 0 坍缩的实测，目标档 50s 有 494 片实测（未见整片坍缩），但**未做 50–180s 之间的刻度**。
3. **`tokens_per_sec=16` 未做召回验证**：理论上存在极密集语句被截断的可能（实测平均 13.9 字/片，远低于预算）。
4. **翻译链路仍有偶发 `ids_mismatch` 重试**（ADN/SNOS 均出现），靠"接受子集 + 只补缺失"自愈；未根治。
5. **`stt_whisperx` 去留未决**：新阶段落地后是否标 legacy，待用户决定。
6. **模型缓存**：`model_cache_size=2` 在 whisper + qwen 共存时可能不够，未实测。

---

## 11. 回滚方案

- 代码：移除 `SUPPORTED_STAGES`/`ASR_STAGES`/`STAGE_CONFIG_KEYS` 中的 `stt_qwen` 与新增 executor；默认 DAG 从未改变，旧路径不受影响。
- 配置：`[stt_qwen]` 段整体删除即可（无其它阶段依赖）。
- 环境：依赖快照 `whisper-stt/tmp/research/venv-freeze-before-fireredvad.txt`；`qwen-asr` 安装前快照 `venv-freeze-before-qwen.txt`。
- 数据：`stt_qwen` 只写 `artifacts/<job_id>/asr/`（DAG 唯一 ASR 写者），回滚不影响既有 job。

---

## 12. 执行顺序（正式落地步骤，按序勾选）

> **执行状态（2026-11-01，本轮）**：1–7 全部完成并附证据；8 未执行（可选）。
> 验收结论 **通过**，详见 `docs/superpowers/executions/2026-11-01-stt-qwen-acceptance.md`。

1. [x] 前置修复 T1/T2（翻译 deadline 与请求体），跑子集测试确认无回归。
   - 证据：子仓库提交 `05e9898`（`--deadline` 取 `[timeouts] translate_timeout_sec`；
     请求体新增 `max_tokens`/`reasoning.enabled`）；`tests/unit/test_translate_reliability.py` 通过。
2. [x] 新增 `qwen_boundary.py` + 单元测试（§9.1 合成用例必须先过）。
   - 证据：`whisper_stt_service/executor/qwen_boundary.py`；`tests/unit/test_qwen_boundary.py` 15 例通过，
     其中 `test_prev_anchoring_beats_grid_anchoring_regression` 用同一份边界证明旧 grid 锚定会切出
     >70s 的片、prev 锚定不会（§13.5「旧实现必须失败」）。
3. [x] 新增 `stt_qwen.py`，本地跑通单部片（脚本直调 executor，不入库）并与原型指标对齐。
   - 证据：`whisper-stt/tmp/research/pilot/run_executor_stt_qwen.py` 直调执行器跑 ADN-783-UC（7102.4s）：
     **384 段 / 3203 字 / 229 片 / 23 批 / 推理 1192.0s / RTF 0.168 / 覆盖 1.0 /
     adjusted 3（最长原始 61.76s→30.0s）/ align_missing 2 / hard_cut 4 / fallback 3 / 最长片 70.0s**，
     与 eval §10 原型（384 段 / 3240 字 / 233 片 / 1061.9s / adjusted 3）逐项对齐。
4. [x] 接入 Service（§5 全部 12 项），补集成测试与配置示例。
   - 实做范围比清单多 3 处（清单写作时未列，属同一语义的必改点）：`core/dag.py` 的
     job_config 类型/范围校验表、`api/app.py` 的 `/metrics` 阶段列表、`service/workers.py` 兼容导出面。
5. [x] 全量测试通过（CPU 子集 + 新增单测；记录 `pytest` 统计）。
   - 证据：`pytest whisper-stt/tests/unit whisper-stt/tests/integration` → **615 passed, 1 skipped**
     （含本次新增的 `test_qwen_boundary.py` 15 例、`test_stt_qwen_stage.py` 26 例）。
6. [x] 起服务，随机选 3 部未翻译影片，走标准三步提交。
   - 证据：种子 `20261101` 抽出 SAN-484-U / ABF-394-U / CAWB-069-U（候选池 30 部）；
     三个 job 全部 `succeeded`，且 `stt_qwen` 阶段的 attempt 均为 0（没靠重试兜底）。
7. [x] 按 §9.3 逐项验收，产物回拷，写验收记录。
   - 证据：`docs/superpowers/executions/2026-11-01-stt-qwen-acceptance.md`。
     **验收过程中发现并修复了 3 个执行器缺陷**（显存门槛未区分冷启动/命中缓存、
     字级时间戳逃逸未按片长夹取、静音片输出「。」形成的纯标点噪声行），均已补回归测试；
     另取证了翻译链路的容量问题（`reasoning.enabled=false` 关不掉思考，批次应降到 20~25）。
8. [ ] （可选）用目标档（50/±20/+30/batch13）复跑 1 部，记录差异留档。
   —— **本次未执行**：用户本轮明确要求用落地档（30/±20/+40/batch10）；目标档参数
   已全部可配置（§14），随时可跑。

---

## 13. 验收标准（当且仅当全部成立）

1. 默认 job 仍走 `stt`，其配置/产物契约无变化；显式 DAG 可路由到 `stt_qwen`。
2. 运行期零联网（可用拔网或 `strace` 抽验），所有模型来自本地路径。
3. 3 部影片标准三步全部 `succeeded`，产物结构全部满足 §9.3 判据（0 超长段、覆盖 ≥98%、ja/zh 段数一致、0 假名残留）。
4. `fallback`/`hard_cut`/`align_missing`/`cleanup_adjusted` 四类计数在日志与指标中可见且与产物一致。
5. 单元 + 集成测试全绿；合成边界用例能区分新旧实现（旧实现必须失败）。
6. 验收记录落档，且明确标注 §10 的未验证项。

---

## 14. 关键参数速查（执行时只看这张表）

| 场景 | nominal | Δback | Δfwd | fallback_fwd | 片长上界 | batch |
|---|---|---|---|---|---|---|
| **本轮落地** | 30 | 20 | 20 | 40 | **70s** | 10 |
| 目标档（可切） | 50 | 20 | 20 | 30 | **80s** | 13 |
| 硬上限（不可越） | — | — | — | — | **180s** | — |

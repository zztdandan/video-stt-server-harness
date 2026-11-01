# stt_qwen × FireRedVAD 定点切片 —— 交接说明（Handoff）

- **日期**：2026-11-01
- **交接来源**：侧会话讨论（Qwen3-ASR 原理 → 切片策略 → VAD 定点切片）
- **交接对象**：主 agent（本工作区 `whisper-stt` 实施方）
- **状态**：决策已定，**实验未跑、代码未动**（等主 agent 执行）

---

## 0. 一句话

把 `stt_qwen` 的切片策略从"固定 30s"改为：**用 FireRedVAD 在 180s 前的 Δ 秒窗口内寻找语音边界定点切片**（不逐句切），切点数保持官方量级（2h ≈ 39 个），但每个切点落在真正的语音停顿处。本文件给出决策依据、硬约束、待跑实验、代码落点与禁止事项，主 agent 无需原上下文即可执行。

---

## 1. 前置状态与必读文档

**目标（不变）**：新增与 `stt` 并列的**本地离线** ASR 阶段 `stt_qwen`（Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B，权重落本地），旧 `stt` 及其配置、产物契约**零改动**；产物仍为 `asr/<stem>.ja.srt`，`translate` 不需要改。

**已完成**：

| 项 | 状态 | 证据 |
|---|---|---|
| 权重本地化 | 1.7B 主干 4.4G + 对齐 1.8G | `models/qwen3-asr/` |
| 依赖安装 | `qwen-asr==0.0.6` 装入主 venv（+40 包，`starlette 1.0.0→1.7.0`） | 装后 CPU 子集测试 **481 passed**；回滚快照 `whisper-stt/tmp/research/venv-freeze-before-qwen.txt` |
| pilot 实测 | 短切片批处理 RTF 0.022 | `docs/superpowers/executions/2026-11-01-qwen3-asr-local-pilot.md` |
| SPEC | 已出，**待用户评审** | `docs/superpowers/specs/2026-11-01-qwen3-asr-local-stage-design.md` |
| VAD 调研 | FireRedVAD 已调研完成、待实施 | `docs/research/vad-diarization-upgrade.md:47-58`、`:83-89`、`:144-202`、`:229-231` |

---

## 2. 本次决策（**覆盖 SPEC 中 `chunk_seconds=30` 的默认值**）

| # | 决策 | 依据 |
|---|---|---|
| **D1** | 切片策略 = **FireRedVAD 定点切片**：只在名义切点附近找语音边界，**不逐句切段** | 逐句切（whisperx 式）会把 2h 切成数百上千片，跨句上下文损失最大，而 Qwen3-ASR 本身是长上下文模型 |
| **D2** | 搜索窗 = **`[180 - Δ, 180]`，只向前找**，Δ 默认 **30s** | 要时间戳时片长硬上限 180s（见 §3），"+20s 向后找"会被包内二次切分废掉 |
| **D3** | VAD 选 **FireRedVAD**，不选 pyannote / Silero | 本方案唯一依赖的能力就是**边界精度**：调研文档明确 pyannote 弱项是"10s 滑窗 + LSTM，边界不精确"（`:38-41`），Silero 误检率 9.41%「在有噪声/音乐的日语视频中不可靠」（`:96`）；FireRedVAD F1 97.57%、误检 2.69%、无窗口边界效应（`:83-89`） |
| **D4** | fallback 链**显式化**：窗内无边界 → ① 向前延长搜索（Δ×2） → ② 取窗内能量最低点（=官方行为） → ③ 允许词中切并**记告警计数** | 连续说话 40s 不换气完全可能；静默兜底=静默契约变更（团队准则：显式优于兜底） |
| **D5** | 切点取**语音段结束（offset）**，不取开始（onset） | 片尾留静音比片头缺半句安全，也避免削掉下一句开头 |
| **D6** | **纯静音片直接跳过**（不送 ASR），并把"语音/非语音"标注落盘 | 省算力；且 Qwen3-ASR **无 VAD**，"没人说话"与"识别失败"原本无法区分，此标注正好补上这个观测盲点 |

**待定（实验后定）**：Δ 最终值；是否把"1–2s 重叠 + 接缝去重"与"`context` 续接上一片尾部文本"从可选升为必做（当前建议：**升为必做**）。

---

## 3. 硬约束（违反即方案失效，证据来自安装包源码）

| 约束 | 证据（file:line） | 违反后果 |
|---|---|---|
| **要时间戳时片长 ≤ 180s** | `.venv/.../qwen_asr/inference/qwen3_asr.py:366`（`max_chunk_sec = MAX_FORCE_ALIGN_INPUT_SECONDS if return_time_stamps else MAX_ASR_INPUT_SECONDS`） | 包内用自己的能量启发式**二次切分**，自选 VAD 切点被废弃 |
| 不要时间戳时上限 1200s | `qwen_asr/inference/utils.py:34-35`（`MAX_ASR_INPUT_SECONDS=1200`、`MAX_FORCE_ALIGN_INPUT_SECONDS=180`） | —— |
| 官方切点判据是**波形能量最低点**（可能在词内） | `utils.py:246-300`（`split_audio_into_chunks`，`np.abs` 滑窗能量） | 这正是本方案要替换掉的行为 |
| 包内**没有任何 VAD** | 全包 grep `vad/silero/webrtcvad/speech_prob` 零命中；依赖清单无 VAD 库 | 语音/非语音判定必须由外部提供（本方案的外部件） |
| 模型侧长音频机制 | 编码器两级窗口：CNN 1s 单元 + 注意力窗最长 8s（`core/transformers_backend/modeling_qwen3_asr.py:682-723`，配置 `n_window=50`/`n_window_infer=800`）；12.5Hz token（`processor_config.json` `timestamp_segment_time: 80`）；文本上下文 65536 → 理论上限 ≈ 87 分钟音频 | "20 分钟一次"是包策略，不是模型能力上限 |

---

## 4. 待执行实验（**P0：先做这个，评审通过前不动主干**）

### 4.1 素材

- 来源：`/srv/media/jellyfin/JELLYFIN/atmp/`
- 抽取规则：**随机 5 部**，排除 **VR**（`KAVR-*`、`MDVR-*`）与已验收过的片子；若主 agent 已选定 5 部则沿用已选定的
- 每部取 **30 分钟窗口**（如 `10:00–40:00`），抽成 `16k mono pcm_s16le` wav
- **输入完整性前置**：校验无 `.aria2` 残留、ffprobe 时长与源一致（历史踩过"源文件没下完导致字幕稀疏"）

### 4.2 对照组（同源同窗，四配置）

| 组 | 切片方式 |
|---|---|
| A | **VAD 定点切**：180s 上限，`[180-30, 180]` 内找语音 offset，Δ=30s |
| B | 官方能量切：180s，±5s 找能量最低点（现状行为） |
| C | 固定 30s（旧默认，作为"切点数量"的对照） |
| R | `faster-whisper large-v3-turbo`（生产默认，作为内容参照） |

### 4.3 指标（**先声明，跑完不改**）

1. **fallback 率** = 窗内无可用语音边界的切点数 ÷ 总切点数（本方案成立与否的第一判据）
2. **切点质量** = 切点处 VAD 语音概率、切点前后各 1s 的静音占比
3. **边界丢字** = 切点 ±2s 窗口内 A/B/C 三组与 R 的字符级文本差异（哪组少了内容）
4. **总量** = 字数/分钟、时间戳覆盖率（末条结束时间 ÷ 音频时长）、空片率
5. **成本** = ASR 墙钟、VAD pass 墙钟、片长分布（mean/std/min/max）、批量 padding 浪费

### 4.4 建议判据（待用户确认）

- fallback 率 **≤10%**；切点前后静音占比中位数 **≥0.6**；
- A 的边界丢字**显著低于** B 与 C；A 的总字数 **≥ R 的 90%**；
- 资源独占：**基准必须在 GPU 独占下跑**，逐次记录 `nvidia-smi` 占用与 compute-app（此前吃过亏：同一任务因 GPU 被占，从 107s 劣化到 519s，另有 20 分钟子集跑出 218.61s vs 5 分钟 6.34s 的异常，未排除争用）。

### 4.5 产出

- 对照表 + 每配置原始 `report.json` + 一段结论（选 Δ；确认是否叠加重叠去重与 `context` 续接）
- 落档：`docs/superpowers/executions/2026-11-01-stt-qwen-boundary-loss.md`

---

## 5. 代码落点（在 SPEC 的 10 处清单之上，新增 VAD 相关项）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `whisper_stt_service/executor/qwen_boundary.py`（新增） | 纯函数：`find_speech_boundaries(vad_probs, nominal, delta, fallback_policy)`；可单测、无模型依赖 |
| 2 | `whisper_stt_service/executor/stt_qwen.py`（新增） | 在切片前跑 VAD，调用 ① 取切点；按 §3 约束保证片长 ≤180s |
| 3 | 模型资产 | `models/vad/fireredvad/`：HF `FireRedTeam/FireRedVAD`（**非 gated**）的 `VAD/model.pth.tar`、`VAD/cmvn.ark`、`config.yaml`（约 2.2MB） |
| 4 | 依赖 | `fireredvad==0.0.2`（`requires_python>=3.10` ✓；真正新增仅 `kaldiio`、`kaldi-native-fbank`、`textgrid`，`soundfile`/`torch` 已装）。装前存 freeze 快照，装后立即跑 CPU 子集 |
| 5 | `[stt_qwen]` 新增键 | `vad_enabled=true`、`vad_model_dir`、`boundary_search_seconds=30`、`boundary_fallback=energy`（`energy\|extend\|hardcut`）、`skip_silence_chunks=true` |
| 6 | 观测 | `stt_qwen_boundary_fallback_total`、`stt_qwen_vad_seconds`、`stt_qwen_chunk_len_seconds` 直方图；日志逐切点记录 `chosen_offset/fallback_used/vad_prob` |
| 7 | SPEC 同步三处 | `chunk_seconds` 默认值 → "由边界损失实验决定（候选 180s）"；`boundary_search_seconds` 3.0 → 30（语义从"能量搜索"改为"语音边界搜索"）；"重叠+去重"与"`context` 续接"升为必做 |

**其余改动点（阶段注册、DAG、worker、io 契约等）沿用已勘查清单**，其中 `repo/job_repository.py:391` 的 `{"stt","stt_whisperx"}` 集合适配为**必须**（否则 `input_path` 会落到原视频而不是 16k wav）。

---

## 6. 禁止事项（团队准则 + 仓库规则）

- **不要停、不要重启**当前运行中的测试服务；不要与其它会话抢 GPU（实验前先确认无人占用并记录）
- **不要 commit / push**；不要提交自己未创建的未跟踪文件
- **SPEC 评审通过前不动主干**：原型一律留 `whisper-stt/tmp/research/pilot/`
- **不得删除既有注释/docstring**（AGENTS MUSTDO：重构时原文迁移，不删）
- 不要静默降级：fallback 必须计数并进日志/指标
- 未实测的量化断言不得写进结论

---

## 7. 复现入口（已有脚本）

| 用途 | 路径 |
|---|---|
| 端到端原型（切片+批处理+对齐→ja.srt） | `whisper-stt/tmp/research/pilot/prototype_stt_qwen.py` |
| 设备落点与分档耗时 | `whisper-stt/tmp/research/pilot/pilot_qwen_diag2.py` |
| 同源 whisper 基线 | `whisper-stt/tmp/research/pilot/pilot_whisper_baseline.py` |
| 长单次 vs 短切片对照 | `whisper-stt/tmp/research/pilot/pilot_qwen_chunking.py` |

示例（单部素材、VAD 定点切待实现，先用现有参数跑基线）：

```bash
.venv/bin/python -u whisper-stt/tmp/research/pilot/prototype_stt_qwen.py \
  --wav <16k.wav> --chunk-seconds 180 --snap-radius 5 \
  --out-srt out.ja.srt --report out.json
```

---

## 8. 风险与未验证项（**必须在报告中标为未知**）

- FireRedVAD 在本批素材（连续非语言人声 + BGM）上的**边界可用性未测** —— 若它把这些都判成语音，fallback 率会飙升，方案退化回能量切；
- FireRedVAD 自带"语音/唱歌/音乐"事件检测对成人素材的**区分能力未测**；
- Δ 变大导致的**片长波动**对批处理吞吐（padding 浪费）的影响未测；
- 本方案不解决**跨片上下文丢失**（2h 仍有约 39 个切点），需靠 `context` 续接/重叠去重补偿，效果未测。

---

## 9. 建议的第一步

1. 确认 SPEC 评审意见 + 本 handoff 的 Δ 取值；
2. 按 §4 跑 5 部素材的边界损失实验（GPU 独占，逐次记录占用）；
3. 用实验结论回填 SPEC 的 `chunk_seconds`/`boundary_search_seconds`，再进入实现。

# VAD 升级 + 说话人分离 技术调研

日期：2026-04-27
状态：调研完成，待实施

---

## 1. 现状

### 1.1 当前 VAD

- **后端**：`pyannote/segmentation`（非 Silero VAD）
- **接口**：`whisperx.vads.pyannote.Pyannote`（继承自 `whisperx.vads.Vad`）
- **模型权重**：`/home/base/.../models/whisperx/vad/pyannote/segmentation/pytorch_model.bin`
- **配置**：`/home/base/.../models/whisperx/vad/pyannote/config.yaml`

当前运行时参数：

| 参数 | config.yaml 原始值 | 运行时覆盖值 | 含义 |
|------|-------------------|------------|------|
| `vad_onset` | 0.81 | **0.35** | 语音开始阈值（概率 > 此值 = 语音开始） |
| `vad_offset` | 0.48 | **0.2** | 语音结束阈值（迟滞：概率 < 此值 = 语音结束） |
| `min_duration_on` | 0.055s | — | 最小语音段时长（短于此的噪音丢弃） |
| `min_duration_off` | 0.098s | — | 最小静音间隔（短于此的停顿不切分） |
| `chunk_size` | — | 30s（默认） | VAD 段合并后的最大分块长度 |

### 1.2 当前说话人分离

**无。** 项目中不存在任何 speaker diarization 代码。

但 whisperx 包（v3.8.5）已内置 `whisperx/diarize.py`：
- `DiarizationPipeline` — 封装 `pyannote.audio.Pipeline`
- `assign_word_speakers()` — 将说话人标签分配给转录段
- `IntervalTree` — 快速重叠查询

### 1.3 当前性能问题

pyannote/segmentation 的边界检测不精确，根本原因：
1. **10s 滑动窗口**（1s stride）：窗口边缘缺乏上下文，边界不可靠
2. **LSTM 串行推理**：长音频中梯度消失导致边界模糊
3. **PyanNet (LSTM + Attention)**：模型复杂度 ~1.5M 参数，推理慢

---

## 2. VAD 方案对比

### 2.1 FireRedVAD（推荐）

| 维度 | 值 |
|------|---|
| HF 仓库 | `FireRedTeam/FireRedVAD` |
| 架构 | DFSMN（Deep Feedforward Sequential Memory Network） |
| 参数 | 588K（~2.2 MB float32） |
| 帧率 | 10ms（100 Hz） |
| 时间上下文 | 400ms（200ms lookback + 200ms lookahead） |
| 流式 | ✅ 支持（非流式 + 流式双模式） |
| 语言 | 100+ |
| 附加 | 音频事件检测（语音/唱歌/音乐） |

### 2.2 DFSMN 架构优势

DFSMN 用**可学习的 1D 深度卷积**替代 LSTM 的循环反馈：

```
LSTM（Silero/pyannote）:             DFSMN（FireRedVAD）:
帧t→隐藏态→帧t+1（必须等上一帧）         [t-10...t+10] → 一次性卷积 → 输出[t]
串行，无法并行                         纯前馈，完全并行
```

**层级化感受野**（不增大卷积核，靠堆叠获得更大上下文）：

```
层1 (k=20):  ±10帧  ≈ 200ms      ← 局部音素边界
层2 (k=20):  ±20帧  ≈ 400ms      ← 音节模式
层3 (k=20):  ±30帧  ...           ← 节奏/停顿
层7 (k=20):  ±70帧  ≈ 1400ms     ← 长时上下文
```

**关键**：浅层卷积保留精细边界，深层卷积判断持续性——这正是 VAD 需要的双重能力。

### 2.3 基准性能对比

| 指标 | FireRedVAD | pyannote/seg-3.0 | Silero VAD v6 |
|------|-----------|-----------------|---------------|
| F1 分数 | **97.57%** | ≈95.13% | ≈95.95% |
| 误检率（False Alarm）| **2.69%** | 2.30% | 9.41% |
| 漏检率（Miss Rate）| **3.62%** | ≈6.5% | 3.95% |
| 推理速度 | 快（全并行）| 中等 | 快 |
| 流式 | ✅ | ❌ | ✅ |
| 窗口边界效应 | 无 | 有（10s 窗）| 无 |

### 2.4 其他备选

| 方案 | 优点 | 缺点 |
|------|------|------|
| Silero VAD（已内置）| 只需改一个配置值 | 误检率 9.41%，在有噪声/音乐的日语视频中不可靠 |
| NVIDIA NeMo MarbleNet | 精度最高（F1≈98%）| 依赖 NeMo（2GB+），与 whisperx 版本冲突风险 |
| 调优现有 pyannote | 零代码改动 | 天花板有限，无法解决架构性问题 |

---

## 3. 说话人分离方案

### 3.1 pyannote/speaker-diarization-community-1（推荐）

| 维度 | 值 |
|------|---|
| HF 仓库 | `pyannote/speaker-diarization-community-1` |
| 许可证 | CC-BY-4.0（完全开源，无需付费） |
| 性能 (DIHARD3) | DER 20.2 |
| WhisperX 集成 | ✅ 原生支持（`DiarizationPipeline` + `assign_word_speakers`） |
| 依赖 | `pyannote.audio`（**已安装**，作为 whisperx 传递依赖） |
| 前提 | HF token + 同意模型使用条款 |

### 3.2 集成方式

在 `stt_whisperx.py` 的 `run_stt_whisperx()` 中，于 ASR 转录后、SRT 写入前插入：

```python
from whisperx import DiarizationPipeline

diarize = DiarizationPipeline(
    model_name="pyannote/speaker-diarization-community-1",
    use_auth_token=hf_token,
    device=device,
)
diarize_segments = diarize(audio, min_speakers=2, max_speakers=6)
result = whisperx.assign_word_speakers(diarize_segments, result)

# result["segments"][i]["speaker"]  →  SPEAKER_00, SPEAKER_01, ...
```

### 3.3 备选方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| NVIDIA Sortformer | DER 15.09（更好）| 需要 NeMo，不支持 whisperx 原生集成，最多 4 说话人 |
| pyannoteAI precision-2 | 精度最高 | 付费 API |

---

## 4. 实施计划

### 4.1 FireRedVAD 替换

#### 与 WhisperX 集成架构

```
音频 (16kHz)
    │
    ▼
┌──────────────────────┐
│ Kaldi Fbank 特征提取  │   80-dim log Mel, 10ms shift
│ (25ms窗, 10ms偏移)   │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ DFSMN 模型推理        │   588K 参数, 输出每帧语音概率 [0,1]
│ (7层 DFSMN Block)    │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ 后处理                │   平滑 → 阈值 → 时长过滤 → 段合并
│ smoothing + threshold│
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ 桥接层               │   SegmentX(start=..., end=..., speaker="UNKNOWN")
│ → WhisperX VAD接口   │
└──────┬───────────────┘
       │
       ▼
  WhisperX Batched ASR
       │
       ▼
  对齐 + 说话人分离
```

#### 接口契约（WhisperX Vad 基类要求）

自定义 VAD 必须继承 `whisperx.vads.Vad`，实现 4 个方法：

| 方法 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `__init__` | `**kwargs` (含 `vad_onset`) | — | 调用 `super().__init__(vad_onset)` |
| `__call__` | `{"waveform": ..., "sample_rate": 16000}` | `List[SegmentX]` | 运行 VAD 推理 |
| `preprocess_audio` | `np.ndarray` (原始音频) | 适配格式 | 静态方法，转换原始音频 |
| `merge_chunks` | `List[SegmentX]`, `chunk_size`, `onset`, `offset` | `List[dict]` | 静态方法，合并相邻段 |

#### 需要修改的文件

| 文件 | 改动 |
|------|------|
| `executor/stt_whisperx.py` | 新增 `fire_red_vad.py` 桥接模块；在 `load_model` 前实例化 FireRedVAD |
| `core/config.py` | `SttWhisperxSettings` 新增 `vad_model_name`, `vad_speech_threshold`, `vad_min_speech_duration`, `vad_min_silence_duration` |
| `core/stages.py` | 注册新增的 VAD 配置键到 `stt_whisperx` 可覆盖键列表 |
| `config.ini` / `config.example.ini` | 添加 `[stt_whisperx]` 的 FireRedVAD 配置节段 |
| `repo/job_repository.py` | 添加默认值 |
| `models/` | 下载 FireRedVAD 模型到 `models/whisperx/vad/firered/` |

### 4.2 说话人分离新增

| 文件 | 改动 |
|------|------|
| `executor/stt_whisperx.py` | 在 `asr.transcribe()` 后 / `align` 后插入 `DiarizationPipeline` + `assign_word_speakers` |
| `core/config.py` | 新增 `diarize_enabled`, `diarize_model_name`, `hf_token` |
| `core/stages.py` | 注册 diarization 配置键 |
| `config.ini` / `config.example.ini` | 添加 `[stt_whisperx]` diarization 节段 |
| `repo/job_repository.py` | 添加默认值 |
| `models/` | 下载 diarization 模型 |

### 4.3 实施顺序

```
Phase 1: HF token 配置 + 说话人分离
    ↓ （改动最小，收益最快，可独立验证）
Phase 2: FireRedVAD 桥接 + 替换
    ↓ （VAD 精度提升，输出更可靠）
Phase 3: 端到端测试 + 回归验证
```

---

## 5. 关键决策记录

- **VAD 替换**：选择 FireRedVAD（DFSMN 架构），而非 Silero 或 NeMo。理由：SOTA 精度、误检率 3.5x 优于 Silero，轻量（588K 参数），无滑动窗口的边界退化问题。
- **说话人分离**：选择 `pyannote/speaker-diarization-community-1`。理由：CC-BY-4.0 开源免费，原生 WhisperX 集成，依赖已有（`pyannote.audio` 已安装）。
- **集成模式**：FireRedVAD 通过子类化 `whisperx.vads.Vad` 桥接，不修改 WhisperX 源码。理由：`issubclass` 检查是接口门控，继承基类即可无缝插入管线。
- **HF token**：需要新增 `hf_token` 配置项，用于 diarization 模型下载（pyannote 系列模型需要接受条款）。

---

## 6. 参考

- FireRedVAD: https://huggingface.co/FireRedTeam/FireRedVAD
- FireRedVAD GitHub: https://github.com/FireRedTeam/FireRedVAD
- pyannote/speaker-diarization-community-1: https://huggingface.co/pyannote/speaker-diarization-community-1
- WhisperX VAD 架构: `whisperx/vads/vad.py` (基类), `whisperx/vads/pyannote.py` (现有后端)
- WhisperX ASR 管线: `whisperx/asr.py` (VAD 注入点: `issubclass(type(vad_model), Vad)` 检查)
- DFSMN 论文: Zhang et al., "Deep Feed-forward Sequential Memory Networks for Speech Synthesis", 2018

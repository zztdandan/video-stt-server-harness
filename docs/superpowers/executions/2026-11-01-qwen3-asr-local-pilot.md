# Qwen3-ASR 本地化 pilot 记录（stt_qwen 可行性验证）

- **日期**：2026-11-01（Asia/Shanghai）
- **执行者**：父代理（DSH），本机 WSL2 + RTX 4080 SUPER 16GB（driver 621.01）
- **目的**：在"音频不出本地"约束下，验证以 **Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B** 自建第二个 ASR 阶段（`stt_qwen`，旧 `stt` 不动）是否可行，并量化切片粒度对速度与质量的影响。
- **素材**：`FNS-270-U`（2h01m12s）由既有 2h E2E 产出的 `audio/FNS-270-U.16k.wav`（232,714,550 B）切片。
  - 稀疏窗口 `30:00–35:00`（长单次负面样本）
  - 密集窗口 `00:00–05:00`（同源质量对照窗口）

## 1. 环境与依赖（已落地）

- 权重本地化：`models/qwen3-asr/Qwen3-ASR-1.7B`（4.4G）、`models/qwen3-asr/Qwen3-ForcedAligner-0.6B`（1.8G）。
- 主 venv 安装 `qwen-asr==0.0.6`（官方包，`transformers==4.57.6` 与既有环境一致）：
  新增 40 包，且 **starlette 1.0.0 → 1.7.0**（触及运行中的 FastAPI 栈）。
- 兼容性验证：安装后跑 CPU 子集 `pytest -q --ignore=tests/unit/test_executor_wav_contract.py --ignore=tests/unit/test_model_cache.py`
  → **481 passed, 5 deselected**（仅 `starlette.testclient` 弃用告警）。
- 回滚凭据：安装前 freeze 快照 `whisper-stt/tmp/research/venv-freeze-before-qwen.txt`（143 行）。

## 2. 官方口径（读安装包源码所得，非社区说法）

- `qwen_asr/inference/utils.py:34` → `MAX_ASR_INPUT_SECONDS = 1200`：**单次最长 20 分钟**，超出自动切片。
- `qwen_asr/inference/utils.py:35` → `MAX_FORCE_ALIGN_INPUT_SECONDS = 180`：请求时间戳时按 **3 分钟**切片。
- 日语支持：ASR 52 语种含 `ja`；ForcedAligner 11 语种含 `ja`（`language="Japanese"` 生效，实测 `detected_language=Japanese`）。

## 3. 实测数据（同一 GPU，逐项标注争用状态）

| 配置 | 音频 | 墙钟 | RTF | 输出字符 | 时间戳 |
|---|---|---|---|---|---|
| Qwen 单次吃完（稀疏段，**GPU 被另一会话占用**） | 300s | 519.0s | 1.73 | 23 | 28 |
| Qwen 单次吃完（稀疏段，GPU 空闲） | 300s | 107.0s | 0.36 | 23 | — |
| Qwen 单次吃完（密集段，GPU 空闲） | 300s | 132.8s | 0.443 | 679 | 316 |
| **Qwen 10×30s 一次调用批处理（密集段）** | 300s | **6.67s** | **0.022** | **802** | 389 |
| Qwen 单片 30s（稀疏段） | 30s | 4.86s | 0.16 | 54 | — |
| Qwen ForcedAligner 单独对齐 | 300s | 0.66s | — | — | — |
| **faster-whisper large-v3-turbo（生产默认，对照）** | 300s（密集段） | 5.78s | 0.019 | 504 | 49 段 |
| faster-whisper large-v3-turbo（对照） | 300s（稀疏段） | 1.74s | 0.006 | 41 | 6 段 |

- 设备落点核查：`param_devices={"cuda:0": 707}`、`hf_device_map={"cuda:0": 1}`，**无 CPU 卸载**；加载后显存 4.08GB，峰值 6.43GB。
- 2h 视频投影：240 个 30s 片 / 每批 10 片 = 24 批 × 6.67s ≈ **160s**（不含对齐），量级为分钟级。

## 4. 结论

1. **可行**：本地 Qwen3-ASR-1.7B 在 4080S 上完全跑得动，日语内容与 whisper-turbo 同源可比，密集段字符产出更高（802 vs 504）。
2. **长单次不是好用法**：官方虽允许 20 分钟一次，但在同一素材上 5 分钟单次的耗时是短切片批处理的 **20 倍**（132.8s vs 6.67s），且输出更少（679 vs 802 字符）。`stt_qwen` 应采用**短切片 + 批处理**，而非吃满 20 分钟。
3. **显存与并发是运行期风险**：模型需 ~4.1GB（bf16）/峰值 6.4GB；与另一会话的 faster-whisper 同时跑时，519s vs 107s 的差距证明 GPU 争用会直接反映为任务超时风险。
4. **素材本身决定"字少"**：`FNS-270-U` 全片语音稀疏（whisper-small 跑完 2h 仅约 2k 字符），稀疏窗口两模型都只出几十字，不能作为质量判据；质量对照必须用密集段。
5. **时间戳可用且便宜**：ForcedAligner 单次 300s 文本仅 0.66s；切片边界本身即可作时间戳，对齐模型用于片内细分。

## 5. 复现入口

- `whisper-stt/tmp/research/pilot/pilot_qwen_chunking.py`（A/B 对照，边跑边打印）
- `whisper-stt/tmp/research/pilot/pilot_qwen_diag2.py`（设备落点 + 分档耗时）
- `whisper-stt/tmp/research/pilot/pilot_whisper_baseline.py`（同源 whisper 基线）
- `whisper-stt/tmp/research/pilot/pilot_qwen_asr.py`（首版：SRT 产出与时间戳覆盖校验）

## 6. 边界与未验证项

- 质量仅抽样单一素材（成人向日语），**未做 CER/WER 定量评测**，也未与该素材的生产配置 `large-v3-turbo` 做全片双跑。
- 未验证 vLLM 后端（`qwen-asr[vllm]`）与 `flash-attn` 是否能进一步提速；未验证长片（>20min）自动切片路径的边界丢字。
- 未验证服务内多 worker 并发时的显存预算；`model_parallelism`/`model_cache_size` 是否覆盖新阶段待定。

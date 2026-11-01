# Qwen3-ASR 本地 Stage（`stt_qwen`）设计说明

- **状态**：待评审（评审通过后再进入实现）
- **关联**：pilot 实测记录 `docs/superpowers/executions/2026-11-01-qwen3-asr-local-pilot.md`
- **前置 SPEC**：`docs/superpowers/specs/2026-04-05-whisperx-stage-design.md`（新增并列 ASR 阶段的先例）

## 背景

当前 Service 的稳定默认流程是 `extract -> stt -> translate`，另有并列可选阶段 `stt_whisperx`。本次要新增**第三个并列 ASR 阶段 `stt_qwen`**，使用本机离线部署的 Qwen3-ASR 权重替代/对照现有 whisper 路径；**旧 `stt` 不改语义、不改默认 DAG**。

用户约束（决定选型，优先于技术最优）：

- **音频不得出网**：排除所有云端 ASR（含 Qwen-Audio-ASR-Filetrans）；权重必须落本地。
- 旧第二步保持可用：新阶段只是"可切换的第二个选项"。

pilot 已经跑通并给出关键事实（详见执行记录）：

| 实测项（RTX 4080 SUPER 16GB，同源素材） | 数值 |
|---|---|
| Qwen 单次吃满 5 分钟（GPU 空闲，密集语音段） | 132.8s，RTF 0.443，679 字符 |
| **Qwen 10×30s 一次调用批处理（同段）** | **6.67s，RTF 0.022，802 字符** |
| Qwen ForcedAligner 单独对齐 300s | 0.66s |
| faster-whisper large-v3-turbo（生产默认，对照） | 5.78s，504 字符 |
| 显存 | 加载后 4.08GB，峰值 6.43GB，全部参数在 `cuda:0` |
| 2h 视频投影（240 片 / 每批 10 片） | ≈160s（分钟级） |

包内硬上限（读 `qwen_asr` 源码所得）：`MAX_ASR_INPUT_SECONDS = 1200`（**20 分钟**）、`MAX_FORCE_ALIGN_INPUT_SECONDS = 180`（**3 分钟**）。结论是：**能用 20 分钟，但不该用满**——同一素材上长单次比短切片批处理慢 20 倍且产出更少。

## 产品决策

本轮采用 **方案 A：新增并列可选 stage，短切片 + 批处理**。

- 保留 `stt` 与 `stt_whisperx`，不改语义、不改默认行为；默认 DAG 仍是 `extract -> stt -> translate`。
- 新增 `stt_qwen`，仅当调用方显式传自定义 DAG 时启用。
- 新阶段的 ASR 粒度**不以 20 分钟为单位**，而是按 `chunk_seconds`（默认 30s）切片、按 `batch_size`（默认 10）批量推理。
- 时间戳默认由"片边界 + ForcedAligner 片内细化"产生，仍输出标准 `.ja.srt`。

明确不采用：

- **直接替换 `stt`**：回归风险高，且用户明确要求旧路径不动。
- **吃满 20 分钟单次推理**：pilot 证明速度与质量双输，仅在 `chunk_seconds=1200` 这种显式配置下才可能发生（且必须受包内上限校验）。
- **本轮不引入 vLLM 后端 / flash-attn**：会增加依赖面与新的常驻服务；现有 transformers 后端在批处理下已达 RTF 0.022，先不做。

## 目标

1. 新增完全本地、离线可运行的 `stt_qwen` 阶段，模型权重来自本地目录。
2. 复用 `extract` 产出的 `16k mono pcm_s16le` wav（不重新抽音频、不读原视频）。
3. 以短切片 + 批处理达到"2h 视频分钟级"的吞吐，并可量化（RTF 写入日志与指标）。
4. 产出与现有 `translate` 完全兼容的 `asr/<stem>.ja.srt`。
5. GPU 使用显式化：加载后校验落点，非全 GPU 或显存不足时 **fail-fast**，不允许静默退化到 CPU 慢跑。
6. 旧 `stt` / `stt_whisperx` 的默认路径、配置、产物契约零改动。

## 非目标

- 不修改默认 DAG；不删除/重命名/改变 `stt` 行为。
- 不实现说话人分离（diarization）。
- 不把 word-level 时间戳作为新的公开产物落盘（仅内部用于提升句级时间戳质量）。
- 不允许运行期联网下载模型；不引入云端 ASR 兜底。
- 不做多语言矩阵验证（本轮只覆盖日语链路，语种来自 job 的 `language`）。

## 全本地模型策略

### 已本地化的权重（pilot 已下载）

- `/home/base/repo/video-stt-whisper-server/models/qwen3-asr/Qwen3-ASR-1.7B`（4.4G）
- `/home/base/repo/video-stt-whisper-server/models/qwen3-asr/Qwen3-ForcedAligner-0.6B`（1.8G）

### 运行期依赖（pilot 已安装并验证）

- 主 venv 安装 `qwen-asr==0.0.6`（其 `transformers==4.57.6` 与既有环境一致）。
- 副作用必须记录在案：该安装把 **starlette 1.0.0 → 1.7.0**（触及运行中的 FastAPI 栈），安装后 CPU 子集测试 **481 passed** 通过；回滚快照 `whisper-stt/tmp/research/venv-freeze-before-qwen.txt`。
- 供 `stt_qwen` 使用的 `qwen_asr` 只允许**从本地目录加载**（传绝对路径），禁止 `from_pretrained("Qwen/...")` 这种可能触发联网的写法。

### 缺失即失败

任一模型目录、processor 配置或对齐模型缺失时，任务必须显式失败并指明缺失路径，不允许回退到联网或回退到其它 ASR。

## 用户可见行为

### 默认 job 行为

保持不变：未传 DAG 时仍走 `extract -> stt -> translate`。

### 自定义 Qwen job 行为

```json
{
  "video_path": "/abs/path/demo.mp4",
  "language": "ja",
  "dag": {
    "version": 1,
    "stages": [
      {"stage": "extract", "depends_on": []},
      {"stage": "stt_qwen", "depends_on": ["extract"]},
      {"stage": "translate", "depends_on": ["stt_qwen"]}
    ]
  },
  "job_config": {
    "stt_qwen": {
      "chunk_seconds": 30,
      "batch_size": 10,
      "align_enabled": true
    }
  }
}
```

DAG 语义不变：仍然是"`SUPPORTED_STAGES` 中恰好一个 ASR 阶段出现在 DAG 里"，`translate` 的依赖闭包必须包含该 ASR 阶段。下游契约不变：`translate` 只认 `asr/<stem>.ja.srt`，不关心上游是哪个 ASR。

## 执行策略

### 切片

1. 输入固定为 extract 产出的 wav；缺失或 0 字节 → `missing_audio_artifact`（沿用 D1 契约）。
2. 按 `chunk_seconds` 切分，**默认 30s**。理由：pilot 实测 30s 片在速度（4.86s/片，RTF 0.16）与质量上都优于长单次。
3. 切片必须校验上限：`chunk_seconds <= 1200`（ASR 上限）且 `align_chunk_seconds <= 180`（对齐上限），越界直接拒绝配置，而不是让底层静默切片。
4. 可选（默认开）"静音边界吸附"：在片边界 ±`boundary_search_seconds`（默认 3s）内寻找低能量点再切，避免在词中间切断。实现复用现有 VAD 依赖（silero/pyannote 已在栈内），不作为新依赖。

### 批处理

1. 每批取 `batch_size`（默认 10）个片，一次 `transcribe(audio=[...], language=[...], return_time_stamps=...)`。
2. 批大小受显存约束：`batch_size` 与实际峰值显存一并记入 `effective_config`，便于事后归因。
3. 进度按片上报（`i/N`），与现有进度/ETA 机制一致。

### 时间戳

1. 主来源：片边界 + 片内对齐结果，统一加片偏移后拼接。
2. `align_enabled=true`（默认）时，片内用 Qwen3-ForcedAligner 取句/字级时间戳再合并为句级 SRT 条目；单次对齐不得超过 180s。
3. `align_enabled=false` 时只用片边界时间戳（最粗 30s 一条），仅作为快速模式。
4. **空文本片**不得产生空条目；整片无语音时跳过但不留空洞。

### 结果校验（防静默失败）

任务成功前必须校验，任一不满足即失败并保留已产出片信息：

- 最后一个时间戳的结束时间不得早于 `wav 时长 - chunk_seconds`（防"只识别前半段"）；
- 非空片比例不低于 `min_nonempty_ratio`（默认 0.05）——全片近乎无输出时视为异常而非成功；
- 产出的 SRT 能被现有 `translate` 的解析路径解析（复用其 `SrtEntry` 解析做一次 dry-parse）。

## 配置设计

### 新增 `[stt_qwen]` 段（`config.ini` 与 `config.example.ini` 同步）

| 键 | 默认 | 说明 |
|---|---|---|
| `model_dir` | `/home/base/repo/video-stt-whisper-server/models/qwen3-asr/Qwen3-ASR-1.7B` | 本地权重目录 |
| `aligner_dir` | `.../Qwen3-ForcedAligner-0.6B` | 本地对齐模型目录 |
| `device` | `cuda:0` | 本轮不做 `auto`：显式设备更利于 fail-fast |
| `dtype` | `bfloat16` | 与 pilot 一致 |
| `chunk_seconds` | `30` | 上限 1200 |
| `align_chunk_seconds` | `60` | 上限 180 |
| `batch_size` | `10` | 每批片数 |
| `max_new_tokens` | `2048` | 长片需要更大值，过小会静默截断 |
| `align_enabled` | `true` | 关闭则只用片边界时间戳 |
| `boundary_snap_enabled` | `true` | 静音边界吸附 |
| `boundary_search_seconds` | `3.0` | 吸附搜索半径 |
| `require_cuda` | `true` | 为 true 时 CUDA 不可用即失败 |
| `min_free_vram_gb` | `6.0` | 加载前空闲显存门槛（pilot 峰值 6.43GB） |
| `min_nonempty_ratio` | `0.05` | 结果校验阈值 |

### 阶段级运行参数（与既有阶段同构）

- `[workers] stt_qwen_workers`：默认 **1**（GPU 串行，避免自相争抢）
- `[timeouts] stt_qwen_timeout_sec`：默认 **5400**（2h 视频预计 3–6 分钟；余量用于 GPU 争用与对齐）
- `[retry] stt_qwen_max_retries`：默认 **2**（沿用既有语义）

读取方式沿用 `stt_whisperx_*` 的 `fallback=` 写法（缺键不阻断启动）。注意：`REQUIRED_CONFIG_OPTIONS` 目前只写 `error` 日志、**不阻断启动**（`bootstrap.py:53`），所以"把新键加进去"只提升可观测性，不能当校验保障。

### job_config 覆盖

`job_config.stt_qwen.*` 的可用键由 `STAGE_CONFIG_KEYS["stt_qwen"]` 白名单决定，未列入即 `job_config_key_not_supported`（`core/dag.py:149`）。允许覆盖：`timeout_sec`、`max_retries`、`chunk_seconds`、`batch_size`、`align_enabled`、`align_chunk_seconds`、`max_new_tokens`、`boundary_snap_enabled`；**不允许**覆盖 `model_dir`/`aligner_dir`/`device`（运行期路径与设备不接受按 job 变更，避免绕过白名单与显存预算）。

## 代码结构改动（最小改动清单）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `whisper_stt_service/core/stages.py` | `SUPPORTED_STAGES` 增加 `stt_qwen`；新增 `STAGE_CONFIG_KEYS["stt_qwen"]` |
| 2 | `whisper_stt_service/core/dag.py:13` | `ASR_STAGES` 增加 `stt_qwen`（唯一 ASR 语义自动生效） |
| 3 | `whisper_stt_service/executor/stt_qwen.py`（新增） | `run_stt_qwen(...)`：切片、批处理、对齐、SRT 原子写、进度、结果校验 |
| 4 | `whisper_stt_service/executor/__init__.py`、`executors.py` | 导出 `run_stt_qwen`，保持包根兼容导出面 |
| 5 | `whisper_stt_service/core/config.py` | `WorkerSettings`/`TimeoutSettings`/`RetrySettings` 增字段与读取；新增 `[stt_qwen]` dataclass；`REQUIRED_CONFIG_OPTIONS` 增键 |
| 6 | `whisper_stt_service/service/bootstrap.py:74+` | `_build_stage_effective_defaults` 增 `stt_qwen`；`stage_max_retries`/`stage_timeouts` 字典增键 |
| 7 | `whisper_stt_service/service/runtime.py` | worker 池（`:336`、`:571`）、阶段分派（`:1110`）、`_build_staging`（`:1137`）、`_execute_stt_qwen(...)`、`effective_config` 组装（`:2262` 附近） |
| 8 | `whisper_stt_service/repo/job_repository.py:391` | `_build_stage_io` 的 `{"stt","stt_whisperx"}` 集合必须加入 `stt_qwen`——否则兜底分支会把 `input_path` 设成原视频而不是 16k wav（静默用错输入） |
| 9 | `whisper_stt_service/service/model_cache.py` | 新增 `get_qwen_asr_bundle(...)`（key 覆盖：模型目录、对齐目录、device、dtype、batch/align 参数） |
| 10 | 测试 | `tests/unit/test_stages.py`、`test_dag_validation.py`、`test_repository_io_paths.py`、`test_config*.py` 等阶段全集/白名单断言同步 |

设计原则：`stt_qwen` 是**独立 executor、独立 stage 身份**，不把现有 `stt` 改成多后端分支。

## 数据契约

- **输入**：`extract` 产出的 `artifacts/<job_id>/audio/<stem>.16k.wav`
- **输出**：`artifacts/<job_id>/asr/<stem>.ja.srt`（与 `stt`/`stt_whisperx` 同一路径，DAG 保证同时只有一个 ASR 写者）
- **中间产物**：`artifacts/<job_id>/asr/qwen/`（切片清单与批次元数据，便于复现与排障），受既有 artifact 清理策略约束
- **copy_back**：仍由 `translate` 负责，`stt_qwen` 不直接回写视频目录

## 资源与并发

- 显存：模型 bf16 加载后约 4.1GB，pilot 峰值 6.43GB；`min_free_vram_gb=6.0` 作为加载前门槛。
- **GPU 落点校验**：加载后遍历参数设备，若存在非 `cuda` 参数 → 立即失败（错误码 `stt_qwen_not_on_gpu`）。pilot 期间因 GPU 被其它进程占用，同一任务从 107s 恶化到 519s，静默 CPU/部分卸载必须被禁止。
- 与 `stt`/`stt_whisperx` 的关系：三者共用同一张卡；`model_parallelism=1` 与同 key 信号量只保证**同模型**串行，跨模型（whisper 与 qwen）仍需按显存预算排队。本轮**不**实现跨模型显存仲裁，改为：加载前检查空闲显存，不足则让任务回到重试预算内（可观测、可自愈），并在日志与 `/metrics` 暴露当前占用。
- `model_cache_size` 默认 2：若同时缓存 whisper 与 qwen 两套模型，需评估是否调大；本轮先在文档标明，不改默认。

## 错误处理与重试语义

必须显式失败（错误码进 `error` 字段，可被现有监控消费）：

- `stt_qwen_model_missing`：模型目录/权重缺失
- `stt_qwen_aligner_missing`：对齐模型缺失（`align_enabled=true` 时）
- `stt_qwen_cuda_unavailable`：`require_cuda=true` 但 CUDA 不可用
- `stt_qwen_not_on_gpu`：加载后参数未全在 GPU
- `stt_qwen_insufficient_vram`：空闲显存低于门槛
- `stt_qwen_chunk_config_invalid`：片长/对齐片长越界
- `stt_qwen_output_incomplete`：结果校验不通过（覆盖不足 / 非空片比例过低）
- `missing_audio_artifact`：沿用既有 D1 契约

重试语义：上述前 6 项属**环境/配置类**，重试大概率无益（但仍走既有重试预算以便显存竞争自愈）；`stt_qwen_output_incomplete` 属**结果类**，允许重试；模型内部推理异常按连接/超时类处理，与既有阶段一致。

## 可观测性

- 任务日志沿用 SPEC G 的 11 字段，并在 `effective_config` 中固化：模型目录、对齐目录、device、dtype、`chunk_seconds`、`batch_size`、`align_enabled`、批次数、`model_cache_hit/key`。
- 新增日志点：每批 `batch_index/total`、批耗时、`rtf`、片级空文本计数、对齐耗时。
- `/metrics`：沿用 `task_duration_seconds{stage=stt_qwen}`；新增 `whisper_stt_qwen_chunks_total{result=ok|empty}` 与 `whisper_stt_qwen_rtf` 直方图（便于回归对比）。

## 测试策略

### 单元测试

- 阶段注册表包含 `stt_qwen`；DAG 校验允许 `stt_qwen` 且仍拒绝"两个 ASR 同现"。
- `job_config.stt_qwen` 白名单：允许键通过、`model_dir`/`device` 等被拒。
- `_build_stage_io("stt_qwen")` 返回 `input_path=wav`、`output_path=asr/<stem>.ja.srt`（**防止 io 兜底陷阱回归**）。
- 片长/对齐片长越界、越界配置被拒。
- 结果校验函数：覆盖不足与非空比例过低各一个反例。
- 配置解析：缺 `[stt_qwen]` 段时走 fallback 不抛，给出默认值。

### 集成测试（fake executor）

沿用 `tests/integration/test_runtime_fake_executors.py` 模式：注册假的 `stt_qwen` 执行器，验证 worker 池、租约心跳、staging/promotion、失败重试与 copy_back 链路——**不加载真实模型**。

### 真实媒体验收（manual，需显式开启）

- 素材：`FNS-270-U` 的 2h 全片（同一份 `16k.wav`）。
- 口径：**同源双跑** `stt`（生产默认 `large-v3-turbo`）vs `stt_qwen`，对比：末条时间戳覆盖率、段数/字符数、抽样日文正确率、墙钟、峰值显存。
- 判别性要求：验收用例必须能区分新旧实现（例如断言 `stt_qwen` 的批次数 > 1、`chunk_seconds` 出现在 `effective_config` 中），旧代码下应当失败。

### 文档

- 本 SPEC + pilot 执行记录 + `docs/02-operations-runbook.md` 增补"如何提交 `stt_qwen` job 与如何回滚"。

## 推进顺序

1. 评审本 SPEC，确认开放问题（见末节）。
2. 实现 executor `run_stt_qwen` + 单元测试（不接 Service，先用脚本对 2h 素材跑通并复现 pilot 指标）。
3. 接入 Service（改动清单 1–9），补集成测试。
4. 真实媒体同源双跑验收，记录数据到 `docs/superpowers/executions/`。
5. 更新 runbook 与 README（如涉及 roadmap 项，按仓库规则标注完成）。

## 验收标准

当且仅当以下条件同时成立：

- 默认 job 仍走旧 `stt`，其行为、配置、产物契约无变化。
- 显式 DAG 可路由到 `stt_qwen`，并可与 `translate` 串联输出 `zh.srt`。
- 运行期全程离线（可用 `local_files_only` 语义 + 拔网/断网方式抽验）。
- 2h 素材 `stt_qwen` 任务成功，末条时间戳覆盖率 ≥ 99%，墙钟在本机 GPU 空闲时 ≤ 15 分钟。
- GPU 落点校验、显存门槛、片长上限三类保护各有可复现的失败用例。
- 单元 + 集成测试全绿；真实媒体验收数据落档。

## 风险与未验证项

- **GPU 争用**：与其它会话/阶段的 whisper 任务共享 16GB 显存，pilot 已观测到 5 倍劣化；本轮只做"检测 + 失败/重试"，不做调度器级仲裁。
- **质量未定量**：仅抽样单一素材，未做 CER/WER；未与全片 `large-v3-turbo` 做逐段对照。
- **切片边界丢字**：静音吸附是启发式，未验证极端素材（连续快语速、无明显静音）。
- **长片自动切片路径**：>1200s 的兜底行为未验证（本设计主动切片，正常不会触发）。
- **依赖副作用**：`starlette 1.0.0 → 1.7.0` 已过测试套件，但运行中的服务需重启才会用上新版本（与另一会话协调）。

## 回滚方案

- 代码：移除 `SUPPORTED_STAGES`/`ASR_STAGES`/`STAGE_CONFIG_KEYS` 中的 `stt_qwen` 与新增 executor，默认 DAG 从未改变，旧路径不受影响。
- 环境：`uv pip install -r whisper-stt/tmp/research/venv-freeze-before-qwen.txt`（或按快照逐项还原 `starlette==1.0.0`）。
- 数据：`stt_qwen` 只写 `artifacts/<job_id>/asr/`（DAG 唯一 ASR 写者），回滚不影响既有 job 的产物。

## 待决策的开放问题

1. **切片粒度默认值**：30s（pilot 最优）还是 60s（更少批次、更少边界）？
2. **静音边界吸附**是否默认开启（会增加一次 VAD 计算；对 SRT 可读性有正收益但未量化）？
3. **是否保留 `stt_whisperx`**：新阶段落地后，`stt_whisperx` 是否仍需维护，或标注为 legacy？
4. **验收素材范围**：是否只验 `FNS-270-U`，还是再补一部语音密集素材（用于质量对照）？
5. **GPU 资源协调方式**：与另一个会话共用本机 GPU，是否需要为 `stt_qwen` 约定固定时间窗或独占约定？

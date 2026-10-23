# WhisperX Stage 设计说明

## 背景

当前 `/home/base/repo/video-stt-whisper-server/whisper-stt` 内的 Service 已经具备以下能力：

- 基于队列的 job 执行模型
- 每个 job 可显式提交 DAG
- 每个 stage 可通过 `job_config` 做独立覆盖，并在创建 task 时固化到 `task_config`
- 默认稳定流程为 `extract -> stt -> translate`
- 已经具备现有 faster-whisper 路径的真实 E2E 覆盖

当前工程结构还需要注意两点：

- 主仓库 `/home/base/repo/video-stt-whisper-server` 负责文档、流程和模型资产管理，`whisper-stt/` 是以 submodule 形式挂载的实际实现仓库
- `whisper_stt_service/` 已完成分层重构，核心实现主要位于 `core/`、`repo/`、`service/`、`executor/` 等子目录，同时在包根目录保留了一组兼容旧导入路径的导出模块（例如 `whisper_stt_service/stages.py`、`whisper_stt_service/config.py`、`whisper_stt_service/workers.py`、`whisper_stt_service/executors.py`）

当前 `stt` stage 的定位是稳定默认路径，本轮不能破坏它的行为，也不能把默认 DAG 直接切到新实现。

但在真实长音频、电影对白、复杂背景噪声场景下，现有实现存在两个明显问题：

- 当前 VAD 效果不够理想，无法满足复杂对白素材的分段质量要求
- 当前执行路径本质上没有利用 WhisperX 的“VAD 切段后批量推理”能力，吞吐偏低

因此，本轮需要新增一个并行可选 stage：`stt_whisperx`。它只在显式自定义 DAG 时启用，默认路径继续走旧 `stt`。

## 产品决策

本轮采用 **方案 A**：

- 保留现有 `stt`，不改语义、不改默认行为
- 新增一个并行可选 stage：`stt_whisperx`
- 默认 DAG 继续保持 `extract -> stt -> translate`
- 只有显式传入自定义 DAG 时，job 才会走 `stt_whisperx`
- 在真正集成到 Service 之前，先在 `whisper_stt/` 目录下增加一个 WhisperX 的 SOP/验证脚本，先验证本地模型、WhisperX 批处理能力和输出效果

本轮明确不采用以下方案：

- 直接替换 `stt`：回归风险高，不符合“旧路径必须稳定可跑”的要求
- 额外拆出 `vad_segment` 中间 stage：会引入新的中间产物和更复杂的 DAG 组合，超出本轮范围

## 目标

1. 新增一个完全本地可运行的 `stt_whisperx` 路径。
2. 新路径复用现有本地 faster-whisper 模型目录作为 Whisper ASR 主模型。
3. 新路径必须使用 WhisperX 的 VAD 分段 + batched ASR 机制，而不是仅仅替换库名。
4. 新路径继续产出与现有 `translate` 兼容的日语 SRT 文件。
5. 在 Service 集成前，先提供一个独立的 WhisperX SOP/验证脚本，用于手工验证和调参。
6. 新增一套基于显式 DAG 的 E2E，把默认第二步从 `stt` 换成 `stt_whisperx`。

## 非目标

- 不修改默认 DAG
- 不删除、不重命名、不改变现有 `stt` 的行为
- 本轮不实现 diarization
- 本轮不把 word-level 时间戳作为新的公开产物落盘
- 本轮不允许 job 执行过程中联网下载模型

## 全本地模型策略

本项目所有 stage 在运行期都必须满足“纯本地执行，不依赖运行时网络访问”。

### 已确认可直接复用的本地模型

以下目录已经可以作为 Whisper 主干模型输入，被旧 `stt` 与新 `stt_whisperx` 共同复用：

- `/home/base/repo/video-stt-whisper-server/models/faster-whisper-large-v2`
- `/home/base/repo/video-stt-whisper-server/models/faster-whisper-large-v3-turbo`
- `/home/base/repo/video-stt-whisper-server/models/faster-whisper-small`

这些目录内已经具备 CTranslate2 / faster-whisper 需要的主模型资产，WhisperX 的 ASR 主干可以直接复用，不要求重新下载 Whisper 主模型。

### 本轮必须具备的 WhisperX 本地辅助模型

- VAD pipeline 根目录：`/home/base/repo/video-stt-whisper-server/models/whisperx/vad/pyannote`
- VAD segmentation 根目录：`/home/base/repo/video-stt-whisper-server/models/whisperx/vad/pyannote/segmentation`
- 日语 alignment 模型根目录：`/home/base/repo/video-stt-whisper-server/models/whisperx/align/ja`
- 中文 alignment 模型根目录：`/home/base/repo/video-stt-whisper-server/models/whisperx/align/zh`

其中 VAD 配置必须引用本地 `segmentation` 目录，而不是只引用 `pytorch_model.bin`，否则离线模式下 pipeline 无法稳定解析完整模型结构。当前已经在 `/home/base/repo/video-stt-whisper-server/models/whisperx/vad/pyannote/config.yaml` 中预设了正确的本地路径。

### 未来预留但本轮不执行的本地模型

- diarization pipeline 根目录：`/home/base/repo/video-stt-whisper-server/models/whisperx/diarization/pyannote`

后续如果要实现说话人分离，这个目录需要补成完整的本地 `speaker-diarization-community-1` 目录结构。当前重点需要预留的位置是：

- `/home/base/repo/video-stt-whisper-server/models/whisperx/diarization/pyannote/segmentation`

该部分不属于本轮交付范围，不应阻塞 `stt_whisperx` 的落地。

## 用户可见行为

### 默认 job 行为

保持不变。未传入显式 DAG 时，仍走：

- `extract`
- `stt`
- `translate`

### 自定义 WhisperX job 行为

调用方可以通过显式 DAG 选择 `stt_whisperx`，例如：

```json
{
  "video_path": "/abs/path/demo.mp4",
  "language": "ja",
  "dag": {
    "version": 1,
    "stages": [
      {"stage": "extract", "depends_on": []},
      {"stage": "stt_whisperx", "depends_on": ["extract"]},
      {"stage": "translate", "depends_on": ["stt_whisperx"]}
    ]
  },
  "job_config": {
    "stt_whisperx": {
      "batch_size": 16
    }
  }
}
```

下游契约保持不变：`translate` 继续读取标准日语 SRT，不需要知道上游到底来自 `stt` 还是 `stt_whisperx`。

## 执行策略

### 第一步：先做独立 SOP / CLI 验证脚本

在真正接入 Service 之前，先在以下目录新增一个独立可执行的 WhisperX 验证脚本：

- `/home/base/repo/video-stt-whisper-server/whisper-stt/whisper_stt/`

它的职责是：

- 验证 WhisperX 能否直接复用现有本地 faster-whisper 主模型目录
- 验证本地 VAD 和 alignment 模型能否在离线模式下正确加载
- 验证 WhisperX 的“VAD 切段 + batch 推理”确实能产出可用 SRT
- 提供一条稳定、可重复的 SOP，用于与现有 `transcribe_video.py` 做效果和性能对比

这个新脚本应尽量延续以下现有脚本的 CLI 风格：

- `/home/base/repo/video-stt-whisper-server/whisper-stt/whisper_stt/transcribe_video.py`

预期能力包括：

- 接收输入媒体路径
- 接收本地 Whisper 主模型路径
- 接收本地 VAD 配置路径
- 接收本地 alignment 模型路径
- 接收 device / compute type / batch size
- 支持调试时关闭 alignment
- 输出标准 `.ja.srt`
- 打印便于人工比对的耗时、进度和关键信息

这个脚本是本轮 WhisperX 人工验证的唯一 SOP 入口，也是后续 Service stage 集成的原型来源。

此步骤完成后，设置人工验收门禁：要求提供真实视频绝对路径进行验证，验证通过后才能进入下一步 Service 集成。

### 第二步：再集成到 Service stage

在 CLI/SOP 路径验证通过后，再新增 `stt_whisperx` stage。

高层行为如下：

1. 读取上游提取后的音频或当前 job 可用媒体输入
2. 使用本地 faster-whisper 主模型目录加载 WhisperX 主 ASR 模型
3. 使用本地 pyannote VAD 配置进行语音分段
4. 基于 VAD 分段结果，使用配置中的 `batch_size` 执行 batched ASR
5. 使用本地 alignment 模型进行时间戳对齐
6. 输出标准日语 SRT，并继续满足 `translate` 的既有输入契约

### stage 命名约束

- 新 stage 名称固定为 `stt_whisperx`
- 现有 `stt` 保持不变
- 本轮不做别名兼容，不做后端切换开关混合模式

## 配置设计

### Whisper 主模型的复用策略

Whisper 主模型的选择逻辑继续沿用现有“本地 faster-whisper 模型路径”这一概念。

区别仅在于执行器如何使用这个路径：

- `stt`：直接通过 faster-whisper 执行
- `stt_whisperx`：通过 WhisperX 的 faster-whisper backend 执行

也就是说，本轮不是引入第二套 Whisper 主模型语义，而是在不同执行器中复用相同的本地主模型目录。

### 新增 WhisperX 专属配置

需要在以下两个文件中新增 `stt_whisperx` 配置段：

- `/home/base/repo/video-stt-whisper-server/whisper-stt/config.ini`
- `/home/base/repo/video-stt-whisper-server/whisper-stt/config.example.ini`

预期配置项包括：

- 本地 Whisper 主模型路径
- 本地 VAD 配置路径
- 本地 alignment 根目录或分语言路径
- `device`
- `compute_type`
- `batch_size`
- `align_enabled`
- `vad_backend`
- WhisperX 所需 VAD 调参项
- `local_files_only=true`

配置规则：

- 运行期禁止隐式联网下载
- 任一本地模型或配置路径缺失时，必须 fail-fast
- `job_config.stt_whisperx` 允许覆盖安全运行参数，例如 `batch_size`、alignment 路径等
- task 创建时，仍然需要把最终生效配置固化到 `task_config_json`

## 代码结构改动

### CLI / SOP 层

需要在以下目录新增或修改代码：

- `/home/base/repo/video-stt-whisper-server/whisper-stt/whisper_stt/`

职责包括：

- 本地模型路径解析
- 操作型 CLI 参数解析
- WhisperX 调用封装
- SRT 输出
- 适合人工观察的进度与耗时打印

### Service 层

预期涉及的区域包括：

- stage 注册表：`/home/base/repo/video-stt-whisper-server/whisper-stt/whisper_stt_service/core/stages.py`
- worker/runtime 装配：`/home/base/repo/video-stt-whisper-server/whisper-stt/whisper_stt_service/service/runtime.py`
- 新的 WhisperX 执行器模块：`/home/base/repo/video-stt-whisper-server/whisper-stt/whisper_stt_service/executor/`
- 配置解析：`/home/base/repo/video-stt-whisper-server/whisper-stt/whisper_stt_service/core/config.py`
- 若 DAG 支持 stage 白名单校验，则补充对应支持列表

另外需要保持当前重构后的兼容导出面不被破坏：

- `whisper_stt_service/stages.py`
- `whisper_stt_service/config.py`
- `whisper_stt_service/workers.py`
- `whisper_stt_service/executors.py`
- `whisper_stt_service/dag.py`
- `whisper_stt_service/repository.py`

原因是现有单元测试与兼容入口仍在使用这些包根导出模块，因此新增 `stt_whisperx` 时，不能只修改分层实现而忽略兼容导出路径。

设计原则：

- 不把现有 `stt` executor 改造成多后端分支逻辑
- `stt_whisperx` 必须是独立 executor、独立 stage 身份

## 数据契约

### 输入

- 上游提取后的音频或可直接读取的媒体输入
- job 的源语言信息
- `task_config_json` 中固化后的 stage 生效配置

### 输出

- 标准日语 SRT，继续写到当前 `translate` 所依赖的同一输出契约位置

### 本轮仅内部使用的增强信息

- alignment 可用于内部提升时间戳质量
- word-level 结果不作为本轮新的公开产物

## 错误处理

`stt_whisperx` 在以下情况必须显式失败：

- 本地 Whisper 主模型路径不存在
- 本地 VAD 配置路径不存在
- 当前语言对应的本地 alignment 模型不存在
- WhisperX 在离线模式下无法加载本地模型资产
- 输入音频明显存在语音，但底层执行抛错或最终字幕输出为空

错误信息必须能明确指出缺失的是哪一个本地模型或配置路径，方便运维和手工排查。

## 测试策略

### 单元测试

补充以下覆盖：

- `stt_whisperx` 的配置解析与校验
- stage 注册表新增 `stt_whisperx`
- DAG 校验允许 `stt_whisperx`
- `job_config` 对新 stage 的归一化和 task 快照固化

### CLI / SOP 验证

在可行范围内增加一个 smoke 级自动化验证；如果不适合自动化，则至少把 SOP 命令明确写入文档。

人工 SOP 必须验证：

- 本地模型路径解析成功
- 可成功生成 SRT
- 进度和耗时信息正确输出
- 与当前 faster-whisper CLI 路径相比，分段质量具备可比较或更优的结果

### Service E2E

新增一条基于显式 DAG 的 E2E 流程，参考现有 real-flow 驱动。

新的 E2E 需要验证：

- 通过显式 DAG 提交 `stt_whisperx`
- 通过 `job_config.stt_whisperx` 传入覆盖参数
- job 能完整成功执行
- 日语 SRT 成功生成
- `translate` 依赖 `stt_whisperx` 时仍可继续成功执行

现有默认路径的 E2E 不应被删除，仍需继续覆盖稳定的 faster-whisper 路径。

## 推进顺序

1. 校验并固定本地模型目录与离线路径。
2. 编写独立 WhisperX SOP / CLI 验证脚本。
3. 用代表性素材进行人工比对和调参。
4. 将已验证逻辑集成进新的 `stt_whisperx` stage。
5. 补充单元测试与显式 DAG 的 E2E。
6. 保持默认 DAG 不变。

## 验收标准

当且仅当以下条件同时成立时，本轮才算完成：

- 默认 job 仍然继续走旧 `stt`
- 自定义 DAG 可以把 job 路由到 `stt_whisperx`
- `stt_whisperx` 在运行期只使用本地模型与本地配置
- 新路径确实使用 WhisperX 的 VAD 分段和 batched ASR
- 新路径输出的日语 SRT 可被现有 `translate` 无缝消费
- 存在独立的 SOP / CLI 验证脚本，可在 Service 集成前单独验证新链路
- 存在针对新 stage 的单元测试与显式 DAG E2E 覆盖

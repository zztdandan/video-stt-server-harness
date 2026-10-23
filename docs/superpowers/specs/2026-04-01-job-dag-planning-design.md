# Job DAG 规划设计

## 背景

`whisper_stt_service` 当前在 `repository.enqueue()` 中固定创建三段式流水线：

- `extract`
- `stt`
- `translate`

这套模型可以支撑第一版上线，但还不支持以下能力：

- job 级参数覆盖，而不是只能依赖全局 `config.ini`
- 显式声明本次 job 要执行哪些步骤，以及步骤之间的依赖关系
- 当上游产物已经存在时，从中间步骤直接开始
- 后续新增 stage 类型时，避免再次重做表结构与调度模型

本轮设计的目标是在保持现有调用方式向前兼容的前提下，把内部统一切换到 DAG 规划模型，以及可以进行逐个 jobs的参数设置。

## 目标

- 保持现有调用方在不改请求的情况下仍可继续使用。
- 把 job 创建统一到 DAG 规划模型中。
- 支持按 job 显式声明 stage 集合与 stage 依赖。
- 支持按 stage 分组的 job 级参数覆盖。
- 在 task 创建时固化每个 task 的最终生效配置快照。
- 为未来新增 stage 类型预留稳定扩展点。
- 在同一路径 job 未归档前，阻止重复活跃 job。
- 增加显式归档能力，在保留历史的前提下释放路径复用资格。

## 非目标

- 本轮不支持 OR 依赖语义。
- 本轮不支持条件分支。
- 本轮不支持同一 job 内同一 stage 出现多个重复节点。
- 本轮不支持自动归档。
- 本轮不提供归档列表/归档详情接口。

## 选定方案

系统内部统一采用单一模型处理新旧两类提交：

- 每个 job 都按 DAG 计划建模。
- 未显式传入 `dag` 的默认请求，会被转换成默认简单 DAG。
- 每个 stage 实例展开为一条 task 记录。
- 依赖关系继续复用 `tasks.depends_on_task_id` 字段存储。
- job 级覆盖参数存入 `jobs.job_config_json`。
- task 级最终配置快照存入 `tasks.task_config_json`。

这样可以保留当前 worker 架构、轮询机制和 task 状态流转方式，只把规划、校验和配置固化前移到 API/Repository 层。

## DAG 边界

本轮仅支持 AND 型依赖。

- 一个 task 只有在全部上游 task 都为 `succeeded` 时才可执行。
- 允许一个 task 有多个依赖。
- 允许并行分支。
- 允许汇合节点。
- 不支持“任一上游成功即可执行”的 OR 语义。
- 不允许出现环。

在一个 job 内，stage 名称必须唯一。因此当前模型仍然是“一个 stage 对应一个 task 实例”。

## 默认规划行为

如果请求中未提供 `dag`，系统仍然按 DAG 模型创建任务，只是自动补齐一个默认简单 DAG：

```json
{
  "version": 1,
  "stages": [
    {"stage": "extract", "depends_on": []},
    {"stage": "stt", "depends_on": ["extract"]},
    {"stage": "translate", "depends_on": ["stt"]}
  ]
}
```

这样可以保持外部行为不变，同时去掉内部对“老模式”的特殊分支。

## 数据模型

### `jobs`

新增字段：

- `dag_json TEXT NULL`
- `job_config_json TEXT NULL`

字段语义：

- `dag_json`：保存本次 job 归一化后的 DAG 计划快照。
- `job_config_json`：保存按 stage 分组的 job 级覆盖参数。
- 如果请求未传 `dag`，则把系统补齐后的默认 DAG 写入 `dag_json`。
- 如果请求未传 `job_config`，则 `job_config_json` 可以存 `NULL`，读取时再标准化为 `{}`。

### `tasks`

新增字段：

- `task_config_json TEXT NULL`

保留现有字段：

- `depends_on_task_id TEXT NULL`

字段语义：

- `task_config_json`：保存该 task 的最终生效配置快照。
- `depends_on_task_id`：继续兼容旧格式与新格式：
  - `NULL` 或空字符串表示无依赖
  - 普通字符串表示单个上游 task id
  - JSON 数组字符串表示多个上游 task id

### 归档表

新增：

- `jobs_archive`
- `tasks_archive`

归档表建议与主表字段基本一致，并额外增加：

- `archived_at TEXT NOT NULL`
- `archive_reason TEXT NOT NULL`

归档是“迁移”，不是“仅复制不删除”。归档成功后，对应数据会从 `jobs` 和 `tasks` 主表中删除。

## DAG 结构与校验

`jobs.dag_json` 建议结构如下：

```json
{
  "version": 1,
  "stages": [
    {
      "stage": "extract",
      "depends_on": []
    },
    {
      "stage": "stt",
      "depends_on": ["extract"]
    },
    {
      "stage": "translate",
      "depends_on": ["stt"]
    }
  ]
}
```

校验规则：

- `stages` 不能为空
- 同一个 job 内 `stage` 必须唯一
- `depends_on` 中的每个引用都必须存在于当前 DAG 中
- 不允许自依赖
- 不允许环
- 每个 stage 都必须是当前运行时已支持的 stage

## Stage 枚举

stage 建议通过代码中的统一枚举/注册表校验，而不是依赖数据库 enum。

当前支持的 stage：

- `extract`
- `stt`
- `translate`

这样后续新增 `qc`、`postprocess`、`publish` 等 stage 时，不需要先改数据库枚举。

## Job 级配置模型

`job_config_json` 采用按 stage 分组的对象结构：

```json
{
  "extract": {
    "timeout_sec": 1800
  },
  "stt": {
    "beam_size": 3,
    "best_of": 3,
    "initial_prompt": "..."
  },
  "translate": {
    "chunk_minutes": 20,
    "retry": 8
  }
}
```

采用对象而不是数组的原因：

- 同一 job 内 stage 本身唯一
- 查找简单稳定
- 不会出现重复 stage 配置项
- 比 stage 数组更容易校验与去重

校验规则：

- `job_config_json` 中出现的 key 必须也存在于当前 job DAG 中
- 每个参数 key 必须属于对应 stage 已支持的配置集合
- 参数类型与取值范围必须在 job 创建前完成校验

## Task 配置快照

在 job 创建时，每个 task 都要生成一个合并后的配置快照，并写入 `tasks.task_config_json`。

示例：

```json
{
  "stage": "stt",
  "effective_config": {
    "timeout_sec": 7200,
    "max_retries": 2,
    "device": "auto",
    "compute_type": "auto",
    "beam_size": 3,
    "best_of": 3,
    "patience": 1.0,
    "vad_filter": true
  }
}
```

配置优先级：

1. `task_config_json` 中已经固化的 task 最终配置
2. `job_config_json` 中该 stage 的覆盖参数
3. `config.ini` 中的全局默认值

运行期应优先使用 task 快照，而不是再次直接读取实时全局配置。这样即使后续 `config.ini` 改变，历史 job 的执行语义仍然稳定。

## API 变更

### 创建 Job

`POST /jobs` 继续作为唯一创建入口。

请求体：

```json
{
  "video_path": "/abs/path/demo.mp4",
  "language": "ja",
  "dag": {
    "version": 1,
    "stages": [
      {"stage": "extract", "depends_on": []},
      {"stage": "stt", "depends_on": ["extract"]},
      {"stage": "translate", "depends_on": ["stt"]}
    ]
  },
  "job_config": {
    "stt": {
      "beam_size": 3,
      "best_of": 3
    },
    "translate": {
      "chunk_minutes": 20,
      "retry": 8
    }
  }
}
```

建议新增响应字段：

- `plan_mode`：`default` 或 `custom`
- `stages`：本次 job 实际展开出的 stage 列表

如果请求未传 `dag`，服务端会自动补齐默认简单 DAG，并返回 `plan_mode=default`。

### 归档 Job

新增显式归档接口：

- `POST /jobs/{job_id}/archive`

建议请求体：

```json
{
  "reason": "manual_archive"
}
```

允许归档的情况：

- 该 job 的所有 task 都仍然是 `queued`
- 该 job 已经进入终态，即 `succeeded` 或 `failed`

不允许归档的情况：

- 存在任一 `claimed` task
- 处于中间混合状态，例如部分已完成、部分仍排队、但尚未进入终态

归档必须在单个事务中完成：

1. 把主表 job 复制到 `jobs_archive`
2. 把主表 task 复制到 `tasks_archive`
3. 删除主表中的 task 记录
4. 删除主表中的 job 记录

该接口的目的，是在保留历史的同时，释放 `video_path` 的活跃占用资格。

### 读取接口

`GET /jobs/{job_id}` 与 `GET /jobs/{job_id}/progress` 建议增加返回：

- 归一化后的 `dag`
- 归一化后的 `job_config`
- 每个 task 的 `task_config`

这样有利于后续 UI 展示、问题排查与历史审计。

## 执行语义

### 入队流程

`enqueue()` 应执行以下步骤：

1. 标准化请求输入
2. 如果未传 `dag`，自动构造默认 DAG
3. 校验 `dag` 与 `job_config`
4. 按 stage 合并默认配置与覆盖配置，得到 task 级最终配置
5. 创建 job 记录
6. 创建全部 task 记录
7. 把 stage 依赖名称转换成真实 task id，并写入 `depends_on_task_id`

### 幂等与拒绝规则

当收到新的同路径请求时，只检查主表中该 `video_path` 的最近一条活跃 job。

- 如果该 job 的所有 task 都仍为 `queued`，则返回该已有 job，响应 `idempotent_returned`
- 如果任一 task 曾进入 `claimed`、`succeeded` 或 `failed`，则拒绝新提交，响应 `rejected_started`
- 已归档的数据不再阻塞新提交，因为它们已经不在主表中

这意味着和旧行为相比，同路径 job 完成后不能立即再次提交，只有归档后才能重新提交。

### 领取任务

`claim_next(stage, worker_id, lease_timeout_sec)` 仍按 stage 维度领取任务，但“可领取”的判断规则需要改为：

- `status='queued'`
- `task.stage` 与当前 worker 的 stage 一致
- `depends_on_task_id` 解析出的所有依赖 task 状态都为 `succeeded`

这样在不改 worker 执行模型的前提下，就可以支持并行分支与汇合节点。

### 状态聚合

job 状态不再依赖“固定三阶段”的假设，而是根据该 job 的全部 task 聚合：

- 全部 task 为 `queued` -> job 为 `queued`
- 任一 task 为 `claimed` -> job 为 `running`
- 全部 task 为 `succeeded` -> job 为 `succeeded`
- 任一 task 永久 `failed` -> job 为 `failed`

本轮不新增 `blocked` 等中间状态。

### 重试与恢复

task 的重试策略仍然保持 task 级别独立：

- 若失败次数未超过 `max_retries`，则 task 回到 `queued`
- 若失败次数超过上限，则 task 进入 `failed`

`recover_claimed_to_queued()` 保持现有职责不变。服务重启后，把 `claimed` task 回退到 `queued`，然后继续按 DAG 依赖规则重新调度。

## 依赖字段兼容编码

`depends_on_task_id` 需要统一走一个兼容解析函数。

解析规则：

- `NULL` 或空字符串 -> `[]`
- 普通字符串 -> `[that_string]`
- JSON 数组字符串 -> 数组内容
- 非法 JSON 或 JSON 对象等错误载荷 -> 视为无效依赖载荷

写入规则：

- 无依赖 -> `NULL`
- 单依赖 -> 单个 task id 字符串
- 多依赖 -> JSON 数组字符串

这样既保留旧数据兼容性，也支持新的多依赖汇合场景。

## 校验与失败处理

在请求校验阶段直接拒绝以下情况：

- DAG 为空
- stage 重复
- 依赖目标不存在
- 存在环
- stage 未知或当前不支持
- `job_config` 引用了 DAG 之外的 stage
- 该 stage 下出现未知配置项
- 参数类型或范围非法

对运行期数据损坏采用保守处理：

- `depends_on_task_id` 非法 -> task 失败，错误为 `invalid_dependency_payload`
- `task_config_json` 非法 -> task 失败，错误为 `invalid_task_config`

下游 task 不需要额外引入 `blocked` 状态。只要上游 task 永久失败，job 最终就会聚合为 `failed`。

## 迁移策略

采用增量式 schema 迁移，不重写历史数据。

- 给 `jobs` 增加 `dag_json` 与 `job_config_json`
- 给 `tasks` 增加 `task_config_json`
- 新建 `jobs_archive` 与 `tasks_archive`

兼容策略：

- 旧数据没有 `dag_json` 时，读取层可按默认简单 DAG 补齐展示
- 旧的单字符串 `depends_on_task_id` 继续按原语义工作
- 没有 `task_config_json` 的旧 task，可通过兼容逻辑继续运行，直到活跃任务逐步切换到新模型

建议发布顺序：

1. 先上 schema 迁移与兼容读取
2. 再上线 DAG 化创建逻辑
3. 最后上线归档接口

## 测试策略

### 单元测试

需要新增或调整的单元测试包括：

- 默认创建 job 时自动生成默认简单 DAG
- 显式 DAG 能正确展开成 task
- 多依赖汇合节点只有在全部上游成功后才可领取
- 同一层多个 ready task 可并行领取
- 环检测
- 缺失依赖检测
- 未知 stage 拒绝
- 非法配置拒绝
- 全部活跃 task 仍为 `queued` 时幂等返回
- 任一活跃 task 已开始或已结束时拒绝再次提交
- 全部 queued 的 job 可以归档
- 终态 job 可以归档
- 部分执行中的 job 不允许归档
- 归档后 path 可重新提交

### API 测试

需要新增或调整的 API 测试包括：

- `POST /jobs` 在不传 `dag` 时的默认行为
- `POST /jobs` 在显式传 `dag` 与 `job_config` 时的行为
- 非法 DAG / 非法配置的校验错误
- `POST /jobs/{job_id}/archive` 的允许与拒绝场景

### E2E 测试

保留现有真实流程脚本，用于验证默认兼容路径。

新增一个独立的真实流程 Python 脚本，要求：

- 仍然读取现有路径清单输入
- 在请求体中显式提交三阶段 DAG
- 在请求体中显式提交各 stage 的自定义 `job_config`
- 验证显式 DAG / 显式配置路径能够校验通过并跑完整条链路

建议文件名：

- `tests/e2e/run_e2e_explicit_dag_flow.py`

这个新 E2E 脚本的目的，是验证“虽然 DAG 仍然是历史上的三阶段，但已完整走新规划模型”。

## 方案收益

该方案刻意保留当前 worker 架构与状态机，核心变化只集中在规划、依赖解释与配置快照固化。

最终得到的收益包括：

- 对现有调用方保持向前兼容
- 可以从中间 stage 开始执行
- 可以平滑扩展未来 stage 类型
- 通过 job/task 快照提升排障、审计和复盘能力
- 通过显式归档来控制 path 复用时机

## 实施注意事项

- 实施时保留现有代码中的所有注释。
- 继续复用当前状态值，不在无必要时扩展新的运行态。
- 建议维护一个共享的 stage 注册表，避免 API 校验、Repository 规划和 Worker 分发之间出现漂移。

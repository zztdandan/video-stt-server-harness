# 批次 4 执行记录：翻译链路加固（C.1–C.7）

- **日期**：2026-10-22
- **SPEC**：[`docs/superpowers/specs/2026-10-22-whisper-stt-reliability-and-translation-hardening-spec.md`](../specs/2026-10-22-whisper-stt-reliability-and-translation-hardening-spec.md) 第 4 节 C、第 8 节批次 4
- **工作树**：`/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening`（分支 `feature/reliability-hardening`）
- **Python**：一律使用 `/home/base/repo/video-stt-whisper-server/.venv/bin/python`，未创建任何 venv
- **负责范围**：`executor/translate.py`、`executor/common.py`、新增 `executor/atomic.py`、新增翻译单测；后续追加 E 脚本模式 wav 契约（`whisper_stt/transcribe_video.py`、`scripts/run_video_ja_srt.sh`、`whisper_stt/translate_srt_ja_to_zh.py` 默认并发）及 `tests/unit/test_script_mode_wav_contract.py`
- **显式未触碰**：`core/config.py`、`api/routes/jobs.py`、`config.example.ini`、`service/runtime.py`（由其他代理负责，参数契约见第 5 节）

---

## 1. 修改文件清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `whisper_stt_service/executor/atomic.py` | 新增 | 原子写工具 `atomic_write_text` / `atomic_write_bytes` / `_cleanup_stale_temp_files` |
| `whisper_stt_service/executor/common.py` | 修改 | 共享异常、三重切分与稳定 batch_id、配置解析、`_dump_srt` 原子化、SHA-256 工具 |
| `whisper_stt_service/executor/translate.py` | 修改 | 受限并发 2、检查点、部分 id 降级、4xx/5xx 重试策略、幂等键、取消检查、原子 copy_back |
| `whisper_stt_service/executors.py` | 修改 | 重导出 `ExecutorCancelledError` / `MissingAudioArtifactError` |
| `tests/unit/test_translate_reliability.py` | 新增 | 44 个用例：C.1–C.7、llm 回退、产物级 fencing |
| `whisper_stt/transcribe_video.py` | 修改 | E：`ensure_wav_artifact`（存在/非空/RIFF-WAVE 校验）、`MissingAudioArtifactError`、`atomic_write_text`、ja.srt 缓冲后原子落盘 |
| `scripts/run_video_ja_srt.sh` | 修改 | E：新增 `TEMP_AUDIO` 透传；修正 `REPO_ROOT`（原 `../..` 少一级）与 venv 解析 |
| `scripts/run_video_ja_srt_whisperx.sh` | 修改 | E：新增 `PREEXTRACT_WAV`/`TEMP_AUDIO` 透传；修正 `REPO_ROOT` 与硬编码 venv 路径 |
| `scripts/run_video_ja_zh.sh` | 修改 | E+D2：透传 wav 变量、`PARALLEL` 默认 2 显式传给翻译脚本；修正 `REPO_ROOT` 与配置路径 |
| `scripts/_venv.sh` | 新增 | 主仓库共享 venv 解析（`WHISPER_STT_ROOT` → git common-dir → 逐级向上查找） |
| `whisper_stt/transcribe_video_whisperx.py` | 修改 | E：接入同一份 wav 契约（预抽/校验），临时 wav 用后即删；显式注入 sys.path |
| `whisper_stt/translate_srt_ja_to_zh.py` | 修改 | D2：脚本模式默认并发 16 → 2（`--parallel` / `[translation] parallel` 仍可覆盖） |
| `tests/unit/test_script_mode_wav_contract.py` | 新增 | 20 个用例：wav 契约（含 WhisperX 路径）、默认并发 2、共享 venv 解析 |
| `tests/unit/test_translate_copy_back.py` | 修改 | copy_back 改为原子写后，注入点从 `shutil.copy2` 改为 `atomic_write_text`；新增 caplog 隔离 fixture |

> 既有的未提交改动 `llm_fallback`（`_load_llm_profiles` / `_pick_llm_profile`）**完整保留**并补充了 profile 选择、去重、attempt 2 起用回退模型的测试。所有既有注释与 docstring 均保留（改写的 docstring 均为扩充，未删除语义）。

---

## 2. 各项落地情况

### C.1 受限并发（D2）
- `ThreadPoolExecutor(max_workers=min(parallel, len(pending)))`，`parallel` 默认 2。
- 结果按 batch 序号聚合，最终按**原 SRT 顺序**写回（非完成顺序）。
- 每线程独立 `requests.Session`（`threading.local`），`trust_env = not disable_proxy`。
- `request_interval` 作为**批次派发最小间隔**（`threading.Lock` + 时间戳），0 表示关闭；未引入令牌桶。
- 任一批次失败：`_aborted` 置位，不再调度新批次，`cancel_futures` 取消未开始批次，等待在途批次收尾后抛错；已成功批次均已落检查点。

### C.2 配置全部生效
- 新增 `common.resolve_translate_settings(config, job_config, ...) -> TranslateSettings`。
- 优先级：`job_config`（含旧关键字覆盖） > `[translation]` > 代码默认值。
- `parallel`/`batch_size`/`max_chars`/`chunk_minutes`/`timeout`/`retry`/`request_interval`/`disable_proxy`/`copy_back`/`checkpoint_enabled`/`strict_ids`/`progress_ttl_sec` 全部真正生效；移除了"读取后只用于 sleep"的假实现。

### C.3 三重切分与稳定 batch_id
- `common.build_translate_batches(entries, window_minutes, batch_size, max_chars)`：时间窗 → 条目数 → 字符数，三个上限取先到者。
- `batch_id = "<window_index>/<part_index>"`，与完成顺序无关，同一输入稳定。
- 单条超过 `max_chars` 时单独成批，**不截断原文**。
- 旧函数 `_split_entries_by_time_window` 保留（兼容旧导入与旧测试）。

### C.4 真实检查点
- 文件 `<output>.progress.json`：`{version, source_sha256, chunk_minutes, max_chars, batch_size, updated_at, batches:{batch_id:{done, inflight, ids, translations, ...}}}`。
- 复用条件：`version` 匹配、`source_sha256` 与当前 ja.srt 一致、`chunk_minutes/max_chars/batch_size` 与本次生效配置一致；任一不符**全量重算**。
- 恢复时要求**有实际译文内容**：仅 `done=true` 但译文为空或 id 不全的批次一律丢弃重算。
- 每批成功立即原子写检查点；请求发出前写 `inflight` 标记。
- **禁止**无条件删除检查点：上次先删 `.progress.json` 的逻辑已移除；成功后保留并按 `progress_ttl_sec` 刷新 mtime 供 TTL 清理。
- `checkpoint_enabled=false` 时不读不写（排障用）。

### C.5 部分 id 降级
- `_call_translate_api` 接受 id 子集，缺失/越界抛 `TranslatePartialIdsError`。
- 先接受返回项，仅对缺失 id 以更小批次重试；重试仍缺失时默认**保留日文原文**写入 zh.srt，并记 `translate_partial` 警告（含缺失数量）。
- `strict_ids=true` 时缺失即整批失败。
- **整批失败（连接/超时/5xx/解析）不降级**，直接抛错交任务重试（避免把失败静默伪装成原文）。

### C.6 重复计费控制
- 只重试：连接错误、超时、HTTP 5xx、JSON 解析失败、id 不匹配。
- **4xx（含 429）一律不重试**，直接 `TranslateNonRetryableError` 失败（依 SPEC 原文）。
- 请求头 `Idempotency-Key: sha256(job_id|batch_id|source_sha256)`；新增 `job_id` 关键字，缺省回退 `task_id`。
- 每次重试记录 `batch_id`、`attempt`、`error_class`、`elapsed_ms`。

### C.7 原子写入
- `atomic_write_text/bytes`：同目录 `.tmp-<pid>-<uuid>.<name>` → `flush` + `os.fsync` → `os.replace`；失败删除临时文件并**原样抛出**，已有产物不变。
- `_dump_srt`、检查点写入、copy_back 全部改用该工具。
- `copy_back` 目标若为符号链接则跳过并告警，防逃逸。

### 附：共享异常（应父代理/ASR 要求）
- `ExecutorCancelledError(RuntimeError)`，`code = "executor_cancelled"`。
- `MissingAudioArtifactError(RuntimeError)`，`code = "missing_audio_artifact"`，`MissingAudioArtifactError(path)`。
- `translate.TranslateCancelledError` 为 `ExecutorCancelledError` 子类；runtime 用基类即可统一捕获。

---

## 3. 验证命令与结果

```bash
VENV=/home/base/repo/video-stt-whisper-server/.venv/bin/python
cd /home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening

# 基线（改动前，由父代理测得）
$VENV -m pytest tests/unit -q          # 55 passed

# 语法检查
$VENV -m py_compile whisper_stt_service/executor/{translate,common,atomic}.py \
    tests/unit/test_translate_reliability.py tests/unit/test_translate_copy_back.py
# exit 0

# 静态检查（父代理要求 ruff E9,F 通过）
$VENV -m ruff check --select E9,F whisper_stt_service/executor/{translate,common,atomic}.py \
    whisper_stt_service/executors.py tests/unit/test_translate_reliability.py tests/unit/test_translate_copy_back.py
# All checks passed!   exit 0

# 本批翻译测试
$VENV -m pytest tests/unit/test_translate_reliability.py tests/unit/test_translate_copy_back.py \
    tests/unit/test_translation_chunking.py -q
# 38 passed
```

### 全量单测现状（共享工作树）
改动前基线为父代理测得的 55 项全绿。全量 `pytest tests/unit` 的通过数与失败项随其他代理的进行中改动持续变化，期间出现的失败均属于**其他代理正在开发的区域**，与本批无关：

| 期间出现的失败用例 | 归属 | 根因 |
|---|---|---|
| `test_executor_wav_contract.py` × 4 | ASR / model_cache 代理 | `service/model_cache.py` `UnboundLocalError`、wav 契约未抛 `MissingAudioArtifactError` |
| `test_observability.py::test_configure_logging_*` × 3 | 可观测性代理 | `dictConfig` 后 `propagate=False` 未在 fixture 中恢复 |
| `test_repository_dependency_payload` / `test_worker_recovery` 等 | 生命周期 / DAG 代理 | 各自改造进行中 |

> **以我负责的 58 项为准**（36 翻译 + 20 脚本模式 + 2 既有 copy_back），当前全绿。

> 说明：`test_observability.py` 的 `propagate` 残留会污染后续用例的 `caplog`。本批已在**自己的测试文件内**加入 autouse fixture 复原 `whisper_stt_service` 的 `propagate`，未改动他人文件；建议可观测性代理同步修复 `logging_isolation` fixture。

---

## 4. 新增测试覆盖

| 用例 | 覆盖点 |
|---|---|
| `test_build_batches_three_way_split_with_stable_batch_ids` | C.3 三重上限 + 稳定 batch_id + 顺序 |
| `test_build_batches_batch_size_limit_wins_when_chars_unbounded` | C.3 条目数上限先生效 |
| `test_build_batches_oversized_entry_becomes_own_batch_untruncated` | C.3 超长单条不截断 |
| `test_build_batches_window_partition_is_stable` | C.3 跨窗口编号稳定 |
| `test_resolve_translate_settings_precedence` | C.2 三级优先级 |
| `test_resolve_translate_settings_legacy_kwargs_still_override` | C.2 旧关键字兼容 |
| `test_resolve_translate_settings_parallel_defaults_to_two` | D2 默认并发 2 |
| `test_translate_concurrency_never_exceeds_parallel` | C.1 并发峰值 ≤ 2 且确实并发 |
| `test_translate_output_preserves_srt_order` | C.1 乱序完成仍按原文序输出 |
| `test_checkpoint_written_and_reused_on_rerun` | C.4 失败后重跑只补未完成批次 |
| `test_checkpoint_invalidated_when_source_changes` | C.4 源 hash 变更失效 |
| `test_checkpoint_without_translations_is_not_reused` | C.4 无译文内容不复用 |
| `test_checkpoint_invalidated_when_batching_config_changes` | C.4 切分配置变更失效 |
| `test_checkpoint_disabled_writes_no_file` | C.4 关闭检查点 |
| `test_partial_ids_fallback_keeps_source_text` | C.5 保留原文 + 不丢行 + 告警 |
| `test_strict_ids_fails_batch_on_missing` | C.5 strict 模式 |
| `test_non_retryable_4xx_fails_immediately` | C.6 4xx 不重试 |
| `test_4xx_including_429_is_never_retried` | C.6 429 不重试 |
| `test_retryable_5xx_retries_and_succeeds` | C.6 5xx 重试 |
| `test_idempotency_key_is_stable_hash` / `..._header_sent_on_request` | C.6 幂等键 |
| `test_idempotency_key_stable_across_task_retries` | C.6 跨 attempt 稳定 |
| `test_atomic_write_replaces_content` / `..._keeps_old_file_on_failure` | C.7 原子写与失败回滚 |
| `test_dump_srt_is_atomic_and_fills_missing_with_source` | C.7 + C.5 回填原文 |
| `test_copy_back_refuses_symlink_target` | C.7 防 symlink 逃逸 |
| `test_cancel_check_aborts_without_writing_output` | 取消不写产物 |
| `test_load_llm_profiles_*` / `test_pick_llm_profile_*` / `test_fallback_profile_used_on_second_attempt` | llm_fallback profile 选择、去重、attempt 2 回退 |

---

## 4bis. E 批次：脚本模式 wav 契约对齐

### 改动
1. **`whisper_stt/transcribe_video.py`**
   - 新增 `MISSING_AUDIO_ARTIFACT_CODE = "missing_audio_artifact"` 与 `MissingAudioArtifactError`（与 service 端错误码一致）。
   - 新增 `ensure_wav_artifact(path)`：校验**存在 + 非空 + RIFF/WAVE 头**，任一不满足抛 `MissingAudioArtifactError`。校验头是为了防止"文件存在但其实是 mp4"绕过契约。
   - `main()` 在调用模型前强制 `ensure_wav_artifact(audio_input)`：
     - `--preextract-wav`（默认）：ffmpeg 产出 `<output>.tmp.16k.wav`，模型吃 wav。
     - `--no-preextract-wav`：只用 `--temp-audio`（已存在的 wav）或 `--input`（必须是 wav）；**绝不把视频交给 faster-whisper**，否则报 `missing_audio_artifact`。
   - ja.srt 改为**先累积内存、循环结束后 `atomic_write_text` 原子替换**（失败保留旧文件、清理临时文件）。
2. **`scripts/run_video_ja_srt.sh`**：新增 `TEMP_AUDIO` 环境变量透传 `--temp-audio`；注释说明关闭预抽时必须给 wav。用 `${TEMP_AUDIO_ARGS[@]+"${TEMP_AUDIO_ARGS[@]}"}` 保证数组为空时在 `set -u` 下不报错。
3. **`whisper_stt/translate_srt_ja_to_zh.py`**：`[translation] parallel` 默认值 16 → **2**（D2），`--parallel` 与配置文件仍可覆盖；其余默认值未动。

### 验证
```bash
$VENV -m py_compile whisper_stt/{transcribe_video,transcribe_video_whisperx,translate_srt_ja_to_zh}.py  # exit 0
bash -n scripts/*.sh                                                                       # 全部 exit 0
$VENV -m ruff check --select E9,F whisper_stt/ <上述文件 + 新测试>                          # All checks passed!
$VENV -m pytest tests/unit/test_script_mode_wav_contract.py -q                             # 20 passed
```

### 新增用例
| 用例 | 覆盖点 |
|---|---|
| `test_ensure_wav_artifact_accepts_non_empty_wav` | 合法 wav 通过 |
| `test_ensure_wav_artifact_rejects_missing` / `..._rejects_empty_file` | 缺失 / 0 字节 → `missing_audio_artifact` |
| `test_ensure_wav_artifact_rejects_video_payload` | 内容是视频的输入被拒绝 |
| `test_main_default_preextracts_wav_and_never_feeds_video` | 默认预抽，模型收到 wav 而非 mp4 |
| `test_main_without_preextract_rejects_video_input` | 关闭预抽 + 无 wav → 抛错且**模型未被调用**、不产出 srt |
| `test_main_without_preextract_accepts_existing_wav` | 关闭预抽 + 显式 wav → 不跑 ffmpeg |
| `test_main_writes_srt_atomically` / `test_atomic_write_keeps_old_file_on_failure` | 原子写与失败回滚 |
| `test_whisperx_default_preextracts_wav_and_never_feeds_video` | WhisperX 路径同样只吃 wav |
| `test_whisperx_without_preextract_rejects_video_input` | WhisperX 无 wav 时 ASR 根本不被调用 |
| `test_whisperx_without_preextract_accepts_existing_wav` / `test_whisperx_cleans_temporary_wav` | 复用外部 wav / 临时 wav 用后即删 |
| `test_venv_helper_resolves_main_repo_from_worktree` / `..._honours_whisper_stt_root` | worktree 场景解析主仓库 venv |
| `test_scripts_never_hardcode_worktree_venv` / `test_scripts_reference_existing_entrypoints` | 三个脚本均 source `_venv.sh`、无 worktree 内 venv、入口文件存在 |
| `test_script_translate_parallel_defaults_to_two` / `..._is_overridable` / `..._source_declares_parallel_default_two` | 默认 2 且可覆盖 |

### 全脚本模式一致性（"不能留一条视频直接 ASR 绕过"）
| 脚本 | ASR 入口 | 是否强制 wav |
|---|---|---|
| `run_video_ja_srt.sh` | `whisper_stt/transcribe_video.py` | ✅ `ensure_wav_artifact` |
| `run_video_ja_srt_whisperx.sh` | `whisper_stt/transcribe_video_whisperx.py` | ✅ 复用同一份 `ensure_wav_artifact` |
| `run_video_ja_zh.sh` | 经 `run_video_ja_srt.sh` + 翻译脚本 | ✅ 透传 `PREEXTRACT_WAV`/`TEMP_AUDIO` |

两条路径共用 `transcribe_video.ensure_wav_artifact`（存在 + 非空 + RIFF/WAVE 头），WhisperX 脚本通过
`sys.path` 注入复用同一实现，避免两份实现漂移。任一入口在 `PREEXTRACT_WAV=false` 且输入不是 wav 时，
都会在调用 ASR 前抛 `missing_audio_artifact`。

### 共享 venv 解析（SPEC：只主仓库 .venv，worktree 不建独立 venv）
新增 `scripts/_venv.sh`，三个脚本统一 `source`。解析优先级：
1. `WHISPER_STT_ROOT` 环境变量；
2. `git rev-parse --git-common-dir`（worktree 下指向主仓库 `.git/modules/<name>`），由此推出主仓库根；
3. 从脚本目录逐级向上查找 `.venv/bin/python`。

全部失败时报错退出并提示设置 `WHISPER_STT_ROOT`，**绝不回退到 worktree 内的 `.venv`**。
同时修正了原先的错误路径：`run_video_ja_srt.sh` / `run_video_ja_zh.sh` 的 `REPO_ROOT` 原为 `../..`（多退一级），
`run_video_ja_srt_whisperx.sh` 硬编码了主仓库 venv 绝对路径，且三者引用的脚本路径含多余的 `whisper-stt/` 前缀。

---

## 4ter. 注释 / docstring 保留专项自查

### 检查方法
1. 对每个改动文件执行 `git diff -U0`，逐行审查所有以 `-` 开头的删除行。
2. 用 AST 枚举 `git diff` 中新增的 `def`/`class`，逐一检查 `ast.get_docstring`。

### 结论
- **新增函数/类全部有 docstring**（`atomic`、`common`、`translate`、`transcribe_video` 共 50+ 个新增定义，逐一通过）。
- **删除行中不含任何注释或 docstring 的净丢失**。仅 4 处 docstring/注释被**扩写**而重写，原文措辞全部保留：
  | 位置 | 原措辞（保留） | 补充内容 |
  |---|---|---|
  | `common._split_entries_by_time_window` | 按字幕起始时间切分窗口，默认每 30 分钟一个翻译批次。 | 追加"兼容旧调用方"说明 |
  | `common._dump_srt` | 按原时间轴写回翻译后的 SRT 文件 | 追加原子替换与缺失回填说明 |
  | `translate._call_translate_api` | 调用 LLM 翻译单个批次并返回 id -> 中文文本映射。 | 追加 id 子集/幂等键说明 |
  | `translate.run_translate` | 直接在 service 内部执行翻译，并把进度写入队列。 | 追加并发/检查点/取消契约 |
  | `translate._translate_batch` | 保留"保留请求节流行为，避免对上游接口形成瞬时冲击。"语义 | 迁移到 `_DispatchThrottle` 并说明 0 = 关闭 |
- 其余删除行均为**被替换的旧实现代码**（如旧的 `session.post` 直连、旧的固定 `parallel=16` 读取、旧的 `shutil.copy2`），非注释。

### 主动移除的危险 helper
`atomic._cleanup_stale_temp_files` 未被任何代码调用，却会无条件 `glob(".tmp-*")` 删除目录内临时文件 ——
这可能误删**另一个进程/线程正在写入**的临时文件，导致对方 `os.replace` 失败。
它既无调用方，又存在误删风险，因此**整段移除**，不做"盲扫"式接入。保留的清理逻辑仅限
`atomic_write_bytes` 异常分支中对**自己创建的那一个** `tmp_path` 的删除（精确、安全）。

---

## 5. 给父代理的整合事项

1. **`[translation]` 新增键需进 `core/config.py` 与 `config.example.ini`**：`max_chars=12000`、`checkpoint_enabled=true`、`strict_ids=false`、`progress_ttl_sec=604800`；`parallel` 默认改 2。
2. **job_config 白名单（DAG 代理）**：建议新增 `parallel`、`batch_size`、`max_chars`、`timeout`/`timeout_sec`、`disable_proxy`、`request_interval`、`checkpoint_enabled`、`strict_ids`、`progress_ttl_sec`。
3. **runtime 集成（6e92e3b6）**：建议补传
   ```python
   run_translate(..., job_config=task_cfg, cancel_check=drain_or_lease_lost,
                 job_id=ctx.job_id, metrics=app.state.metrics)
   ```
   不传也可运行（向后兼容），但 `cancel_check`、`job_id`（幂等键跨 attempt 稳定）、`metrics` 与新增键只有传入才生效。
4. **`config.example.ini` 的 `parallel = 16` 需改为 2**（本批按要求未改该文件）。
5. **产物级 fencing 接口已就绪（P0，见 6quater）**：`run_translate` 新增可选 `checkpoint_path` / `defer_copy_back` / `checkpoint_publish`；`atomic.atomic_write_text_fenced` + `StaleWriteRejected` 供 repo helper 使用。runtime 需实现"staging 输出 + 事务内校验租约 + promotion"，执行器不参与回写。

---

## 6. 检查点 TTL 存储建议（供 runtime owner 整合）

### 现状（已核实代码）
- 配置里**已存在** `[runtime] progress_ttl_sec`（`core/config.py:243`，默认 3600），但它当前只服务于**内存 `ProgressStore`**（`ProgressStore(settings.runtime.progress_ttl_sec)`），与磁盘上的翻译检查点文件无关。
- 翻译检查点文件 `<output>.progress.json` 位于 `artifacts/<job_id>/translate/` 下，**没有独立的 TTL 存储**。
- `_run_artifact_cleanup_once`（`service/runtime.py:1132`）按 `artifact_cleanup_statuses`（默认 `succeeded`）**整目录 `shutil.rmtree`**，间隔 `artifact_cleanup_interval_sec`（默认 3600，最小 60）。
- 关键结论：**job 一旦 success，下一轮 artifact 清理就会连同 `translate/*.zh.srt.progress.json` 一起删掉**。我实现的"成功后保留检查点"在默认配置下**实际只会存活到下个清理周期（≤1h）**，这正好近似 `[runtime] progress_ttl_sec=3600` 的语义，但**是巧合，不是设计**。
- 我新增的 `[translation] progress_ttl_sec`（默认 604800）目前只用于成功后 `os.utime` 刷新 mtime + 日志，**没有被任何清理器读取**。

### 已定方案（父代理 2026-10-22 决策，实施结论）
> 以下是本批的**交付结论**，不再讨论替代方案。

1. **保留 `[translation] progress_ttl_sec` 作为翻译检查点独立 TTL**（默认 604800）。它生效：
   - 翻译成功后由 `_touch_checkpoint_retention` 用 `os.utime` 打点（已实现）；
   - runtime 的 artifact 清理对该 mtime 做 TTL 判定，**未过期则延迟清理成功 job 目录**。
2. **检查点路径保持 SPEC 规定的 job 目录**（`artifacts/<job_id>/translate/<stem>.zh.srt.progress.json`），**不移出** job 目录。
3. **成功目录清理改为延迟执行**：job 状态为 `succeeded` 时，若目录内存在未过 `progress_ttl_sec` 的检查点，则本轮跳过该目录；待检查点过期后再按原有 `artifact_cleanup_statuses` 语义整目录删除。
4. 效果：同一 job 在 TTL 窗口内 retry 可复用检查点、只补未完成批次；TTL 过期后复查则整部重翻。

### runtime owner 需落地的接口约定
- 只读判定的输入：目录内 `*.progress.json` 的 `st_mtime`（本批已用 `os.utime` 打点，无需新增文件或 DB 列）。
- 判定位置：`_run_artifact_cleanup_once` 在 `is_job_completed_for_cleanup` 通过后、`shutil.rmtree` 之前插入"检查点 TTL 未过期则跳过"。
- 建议日志字段：`job_id`、`checkpoint_path`、`age_sec`、`ttl_sec`、`deferred=true`。
- 配置读取：`TranslationSettings.progress_ttl_sec`（`common.resolve_translate_settings`）；若 runtime 侧需要默认值，与 `[translation] progress_ttl_sec` 保持一致（604800）。
- `progress_ttl_sec=0` 语义建议为"不延迟"（等价于立即按原逻辑清理）。
- 该实现属 runtime owner，本批未改动 `service/runtime.py`。

---

## 6quater. 产物级 fencing（P0）：翻译侧接口

**背景**：旧 worker 复活后可覆盖新 attempt 的正式字幕、以及可提前 copy_back —— 这是 SPEC 中"结果写回 fencing"在**产物层面**的缺口。

### 设计职责划分
| 层 | 职责 |
|---|---|
| runtime | 每 attempt 使用**唯一 staging output**；在事务内校验 `lease_owner`/`attempt` 后 **promotion** 到正式路径；promotion 成功后负责 copy_back |
| repo helper | 提供"BEGIN 事务内确认 owner/attempt 后执行 atomic write"的 helper，返回是否接受本次写入 |
| executor（本批） | **不得提前 copy_back**；检查点走 fenced 发布；写正式产物前再做一次取消检查 |

### 新增接口（全部可选、向后兼容）
```python
run_translate(
    ...,
    checkpoint_path: Path | None = None,              # 默认 <output>.progress.json（行为不变）
    defer_copy_back: bool = False,                    # True 时不回写，由 runtime promotion 后负责
    checkpoint_publish: Callable[[Path, str], bool] | None = None,  # 租约 fenced 检查点发布
)
```

```python
# executor/atomic.py
class StaleWriteRejected(RuntimeError):  # code = "fenced_stale_write"
    ...

def atomic_write_text_fenced(
    path, text, publish: Callable[[Path, str], bool] | None = None, *, encoding="utf-8"
) -> Path:
    """publish 返回 False → 抛 StaleWriteRejected 且不落盘；None → 退化为普通原子写。"""
```

### 语义约定
1. **`checkpoint_path`**：runtime 传 canonical 稳定路径，使不同 attempt 的 staging 输出共享同一检查点 → 跨 attempt 续跑、不重复计费。
2. **`defer_copy_back=True`**：`run_translate` 完成后只写 `output_zh_srt`（staging），**不触碰**视频目录与 copy_back 目录。
3. **`checkpoint_publish`**：每次写检查点都调用回调；回调在事务内确认所有权，返回 `False`（或抛异常）即视为 stale → executor 立即 `_aborted=True` 并抛 `TranslateCancelledError("translate_fenced_stale")`，**不再继续产出**，正式产物不会被写。
4. **写正式产物前取消检查**：`_raise_if_cancelled(cancel_check)` 在 `_dump_srt` 之前执行，失租后不得覆盖既有正式字幕。

### runtime 落地建议（未改动 runtime）
```python
def publish(path, text) -> bool:
    with repo.transaction() as tx:                      # BEGIN IMMEDIATE
        if not tx.lease_valid(task_id, worker_id, attempt):
            return False                                # stale：executor 会中止
        atomic_write_text(path, text)                   # 事务内落盘
        return True

run_translate(
    staging_zh, ja_srt, config_path,
    timeout_sec=..., input_video_path=video,
    checkpoint_path=canonical_ckpt,      # 稳定路径，跨 attempt 续跑
    defer_copy_back=True,                # promotion 后再回写
    checkpoint_publish=publish,
    cancel_check=lambda: repo.lease_lost(task_id, worker_id, attempt),
    job_id=ctx.job_id,
)
```
promotion 由 runtime 在确认租约后执行（`os.replace(staging, official)` + copy_back），执行器不参与。

### 测试覆盖（新增 8 项）
| 用例 | 覆盖点 |
|---|---|
| `test_atomic_write_fenced_rejects_stale_writer` | stale 写入不覆盖正式产物 |
| `test_atomic_write_fenced_accepts_fresh_writer` | 正常写入 |
| `test_atomic_write_fenced_without_publish_is_plain_write` | 未给回调时向后兼容 |
| `test_checkpoint_save_uses_fenced_publish` | `_save_checkpoint` 透传 publish，拒绝时不落盘 |
| `test_run_translate_uses_explicit_checkpoint_path` | 检查点写到指定路径而非 output 旁边 |
| `test_run_translate_resumes_from_canonical_checkpoint` | 不同 staging 输出 + 同一 canonical 检查点 → **0 请求**续跑 |
| `test_run_translate_defer_copy_back_skips_writeback` | 不回写视频目录/copy_back 目录 |
| `test_run_translate_fenced_checkpoint_rejection_aborts` | 拒绝即中止，不产出正式 zh.srt、不生成检查点 |
| `test_run_translate_cancel_check_blocks_final_output` | 失租后不覆盖已有正式字幕 |
| `test_run_translate_default_copy_back_still_works` | 默认行为不变 |

---

## 6bis. 受控真实上游翻译 smoke（API smoke，非完整 E2E）

> **性质声明**：本次仅验证"真实上游可调用 + 检查点可复用"这两条链路事实。
> **不构成**翻译质量评估，**不代表** 2 小时完整媒体通过，**也不是**完整 E2E。

### 受控条件
| 项 | 值 |
|---|---|
| 输入 | `tmp/real-media-hardened/sample_30s.ja.srt`（父代理产出的 CPU 基线，5 段） |
| 凭据 | 原 `whisper-stt/config.ini`（未修改、未回显 `api_key`） |
| 输出 | `tmp/real-media-hardened/api-smoke/sample_30s.zh.srt` |
| copy_back | 仅 `tmp/real-media-hardened/api-smoke/` |
| `input_video_path` | `.../api-smoke/sample_30s.mp4`（占位文件，避免回写原视频目录） |
| job_config（仅本次） | `retry=1`、`timeout=60`、`request_interval=0`、`parallel=2` |
| 总 task timeout | 120s |
| `job_id` | `real-smoke-30s` |
| 上游 | OpenRouter（`deepseek/deepseek-v3.2`） |

### 第一次运行：真实翻译
| 指标 | 结果 |
|---|---|
| status | **ok** |
| HTTP 请求数 | **1** |
| HTTP 状态码 | `[200]`（无 429/4xx，未触发任何重试） |
| 单请求耗时 / 总墙钟 | 17479 ms / **17.49 s** |
| ja 条数 → zh 条数 | 5 → **5**（无丢行） |
| 末条时间戳 | `00:00:26,540 --> 00:00:29,540`（ja/zh 一致） |
| 检查点批数 | **1** 批（`0/0`），done=**1** |
| 真实 usage | `prompt_tokens=321`，`completion_tokens=358`，`total_tokens=679`，`cost=0.0001778616`（含 `reasoning_tokens=251`） |

### 第二次运行：检查点复用验证
注入 `post_func` 为"一旦被调用即抛 `AssertionError`"，仍使用**相同 source 与相同 config**：

| 指标 | 结果 |
|---|---|
| status | **ok** |
| **HTTP 请求数** | **0** ✅（未触碰网络） |
| 墙钟 | **0.009 s** |
| 检查点 | 1 批、done=1（复用后重写 mtime，内容为同一 source_sha256） |
| 输出 | 5 段，末条 `00:00:26,540 --> 00:00:29,540` |

**结论**：检查点按 `source_sha256 + 切分配置` 正确复用，重跑 0 请求、不重复计费。

### 产物与保密
- 产物：`tmp/real-media-hardened/api-smoke/{sample_30s.ja.srt, sample_30s.zh.srt, sample_30s.zh.srt.progress.json, sample_30s.mp4(占位)}`
- 已核查：输出与检查点中**无 `api_key`/`Bearer`/token 字样**；`tmp/` 未进入 git 跟踪。
- 失败路径设计：仅记录 `error_class` 与 HTTP 状态码，不打印异常全文/URL。

### 明确未做
- 未做翻译**质量**评估（无人工/参考译文比对，仅 5 段短样本）。
- 未跑 2 小时完整媒体；未跑 WhisperX 真实媒体。
- 未验证 429/5xx 在真实上游下的重试行为（本次一次即成功），该行为仅有单测覆盖。

---

## 6quinquies. P1 修复：C5 部分降级死代码 + C1 失败收尾丢检查点

### 复现（受控，非推测）
| 缺陷 | 复现方式 | 修复前表现 |
|---|---|---|
| **C5**：`_call_translate_api` 任一 missing 即抛且**丢弃 mapping** | 2 条源、每轮只返回 id1、retry=2 | `RuntimeError`，2 次请求都是整批 `[1,2]`，zh.srt 不存在，**id1 已译结果丢失**，未回退日文 |
| **C1**：`_run_batch` 失败置 `_aborted` → `_commit_batch` 拒绝在途成功 | 确定性时序：B 延迟 200ms 返回成功、A 在 50ms 失败 | 检查点 `{"0/0":false,"0/1":false}`，B 的译文 `{}` **未保存** |

### 修复
1. **C5 真实路径**
   - `TranslatePartialIdsError` 新增 `partial: dict[int,str]`，随异常带出已解析子集（原先被丢弃）。
   - `_translate_batch` 在 `except` 分支先 `accepted.update(exc.partial)`，再只对缺失 id 续请求。
   - 通用重试分支中 `ids_mismatch` 视为可降级（`partial_only = isinstance(exc, TranslatePartialIdsError)`），
     避免"补缺失后又少返回"被误判为整批失败。
   - 最终仍缺的 id 回退**日文原文**，不丢行。
2. **C1 失败收尾**
   - 新增 `_cancelled` 与 `_aborted` 分离：
     - `_aborted`：本次运行已失败，**不再派发新批次**（在途批次仍可落检查点）；
     - `_cancelled`：失租/停机取消、fenced stale，**连在途批次也禁写**。
   - `_commit_batch` 只检查 `_cancelled`；`_run_batch` 仅在取消类异常时置 `_cancelled`。

### 幂等键（C6）修正
- 完整批次沿用 SPEC 的 `batch_id`（`<window>/<part>`），同 payload 重试 key 稳定。
- 补缺失时 payload 已变化，改用子批次 id：`<batch_id>#missing-<id,id>`，**key 随之变化**，
  防止支持幂等的上游返回旧 payload 的缓存响应。
- 新增 `_sub_batch_id(batch_id, ids)`，不引用参数外的自由变量。

### 新增回归测试（4 项，真实 `_call_translate_api` 路径，非 mock 返回 mapping）
| 用例 | 断言 |
|---|---|
| `test_real_api_partial_subset_keeps_translated_and_requests_only_missing` | 请求序列 `[[1,2],[2]]`，zh.srt 同时含 zh-1 与 zh-2 |
| `test_real_api_partial_exhausted_keeps_source_text` | 永远只返回 id1 → 2 行不丢，id2 回退日文原文，有 `translate_partial` 告警 |
| `test_partial_subset_uses_distinct_idempotency_key` | 完整批 key ≠ 子批 key；同子集 key 稳定 |
| `test_inflight_success_after_failure_still_commits_checkpoint` | A 失败后 B 仍 `done=true` 且译文已持久化；**重跑只请求 [1]** |

### 验证
```
py_compile                       -> OK
ruff --select E9,F（我的文件）    -> All checks passed! exit 0
pytest 我的 72 项                 -> 72 passed
```
> 注：`whisper_stt_service/service/launcher.py:160 F841` 属其他代理新增文件，不在本批范围。


---

## 6sexies. CLI 翻译（`whisper_stt/translate_srt_ja_to_zh.py`）差距评估（只读，未改实现）

> 本节为**评估与方案**，不含实现改动；等 scope 决策后再动手。

### 已核实的差距（逐条对照服务端 `executor/translate.py`）
| 项 | CLI 现状（行号） | 服务端行为 | 影响 |
|---|---|---|---|
| C.6 重试策略 | `translate_batch_with_retry:237-249` 对**所有异常**重试 | 4xx（含 429）不重试，仅 5xx/超时/连接/解析/id 不匹配重试 | CLI 会把 401/400 重试 N 次，**无意义计费** |
| C.4 检查点校验 | `main:396-399` 直接读 `progress.json` 为 id->text，**不校验 source** | `version + source_sha256 + chunk/batch/max_chars` 校验，不符即全量重算 | ja.srt 变化后**复用错位译文** |
| C.3 batch_size | `main:402` 只用 `_split_entries_by_time_window` | 三重切分（时间窗 + batch_size + max_chars） | `--batch-size` **被解析却完全未使用** |
| C.7 原子写 | `dump_srt:49-57` 直接 `open(w)`；progress 写 `main:458` 也非原子 | `atomic_write_text` | 中断留半截 zh.srt / 半截 json |
| C.5 部分 id | `_call_api:218-221` 缺 id 直接抛 ValueError | 保留已返回项、只补缺失、最终缺的回退日文 | CLI 整批丢弃已得译文 |
| C.6 幂等键 | 无 | 每请求带 `Idempotency-Key` | 上游去重/计费核算缺失 |
| C.1 并发 | 有 `ThreadPoolExecutor` + `parallel` | 一致（默认 2） | 此项基本对齐 |

### 最小安全复用方案（推荐，保留全部旧函数）
把 `main()` 的**编排部分**改为调用统一引擎，旧函数**原样保留**（不删注释/docstring），仅标注 deprecated：

```python
# 保留：parse_srt / dump_srt / _call_api / translate_batch_with_retry / _split_entries_by_time_window ...
def _run_engine(args, config_path, timeout, parallel, batch_size, chunk_minutes,
               retry, request_interval, disable_proxy) -> None:
    """CLI 编排委托给服务端统一引擎（唯一实现，避免第二份逻辑）。"""
    from whisper_stt_service.executor.translate import run_translate
    run_translate(
        args.input, args.output, config_path=config_path,
        timeout_sec=timeout,
        input_video_path=args.output.parent,   # CLI 无视频
        defer_copy_back=True,                  # 显式不回写任意目录
        job_config={
            "parallel": parallel, "batch_size": batch_size,
            "chunk_minutes": chunk_minutes, "timeout": timeout,
            "retry": retry, "request_interval": request_interval,
            "disable_proxy": disable_proxy,
        },
        job_id=cli_job_id,
    )
```

### 接口映射与代价
| CLI 参数 | 引擎参数 | 备注 |
|---|---|---|
| `--input/--output` | `input_ja_srt/output_zh_srt` | 直接对应 |
| `--config` | `config_path` | 直接对应 |
| `--base-url/--api-key/--model` | **无直接参数** | 见凭据处理 |
| `--batch-size/--chunk-minutes/--timeout/--retry/--parallel/--request-interval/--disable-proxy` | `job_config` 同名键 | job_config > [translation] |
| `--sleep` | **无对应** | 引擎用 `request_interval` 节流；需保留为 no-op 或告警 |

**凭据处理（不得落临时文件）**：引擎通过 `config_path` 读 `[llm]`。若用户用 `--base-url/--api-key/--model` 覆盖，
**不能**写临时 ini（会把 key 落盘）。两个安全选项：
1. **推荐**：给 `run_translate` 增加可选 `llm_overrides: dict|None`（仅内存传递），`_load_llm_profiles` 合并覆盖；
2. 或 CLI 检测到命令行覆盖时报错，提示写进 config（不引入新参数）。

### 代价估算
- 选项 1（引擎 + `llm_overrides`）：`translate.py` 约 +15 行，CLI `main` 编排约 -60/+40 行；旧函数全部保留；**新增 CLI 测试 4-6 项**。
- 风险：CLI 的 `progress.json` 结构从 `id->text` **改为**引擎结构（`version/source_sha256/batches`）；旧 CLI 进度文件**失效重算**（需写进 release note）。
- 行为变化：4xx 不再重试、缺 id 回退日文、写盘原子 → 均为改进，但属破坏性变更。

### 关于文档漂移（需交付 owner 决策）
README.md:26 / README.zh-CN.md:25 的 **Translation hardening** 泛称，若本轮决定 CLI 不统一，则必须明确限定服务端：

> **Translation hardening (service executor)**: concurrency capped at 2, per-batch checkpoint resume with `source_sha256`, atomic writes, missing-id fallback, 4xx never retried, `Idempotency-Key`.
> The standalone CLI (`whisper_stt/translate_srt_ja_to_zh.py`) still uses its legacy loop and is not covered by these guarantees.

否则即为虚称脚本模式。**本评估不改 README**（属交付 owner）。

### 结论
- SPEC 批次 4 的文件列表只有 `executor/translate.py`、`executor/common.py`、`executor/atomic.py`（+ 新增测试），字面范围**仅含 executor**。
  按此范围：本轮**不动 CLI 实现**，仅按上面措辞修正 README 精确区分，把 CLI 统一列为后续独立任务。
- 若要求 CLI 同等保证：采用"最小安全复用"方案（含 `llm_overrides`），并把旧进度文件失效写进 release note。

---

## 7. 未完成 / 需关注

- 已做：受控真实上游 API smoke（见 6bis，1 请求、17.49s、检查点复用 0 请求）。**仍未做**：2h 完整媒体 E2E、真实媒体 WhisperX、翻译质量评估。
- 脚本模式三个入口（`run_video_ja_srt.sh` / `run_video_ja_srt_whisperx.sh` / `run_video_ja_zh.sh`）已全部统一 wav 契约与共享 venv 解析；未做真实媒体的脚本模式端到端运行（父代理正跑基线，本批未重复）。
- 检查点 TTL 的实际删除动作见第 6 节建议，由 runtime owner 整合。
- 我的全部用例（50 项：36 翻译 + 12 脚本模式 + 2 既有 copy_back）当前全绿；全量 `pytest tests/unit` 的失败项随其他代理进度变化，最后一次运行为 317 passed / 4 failed，4 项均属可观测性代理的 DB readiness 测试。

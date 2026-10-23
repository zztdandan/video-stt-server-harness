# Whisper STT 操作手册（Runbook）

## 1) 环境前置

- 使用仓库根目录共享环境：`/home/base/repo/video-stt-whisper-server/.venv`
  （子仓库与 `.worktrees/*` **不得**创建独立 venv，所有 Python 命令都显式指向该解释器）。
- 推荐直接在任意目录用绝对路径调用：
  `/home/base/repo/video-stt-whisper-server/.venv/bin/python`、
  `/home/base/repo/video-stt-whisper-server/.venv/bin/uvicorn`。
- 若使用 `uv`，必须先固定项目环境，避免 uv 在工作树里自动建 venv：
  `export UV_PROJECT_ENVIRONMENT=/home/base/repo/video-stt-whisper-server/.venv`。
  需要同步依赖时用 `uv pip install --python /home/base/repo/video-stt-whisper-server/.venv/bin/python <pkg>`，
  **不要**在工作树里直接执行 `uv sync` 重建环境（会替换显卡依赖）。
- 确保系统可用：`ffmpeg`、`ffprobe`。
- 安全默认值（v0.5.0）：`[security] require_token = true` 且 `api_token` 为空或为占位符时**拒绝启动**。
  首次运行请先设置真实 token（建议 `≥16` 字符；代码只拒绝空/占位 token，短 token 仅告警），或显式
  `require_token = false` 自行承担风险。

## 2) 视频 -> 日语字幕（ja.srt）

使用一键脚本（内部即“先 ffmpeg 抽 16k mono wav，再转写”；v0.4.0 及以前是可选预抽，
v0.5.0 起服务模式固定为 wav 契约，脚本模式默认 `PREEXTRACT_WAV=true`）：

```bash
INPUT_VIDEO="/abs/path/to/video.mp4" \
OUTPUT_SRT="/abs/path/to/video.ja.srt" \
DEVICE="auto" \
COMPUTE_TYPE="auto" \
PREEXTRACT_WAV="true" \
KEEP_TEMP_AUDIO="false" \
PROGRESS_EVERY="40" \
bash whisper-stt/scripts/run_video_ja_srt.sh
```

### 参数建议

- GPU：`DEVICE=cuda COMPUTE_TYPE=float16`
- CPU：`DEVICE=cpu COMPUTE_TYPE=int8`
- 若排查解码问题：保留中间音频 `KEEP_TEMP_AUDIO=true`
- 服务模式与脚本模式一致：**ASR 只吃 extract 产出的 wav**，不再直接读原视频。

## 3) 日语字幕 -> 中文字幕（zh.srt）

### 3.1 脚本模式

```bash
/home/base/repo/video-stt-whisper-server/.venv/bin/python \
  whisper-stt/whisper_stt/translate_srt_ja_to_zh.py \
  --input "/abs/path/to/video.ja.srt" \
  --output "/abs/path/to/video.zh.srt" \
  --base-url "<LLM_BASE_URL>" \
  --api-key "<YOUR_API_KEY>" \
  --model "<LLM_MODEL>" \
  --batch-size 200 \
  --parallel 2 \
  --request-interval 1 \
  --retry 6 \
  --timeout 240
```

- `--parallel` 默认 **2**（由 16 下调）；并发上限本身就是限流手段。
- 示例里的 `base_url` / `model` 用占位符：真实上游与模型名以本机 `config.ini` 的 `[llm]` 段为准，不要写进文档。
- `--request-interval` 是“批次派发最小间隔”，0 表示关闭。

### 3.2 服务模式配置（`config.ini` 的 `[translation]`）

```ini
[translation]
parallel = 2                 # 并发上限；旧配置里的 16 会被读成 16，请改成 2
batch_size = 200             # 每批条目上限
max_chars = 12000            # 每批字符上限（新增）
chunk_minutes = 20           # 时间窗
request_interval = 1.0       # 批次派发最小间隔，0 = 关闭
retry = 10
timeout = 240
disable_proxy = true
copy_back = __video_dir__
checkpoint_enabled = true    # 新增：逐批检查点续跑
strict_ids = false           # 新增：true 时缺 id 直接失败
```

> 取值以文件为准：`config.example.ini` 的默认值（也是代码内默认）为
> `parallel=2`、`batch_size=200`、`max_chars=12000`、`chunk_minutes=20`、`timeout=240`、`retry=10`。
> 本机 `config.ini` 可能覆盖其中任意值，请以实际生效配置为准，不要假设一定是默认值。
> 检查点保留秒数是 `[translation] progress_ttl_sec`（示例 604800），与 `[runtime] progress_ttl_sec`
> （内存进度 TTL，示例 3600）不是同一项，升级时不要混同。

配置优先级：`job_config.translate` > `[translation]` > 代码默认值。

> 发布提示：升级到 v0.5.0 后必须把 `parallel` 从 16 改为 2，否则仍按 16 并发。

## 4) 输出日志解释

- `EXTRACT ...`：ffmpeg 抽音频进度。
- `TRANSCRIBE ...`：Whisper 转写进度。
- `DISPATCH ...`：翻译请求派发序列。
- `RETRY ...`：翻译请求失败重试（附 `batch_id`、`attempt`、`error_class`、`elapsed_ms`）。
- `TRANSLATE ...`：翻译总体完成率与 ETA。
- 服务日志：`log_root/service.log`（轮转 10MB × 5），级别由 `WHISPER_STT_LOG_LEVEL`（默认 INFO）控制；
  `WHISPER_STT_LOG_JSONL=1` 输出 JSON 行。请求带 `X-Request-ID`（未传则自动生成并在响应头回写）。

## 5) 标准执行顺序（建议）

1. 先裁 2-3 分钟短片联调（看三段进度都正常）。
2. 短片验证后，再跑长片全量。
3. 对比 `ja.srt/zh.srt` 行数一致性。
4. 抽查头尾字幕内容与时间戳。

## 6) 任务生命周期运维接口（v0.5.0）

所有接口需带 `-H "X-API-Token: <你的 token>"`（鉴权开启时）。

| 接口 | 用途 |
|---|---|
| `POST /jobs` | 入队（DAG 语义、路径白名单、扩展名白名单、token 前置校验） |
| `GET /jobs/{job_id}` / `GET /jobs/{job_id}/progress` | 查询 job 详情与实时进度 |
| `GET /jobs/by-path?video_path=...` | 按视频路径查最近一条 job（v0.5.0 修复：不再被 `/jobs/{job_id}` 吞成 404） |
| `POST /jobs/{job_id}/retry` | **仅 failed job**：把 failed/blocked 任务重置为 queued（attempt=0），job 回 queued，返回受影响 task 数 |
| `POST /jobs/{job_id}/cancel` | **仅 queued / 全部任务未开始**：置 `cancelled` 并释放路径占用；运行中取消不在支持范围 |
| `POST /jobs/{job_id}/archive` | 显式归档释放路径占用 |
| `GET /queue/summary` | 各阶段队列计数（含 `blocked`）、worker 视图、`throughput`（最近 5 分钟完成数/阶段） |
| `POST /admin/shutdown` / `GET /admin/shutdown/status` | 有界 drain 停机：状态含 `drain_deadline_at`、`inflight`、`blocked` |

任务状态机（v0.5.0）：

```text
queued ──claim──> claimed ──成功──> succeeded
   │                 │
   │                 ├─失败──> failed ──(级联)──> 下游 blocked
   │                 └─租约过期──> queued(attempt+1) / failed(超预算)
   └─cancel──> cancelled
```

- `blocked`、`cancelled` 是新增终态；`jobs.status` 仍是 `queued/running/succeeded/failed`。
- 历史 job 若 DAG 不含 extract（或同时含两个 ASR 阶段），`retry` 会被新校验拒绝（409），需按新 DAG 重新入队。

## 7) 健康检查与指标

| 端点 | 说明 |
|---|---|
| `GET /healthz` | 进程存活 + DB 可查询（`SELECT 1`） |
| `GET /readyz` | 配置完整、DB 可写、model_path 存在、artifact_root 可写；不满足返回 503 + 明细 |
| `GET /metrics` | Prometheus 文本；`metrics_enabled=false` 时不注册（404） |

关键指标：

- `whisper_stt_tasks_claimed_total{stage}`、`whisper_stt_tasks_finished_total{stage,result}`
- `whisper_stt_task_duration_seconds{stage}`（histogram）
- `whisper_stt_queue_depth{stage,status}`（采集时读 DB）
- `whisper_stt_translate_batches_total{result}`、`whisper_stt_translate_retries_total`
- `whisper_stt_model_cache_hits_total` / `whisper_stt_model_cache_misses_total`

> 注意：`/healthz`、`/readyz`、`/metrics` 与其他业务接口一样受 `X-API-Token` 保护。

示例：

```bash
curl -s -H "X-API-Token: $TOKEN" http://127.0.0.1:18000/healthz
curl -s -H "X-API-Token: $TOKEN" http://127.0.0.1:18000/readyz
curl -s -H "X-API-Token: $TOKEN" http://127.0.0.1:18000/metrics | grep whisper_stt_
```

## 8) 交付前核对清单（v0.5.0 实现/P1/三次 CI 绿完成；tag 已 push，父将重指最终文档提交）

> 截至 2026-10-24，v0.5.0 实现、七项 P1、连续三个远端绿色 run、main FF 与 annotated tag 已完成；
> 父只需把 tag 重指到本次最终文档提交并提交该文档。真实 2h/GPU/供应商轮换不能以本地结果替代。

### 8.1 本地可验证门禁

- [x] 全量单测：`/home/base/repo/video-stt-whisper-server/.venv/bin/python -m pytest -q`
  （2026-10-24 本地复核：532 passed / 5 deselected；最终提交前如需再跑一次并记录提交号）
- [x] 语法门禁：`python -m compileall -q` 覆盖跟踪与新文件（2026-10-23 本地 111 个 py 文件通过）
- [ ] 锁一致性：child/root 均用公共 PyPI 默认源；在空 `XDG_CONFIG_HOME`、无 `UV_INDEX`/`UV_DEFAULT_INDEX`
  的干净环境跑 `uv lock --check --python 3.10`（child）与 root `uv lock --check --python 主.venv`，exit 0；
  child/root 的 `pypi.tuna.tsinghua.edu.cn` 计数必须为 0，torch/torchaudio 仍为 `2.8.0+cu128`
- [ ] secret 扫描：`bash .github/scripts/secret_scan.sh` + `secret_scan_selftest.sh`
- [ ] CI 启动冒烟：显式注入测试 token；错误 token=401、queue/health=200、缺失 model 的
  `/readyz`=503 且不创建 `model_path`
- [x] 七项 P1（copyback 真 sink、checkpoint 固定身份、finally compare-and-remove、stop/drain
tuple-fenced rollback、promotion 异常收敛、atomic fenced 单写、worker boot nonce 防 ABA）已由官方
实施代理修复，并经 Sol 用原真 SQLite/文件反例及跨 FS copyback、symlink 替换独立复验关闭
- [ ] 文件存在：`*.ja.srt`、`*.zh.srt`；行数一致；末尾时间戳不超过媒体总时长
- [ ] 翻译进度文件可用于续跑：`*.zh.srt.progress.json`
- [ ] `config.example.ini` 与本机 `config.ini` 的 `[translation] parallel = 2`
- [ ] 配置新键同步：`[translation] progress_ttl_sec`（检查点 TTL，示例 604800）与
  `[runtime] progress_ttl_sec`（内存进度 TTL）是两项，不得混同；本机
  `whisper-stt/config.ini` 已补前者且保留原 `chunk_minutes=30` / `retry=6` / token 值，
  工作树不复制含密钥的 `config.ini`
- [x] 根依赖入库：主仓库 `pyproject.toml` / `uv.lock` / `.gitignore` 已随 **ee1cf98** 提交；
  root 清单含 `prometheus-client==0.26.0`，root lock 已归一公共 PyPI，`uv lock --check` 通过
- [ ] 主 docs 入库清单：`docs/00-index.md`–`docs/04-troubleshooting.md`、
  `docs/research/vad-diarization-upgrade.md`、`docs/superpowers/specs/2026-10-22-whisper-stt-reliability-and-translation-hardening-spec.md`、
  `docs/superpowers/plans/2026-10-22-hardening-execution.md` 及本轮其他新增 spec/plan/execution 文件；
  不含 `docs/hf-token.md`、`*.token`、`token.env`、`.env` 等密钥文件

### 8.2 源码整合与提交（父代理统一执行）

- [x] 工作树实现的源码已合回子仓库（原子仓库）`whisper-stt/`，保留用户最初的 3 处修改与既有注释/docstring；`main` 已 FF 到发布文档提交（当前 **f495fe0**）并 push，本次最终文档由父再 FF
- [x] 合入前对比主仓库子模块与工作树，未把 `config.ini` / 真实媒体路径 / 密钥带入
- [x] 在三次发布提交上分别取得**远端 CI 绿灯**（连续绿色：2623545 → 39996457310；5e67c7b → 39997343133；c88cc80 → 39997953791，另有 39997946922/39997927908 同为成功。此前 run 39981535390 锁失败、run 39995654486 clean-runner 用例失败仅作历史记录）
- [x] 版本号 `0.5.0` 一致；annotated `v0.5.0` tag 已 push 并指向本次最终文档提交；父在最终文档提交后重指
- [x] 历史 `v0.4.0` tag 已补 push 到 **b029d07**（此前远端缺失，已修补该发布缺口）

### 8.3 外部/真实环境证据（不可用本地 fake 代替）

- [ ] 真实 2 小时样本端到端跑通，记录各阶段墙钟、翻译批次数、请求数、token 消耗
- [ ] 显存峰值（`nvidia-smi` 采样）
- [ ] 中途 `kill -9` 后重启，验证只补未完成批次
- [ ] 供应商侧轮换曾落盘的 HF token 与 LLM API key（本地删除/忽略不等于 provider 端撤销）

### 8.4 已收集的真实 smoke（仅短片，不等于全量验收）

- 真实 LLM 接口的 5 段字幕翻译 smoke：1 次请求、679 tokens、cost 0.0001778616、耗时 17.49s；
  复跑命中检查点：0 请求、0.009s。证明受限并发 + 检查点续跑 + 真实上游在短片可用，但样本很小。
- 2026-10-23 复核：`tests/e2e/video_paths.txt` 的 4 条 `/srv/media/...` 路径仍全部不存在，
  `/srv/media/jellyfin` 为空；本机只有 30s / 180s 样本，`nvidia-smi` 退出 255 且报
  `NVML GPU access blocked by OS`。以上 2h/显存/`kill -9` 三项均未执行。

### 8.5 追踪清单（2026-10-24 实测）

主仓库根依赖（已随 ee1cf98 提交，含 prometheus-client 与公共 PyPI 锁归一）：

- `pyproject.toml`
- `uv.lock`
- `.gitignore`

主 docs（已随 ee1cf98/4ee839d 提交；本次最终定稿仍需父提交）：

- `docs/00-index.md`、`docs/01-project-memory.md`、`docs/02-operations-runbook.md`、
  `docs/03-architecture-and-key-features.md`、`docs/04-troubleshooting.md`
- `docs/research/vad-diarization-upgrade.md`
- `docs/superpowers/specs/2026-03-31-asr-translation-roadmap.md`
- `docs/superpowers/specs/2026-04-01-job-dag-planning-design.md`
- `docs/superpowers/specs/2026-04-05-readable-job-task-id-design.md`
- `docs/superpowers/specs/2026-04-05-whisperx-stage-design.md`
- `docs/superpowers/specs/2026-10-22-whisper-stt-reliability-and-translation-hardening-spec.md`
- `docs/superpowers/plans/2026-03-31-long-context-translation-and-model-roadmap.md`
- `docs/superpowers/plans/2026-04-02-job-dag-planning-implementation-plan.md`
- `docs/superpowers/plans/2026-10-22-batch1-lifecycle-wal-execution-record.md`
- `docs/superpowers/plans/2026-10-22-hardening-execution.md`
- `docs/superpowers/executions/2026-10-22-batch4-translation-hardening.md`
- `docs/superpowers/executions/2026-10-23-sol-final-review-round3.md`
- `docs/superpowers/executions/2026-10-23-sol-final-review-round4.md`

工作树需保留的用户初始修改（合回子仓库时不得覆盖）：

- `.gitignore` 的 `.codegraph/`
- `config.example.ini` 的 `[llm_fallback]`、`chunk_minutes=20`、`retry=10`、`extract_timeout_sec=3600`
- `whisper_stt_service/executor/translate.py` 的 LLM profile / fallback 选择逻辑

## 9) 测试与 CI

```bash
cd /home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening
# 单元测试（默认跳过真实媒体与 E2E）
/home/base/repo/video-stt-whisper-server/.venv/bin/python -m pytest -q

# 真实媒体手工用例（需要本地模型、素材与真实 LLM 配置）
WHISPER_STT_REAL_MEDIA=1 \
  /home/base/repo/video-stt-whisper-server/.venv/bin/python -m pytest \
  tests/manual/test_real_media.py -m manual -v
```

真实媒体用例可用环境变量覆盖素材位置：`WHISPER_STT_REAL_OUTPUT_DIR`（默认 `<repo>/output`）、
`WHISPER_STT_REAL_VIDEO`（默认 `sample_30s.mp4`）、`WHISPER_STT_MODEL`、`WHISPER_STT_CONFIG`。

CI（`whisper-stt/.github/workflows/ci.yml`）：

> run 39981535390 @ bba96a0 在提交锁校验失败（锁含宿主机 TUNA 镜像）；
> run 39995654486 @ 66678d0 锁校验通过，但 2 个 clean-runner 用例失败（service.log 创建顺序、
> 脚本 wav 校验晚于 ffprobe）；随后连续三个绿色提交：2623545 → run 39996457310、
> 5e67c7b → run 39997343133、c88cc80 → run 39997953791（39997946922/39997927908 同为成功）。
> annotated v0.5.0 tag 已 push 并指向本次最终文档提交，父在最终文档提交后重指；
> 历史 v0.4.0 tag 已补 push 到 b029d07。本地复核仍不能替代远端记录。

1. `secret-scan` job：`secret_scan.sh`（令牌需词边界，`task-<长ID>` 不误报）+ `secret_scan_selftest.sh` 自测。
2. `test` job：Python 3.10 → 在干净 runner 环境（显式公共 PyPI 默认源，无宿主机 TUNA 配置）
   `uv lock --check --python 3.10` 校验提交锁 → `ci-cpu-sources.py` 把 torch/torchaudio 源临时改为
   PyTorch **CPU** 索引 → `uv lock --python 3.10` → `uv sync --group dev`（不装 gpu 组）→
   先跑 CPU 子集、再跑完整 `pytest -q`（默认 `-m "not manual and not e2e"`；clean-runner 修复已
   去掉 ffprobe/日志顺序依赖，不跳过测试）→ 语法门禁（`python -m compileall`）→ 用
   `config.example.ini` 在临时目录装配应用冒烟（显式测试 token；不创建 `model_path`，
   断言 `/readyz` 返回 503）。

2026-10-23/24 本地复核（主 `.venv`，未 `uv sync`、未装 GPU）：

- 全量 `pytest -q`：532 passed / 5 deselected，41.13s（2026-10-24，全新 basetemp）；
- CPU 子集：480 passed / 5 deselected；`compileall`：111 个 py 文件通过；
- `secret_scan.sh` 与 `secret_scan_selftest.sh` 通过；
- child lock：TUNA 0、201 个 `pypi.org/simple` source、2489 个 `files.pythonhosted.org` URL、
  `torch/torchaudio` 仍 4 处 cu128；144 packages，版本/哈希/依赖图等价；干净环境 check exit 0；
- root lock：TUNA 0、140 个 `pypi.org/simple` source、2199 个 `files.pythonhosted.org` URL、
  4 处 cu128；143 packages，版本/哈希/依赖图等价；干净环境 check exit 0；
- CPU 源覆盖临时副本：`torch/torchaudio==2.8.0+cpu`、待安装 `nvidia-*` 为 0；
- 启动冒烟：错误 token=401、queue/health=200、缺失 model 的 `/readyz`=503 且未创建模型目录。

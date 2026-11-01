# stt_qwen 真实媒体验收记录（SPEC §9.3 / §13）

- **日期**：2026-11-01
- **对应 SPEC**：`docs/superpowers/specs/2026-11-01-stt-qwen-execution-spec.md`（§12 第 6–7 步）
- **结论**：**通过**。3 部随机抽取的未翻译影片全部走标准三步
  （`extract → stt_qwen → translate`）成功，产物结构、段数一致性、覆盖率、哈希全部达标，
  已回拷到视频目录。验收过程暴露 2 个**执行器缺陷**（已修 + 补回归测试）与 1 个
  **翻译链路容量问题**（给了证据与配置建议，未改代码）。

---

## 1. 素材：随机抽取与排除口径

- 抽取脚本：`random.Random(20261101).sample(candidates, 3)`（**随机种子 20261101**，可复现）。
- 候选池：`/srv/media/jellyfin/JELLYFIN/atmp/` 下同时满足
  1. 目录名不以 `KAVR-` / `MDVR-` 开头（排除 VR）；
  2. 目录内**没有任何** `.ja.srt` / `.zh.srt`（"没翻译过"）；
  3. 恰有 1 个视频文件；
  4. 未出现在历史实验产物目录名里（`whisper-stt/tmp/**/*.16k.wav` 与 `*.ja.srt`，
     排除 ABF-389-UC、ABF-391-U、ABF-395、ADN-783-UC、ATID-799-UC、CJOD-439-UC、
     CJOD-539-U、FNS-270-U、JUR-897-U、MIDA-853、SNOS-353-UC 共 11 部）。

候选池 30 部，抽中：

| 影片 | 视频 | 时长(s) |
|---|---|---|
| SAN-484-U | `SAN-484-U.mp4` | 7272.04 |
| ABF-394-U | `ABF-394-U.mp4` | 7328.15 |
| CAWB-069-U | `CAWB-069-U.mp4` | 8752.32 |

**发布前置核对**：三部目录抽中时均无任何字幕文件（记录见
`whisper-stt/tmp/research/acceptance/pre_run_dir_state.txt`），因此本次回拷
不会覆盖任何既有产物，产物用播放器可直接识别的原名 `<name>.ja.srt` / `<name>.zh.srt`。

---

## 2. 执行方式与运行环境

- **标准三步，走服务 API**（不是临时脚本）：
  `POST /jobs`，`dag = extract → stt_qwen → translate`，鉴权头 `X-API-Token`。
  提交脚本 `scripts/submit_stt_qwen_jobs.py`，提交回执见
  `whisper-stt/tmp/research/acceptance/submit_result.txt`。
- **服务**：`whisper-stt/scripts/run_service.sh`（`whisper-stt/config.ini`，
  DB `tmp/whisper_stt_service.db` 为本次全新建库）。
- **参数**：`[stt_qwen]` 用**本轮落地档**（nominal 30 / Δback 20 / Δfwd 20 /
  fallback_fwd 40 → 片长上界 70s / batch 10 / min_chunk 10 / max_new_tokens 1120），
  提交请求里**没有**下发任何 `job_config.stt_qwen` —— 验收验证的是配置文件里的档位真的生效。
- **零联网正面证据**：服务进程以 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
  HF_DATASETS_OFFLINE=1` 启动；ASR 阶段实测**无任何出站连接**（`ss -tnp` 按 PID 查，
  仅 LISTEN 127.0.0.1:18000），权重全部从本地绝对路径加载
  （模型缓存 key 可见 `model=/…/models/qwen3-asr/Qwen3-ASR-1.7B`
  `aligner=…/Qwen3-ForcedAligner-0.6B` `vad=…/models/vad/fireredvad/VAD`）。
- **GPU 独占**：`nvidia-smi` 采样 1118 点（每 5s，13:23–14:59），
  **计算进程数在 ASR 期间恒为 1**；仅 17 个采样点（13:35–13:36，服务重启窗口、
  旧进程尚未完全退出）出现 2 个进程，**两部片的 ASR 从未并发**（`stt_qwen_workers=1`）。

---

## 3. 三部实测结果

| 影片 | 状态 | 时长(s) | 片数 | 批数 | VAD(s) | 推理(s) | RTF | torch峰值(GB) | 行数 | 字符 | 覆盖 | 片长 min/mean/max(s) | 策略 vad/ext/hard | align_missing | 清洗 adjusted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ABF-394-U | succeeded (attempt 0) | 7328.15 | 243 | 25 | 14.17 | 1181.37 | 0.1612 | 9.05 | 509 | 5253 | 0.9991 | 16.18 / 30.16 / 66.16 | 240 / 2 / 0 | 0 | 2（53.12s→30.0s） |
| SAN-484-U | succeeded (attempt 0) | 7272.04 | 236 | 24 | 13.78 | 1090.60 | 0.1500 | 7.77 | 720 | 9788 | 0.9965 | 22.65 / 30.81 / **70.00** | 231 / 0 / 4 | 4 | 6（70.0s→30.0s） |
| CAWB-069-U | succeeded (attempt 0) | 8752.32 | 285 | 29 | 16.86 | 1528.06 | 0.1746 | 9.25 | 820 | 11049 | 0.9974 | 13.00 / 30.71 / **70.00** | 280 / 1 / 3 | 2 | 7（70.0s→30.0s） |
| **合计/均值** | 3/3 | 23352.5 | 764 | 78 | 44.81 | 3799.0 | 0.1627 | ≤9.25 | 2049 | 26090 | ≥0.9965 | — | 751 / 3 / **7** | 6 | 15 |

- **每音频小时推理 586s ≈ 9.8 分钟**（含 VAD 587s/h），一部 2 小时片约 20 分钟。
- `stt_qwen` 三个阶段任务的 `attempt` 全部为 **0**（没有靠重试兜底）。
- 逐批耗时 `batch_seconds` **强烈依赖内容**：78 批中最短 2.32s、最长 58.87s、中位 55.6s、均值 48.7s
  （同档位下"某片退化重复生成打到 token 上限"是主要长尾来源，见 §6.3）。
- 整卡显存（`nvidia-smi` 口径，含桌面约 1.8GB）：**峰值 15856 MiB / 16376 MiB**，
  均值 14492 MiB；按阶段峰值 ABF 尾段 15856、SAN ASR 12850、CAWB ASR 15591 MiB。
  功耗峰值 197W、GPU 利用率均值 47%。

---

## 4. 产物校验（SPEC §9.3 判据逐项）

判据来源：`scripts/verify_stt_qwen_acceptance.py`（只读产物，原始输出
`whisper-stt/tmp/research/acceptance/verify_report.json`）。

| 判据 | ABF-394-U | SAN-484-U | CAWB-069-U | 结论 |
|---|---|---|---|---|
| 任务 `succeeded` | ✅ attempt 0 | ✅ attempt 0 | ✅ attempt 0 | 通过 |
| 片数 / 批数与日志一致 | 243 / 25 | 236 / 24 | 285 / 29 | 通过 |
| 片长 min ≥ 10s | 16.18 | 22.65 | 13.00 | 通过 |
| **片长 max ≤ 70s，0 片 > 70s** | 66.16 / 0 | **70.00** / 0 | **70.00** / 0 | 通过（硬切上界被触达：SAN 4 片、CAWB 3 片） |
| 最长字幕段 ≤ 30s | 30.0 | 30.0 | 30.0 | 通过 |
| > 30s 段数 = 0 | 0 | 0 | 0 | 通过 |
| 时间轴单调（非单调数 0） | 0 | 0 | 0 | 通过 |
| 空文本条数 = 0 | 0 | 0 | 0 | 通过 |
| 覆盖终点 ≥ 98% | 0.9991 | 0.9965 | 0.9974 | 通过 |
| ja / zh 段数相等 | 509 = 509 | 720 = 720 | 820 = 820 | 通过 |
| checkpoint 键集合 = 段数 | 509/509 | 720/720 | 820/820 | 通过 |
| checkpoint `source_sha256` = ja.srt sha256 | ✅ | ✅ | ✅ | 通过 |
| zh 残留假名 = 0 | 0 | 0 | 0 | 通过 |
| copy_back ja/zh sha256 一致 | ✅ / ✅ | ✅ / ✅ | ✅ / ✅ | 通过 |

四类计数（`fallback` / `hard_cut` / `align_missing` / `cleanup_adjusted`）全部
出现在 `stt_qwen` 任务日志与 `effective_config` 快照中，且与产物一致：

- `hard_cut`：SAN 4、CAWB 3、ABF 0（高上界告警日志见 `stt_qwen hard cut applied`）；
- `vad_offset_extended`（fallback 扩窗）：ABF 2、CAWB 1、SAN 0；
- `align_missing`：SAN 4、CAWB 2、ABF 0（每条都有 `align missing fallback used` WARNING）；
- `cleanup_adjusted`：ABF 2 / SAN 6 / CAWB 7，原始最长 53.12s / 70.0s / 70.0s → 全部收到 30.0s。

**发布**：三部的 `<name>.ja.srt` 与 `<name>.zh.srt` 已回拷到各自视频目录，
sha256 与本地产物逐一相等（上表）。发布前后目录里原本没有同名文件。

---

## 5. 独立复核：用 CPU 重算切片计划

为避免"只信日志"，另写 `whisper-stt/tmp/research/acceptance/verify_chunk_bounds.py`：
用**同一份 VAD 权重在 CPU 上**重新跑 VAD + `pick_cuts`（GPU 档位完全相同的参数），
再逐行核对 SRT 是否落在自己所属的片内。

| 影片 | 复算片数 | 日志片数 | 片长 min/max | >70s 片数 | SRT 行数 | 越出本片边界的行 |
|---|---|---|---|---|---|---|
| ABF-394-U | 243 | 243 ✅ | 16.18 / 66.16 | 0 | 509 | 1（超出 0.199s，机制见 §6.2） |
| SAN-484-U | 236 | 236 ✅ | 22.65 / 70.00 | 0 | 720 | 0 |

**片数与日志逐一致**，说明切片决策可被第三方独立复现（不是"日志里写了什么就是什么"）。

---

## 6. 验收暴露的缺陷

### 6.1 缺陷 1（已修）：显存门槛不区分"冷启动"与"命中缓存" —— **首次验收 2/3 部片失败**

- **现象**：第 1 部（ABF-394-U）成功后，第 2、3 部片的 `stt_qwen` 连续 3 次
  （attempt 0/1/2）以
  `stt_qwen_insufficient_vram: free=0.00GiB total=15.99GiB required=12.00GiB`
  失败，两个 job 直接 `failed`、`translate` 被 `blocked`。
- **根因**：`model_cache`（`model_cache_size=2`）在任务结束后**仍持有**已加载的模型，
  显存没有归还给驱动；`torch.cuda.mem_get_info()` 会把缓存分配器持有的块算成**已用**，
  于是空闲显示 0.00GiB。而我的门槛在 `get_qwen_asr_bundle()` **之前**无条件要求
  "空闲 ≥ 12GB"，对"其实已经加载好、下一步就是命中缓存"的场景必然误判。
- **修复**（`service/model_cache.py` + `executor/stt_qwen.py`）：
  新增 `ModelCache.has_qwen_asr_bundle(...)`（与 `get_*` 共用同一份 `qwen_asr_bundle_key`，
  避免 key 漂移）；执行器先判断是否命中缓存，命中则把门槛置 0（= 不设门槛）**并记录**
  `vram_gate_skipped=true` 与一条 `stt_qwen vram gate skipped … reason=bundle_cached` 日志
  ——行为差异必须留痕，不许静默。
- **修复后实测**：CAWB-069-U 日志出现
  `stt_qwen vram gate skipped: task_id=task-CAWB069U-… reason=bundle_cached min_free_vram_gb=12.00`，
  `effective_config.model_cache_hit=true`，任务一次通过。
- **回归测试**：`tests/unit/test_stt_qwen_stage.py::test_vram_gate_skipped_when_bundle_cached`
  （断言冷启动传 12.0、命中缓存传 0.0，且换 `batch_size` 必须判为未命中、参数不全保守判未命中）。

### 6.2 缺陷 2（已修，对本次三部产物为 no-op）：字级时间戳未按片长夹取

- **现象**：`_group_lines` 的"保证单调"兜底会把后一行的 `start` 推到前一行的 `end`；
  若对齐模型给出**远超片长**的逃逸时间戳（历史上 whisper 出现过 886.7s 级），
  后面所有行都会被推到音频之外——写出的字幕起点会超过音频时长（违反 I6）。
- **修复**：`_group_lines` 新增 `max_end` 参数，字级 `start/end` 先夹到
  `[0, 片内时长]` 再聚合；`_collect_batch_lines` 传入该片的实际时长。
- **对本次产物无影响的证明**（不靠"应该不会发生"）：
  1. 修复前的 `_collect_batch_lines` 只把 `end` 夹到**音频总时长**，因此**若真的发生逃逸，
     必然留下"某行 end 恰好等于音频时长"的痕迹**。实测三部片的末行结束时间是
     7321.51 / 7246.85 / 8729.59（音频 7328.15 / 7272.04 / 8752.32），**没有一行贴到时长上**
     → 没有发生逃逸。
  2. §5 的 CPU 独立复算只发现 ABF 有 1 行越出本片边界 0.199s，且该行时长恰为 0.200s
     （`start + MIN_SEGMENT_SEC` 的最小时长兜底），这一步在**夹取之后**执行，
     因此加上夹取后该行仍会如此——差异为零。
- **回归测试**：`tests/unit/test_stt_qwen_stage.py::test_messy_timestamps_sanitized_without_losing_text`
  （倒挂 + 重叠 + 900s 逃逸 + 零长，断言"一字不少、全部落在音频内、单调、≤30s"）。

> **诚实标注**：缺陷 2 的修复发生在本次三部片**跑完之后**，所以严格来说三部产物出自
> "修复前 + 缺陷 1 已修"的代码状态。上面给出了"修复对其无影响"的两条独立证据；
> 若要绝对统一，重跑一部的成本约 20 分钟 GPU，随时可做。

### 6.3 翻译链路：`batch_size=100` + 思考无法真正关闭 → parse 空转（未改代码，给配置口径）

`translate` 阶段虽然最终成功，但代价极高（本次仍属**范围外的既有链路问题**，
按用户"translate 不是主流程"的定性只做取证与建议）：

- 统计：`parse` 类重试 **56 次**、`ids_mismatch` 2 次、`translate_partial` 子集重试 4 次，
  成功批次 29 个；**单批尝试耗时中位 194.9s、最大 313.7s**。
- 直连复现（用 SAN 的真实 ja.srt，同一批内容做单变量对照）：

  | batch_size | max_tokens | 耗时 | finish_reason | completion_tokens | reasoning_tokens | 可用 |
  |---|---|---|---|---|---|---|
  | 100 | 16000 | 204.8s | **error** | 13773 | 0（路由误报） | ❌ 内容截断在 `"90": "震动` |
  | 100 | 8000 | 305.3s | **error** | 22974 | 0 | ❌ |
  | 40 | 16000 | 203.6s | stop | 13585 | **13110** | ✅ 40/40 |
  | 25 | 16000 | **16.6s** | stop | 1012 | 577 | ✅ 25/25 |

- **关键更正**：SPEC §7 的 T2 曾记录"`reasoning.enabled=false` 无可测效果、
  `reasoning_tokens` 恒为 0"。本次实测**推翻该结论**：同一批 40 条上
  `reasoning.enabled=false` 仍产生 **7185** 个 reasoning token（不传该字段为 12676），
  `effort=low` 6148、`max_tokens=0` 5732 —— 这些参数只是**减少**思考，**关不掉**。
  耗时与 `parse` 失败与思考量强相关。
- **实测建议（配置即可，不改代码）**：`batch_size` 由 100 下调到 **20~25**
  （实测 25 条 → 16.6s 且稳定），`parallel` 保持 4。
- **最终决定（2026-11-01，用户拍板）**：`batch_size = 50`、`max_tokens = 20000`
  （由 16000 上调，因为该路由的思考 token 计入 completion）、
  `reasoning: {"enabled": false}` **仍下发**（用户明确保留）。
  **该折中值未做回归验证**——用户要求"不再重试，只改参数然后结束本任务"。
  已同步四处：`config.ini`、`config.example.ini`、`executor/common.py` 的
  `DEFAULT_TRANSLATE_BATCH_SIZE`/`DEFAULT_TRANSLATE_MAX_TOKENS`、
  `core/config.py` 的 `TranslationSettings.batch_size`；并新增两条用例
  （`test_shipped_config_example_matches_code_defaults`、
  `test_shipped_config_values_reach_the_request_body`）把
  「模板值 = 代码默认值」「配置值真的带 max_tokens=20000 + reasoning.enabled=false 进请求体」钉死。
- **产品行为未被破坏**：检查点按 `source_sha256` 绑定且逐批落盘，重试只补缺失批次
  （SAN 10/10、CAWB 10/10 最终齐全），ja/zh 段数严格相等、0 假名残留。

### 6.4 缺陷 3（已修，本次已发布产物中仍残留 6 行）：静音片被输出成「。」→ 30 秒只有一个句号

- **发现方式**：发布后做真片抽检（`head` 看前几条）时肉眼发现 CAWB-069-U 第 1 条是
  `00:00:00,000 --> 00:00:30,000` + 文本「。」。
- **量化**（脚本化复核，非估计）：

  | 影片 | 总行数 | 纯标点/无内容行 | 位置 |
  |---|---|---|---|
  | SAN-484-U | 720 | **4** | 6953.9 / 7023.9 / 7093.9 / 7163.9（**间隔恰为 70s = 片长上界**） |
  | CAWB-069-U | 820 | **2** | 0.0 / 8659.4 |
  | ABF-394-U | 509 | 0 | — |

- **根因**：`chunk_zero_speech`（VAD 判定整片无语音的片数）在 SAN 是 5、CAWB 是 2；
  这些片模型只输出一个「。」，`text.strip()` 后非空 → 不被 `empty_chunks` 捕获 →
  被当正常内容写出；对齐器又给它整片时长，于是成了"30 秒一个句号"。
- **修复**（`executor/stt_qwen.py`）：新增 `_has_content()`（假名/汉字/字母/数字至少一个）
  与 `_CONTENT_CHAR_RE`；`_collect_batch_lines` 的两条路径（正常时间戳 + `align_missing`
  兜底）都过滤纯标点行，并计入 `punct_only_lines`，`>0` 时打 WARNING
  `stt_qwen punctuation-only lines dropped`，同时写入 `effective_config`。
- **回归测试**：
  `test_punctuation_only_lines_are_dropped_and_counted`（「。」占满整片 → 0 条输出、
  计数 2、其余有效行一条不少）、
  `test_punctuation_only_fallback_text_is_also_dropped`（全是纯标点 → 明确
  `stt_qwen_empty_srt` 失败，绝不输出满屏句号）。
- **诚实标注**：该修复发生在本次三部片**跑完并已发布之后**，因此
  **已发布文件里仍有这 6 行**（SAN 4 / CAWB 2）。不重跑的理由：修 ASR 需独占 GPU
  约 20 分钟/部，且重跑会让"检查点 `source_sha256` ↔ ja.srt"的既有验收证据失效。
  需要干净产物的话，重跑命令见 §9，成本约 45–60 分钟（含 translate）。

---

## 7. SPEC §13 验收标准对照

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 默认 job 仍走 `stt`，配置/契约无变化；显式 DAG 可路由 `stt_qwen` | ✅ | `build_default_dag()` 未改（单测 `test_default_dag_is_unchanged`）；本次三个 job 的 `stages` 均为 `["extract","stt_qwen","translate"]` |
| 2 | 运行期零联网，模型全部本地 | ✅ | 离线环境变量启动 + ASR 期间零出站连接 + 缓存 key 全为本地绝对路径（§2） |
| 3 | 3 部影片标准三步 `succeeded`，产物满足 §9.3 判据 | ✅ | §3 §4 |
| 4 | 四类计数在日志/快照可见且与产物一致 | ✅ | §4 末段 |
| 5 | 单元 + 集成测试全绿；合成边界用例能区分新旧实现 | ✅ | `pytest tests/unit tests/integration` → **615 passed, 1 skipped**；`test_prev_anchoring_beats_grid_anchoring_regression` 用同一份边界证明旧 grid 锚定会切出 >70s 的片 |
| 6 | 验收记录落档，明确标注未验证项 | ✅ | 本文件 + §8 |

---

## 8. 未验证项与风险（必须随结论一起看）

1. **坍缩（退化重复生成）未定性**：`batch_seconds` 跨度 2.32s–58.87s（同档位、同批大小），
   说明部分批次仍在"打到 token 上限"的长尾里；本次未做 30–180s 的片长坍缩刻度，
   触发条件仍未知。**影响**：耗时不可预测（±3 倍），不影响产物完整性
   （覆盖率 0.9965+、0 空文本、0 超长段）。
2. **显存余量薄**：整卡峰值 15856 MiB / 16376 MiB（余量约 0.5GB，含桌面 1.8GB）。
   `min_free_vram_gb=12.0` 在"进程内已有缓存"时会误判（缺陷 1 已修），但
   **冷启动且前序阶段（如 whisper）占着显存时仍会按设计失败**——这是期望行为，
   但也意味着 `stt_qwen` 与其它 GPU 阶段**不能真正并发**，必须独占。
   `model_cache_size=2` 在 whisper + qwen 共存时是否够用**仍未实测**。
3. **`tokens_per_sec=16` 未做召回验证**：`max_new_tokens=1120` 是配置上界推导
   （70s × 16），不是按实际最长片算的；极密集语句理论上存在被截断的可能
   （实测平均 34.1 字/片，远低于 1120 的预算）。
4. **翻译链路的思考开关关不掉**（§6.3）：`reasoning.enabled=false` 只减不关；
   当前靠"小批量 + 检查点续跑 + 子集重试"兜住，未根治。这是**既有链路问题**，
   不在本次 stt_qwen 改动范围内。
5. **产物文件名**：本次三部片原本没有字幕，故直接用 `<name>.ja.srt`/`.zh.srt`。
   若对**已有字幕**的影片运行本阶段，回拷会覆盖既有文件——上线前需要明确命名策略。
6. **`stt_whisperx` 去留未决**：新阶段落地后是否标 legacy，仍待用户决定。
7. **已发布产物含 6 行纯标点噪声**（缺陷 3，见 §6.4）：代码已修 + 已补测试，但
   本次三部片未重跑，因此 `SAN-484-U.ja.srt`(4 行) / `CAWB-069-U.ja.srt`(2 行) 里
   仍有"30 秒只有一个「。」"的条目；对应 zh.srt 同样有 6 行。

---

## 9. 复现命令

```bash
# 1) 起服务（离线环境变量 = 零联网模型的正面约束）
cd whisper-stt && HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
    bash scripts/run_service.sh

# 2) 标准三步提交（DAG 见脚本内的 STT_QWEN_DAG）
python scripts/submit_stt_qwen_jobs.py \
    --video /srv/media/jellyfin/JELLYFIN/atmp/SAN-484-U/SAN-484-U.mp4 \
    --video /srv/media/jellyfin/JELLYFIN/atmp/ABF-394-U/ABF-394-U.mp4 \
    --video /srv/media/jellyfin/JELLYFIN/atmp/CAWB-069-U/CAWB-069-U.mp4

# 3) 逐项验收（只读）
python scripts/verify_stt_qwen_acceptance.py \
    --film "SAN-484-U=whisper-stt/tmp/artifacts/<job_id>:/srv/media/jellyfin/JELLYFIN/atmp/SAN-484-U" \
    --pretty

# 4) 独立复算切片计划（CPU，不需 GPU）
python whisper-stt/tmp/research/acceptance/verify_chunk_bounds.py \
    "SAN-484-U=whisper-stt/tmp/artifacts/<job_id>"
```

**Job ID 对照**（本次验收）：

| 影片 | job_id |
|---|---|
| SAN-484-U | `job-SAN484U-job-20261101050751-dafa` |
| ABF-394-U | `job-ABF394U-job-20261101050751-a9c1` |
| CAWB-069-U | `job-CAWB069U-job-20261101050751-0b81` |

**代码指纹**（`git diff` + 两个新执行器文件的 sha256，取法：
`{ git diff; cat whisper_stt_service/executor/stt_qwen.py whisper_stt_service/executor/qwen_boundary.py; } | sha256sum`）：

| 阶段 | 指纹 |
|---|---|
| 三部片提交时（缺陷 1 修复前） | `d3e1d59ece06f6b24f72c78c6bc044c1a35306e66d16b724926d193c101003d8` |
| 缺陷 1 修复后（**本次验收运行所用代码**） | `4810ce308d13789c02eb9ee0bd85cc5445030301c4efebe65b847599d033f6e4` |
| 缺陷 2 修复后（夹取，对本次产物已验证为 no-op，见 §6.2） | `5bd378ec770bdebe232591b89e21d03c66169e3e3f0d1c79abde490bfd1259e8` |
| 缺陷 3 修复后（**当前最终代码**，纯标点过滤；本次已发布产物未包含） | `955f02f7a0511222107df07f0fe0cf727272e0378cd8d03e1344a408f265ccdc` |

最终测试统计：`pytest whisper-stt/tests/unit whisper-stt/tests/integration` → **615 passed, 1 skipped**
（`test_qwen_boundary.py` 15 例 + `test_stt_qwen_stage.py` 26 例）。

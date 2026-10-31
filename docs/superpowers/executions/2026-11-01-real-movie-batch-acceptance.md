# 真实电影批量端到端验收（3 部完整影片）

- **日期**：2026-11-01（Asia/Shanghai）
- **执行**：父代理，服务以 systemd 用户单元运行（User=base），配置为运行期临时配置
- **样本目录**：`/srv/media/jellyfin/JELLYFIN/atmp`（SMB 共享 `//192.168.3.138/Raid16T`）

## 1. 输入完整性核验（先证输入完整，再判流水线）

判定方法：目录无 `.aria2` 残留、文件大小稳定、文件尾部可解码（`ffmpeg -sseof -10`），
并以“提取 wav 时长 ≈ 容器时长”作为最终一致性校验。

| 电影 | 容器时长 | 提取 wav | 差值 | 判定 |
|---|---|---|---|---|
| MIDA-853 | 7316.309s（2h02m） | 7306.219s | 10.1s（音频编码填充） | 完整 |
| ADN-783-UC | 7102.379s（1h58m） | 7102.379s | 0.0s | 完整 |
| CJOD-539-U | 6864.792s（1h54m） | 6854.763s | 10.0s | 完整 |

> 首轮曾误用尚未下载完的 MIDA-853（当时存在 `.aria2` 且持续增长），仅提取到 2897s，
> 字幕只覆盖 48 分钟。下载完成后重跑即完整覆盖 2h01m，证明这是输入问题而非产品缺陷。

## 2. 结果（3/3 succeeded，attempt=0）

| 电影 | extract | stt | translate | 字幕段数 | copy_back |
|---|---|---|---|---|---|
| MIDA-853 | 128s | 353s | 1076s* | ja 402 / zh 402 | 视频同目录 |
| ADN-783-UC | 140s | 150s | 43s | ja 136 / zh 136 | 视频同目录 |
| CJOD-539-U | 142s | 82s | 6s | ja 3 / zh 3（该片音频以音乐/环境音为主，已用 `vad_filter=False` 直探证实） | 视频同目录 |

\* MIDA 的 translate 偏慢，是当时上游单批响应 150–250s 且伴随 parse 重试所致。

一致性与安全证据：
- 本地产物与共享回写文件 **sha256 完全相同**（ja：326d0fc6…/c0addb1a…/87eb4d05…；zh：b734d8f5…/c7e34882…/6cee14cb…）
- 3 部影片的 `progress.json` 中 `source_sha256` 均等于各自 `ja.srt` 的实际哈希（C.4 源绑定生效）
- 并发与限流按配置生效：3 个 extract 并行、stt 受 `stt_workers=2` 排队、模型槽位 `model_parallelism=1` 排队（日志可见 `model_transcribe_wait`）

## 3. 真实场景暴露并修复的产品缺陷

### 3.1 P1：翻译任务被 240s 误杀（已修复）

- 现象：2h23m 影片的 translate 任务在约 240s 报 `translate_timeout`，即使 `[timeouts] translate_timeout_sec=7200`。
- 根因：`[translation] timeout=240`（单批 HTTP 超时）被 `TranslationSettings.as_job_config()` 映射成任务级
  `timeout_sec`，覆盖 `stage_timeouts["translate"]` 写入 `tasks.timeout_sec`，又被当作 `run_translate` 的总 deadline。
- 修复（commit `384676e`）：任务级 deadline 只来自 `[timeouts]` 或显式任务级覆盖；HTTP 超时仍读 `[translation] timeout`；
  顺带修正 `resolve_translate_settings` 一直读错键名（`timeout_sec` 而非 `timeout`）的问题。
- 验证：新入队任务 `tasks.timeout_sec = 7200`（extract 1200 / stt 7200 不变）；远端 CI 41242275143 success。

### 3.2 P2：模型回复带尾部内容导致解析失败（已修复）

- 现象：上游返回 `JSON + 额外内容` 时反复 `error_class=parse`，同一批次 8 次重试全部失败，任务最终失败。
- 根因：`_extract_json_object` 取「首个 `{` 到最后一个 `}`」再整体 `json.loads`，遇 `{...}{...}` 或 JSON 后跟说明文字即 `Extra data`。
- 修复（commit `0bd6d3d`）：改用 `JSONDecoder.raw_decode` 逐候选提取，返回首个可用 JSON 值并忽略尾部；
  无 JSON 时抛可重试的 `JsonExtractionError`；脚本模式同款实现改为委托同一函数。
- 验证：拼接对象/数组、JSON+说明、围栏+围栏外说明均可解析；纯文本仍报错（不静默）；缺 id 仍走 C.5 只补缺失。
  远端 CI 41244633806 success；本地全量 546 passed。

## 4. 第 4 部（JUR-897-U）观察

- 2h23m 影片：extract / stt 成功（8563.99s 源 → 8553.92s wav），translate 10/11 批次成功，
  但同一批次（0/0）在解析加固后仍持续 `error_class=parse` → 说明该批次的上游回复很可能**不含可解析 JSON**
  （例如拒答/异常文本），而非"JSON 带尾部"。
- 现状：任务按重试策略最终失败（不会静默产出错误字幕）。已记录为**上游内容相关失败**，
  候选改进：连续 parse 失败达到阈值后按 C.5 语义回退保留日文原文（当前 strict_ids=false 仅覆盖"缺 id"场景）。

## 5. 环境与清理

- SMB 共享：`/mnt/JELLYFIN` 已挂载到 JELLYFIN 目录（UNC 子路径 + zztdan 凭据，`/etc/cifs-jellyfin.cred` 600）；
  `/srv/media/jellyfin` 保持原样（共享根、guest）。
- 运行期临时配置与 token 位于 `whisper-stt/tmp/e2e-batch3/`（gitignored），验收结束后删除。
- 未验证项（外部限制）：GPU 显存峰值（NVML 被 OS 阻断）、供应商侧 HF/API token 轮换（人工动作）。

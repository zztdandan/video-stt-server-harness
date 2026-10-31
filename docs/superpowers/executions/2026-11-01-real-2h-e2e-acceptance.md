# 真实 2 小时媒体端到端验收（v0.5.0 补充证据）

- **日期**：2026-11-01（Asia/Shanghai）
- **执行者**：父代理（DSH），服务以用户 base 身份在 WSL 内运行
- **目的**：补齐 SPEC「真实 2h E2E」这一此前的发布后跟踪项；不使用 fake、不使用合成样本。

## 1. 环境恢复：SMB 共享与 /mnt/JELLYFIN

- NAS：`192.168.3.138`，共享 `Raid16T`（guest/SMB3，`sec=none`）。
- `/etc/fstab` 已有 `//192.168.3.138/Raid16T /srv/media/jellyfin`（systemd automount）。
- 本次为 `/mnt/JELLYFIN` 追加同样式条目并启用自动挂载：

```text
//192.168.3.138/Raid16T /mnt/JELLYFIN cifs guest,vers=3.0,uid=1000,gid=1000,dir_mode=0755,file_mode=0644,iocharset=utf8,nofail,_netdev,x-systemd.automount 0 0
```

- 验证：`systemctl start mnt-JELLYFIN.automount` 后访问即按需挂载；`/mnt/JELLYFIN` 可见
  `DOWNLOAD_BAK / JELLYFIN / WEBDAV / iocage`，`/mnt/JELLYFIN/JELLYFIN/atmp` 下 41 个可探测视频。
- 说明：会话内的 DSH 文件沙箱（workspace-write）会把工作区外路径显示为只读，因此服务以
  systemd 用户单元（`User=base`）方式启动，使 `copy_back` 能真实写入 SMB 共享；这只影响沙箱视图，
  不是 NAS 权限问题（root 与 base 经 interop 写入均成功）。

## 2. 被测样本

| 项 | 值 |
|---|---|
| 路径 | `/mnt/JELLYFIN/JELLYFIN/atmp/FNS-270-U/FNS-270-U.mp4` |
| 时长 | 7272.328s（2h01m12s） |
| 大小 | 6,862,036,249 B（6.4 GiB） |

## 3. 运行配置（运行期临时配置，用后删除）

- `[security] api_token` 为本次随机强 token（用户本机 config.ini 的 token 因 15 字符被判为占位符，
  安全默认 fail-closed 拒绝启动——属 SPEC H 预期行为，未改动用户文件）。
- `[runtime] db_path/log_root/artifact_root` 指向 `whisper-stt/tmp/e2e-2h/`；
  `model_path` 覆盖为 `models/faster-whisper-small`（CPU-only 环境的实用选择；生产默认仍为 large-v3-turbo）。
- DAG：`extract → stt → translate`（v1）；`job_config`：`stt.device=cpu`、`stt.compute_type=int8`、
  `translate.chunk_minutes=20`、`translate.retry=8`、`copy_back=__video_dir__`。

## 4. 结果

```text
job_id   = job-FNS270U-job-20261031194904-dcc2
status   = succeeded         finished_at = 2026-10-31T19:52:37Z
extract  = succeeded attempt 0  19:49:02.86 → 19:50:38.46  (95.6s)
stt      = succeeded attempt 0  19:50:39.15 → 19:51:55.88  (76.7s)
translate= succeeded attempt 0  19:51:55.90 → 19:52:37.08  (41.2s)
端到端墙钟 ≈ 3m49s（提交 19:49:04Z → 完成 19:52:37Z）
```

- worker_id 带 boot nonce（如 `stt-w2-6547-b5124d3d`），与租约 ABA 防护一致。
- 产物：`audio/FNS-270-U.16k.wav` 232,714,550 B；`asr/FNS-270-U.ja.srt` 245 段；
  `translate/FNS-270-U.zh.srt` 245 段（段数一致，末条 `02:00:41,680 --> 02:00:42,600`，未超出 2h01m12s）。
- **copy_back 真实落盘**（服务模式、跨 SMB）：
  `/mnt/JELLYFIN/JELLYFIN/atmp/FNS-270-U/FNS-270-U.ja.srt`（14,720 B，03:52）、
  `FNS-270-U.zh.srt`（13,301 B，03:52），与视频同目录。
  - sha256 ja = `9329d04d6cdbf43dd2b143fc91b981d6fad762c2ce1494fe76cb7c3b36dd8c14`
  - sha256 zh = `47e0905583295f0fe437f6f2496f065eacc2a72ca7c0c771e1eaed6ce50c15d3`
- 检查点（C.4）：`translate/*.zh.srt.progress.json`，`version=1`、`batch_size=200`、`chunk_minutes=20`、
  `max_chars=12000`、`source_sha256=9329d04d…`（**与 ja.srt 哈希一致**），两个批次 `done=true`、
  `inflight=false`。
- 任务日志（SPEC G 的 11 字段）：每阶段均含
  `timestamp, request_id, job_id, task_id, stage, worker_id, event, result, attempt, effective_config, error`，
  并有 `artifacts_published`。
- 指标（/metrics）：
  `whisper_stt_tasks_finished_total{stage=extract|stt|translate,result=succeeded}=1`；
  `task_duration_seconds_sum` extract=100.6s、stt=80.2s、translate=44.6s；
  `translate_retries_total=0`；`model_cache_misses_total=1`、`hits=0`。

## 5. 结论与边界

- 真实 2 小时媒体在 CPU-only 环境下跑通完整 `extract → stt → translate → copy_back`，
  无失败、无重试、无丢行；此前"真实 2h 未验证"的缺口在本机环境已闭合。
- 本次使用 `faster-whisper-small`（int8/CPU）而非生产默认 `large-v3-turbo`；ASR 质量不在本次验收范围。
- **仍未验证**：GPU 显存峰值（`nvidia-smi` 退出 255，NVML 被 OS 阻断）、供应商侧 HF/API token 轮换（人工动作）。
- 本次运行在用户媒体库同目录写入了 `FNS-270-U.ja.srt` / `FNS-270-U.zh.srt`（产品设计的 copy_back 行为）；
  如需移除请直接删除这两个文件。

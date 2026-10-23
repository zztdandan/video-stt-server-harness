# Sol 最终独立验收：新上下文第三轮（持续更新）

## 结论与边界

2026-10-23 21:45 CST 起，只读审查/临时目录实验；未改实现、未提交、未读取真实配置凭据。完整读取主 AGENTS、603 行 SPEC 和主执行记录最新续作。工作树为 `/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening`。**当前不可通过最终验收**：下面的新增 P1 与此前 copyback/动态身份 P1 均未修复，不能用测试数替代正确性。

## 已独立复现的新 P1

### R3-1：旧 runtime 停机撤销新 owner 的租约

- 位置：[runtime:373–376](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L373-L376)、[runtime:665–668](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L665-L668)、[repository:1614–1662](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/repo/job_repository.py#L1614-L1662)。
- 真 SQLite 最小实验：旧 w1 租约保存在旧 runtime 的 `_inflight_leases`；手动让其过期、运行 reaper、w2 领取 attempt=1。分别调用旧 runtime 的 `stop(timeout_sec=1)` 与 `_force_drain_timeout()`。
- 两条路径均从 `claimed/new-worker/attempt1` 变成 `queued/NULL/attempt1`，错误分别为 `shutdown_rollback` 和 `drain_timeout_rollback`。
- 原因：批量 rollback 只使用 task_id，不匹配冻结的 owner/attempt。任务已被接管不意味着旧 runtime 的本地 map 会同步消失。
- 修复要求（交 CC）：逐个 frozen lease 调 `rollback_claimed_task(worker_id=...,attempt=...)` 或等价 tuple-fenced 批事务。不可只检查当前 map 的新身份。

### R3-2：promotion I/O 异常逃出 worker 循环

- 位置：[runtime:914–930](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L914-L930)、[runtime:693–712](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L693-L712)。
- 实验：真实 repo 领取 extract，fake extract 真写私有 staging；仅将 `publish_task_artifacts` 注入 `OSError("simulated destination I/O error")`。直接调用 `_execute_claimed`。
- 实测异常原样逃出，task 仍 `claimed, attempt=0,last_error=NULL`，`_inflight_leases=[]`。真实 worker loop 未捕获该异常，因此唯一该 stage worker 会退出；reaper 再 queued 也没有消费者。
- 修复要求（交 CC）：promotion/copyback 错误进入 fenced mark-failed/retry 与统一日志，保留 worker 循环；不得只清 staging、移除 map 然后异常退出。

### R3-3：fenced 检查点 helper 在事务外第二次写，绕过租约

- 位置：[atomic:68–90](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/executor/atomic.py#L68-L90)、[translate:617–633](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/executor/translate.py#L617-L633)、[runtime:1518–1531](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L1518-L1531)。
- `publish(path,text)` 已在 `with_task_lease` 事务内写盘，但 helper 在其返回 True 后又无条件 `atomic_write_text(path,text)`，此时锁已释放。
- 真 SQLite 确定性实验：w1 callback 在真实租约事务内写旧 cp 并提交；模拟提交后抢占，rollback/claim w2，w2 锁内写 `NEW OWNER CHECKPOINT`；返回到 w1 helper。
- 实测最终从 `NEW OWNER CHECKPOINT` 被覆盖成 `{"owner": "STALE w1"}`。这与动态查 map 是两个独立缺陷；只修 map 仍不安全。
- 修复要求（交 CC）：定义 callback 全权 publish 语义，存在 callback 且接受时不能再锁外写。必须增加在 callback 提交与 helper 返回间接管的回归。

## 旧 P1 当前核查

- **未修**：服务 translate `defer_copy_back=True`，promotion 后没有真实 sink。位置：[runtime:1474–1485](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L1474-L1485)、[runtime:914–951](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L914-L951)。
- **未修**：checkpoint publisher 从 `_inflight_leases[task_id]` 动态取新 owner/attempt；旧 callback 可借新 lease。位置：[runtime:1504–1509](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L1504-L1509)。
- **未修**：旧 `_execute_claimed` finally 无条件 `pop(task_id)` 删除新 lease。位置：[runtime:757–761](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L757-L761)。
- promotion、cancel_check 目前使用传入的固定 `lease`，未见上述动态借身份；staging 固定 worker hash+nonce，清理只遍历自身登记路径，未见旧 cleanup 删新 staging。整 job cleanup 的 DB 检查与 rmtree 非同一事务，仍需专项竞态核查。
- `_touch_checkpoint_retention` 仅 os.utime，不是读改写内容；不能误报其覆盖正文。

## A–I 验收矩阵（第一批）

| 项目 | 当前判断 | 已确认范围/剩余 |
|---|---|---|
| A 生命周期 | 不通过 | 旧 lease promotion 被拒、reaper/retry/cascade 测试过；新增 R3-1/R3-2、动态身份/finally 未闭环 |
| B API/DAG | 条件通过 | DAG 合法/非法、路径、stage IO 已有独立测试；整体 publication 受 A 阻塞 |
| C 翻译 | 不通过 | 旧部分 id/在途完成 cp 修复已由上轮验证；本轮 R3-3、动态身份、copyback 未闭环；CLI已默认复用引擎，但两个新测试fixture失败，行为验收不完整 |
| D 模型 | 本轮针对通过 | 缓存/许可/LRU 与 lazy generator 并发迭代测试过；代码确认普通/batched STT 整迭代及 WhisperX ASR+align 都在 slot 内；不能当 GPU 证据 |
| E wav | 针对通过 | executor wav 合约测试过；父 CPU30s manual2pass 为短片证据，不是2h |
| F SQLite | 针对通过 | 迁移/网络盘/DELETE failfast 针对测试过；跨FS发布故障受 A 阻塞 |
| G 观测 | 针对通过 | readyz/main DB write、audit 针对测试过；promotion 异常漏 task failure 由 R3-2 阻塞 |
| H 安全 | 条件通过 | token/roots/DAG测试过；服务 copyback 真 sink 安全重验未实现；launcher run 源已 pin 环境早于 import，现有测试还需真正 run 验证 |
| I 交付 | 未完成 | 未提交/未整合、主根依赖未跟踪、两新提交远端CI/v0.5/真实2h/GPU/token供应商轮换均无证据 |

## 本轮已收集测试证据

仅 Python `/home/base/repo/video-stt-whisper-server/.venv/bin/python`。独立运行 12 个针对文件：runtime/repository artifact fencing、model cache、DB migrations、observability/audit、task lifecycle、repo P1、core security、DAG、launcher、wav：**269 passed in 4.20s，exit0**。后台 `bash-a8045fa3ac8d4b18` 已收集。新增问题为上述套件未覆盖边界，不能据全绿宣称完成。

父报告的短片 CPU/真实 API smoke 未在此上下文重复发起付费请求；不将其扩张为2h/GPU或完整链路验收。

## 收尾补充：R3-4 P1，租约身份 ABA

- 位置：[runtime:521–543](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L521-L543)、[repository:2249–2255](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/repo/job_repository.py#L2249-L2255)、[repository:1422–1450](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/repo/job_repository.py#L1422-L1450)。
- worker_id只有extract-w1等可复用文本，无runtime boot nonce；API retry重置attempt=0。同任务可能重新产生相同(task_id,owner,attempt)。暂存nonce不等于DB租约identity唯一。
- 真SQLite实证：旧extract-w1/attempt0暂停；设置合法max_retries=0并过期/reaper到failed/attempt1；retry_job重置0；新实例同名extract-w1领取attempt0；旧lease调用publish_task_artifacts返回True，正式文件=STALE OLD RESULT，实验exit0（assert accepted）。debug recovery_counts_as_attempt=false重启也有同类ABA。
- 交CC修：lease_owner含每runtime boot nonce/使用不复用claim generation；仅stage nonce、固定callback身份、map对象比较都不足。补跨runtime同名worker+API retry/debug恢复false真实文件回归。

## CLI当前权威状态与失败边界

- [CLI:393–478](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt/translate_srt_ja_to_zh.py#L393-L478)已委托统一run_translate；[main:634–657](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt/translate_srt_ja_to_zh.py#L634-L657)默认unified，仅显式legacy回退。llm_overrides只传内存，旧无hash检查点安全失效，batch_size下发job_config。不得沿历史误称完全未统一。
- 父full结果2 failed/511 passed/5 deselected。两个失败在[4xx测试:212–230](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/tests/unit/test_cli_translate_hardening.py#L212-L230)及[partial测试:256–268](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/tests/unit/test_cli_translate_hardening.py#L256-L268)。
- fixture基础配置已有retry=3，再append retry=5/2造成DuplicateOptionError。4xx用宽泛pytest.raises(Exception)掩盖配置错误，根本未调fake HTTP，calls=0；partial直接报配置重复。**这是fixture缺陷/验收空洞，不是已证明引擎401行为错误**；不准放宽断言或产品import失败skip。
- 本轮CLI/C/fake integration选跑bash-e61dcf029ca24d42(exit1)也复现两个CLI失败，额外出现一次restart recovery失败。仅重跑该integration+两个lazy-generator用例，bash-c8479173f37649ec收集为3 passed/19 deselected in5.01s，exit0。记录一次不稳定失败，不用重跑绿洗成首次全绿；第一次故障栈尾被展示截断，未据此认定新的产品缺陷。

## D懒迭代独立确认

- [STT:446–496](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/executor/stt.py#L446-L496)的_model_slot覆盖普通/batched transcribe及整个segments迭代。[_model_slot:239–262](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/executor/stt.py#L239-L262)finally归还slot，外层finally释放cache ref。
- [WhisperX:354–386](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/executor/stt_whisperx.py#L354-L386)许可覆盖load_audio/ASR/align，finally归还。
- 两线程共享模型惰性generator测试峰值=1，异常迭代后refs=0；269套件及隔离3例均通过。只证明fake资源契约，不证明GPU峰值或2h。

## 跨FS/copyback/cleanup边界

- staging与正式主产物同目录，当前主promotion不跨FS；多个rename只有SQLite锁，**不是FS事务**，docstring已如实说明部分发布后重试收敛，不应误称FS回滚。
- copyback真实sink不存在，跨FS/执行期roots及symlink重验无法验收。恢复后目标目录先私有临时copy/flush/fsync，再同FS原子rename，并在冻结身份保护的短发布点执行；不能直接artifact staging rename到视频盘导致EXDEV。
- 先mark succeeded会清掉claimed lease，不能简单随后复用with_task_lease，也不能无条件旧线程回写。应纳入成功事务或明确持久sink协议；慢copy与受锁短publish分离，最终重验身份，避免全库长写锁。
- own nonce staging cleanup未见误删新实例。整job DB检查与rmtree分离，配置允许清failed时可能与retry/在途竞态；**仅静态风险，未复现，不计入确认P1**。默认只清succeeded不能直接宣称已复现retry竞态。
- launcher run先pin WHISPER_STT_CONFIG再import main，解析及真实bootstrap probe针对测试过；本轮未启动真实监听器验证完整run，保留条件判断。

## I交付与指定实施代理限制

1. HEAD仍b029d07d569da2c3aa52dee98608f7350de664a7，未提交/未整合原子仓库。根依赖/锁/docs跟踪、两个新提交远端CI、本轮v0.5无完成证据。历史v0.4不能代替发布。
2. 真实2h四路径不可用、NVML受OS阻止；CPU30s新旧SRT相同、API5段1请求/679tokens/17.49s+复跑0请求/0.009s仅短片/供应商smoke，不能冒充2h/显存/kill-9恢复。
3. 供应商端HF/API token撤销/轮换无证据，本地忽略/删除不等于撤销。
4. 父最小CC probe明确HTTP400 QUOTA/insufficient credits。**这是指定实施代理不可用，不是产品bug**。本验收代理不改实现、不擅自换模型实施，未修保持未完成。

## 可恢复修复清单与最终结论

- **七项P1**：旧缺copyback sink、checkpoint动态借新lease、finally无条件pop新lease；新R3-1停机taskid回滚新owner、R3-2发布异常杀worker、R3-3锁外二写cp、R3-4身份ABA。全部要求真实SQLite+文件回归，不接受仅SQL mock。
- 建议CC恢复顺序：身份生成/固定绑定+fenced helper → stop/drain/finally → 跨FS安全sink与发布异常收敛；identity涵盖promotion/checkpoint/cancel/cleanup/stop/API retry。
- CLI fixture用覆盖而非append重复key，精确4xx异常而非任意Exception，补main/HTTP源变更失效/401一次/batch_size/partial不丢行/原子输出；默认不得回旧legacy。调查restart一次不稳定，再全套pytest/compile/secret scanner/最终Sol快照验收；后续由父处理整合/tag/两CI/主docs跟踪/真实媒体/轮换，不能未验提交。
- 快照SHA256：runtime=d01557f19901d472e2f6abda8d4f108ecb6c8a50137f0ca104730020b72ad50d；atomic=94f0a0b06d655eff21d08d11914794cbaafd4f7497698d1fa4cb2e448481f3cf；translate=2202a77dc4f44cb4e9af6704a3f0fe2602ec5319e7047362787102ae94f3d3df；stt=6d1dd1c5c52b884b48d5e81c64efee5fbd29467ad9c5bacc9005988af2325022；whisperx=649edd24e68b8dabb808135dff97f152c30876163d3a50ff251942b67526a5ac；CLI=a37dd5ddce593b57fed210f76f981902efda3edecee381403ce29ee1cd62a4d2。
- 三个后台bash均已收集：269通过、CLI/C/integration失败、隔离3通过；无未收集相关运行作业。**最终验收不通过**。未改实现、未提交；通过项不冲销七项P1与交付门槛。

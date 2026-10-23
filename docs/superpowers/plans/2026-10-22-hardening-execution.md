# 可靠性与翻译链路加固执行记录

## 最新续作状态（2026-10-24 发布完成，优先于下方历史）

- 用户授权后实施代理改为官方 DeepSeek V4.1 Flash（deepseek-official/deepseek-flash）；剩余七项 P1 全部修复并由 GPT-6.1-Sol 用原真 SQLite/文件反例独立复验关闭。
- 后续 clean-runner CI 修复：1) uv.lock 从隐式 TUNA 默认源归一为显式公共 PyPI（pyproject 增加 `[[tool.uv.index]] name="pypi" default=true`；root 同）；2) service.log 在 configure_logging 时立即创建（不再依赖首条日志）；3) 脚本模式 wav 契约校验先于 ffprobe，且 `_probe_duration` 对缺失 ffprobe 返回 None 仅降级进度。
- 子仓库提交序列（feature/reliability-hardening → main FF）：bba96a0 实现 → 66678d0 锁可移植 → 2623545 clean-runner 修复 → 5e67c7b 验收证据文档 → c88cc80 第二绿文档。main 已 FF 到 c88cc80 并 push；annotated tag v0.5.0（object 6732f9c4a48ef2699f553ba49b8c33c31b4dbf44）。
- 远端 CI 事实：39981535390 @ bba96a0 failure（lock TUNA）、39995654486 @ 66678d0 failure（clean-runner 2 用例）、39996457310 @ 2623545 success、39997343133 @ 5e67c7b success；c88cc80 新 run 39997953791（父已发起并收集）。
- 主仓库 commit ee1cf98：docs/00-04、根 pyproject.toml/uv.lock（补 prometheus-client、公共 PyPI 归一）、.gitignore（含 .codex/、secret 规则）、子仓库 gitlink；AGENTS.md 与 scripts/run_shutdown_round.sh 为用户既有改动未纳入。
- 本地验证：全量 pytest 532 passed/5 deselected；集成后（whisper-stt main）targeted 49 passed；secret scanner + selftest 通过；child/root `uv lock --check` 在干净 HOME（无镜像 env）exit 0；CPU 源覆盖 dry-run 解析 torch==2.8.0+cpu 且 0 个 nvidia-*。
- 最终独立验收代理 `1783ee97-c8e0-4750-b564-65e5dc4690d8`（GPT-6.1-Sol high）正在对交付快照做 A–I 最终验收，报告将落 docs/superpowers/executions/2026-10-24-sol-final-acceptance-v0.5.0.md。
- 外部不可验证项（如实记录，非本次失败）：真实 2h 媒体四条 /srv/media 路径不存在；NVML GPU access blocked by OS，无显存峰值；供应商侧 HF/API token 轮换需人工执行。

## 历史续作状态（2026-10-23 23:16 官方模型切换）

- 用户已明确将实施子模型改为官方DeepSeek V4.1 Flash，route deepseek-official/deepseek-flash；goal已edit+resume，revision5 active，旧CC QUOTA不再阻止使用新授权模型。最终仍GPT-6.1-Sol独立验收。
- 官方实施并行：runtime+repo租约/发布修复 `dfc9e837-f0eb-4d39-ab17-df98187d99e3`；atomic/翻译/CLI `0df2f345-74f5-42ef-9a13-3c5e38471634`（已完成）；CI/README/主docs00-04 `1dbca2f2-049f-4601-8d9f-c8a928ffcc9d`。旧实施代理不再有编辑任务，避免冲突。
- 官方0df已修R3-3 callback全权publish(不再锁外二写/非bool拒绝)，补真实SQLite接管文件回归；CLI fixture重复retry已改ConfigParser.set，401精确异常/1请求含key，partial真实main。父独立CLI+translate59 passed in0.89s；代理full516passed5deselected in36.27s仅作其报告，待父全套。
- Sol原验收代理0a70已恢复，先独立复验atomic/CLI两个稳定区域，runtime官方完成后再验其六P1。旧未通过报告保持历史，新最终验收另写主docs，不覆盖不利证据。
- 新runtime范围：固定执行身份+compare-remove；boot nonce防ABA；stop/drain冻结tuple回滚；promotion异常重试且worker不死；跨FS安全copyback真实sink，最终短发布点fencing，不先成功再无条件回写。atomic代理修callback全权写后不得锁外第二写；CLI fixture去重复retry并精确断言真实HTTP。
- 父远端复核：实际子repo origin为japan-media-skill-hub/video-stt-translate-server，gh viewerPermission=ADMIN，默认main且Actions enabled=true。
- 七P1已全部官方修复并由Sol原真SQLite/文件反例独立复验关闭；父完整pytest 529 passed/5 deselected in39.83s，Sol完整529passed in39.86s；实际跨FS与copy期间dirswap安全两路径均独立通过。新Sol round4报告保留技术通过/运营验收未完边界。
- 已创建并push首个feature提交 bba96a0709e1bcc05debc893461da3292f06a28d（未改remote main），源hash保持af58/runtime、c24d/repo、deb0/atomic。Git CLI legacy credentialhelper失败已调查，用命令作用域GH现有凭据helper成功，未打印/复制token、未改全局凭据。
- 真实首CI run39981535390失败：https://github.com/japan-media-skill-hub/video-stt-translate-server/actions/runs/39981535390 。失败在uv lock --check，lock隐含TUNA默认index而runner默认PyPI。官方delivery1dbc已接修锁可移植性，不能跳过check；修后再两个新commit远端CI绿。CIwatch作业bash-1892已收集exit1，push失败bash-531c已收集exit128，无父未收集相关运行作业。
- root .gitignore/docs/pyproject/uv.lock已显式stage并secret扫描，保留AGENTS和root脚本既有未提交改动未stage；根prometheus-client缺项已官方补并锁，最终提交前须重add最新授权文件。原子仓库尚未FF整合，v0.5tag尚未打。

## 历史续作状态（以下为先前快照）

- 用户已要求继续，goal已resume，revision=2；不提问。
- Goal round3确认：最小CC探测fbc58ca9仍turn/end HTTP400/QUOTA(insufficient credits)，与round1 probe26d1、round2 probef3b9为同一条件连续3轮；指定实施模型无法启动。已核runtime/atomic/translate/CLI四份SHA256与Sol最终报告完全相同，7P1仍未修，75项工作树改动安全保留且未发布。将目标标blocked而非complete，恢复条件为指定CC路由额度可用；未请求用户切换模型或购买额度，未改凭据。
- Goal round2复查：最小CC low探测f3b95e66仍立即HTTP400/QUOTA(insufficient credits)，已独立解码其turn/end证实，同一阻碍持续第2连续目标轮。未切换实施模型。父另验证secret scanner自测/当前扫描/diff检查通过，未排除两失败的其余CLI6例通过(2 deselected，明确不是全CLI通过)。无相关运行后台任务，目标继续active未完成。
- 原子仓库仍未整合；全部实现仍在.worktrees/reliability-hardening，feature分支未提交。
- 父当前全套pytest `bash-ce5ac58da3424867` 已收集exit2：test_translate_reliability.py在1498行截断，run_translate调用未闭合。已交CC583优先补完整测试；此前各代理宣称“编辑中”的旧快照不能当当前验收证据。
- 当前独立复验：父稳定A/D/F/G/runtime相关81测试通过；真实CPU extract+STT manual作业bash-676733fa180947ec已收集2 passed/1 deselected in6.19s，未调用LLM。新全套bash-df4e9f4d0c184981已收集2 failed,511 passed,5 deselected in36.30s；失败为新CLI 4xx计数0/partial配置重复retry，不算全绿。Sol已确认两失败均fixture追加重复retry（4xx宽Exception掩盖DuplicateOption所以0请求），仍需CC修fixture并真实验收。
- Sol核当前CLI新main已委托统一run_translate、llm_overrides仅内存、旧cp安全失效，不再沿用旧“CLI完全未实现”的历史描述；D当前_slot确实覆盖普通/batched transcribe+完整lazy迭代，WhisperX同样覆盖同步链。独立269pass含真实lazy峰值1回归。
- 指定CC路由当前明确外部阻塞：新runtime/CLI代理及最小low probe26d1均立即失败，已解码其session多zstd frames确认turn/end error code=QUOTA、HTTP400、insufficient credits。不是上下文长度或代码失败；不能擅自换实施模型，不能声称完成。没有购买额度/更改凭据。Sol仍可审查、不得实施修复。
- Sol0a70最终只读验收已收尾：docs/superpowers/executions/2026-10-23-sol-final-review-round3.md，结论不通过，七P1未修（copyback缺sink/动态借新lease/finally删新lease/stop回滚新owner/promotion异常杀worker/atomic锁外二写/跨runtime租约ABA）。报告含A-I矩阵、真SQLite/文件实证、snapshot hashes和修复顺序。D独立确认lazy slot正确，CLI主流程统一但2fixture待修；一次restart集成失败隔离重跑3pass仍记录不稳定。该Sol全部3后台job已收集，父全部bash亦已收集，无相关后台运行。CC QUOTA外部限制未恢复，未提交/未合原子仓库/未打v0.5.0/未远端CI，不能标完成。
- 最新未修独立P1（Sol0a70）：runtime stop/forceDrain只task_ids回滚会把已被w2接管任务重置queued；publish_task_artifacts抛OSError穿透worker loop致stage唯一worker死亡；atomic_write_text_fenced回调已锁内落盘后再次锁外atomic_write允许旧worker覆盖新checkpoint。连同缺copyback/动态借新lease/finally pop，必须恢复CC后修。
- 新独立P1租约ABA：_spawn_stage_workers使用extract-w1等跨runtime可复用owner，retry_job将attempt重置0。旧extract-w1/attempt0暂停→过期failed1→API retry清0→新同名worker claim0→旧publish竟通过并正式发布STALE。必须每runtime boot nonce写入lease_owner，必要时持久claim generation；仅staging nonce和固定callback身份都不足。debug recovery_counts=false同样回归。
- Sol复验确认此前C/D/G/F/A修复通过；launcher正在查真run路径。新P1：runtime传defer_copy_back=True却未有promote后copyback sink，已交6e92修，并由4f新增真实run_translate fakeHTTP/真runtime回写安全集成。
- 正式决策：CLI翻译必须复用服务引擎同等加固，不能仅改README缩scope。CC583实施main委托+内存llm_overrides，保留CLI参数/旧函数注释；旧无sourcehash检查点须失效，补真实CLI/HTTP回归。
- CCc7负责移除launcher测试对SyntaxError/ImportError等skip容错，关键产品启动失败必须测试失败。
- 旧代理runtime6e92/translate583/Sol10d5恢复后再次上下文失败，已停用其编辑权并创建新上下文：runtime/copyback/checkpoint身份 `f4804390-0018-4a92-8870-fd0fbec77ae0`（CC Flash）；CLI统一引擎 `acf5a7ec-abff-456c-9cc2-98d981a27d7d`（CC Flash）；最终独立验收 `0a70d692-87f8-442a-b1eb-240f4e18dda0`（GPT-6.1-Sol high）。老代理inactive不可再同时编辑。
- 新runtime P1：checkpoint_publish动态从taskid字典借新租约credentials+finally无条件pop新lease，要求固定实例credentials/compare-remove；canonical目标固定不能只比basename；与缺失copyback一并修。
- 已报告修复待独立复验：C部分id/失败后在途checkpoint；D slot超时放行/错误release/LRU释放收敛/lazy generator迭代许可；F网络盘DELETE失败failfast；G readonly主DB写就绪探针；A损坏deps级联；launcher配置同源；runtime nonce私有stage+事务promotion+finally清理+11日志。
- 后续必须完整pytest/compile/scanner稳定全绿→Sol复验→安全提交与原子仓库ff整合→本地v0.5.0→两个新提交远端CI证据→主docs/根依赖跟踪。真实2h/GPU/供应商token撤销仍无证据，不得虚报完成。

## 目标与约束

依据 `docs/superpowers/specs/2026-10-22-whisper-stt-reliability-and-translation-hardening-spec.md` 完成 A–I；用户要求不中途提问。实施使用 `command-code/deepseek/deepseek-v4.1-flash-fast`，最终独立验收使用 `openai-codex/gpt-6.1-sol`。保留现有修改、注释及 docstring；Python 仅使用主仓库 `.venv`。

## 开发位置

- 子仓库开发工作树：`.worktrees/reliability-hardening`
- 分支：`feature/reliability-hardening`，基线 `b029d07`
- 原子仓库已有 `.gitignore`、`config.example.ini`、`executor/translate.py` 未提交修改，已复制到工作树，原工作区保持原样。完成后必须整合回 `whisper-stt`，不得漏掉开发工作树成果。
- 主仓库已有多处用户未提交修改，不覆盖、不清理。

## 基线

- 原子仓库：`/home/base/repo/video-stt-whisper-server/.venv/bin/python -m pytest tests/unit -q`
- 结果：55 passed in 18.36s（2026-10-22）。

## 批次与状态

- [ ] 1 生命周期主体完成且cancelled job已修收敛failed/释放路径；drain stop总deadline已修。最终关键P0未完成：仅cancel_check+SQL fencing不足保护物理产物（旧attempt可在检查后os.replace覆盖新结果）。已分派runtime6e92 staging编排、repo c7事务fenced promotion、translate583新增checkpoint_path/defer_copy_back/checkpoint_publish联合修复，详见下方。
- [ ] 2 API/DAG + wav + 安全：DAG 语义与翻译 override 白名单已实现；父代理验证新增/原有 DAG 用例 48 passed in 0.06s；IO/安全待整合
- [ ] 3 模型缓存与实例信号量：执行器/缓存实现及单测完成，循环与语法问题已修，父代理全量277 passed in 2.92s。尚待runtime model_cache_size/model_parallelism配置与bootstrap configure/clear接入。ASR代理续接fake executor集成测试（仅新测试文件）。
- [ ] 4 翻译并发、检查点、原子写、缺失 id、成本控制：主要实现已就绪，父代理独立验证翻译3个测试文件 33 passed in 0.37s；继续边界自审与runtime整合。run_translate新增job_config=task_cfg/cancel_check布尔回调，common.ExecutorCancelledError与MissingAudioArtifactError(path)已就绪，atomic工具已就绪。
- [ ] 5 可观测性：代理 `7658596f-cafb-4595-a72a-0bd5d9dce3c9` 正在实现 app/queue/health/logging/metrics（含 app 鉴权/docs），runtime/bootstrap/config 接入待生命周期完成。F数据库迁移/网络挂载识别已完成，父代理独立验证migration+schema测试20 passed in 0.10s；service代码ruff E9,F821已验证通过。
- [ ] 6 CI/CPU源覆盖/secret scanner/manual测试迁移/README中英与docs初步完成；本机config parallel2其余值保留且新键已加；历史tag v0.4.0已补。父独立运行secret scanner selftest10例+当前tracked扫描+compileall+ruff E9,F821全部通过。最终文档对齐进行中；v0.5.0/提交/远端两次CI/根锁文件跟踪/原子仓库整合/密钥提供商撤销轮换尚未完成。
- [ ] 最终 GPT-6.1-Sol 独立验收与修复：已启动openai-codex/gpt-6.1-sol high代理 `10d5e1da-60f0-4144-a208-7417464f27ac`，只读验收A–I与最小复现，先审稳定模块；runtime P0接线完成后须通知其复核最终快照。修复仍由CC实施代理执行。
- [ ] 真实 2h E2E/恢复、性能与显存记录（必须核查素材和硬件，不以 fake 替代真实证据）

## 活跃代理（共享工作树，文件职责隔离）

- 生命周期：`6e92e3b6-f623-42de-bd80-03f66bc0a4ed`：repo/runtime/bootstrap/config/jobs/admin
- 翻译：`583b7abf-fb9f-4331-b996-3d907f956c3c`：translate/common/atomic 与新增测试
- ASR/缓存：`4f965689-5a87-45e2-a9f0-f897532bed1c`：model_cache/stt/stt_whisperx/extract 与新增测试
- DAG/安全纯工具：`c7fad24d-0a88-483f-8bd4-1069919d365b`：已完成。core/security.py 提供 SessionConfig、SecurityError、resolve_video_path、resolve_copy_back_dir、validate_startup_token、tokens_match 等；含符号链接逃逸测试。已重新委派 F 数据库迁移与 WAL 网络挂载识别，database.py 所有权由生命周期 owner 正式释放。
- 最新契约：显式 version=null 拒绝；translate.progress_ttl_sec>=0 已加入 override 白名单。
- 交付代理已在主 venv 窄安装 prometheus-client 0.26.0 与 ruff 0.17.1，未全量 sync。
- 全量验证须待 ASR 修复 stt.py 进行中的拼接语法残留/循环导入；生命周期 owner 另需修 fenced_stale_result 漏引号以及清理 .batch1_scratch 临时片段。
- 观测：`7658596f-cafb-4595-a72a-0bd5d9dce3c9`：api/app、api/routes/queue、logging/metrics/health，以及已正式接手config/bootstrap/example/main全部配置装配。ASGI middleware递归已修为保存下游class，父代理最新全量396 passed in 5.73s（后台bash-0341ffad3c3a4226已收集）。disabled metrics应不论token均404已明确要求，enabled仍鉴权。

## 下一步整合顺序

1. 生命周期已完成本批并释放：c7fad24d现拥有repo/job_repository.py + repo/models.py + api/routes/jobs.py（B3/H io/路径、cancel终态、retry）；7658596f现拥有core/config.py + service/bootstrap.py + config.example.ini + main.py（H/G/D/C配置装配）；6e92e3b6仅保留runtime.py + admin.py（IO/metrics/TTL/有界stop）。三者已收到正式任务继续实施，无需再等待确认。
2. 交由 CC Flash 实施 B.3 入队 io/artifact 路径、runtime wav 传参、H security 配置/路径接入、安全 run_service.sh、模型缓存生命周期接入、翻译全部有效参数默认/override 接入。
3. 完成 F schema_migrations 自动事务化迁移、网络文件系统 WAL 回退、claim P95/busy 与 EXPLAIN 日志。
4. 整合 G 日志/指标到 bootstrap/runtime/翻译/缓存，checkpoint TTL 清理，fake executor 故障/恢复端到端集成。
5. 更新测试兼容：test_repository_dependency_payload 旧 stt无extract依赖形态需修正（保持多依赖断言意图）；test_worker_recovery 需适配恢复结果含计数的新返回契约。
6. 全量验证、文档核对、最终Sol审查后修复，再工作树提交并整合回原子仓库；可在原子仓库安全stash既有3处改动（已被工作树完整包含，保留stash不删）再main --ff-only合入feature，避免覆盖原未提交用户工作。必须比对原改动未丢。v0.5.0打最终稳定commit；feature分支远端两次新提交CI绿后再最终整仓Sol验收。
7. 最新委派：c7fad24d继续F/G repo claim P95/busy、有界采样/list_finished_since、enqueue request_id持久化task_config.metadata.request_id、repo task日志完整字段及global copy_back默认生效；6e92e3b6同步runtime日志完整字段。

## P0 产物级 fencing 联合修复（最新任务）

- runtime owner 6e92e3b6：所有执行器输出指向每attempt唯一staging；正式产物只经repo事务promotion，旧worker只能写自身staging；下游读正式ctx io。成功promotion后不再重复mark_succeeded。copyback必须promotion成功后且roots/symlink重验，失败/stale不得回写。
- repo owner c7fad24d已实现：publish_task_artifacts(task_id,*,worker_id,attempt,artifacts=[(staged,final)],request_id=None)->bool 在BEGIN IMMEDIATE验证有效租约/owner/attempt后rename+mark_succeeded/job刷新；stale不写任何正式文件。with_task_lease(task_id,*,worker_id,attempt,action)->bool 在事务中fence checkpoint副作用不改任务状态，stale不调用action。13例真实tempfile回归已由代理报告通过，repo不导入executor避免循环。parent已转精确接口给runtime，待接入。多文件FS rename不能回滚，需要如实描述失败恢复，不虚称事务FS原子。
- translation owner 583b7abf：run_translate兼容可选checkpoint_path(稳定canonical)、defer_copy_back=True(runtime用)、checkpoint_publish(path,text)->bool；checkpoint失败/失租不得发布。不改原默认脚本行为。
- 必须增加真实文件旧attempt阻塞→reap→新attempt发布→旧attempt复活仍保留新内容的回归，不接受只SQL断言。ASR集成owner已确认采用a：执行器传入staging，runtime统一promotion，不再讨论仅DB fencing。
- 父代理default全套pytest后台 `bash-a814d2d4b31341c8` 正在运行，必须收集；已包含integration(普通fake gate已修7pass)、manual/e2e默认deselect。
- runtime统一11字段日志仍待完成：request_id读ctx.task_config.metadata.request_id；repo已完整实现。
- Sol已独立repro确认3个P1并转CC修：C5真实APIhelper缺id即丢已有mapping抛错，无法fallback；C1并发一批失败后另一在途成功也拒checkpoint；D ModelLease.acquire_transcribe_slot超时不拿许可就放行且release释放他人许可，真实STT/WhisperX均使用。翻译583修前两+补缺失payload的幂等subbatchid，cache4f修排队/owner许可。不能宣称C/D已验收。
- Sol又确认launcher --config只选监听但未让bootstrap读同配置（仍WHISPER_STT_CONFIG旧路径）P1，已交c7修并要求真正bootstrap回归不只print。
- 父额外核实runtime ArtifactStaging路径只attempt+taskid，不含worker；debug recovery_counts=false时同attempt跨owner共用stage，已交6e92改固定nonce+worker hash保证每个实例唯一并测试，Sol已知待复核。
- Sol再确认G P1：readyz只写TEMP，mode=ro DB仍返回可写，已交obs765修main canary write+rollback及真实ro反例。F P1：WAL DB读锁阻止切DELETE，_disable_wal吞异常并谎报delete（实际wal），已交repo c7改failfast并真实锁回归。A P2：损坏extract依赖JSON使claim置failed但不cascade，stt/translate幽灵queued，已交c7同事务级联+refresh。
- cache4f已报告修许可超时不放行/只归还自持slot/重复release幂等/cancel轮询，27真实BoundedSemaphore用例通过，待Sol复验。
- fake集成普通7例曾全通过；新stage接入后断言已更新，剩旧attempt放弃路径未cleanup stage，已交runtime6e92统一finally清理自身唯一stage（不得扫别人文件）。
- 父default全套job bash-a814d2d4b31341c8已收集exit1：三例integration旧路径/.published假标记断言不适配新staging(已ASRowner更新增强)，另cache日志次序问题obs修。无父未收集shell后台作业。

## 交付注意

- SPEC 要求轮换曾落盘的 HF token/API key；本地清理不等于提供商端已撤销，不能捏造轮换完成。
- SPEC 要求两个远端 CI 绿、版本 tag、真实 2h 样本；须分别收集证据，不能仅以单测全绿宣称全目标完成。
- 已补本地历史tag v0.4.0 -> b029d07（未push）；v0.5.0须最终稳定提交后再打。
- 观测到子仓库origin实际为 https://github.com/japan-media-skill-hub/video-stt-translate-server.git，与AGENTS旧地址不同，不擅自覆盖remote；gh auth当前zztdandan登录可用，后续CI可尝试feature分支（不得覆盖main）。
- 安全默认拒绝空/占位 token，更新现有测试需显式禁用鉴权或设真实测试 token。
- 后台 shell 基线作业 `bash-0624c5c49d0e4878` 已收集；集成单测作业 `bash-7cf852a10fb24b57` 已收集，277 passed in 2.92s。
- 真实30s CPU离线基线 `bash-4761880e835b48d6` 已收集成功：原whisper-stt/transcribe_video.py + faster-whisper-small、cpu/int8、预抽wav，wall=5.70s，RSS=1180304KB，segments=5，字幕末条29.540s/媒体30.016s。输出tmp/real-media-baseline/sample_30s.ja.srt。不能当作2h完成。
- 新工作树同样30s CPU对照 `bash-accd7824e5084e2d` 已收集成功：wall=5.90s，RSS=1178104KB，segments=5，末条29.540s。父代理用read比较前后SRT全文完全一致（文本差异0）。两次是CPU短片实测，不代表2h/显存/真实翻译验收。
- 真实服务执行器manual extract+stt离线CPU测试 `bash-e3f0bd3789eb49b5` 曾失败(exit1)，两例ffmpeg extraction failed。4f965689已修临时.part无容器（临时名.wav且-f wav），并修extract/STT/WhisperX先preclean正式产物违反失败保留。代理复跑真实manual两例2 passed（sample30s/small/cpu，未调LLM），补命令构造和真实ffmpeg回归；真实冒烟要求manual/optional，不让默认unit依赖ffmpeg。
- CI smoke已由交付代理本地验证：显式注入测试token，wrong=401、queue/health=200、missing-model ready=503且不创建假模型目录；未远端CI验证。
- B3/H接入决策已确认给c7fad24d：repo不强制视频存在但做规范化/absolute/extension/roots；API严格exists/isfile/resolve；TaskExecutionContext必须加input_path/output_path默认字段；严格audio/asr/translate目录无过渡；默认copyback仅视频目录，非空roots可配置放宽；等待生命周期释放repo/models/jobs。
- ASR代理4f965689续接fake executor集成测试：曾7例超时，父读源码已定位fake bug（新gate默认unset、_gate_publish无条件等待而正常测试从未set，非GIL猜测）；已要求正常gate默认open，仅特定故障显式close，去除_TestClientWithState及timeout_probe workaround后复跑。
- 翻译代理583b7abf脚本模式全链已完成且真实API smoke成功。观测代理7658596f已完成config/bootstrap/example新字段装配，父复验test_config_integration为18pass1fail(JSONL实际request_id缺失，仍需修，不放宽断言)。交付代理已通知现在开始最终文档对齐，不能写全目标已完成。
- 交付代理：`a111f1ea-137d-4d68-8e01-8794e31e0309`，负责 CI/pyproject/lock/README/manual 测试和主 docs（不改本记录）。
- 真实环境初查：ffmpeg/ffprobe 存在；nvidia-smi 退出 255，NVML 报 GPU access blocked by operating system，无法采集 GPU 峰值。已调查确认不是测试失败。配置前两个长片路径不可用；本地样本分别 30.03s、180.08s。small/large-v2/large-v3-turbo 权重存在；不能替代真实 2h 样本验收。
- 583b7abf已续派受控真实LLM 5字幕smoke：源tmp/real-media-hardened/sample_30s.ja.srt，原config凭据不回显；本次override retry1/HTTPtimeout60/总120，并行2；输出与copyback严格tmp/api-smoke，不写原视频目录。第二次相同配置注入禁止网络post确认checkpoint复用0请求。代理后台bash-82cd4921bdd1484e已自行收集成功：真实OpenRouter/DeepSeek-v3.2单次HTTP200，1请求/17.49s，ja5->zh5，末条时间一致；usage321prompt+358completion=679/cost0.0001778616。第二次注入禁止post，0请求/0.009s，checkpoint1批done，确证续跑不重复计费。父代理read核实实际zh/progress产物结构。仅API smoke非2h/完整E2E/翻译质量验收。
- CI CPU方案A环境变量单独覆盖已实测无效（explicit uv.sources优先）；交付代理新增CI临时改CPU源脚本，dry-run证据torch/torchaudio+cpu、0个nvidia待安装、httpx可解析，部署lock仍cu128。远端CI尚待最终提交后实测。

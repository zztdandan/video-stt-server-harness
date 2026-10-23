# Sol最终独立验收第四轮（续验，持续更新）

## 范围与状态

2026-10-23 23:25 CST恢复。用户授权实施改官方DeepSeek V4.1 Flash，Sol仍只读审查/临时实验，不改实现、不提交、不调用付费网络、不读真实凭据。主AGENTS/SPEC约束不变，Python仅主仓库.venv。历史[第三轮未通过报告](/home/base/repo/video-stt-whisper-server/docs/superpowers/executions/2026-10-23-sol-final-review-round3.md)保留，不覆盖。当前HEAD仍b029d07。首批记录时runtime修复并行；23:38父正式冻结业务源码后，Sol已完成下方七项原反例复验。**七项技术缺陷已独立复验关闭；发布交付仍未完成，不能称完整SPEC已通过。**

## 第一批：atomic/CLI独立复验

### R3-3锁外二写：原反例已通过

位置：[atomic:68–101](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/executor/atomic.py#L68-L101)。读代码确认callback成功表示全权发布，helper不再写第二次；非bool抛TypeError。

独立执行原真SQLite/真实文件反例：w1在with_task_lease内写旧cp→提交后模拟抢占→回滚w1/claim w2→w2锁内写NEW OWNER CHECKPOINT→返回旧helper。**最终正文仍NEW OWNER CHECKPOINT**，不再变STALE。None/1/string回调分别TypeError，目标正文保持NEW。实验exit0。此结论不依赖新增测试数量。

### CLI此前两个失败边界：独立通过

[fixture:84–105](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/tests/unit/test_cli_translate_hardening.py#L84-L105)改ConfigParser.set覆盖，不再append重复retry。

- [401测试:225–251](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/tests/unit/test_cli_translate_hardening.py#L225-L251)：精确TranslateNonRetryableError、cause HTTPError且status401、HTTP仅1次、有Idempotency-Key。
- [partial测试:277–314](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/tests/unit/test_cli_translate_hardening.py#L277-L314)：真实main默认统一引擎，经fake HTTP初次+缺失ID重试共2请求，保留已得译文及缺失项原文，不丢行。
- 独立主venv pytest只选此两例：**2 passed in0.10s，exit0**。未触网、未消费token。

### 稳定翻译套件

独立运行CLI hardening、translate reliability、translate copy_back三个完整测试文件：**61 passed in0.87s，exit0**，后台bash-882405698c7f40c5已收集。仅使用fake HTTP，无付费请求。

## 冻结runtime最终复验（23:38后）

父确认无其他业务编辑者。Sol只读代码，实验均用独立临时SQLite/文件，不改实现。最终全套后SHA256与父冻结一致：runtime=af58f6677af8c2ff2ad5747fe68183fe4b7bdb23bf76db987c5361492696a52a；repo=c24dcfe96866b9880098875fc572f98e71fcbbeb80abebc91de61a8ed4e0505e；atomic=deb0dc1ffa01f8cb9354e38c4d5234f41c64d92832894128b911c0a556b6a68a。

### 七项原P1闭环矩阵

| 第三轮问题 | Sol独立实证与实际结果 | 当前结论 |
|---|---|---|
| R3-3 atomic事务外二写 | 原SQLite反例：w1事务提交后w2接管写NEW，再返回旧helper，最终仍NEW；非bool拒绝且无写 | 已关闭 |
| 旧checkpoint callback借新map身份 | 构建旧callback；expire/reap/claim新owner；map指向新lease；canonical写NEW；旧callback返回False，NEW不变 | 已关闭 |
| 旧finally删除新lease | 真实_execute_claimed旧frame中reaper/新claim并替换map；旧finally退后map对象仍是新lease，新workerstate保留 | 已关闭 |
| R3-1 stop/drain撤新owner | 原SQLite反例分别调用旧runtime.stop和_force_drain_timeout；新claimed/owner/attempt/last_error整行前后完全相同 | 已关闭 |
| R3-2 promotion OSError杀worker | 原_execute_claimed注入同一OSError不再逃出，task变queued/attempt1/publish_failed:OSError；另独立运行真实worker线程回归，首次失败后继续领取至succeeded/attempt1，线程alive且有task_failed日志 | 已关闭 |
| R3-4 owner/attempt ABA | 两runtime同stage-slot不同bootowner；原retry清attempt0与debug恢复false保0两路径，旧owner publish均False，canonical保持NEW | 已关闭 |
| 旧defer_copy_back无sink | 自建真实跨FS：artifact工作树dev2096，视频/tmp当次dev105，同进程assert不同；真run_translate仅fakeHTTP；ja/zh真实回写且两正文逐字节=canonical，succeeded，1请求/2copies，无临时残留 | 已关闭 |

以上原反例由Sol独立inline Python重放，均exit0，不只相信新增测试数。实现位置：[boot worker identity:542–562](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L542-L562)、[finally compare-remove:809–865](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L809-L865)、[checkpoint:1845–1919](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L1845-L1919)、[stop:380–397](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L380-L397)、[drain:700–723](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L700-L723)、[promotion异常收敛:1030–1057](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L1030-L1057)。

### 目录切换TOCTOU与跨FS安全

- 完整阅读[prepare:1392–1533](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L1392-L1533)、[CopyBackPlan:2511–2618](/home/base/repo/video-stt-whisper-server/.worktrees/reliability-hardening/whisper_stt_service/service/runtime.py#L2511-L2618)：O_DIRECTORY/O_NOFOLLOW打开并校验目录fd，O_EXCL相对dirfd创建临时，慢copy锁外flush/fsync；租约事务prepublish校验fd路径/文件类型，再同dirfd rename；close通过原fd清理。
- Sol自建两个不同设备上的实验：一在慢copy全部结束后、repo发布前将视频目录rename并换symlink outside；二在第一份copy结束、第二份目标尚未open时相同切换。**两条都queued/attempt1/copy_back_target_dir_changed；outside无任何正式/临时文件，moved原目录无临时残留。** 中途切换证明第二次临时写仍锚定旧fd，未跟随新父symlink。
- 独立新增runtime身份/回写集成文件：12 passed in2.90s，exit0，bash-417bdb843a274f63已收集。读过关键真实线程/SQLite/文件测试，无产品import失败skip；含外部roots篡改拒绝、文件symlink拒绝、失租copyback不覆新内容。
- 设备号随工具临时mount namespace变化；父/代理的/tmp可能111/115等，本轮只以同一实验进程stat与两边st_dev不等断言为准。
- 多文件rename无法FS整体回滚仍为已知且如实记录的边界；当前是租约事务互斥与失败重试收敛，不将此误认七项P1未修。

### A–I当前矩阵

| 区域 | 当前技术验收 | 仍需区分的交付边界 |
|---|---|---|
| A生命周期 | 新旧租约、stop/drain/finally/ABA/promotion错误原反例通过；reaper/cascade/retry现有测试通过 | 待交付快照确认 |
| B API/DAG/IO | 既有独立DAG/安全/路由/IO测试通过，发布身份闭环 | 兼容与错误码以当前测试为界 |
| C翻译 | 部分ID/在途checkpoint/原子写、七P1相关checkpoint/copyback及CLI原两负例通过 | 不代表2h/供应商翻译质量验收 |
| D模型 | 上轮独立cache/LRU/slot/lazy完整迭代通过，本轮业务未改该区域 | 无GPU峰值证据 |
| E wav | 合约测试及既有CPU30s证据有效，本轮无相反证据 | 不能替代2h |
| F SQLite | WAL/DELETE失败failfast/迁移/readonly测试通过；本轮tuple/prepublish真实事务闭环 | 多文件不是FS事务 |
| G观测 | 探针/日志/metrics测试通过；本轮promotion失败有task_failed错误与重试证据 | 不替代远端运维验收 |
| H安全 | token/roots既有通过，本轮目录切换/文件symlink/真实跨FS sink通过 | 提供商token撤销轮换仍无证据 |
| I仓库/CI/文档 | 尚未完成交付验收 | 源整合/提交/tag/两个新提交CI/根锁与docs跟踪待父提供 |

### Sol最终全套独立结果

独立主venv执行pytest -q：**529 passed,5 deselected in39.86s，exit0**，后台bash-b1ad6b0f05804e66已收集（已包含新增实际crossFS文件）。全套后runtime/repo/atomic hash仍匹配本段冻结值。先前restart集成一次不稳定证据保留于round3；本轮最终full无失败，不改写历史。所有本轮相关后台作业已收集。

**本轮技术结论：已报七项P1闭环通过，无本轮新确认P1；整体SPEC发布交付尚不通过。** 该结论基于原反例与真实跨FS/目录切换实证，不是单靠529数量。未改实现、未提交、未调付费网络、未读真实密钥。

## 不变的交付边界

源整合/提交/tag/两个新提交远端CI/主根锁与docs跟踪尚需父完成。真实2h/GPU峰值、供应商token撤销轮换仍无证据；短片CPU与API smoke不能代替。

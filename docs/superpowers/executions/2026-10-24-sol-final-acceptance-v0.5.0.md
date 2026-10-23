# Sol 最终交付验收：v0.5.0

- 验收人：用户指定 GPT-6.1-Sol；时间：2026-10-24（Asia/Shanghai）。
- **最终结论：验收通过。最终冻结快照 699bb857ecbad65537bd7247700865bf8eebc7b4；无未关闭 P0/P1 或本次发布阻塞项。**
- 02:10 后续独立复验：完整 pytest 532 passed / 5 deselected（35.55s）；restart 用例五轮通过；最终 feature/main/tag 三个远端 run 均 success。中途 CI 失败与原测试竞态证据完整保留于第 9 节，修复闭环见第 10 节。
- 本次只读实现，仅新增本报告；未 git add/commit/push/tag，未安装依赖，未发付费请求，未打印本机真实凭据。
- 依据：[可靠性与翻译加固 SPEC](</home/base/repo/video-stt-whisper-server/docs/superpowers/specs/2026-10-22-whisper-stt-reliability-and-translation-hardening-spec.md>)。按本次用户直接指令，真实 2h、GPU、供应商端 token 轮换列发布后跟踪，不计本次失败；**不等于原 SPEC 的这些真实环境标准已完成**。

## 1. 快照、提交与远端身份

首轮完整测试与原 P1 实验实际运行时的快照（最终 699bb85 上又独立执行完整 pytest，结果见第 9 节）：

| 对象 | 独立实测身份 |
|---|---|
| 子仓库本地 HEAD / 远端 main | c88cc80564174903c111489b54e8061771ce96c4 |
| 原 annotated v0.5.0 object | 6732f9c4a48ef2699f553ba49b8c33c31b4dbf44 |
| 原 tag peeled commit | c88cc80564174903c111489b54e8061771ce96c4 |
| 主仓库交付提交 | ee1cf98；父后续执行记录提交 4ee839d27ce75c78fa2464064b12df44e416200a |

验收期间父先定稿 README，随后官方 Flash 修复 restart 测试同步竞态、父定稿发布文档并移动 tag。本代理对冻结最终快照再次独立复核：

| 对象 | 最终复核身份 |
|---|---|
| 子仓库本地 HEAD / 远端 main | 699bb857ecbad65537bd7247700865bf8eebc7b4 |
| 最终 annotated v0.5.0 object | 901214f5767d2f79d113a650247c9b3552b63f9f |
| 最终 tag peeled commit | 699bb857ecbad65537bd7247700865bf8eebc7b4 |
| 历史 v0.4.0（起初仅本地存在，父补 push 后复核） | 远端 b029d07d569da2c3aa52dee98608f7350de664a7 |

tag 为 annotated、unsigned，不冒称签名验证通过。移动 tag 是将交付说明纳入发布树，并非修改实现。实际命令（子仓库 cwd）：

~~~bash
git rev-parse HEAD
git ls-remote origin refs/heads/main refs/tags/v0.4.0 refs/tags/v0.5.0 'refs/tags/v0.5.0^{}'
git cat-file -t v0.5.0
git rev-parse v0.5.0^{}
gh api repos/japan-media-skill-hub/video-stt-translate-server/git/ref/heads/main
gh api repos/japan-media-skill-hub/video-stt-translate-server/git/ref/tags/v0.5.0
gh api repos/japan-media-skill-hub/video-stt-translate-server/git/tags/901214f5767d2f79d113a650247c9b3552b63f9f
git diff --name-status c88cc80564174903c111489b54e8061771ce96c4..HEAD
git diff --name-status fd383c93e45f90cb474a0704df283d1b627342cb..HEAD
git diff --exit-code c88cc80564174903c111489b54e8061771ce96c4..HEAD -- whisper_stt whisper_stt_service .github pyproject.toml uv.lock config.example.ini scripts .gitignore
~~~

均 exit 0；cat-file 返回 tag；API ref/object/peeled 与最终表一致。c88cc80→fd383c9 当时仅 README 中英文档差异；fd383c9→699bb85 最终差异为中英 README 加 tests/integration/test_runtime_fake_executors.py 单个测试文件，已逐段读补丁。所有生产实现、脚本、CI、配置、依赖/锁文件相对 c88cc80 差异为空，exit 0。此前中间发布为 f495fe0 / tag 4dc6a335a4f3f93a7fe58435450579a4df0670b0、fd383c9 / tag dbfe963b265cace4c08763af8b14a174b14045cb；最终 tag 因官方确定性测试修复 da43057397c27ab9905067f31792a940192fbed7 和文档对齐 699bb85 再重指。最终全量测试确实在 699bb85 独立执行，不仅沿用旧代码树推断。主仓库最终复核 7b9493bd15db61a02e8822fb500621d606b61bc5，gitlink 精确指向 699bb857ecbad65537bd7247700865bf8eebc7b4。

## 2. 独立执行的测试与卫生门禁

唯一 Python：/home/base/repo/video-stt-whisper-server/.venv/bin/python，版本 3.10.19。以下命令均实际执行，不仅引用父代理结果。

~~~bash
PYTHONDONTWRITEBYTECODE=1 /home/base/repo/video-stt-whisper-server/.venv/bin/python -m pytest -p no:cacheprovider -q
PYTHONDONTWRITEBYTECODE=1 /home/base/repo/video-stt-whisper-server/.venv/bin/python -m pytest -p no:cacheprovider -q tests/integration/test_runtime_lease_identity_and_copyback.py tests/integration/test_runtime_cross_filesystem_copyback.py
PYTHONDONTWRITEBYTECODE=1 /home/base/repo/video-stt-whisper-server/.venv/bin/python -m pytest -p no:cacheprovider -q tests/unit/test_translate_reliability.py -k "profile or dedupe"
bash .github/scripts/secret_scan.sh
bash .github/scripts/secret_scan_selftest.sh
(cd .. && bash whisper-stt/.github/scripts/secret_scan.sh)
~~~

| 门禁 | 本代理结果 |
|---|---|
| 完整 pytest | 首轮 c88cc80：**532 passed, 5 deselected in 39.90s；exit 0**；最终 699bb85 再独立跑：**532 passed, 5 deselected in 35.55s；exit 0**。两个后台作业均已收集 |
| 租约身份/真实 copyback/cross-FS 集成 | **13 passed in 1.98s；exit 0**，没有 skip |
| 用户 LLM profile / fallback / 去重 | **5 passed, 46 deselected in 0.11s；exit 0** |
| 子仓库与主仓库 secret scan | 均 secret scan passed；exit 0，最终文档提交后再次扫描仍通过 |
| scanner 自测 | 6 种 key 形态应命中、4 种合法/占位内容不误报；10 样本通过，exit 0 |

5 deselected 是默认 manual/e2e 选择策略，不是 5 个已执行通过的真实媒体测试。此轮没有打开真实 LLM manual 开关。

### 工作树与文件完整性

实际执行 git status --short、git ls-files、git -C .. ls-files、git -C .. ls-tree HEAD whisper-stt、git check-ignore .codegraph/ config.ini .venv/，并检查旧源文件/venv 是否存在：

- 子仓库全程（含最终纯文档提交后）status 无输出。
- 主仓库在父并行定稿时出现文档/gitlink 修改，非本代理遗留。父已明确允许的用户工作是 [AGENTS.md](</home/base/repo/video-stt-whisper-server/AGENTS.md>)、[run_shutdown_round.sh](</home/base/repo/video-stt-whisper-server/scripts/run_shutdown_round.sh>)、[submit_jobs_from_video_paths.py](</home/base/repo/video-stt-whisper-server/scripts/submit_jobs_from_video_paths.py>)、[video_paths.txt](</home/base/repo/video-stt-whisper-server/scripts/video_paths.txt>)；不纳入本轮提交，不改动。
- [主依赖清单](</home/base/repo/video-stt-whisper-server/pyproject.toml>)、[主锁文件](</home/base/repo/video-stt-whisper-server/uv.lock>)、[主忽略规则](</home/base/repo/video-stt-whisper-server/.gitignore>)及 [00](</home/base/repo/video-stt-whisper-server/docs/00-index.md>)–[04](</home/base/repo/video-stt-whisper-server/docs/04-troubleshooting.md>)、SPEC/plan/research/历史验收记录均已跟踪；ee1cf98 的 gitlink 为 c88cc80。
- [manual 测试](</home/base/repo/video-stt-whisper-server/whisper-stt/tests/manual/test_real_media.py>)已跟踪，带 manual 标记与 WHISPER_STT_REAL_MEDIA 显式 skipif 开关，ASR 前先 extract；旧 tests/unit/test_workers_real_media_inputs.py **既未跟踪也不存在**（遗留 pycache 不作为源文件）。子仓库独立 .venv 不存在。
- [子忽略规则](</home/base/repo/video-stt-whisper-server/whisper-stt/.gitignore#L9-L30>)保留 .codegraph/、.venv/、config.ini 等；[示例配置](</home/base/repo/video-stt-whisper-server/whisper-stt/config.example.ini>)保留 llm_fallback，以及 chunk_minutes=20、retry=10、extract_timeout_sec=3600、parallel=2。
- [fallback 实现](</home/base/repo/video-stt-whisper-server/whisper-stt/whisper_stt_service/executor/translate.py#L52-L125>)仍包含 profile 加载/启用开关、base/model/key 去重、attempt 1 主模型、attempt 2 起回退；独立 5 用例覆盖，不是只检查字符串。
- 本机密钥配置未全文读取/打印、未复制进临时目录；secret scan 无已知 token 形态命中。此结论是扫描能力范围内的检查，不冒称所有历史密钥均已撤销。
- 本代理用 git ls-files 结果逐路径检查 scratch/diagnostic/probe、缓存、config.ini/.env/*.token、db/sqlite/log/mp4/wav/pyc 可疑入库项，结果 **[]**；主仓库跟踪列表也无此类交付 scratch。已有用户未跟踪脚本不混作本轮垃圾。

## 3. 原 P1 反例：重新独立构造真实 SQLite/文件

不只运行新增回归测试。本轮重新手写 inline Python，使用真实 Database、JobRepository、WorkerRuntime 和磁盘文件；只借测试中的设置构造器生成隔离配置，不调用测试断言或 fake repository。实际命令如下（exit 0）：

~~~bash
PYTHONDONTWRITEBYTECODE=1 /home/base/repo/video-stt-whisper-server/.venv/bin/python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from whisper_stt_service.db import Database
from whisper_stt_service.repository import JobRepository
from whisper_stt_service.progress import ProgressStore
from whisper_stt_service.service.runtime import WorkerRuntime, FencedLease
from whisper_stt_service.executor.atomic import atomic_write_text, atomic_write_text_fenced
from tests.integration.test_runtime_fake_executors import _settings

def setup(p):
    db=Database(p/'q.db'); db.init_schema()
    repo=JobRepository(db, log_root=p/'logs', artifact_root=p/'artifacts')
    v=p/'a.mp4'; v.write_bytes(b'fake')
    repo.enqueue(str(v), 'ja')
    return repo

with TemporaryDirectory(prefix='sol-final-atomic-') as d:
    p=Path(d); repo=setup(p); old=repo.claim_next('extract','old',60)
    target=p/'checkpoint.json'
    def publish(path,text):
        assert repo.with_task_lease(old.task_id,worker_id='old',attempt=old.attempt,action=lambda: atomic_write_text(path,text))
        assert repo.rollback_claimed_task(old.task_id,worker_id='old',attempt=old.attempt)
        new=repo.claim_next('extract','new',60); assert new.task_id==old.task_id
        assert repo.with_task_lease(new.task_id,worker_id='new',attempt=new.attempt,action=lambda: atomic_write_text(path,'NEW OWNER CHECKPOINT'))
        return True
    atomic_write_text_fenced(target,'STALE OLD CHECKPOINT',publish)
    assert target.read_text()=='NEW OWNER CHECKPOINT'
    for invalid in (None,1,'true'):
        try: atomic_write_text_fenced(target,'WRONG',lambda p,t:invalid)
        except TypeError: pass
        else: raise AssertionError('non-bool accepted')
        assert target.read_text()=='NEW OWNER CHECKPOINT'
    print('R3-3 PASS: transaction takeover preserves NEW; non-bool None/1/string rejected')

for mode in ('stop','drain'):
    with TemporaryDirectory(prefix='sol-final-'+mode+'-') as d:
        p=Path(d); repo=setup(p)
        runtime=WorkerRuntime(repo=repo,progress_store=ProgressStore(300),settings=_settings(p),config_path=p/'config.ini',model_path=str(p/'model'),exit_callback=lambda:None)
        owner=runtime._worker_identity('extract',1)
        first=repo.claim_next('extract',owner,60)
        lease=FencedLease(repo=repo,task_id=first.task_id,job_id=first.job_id,stage=first.stage,worker_id=owner,attempt=first.attempt,lease_timeout_sec=60,heartbeat_interval_sec=60)
        runtime._inflight_leases[first.task_id]=lease
        with repo.db.tx() as c: c.execute('UPDATE tasks SET lease_expires_at=? WHERE task_id=?',('2000-01-01T00:00:00+00:00',first.task_id))
        repo.reclaim_expired_leases()
        second=repo.claim_next('extract','new-owner',60); assert second.attempt==1
        def row():
            with repo.db.connect() as c: return tuple(c.execute('SELECT status,lease_owner,attempt,last_error FROM tasks WHERE task_id=?',(first.task_id,)).fetchone())
        before=row()
        if mode=='stop': runtime.stop(timeout_sec=1)
        else:
            runtime.request_shutdown('sol-final'); runtime._force_drain_timeout()
        assert row()==before, (before,row())
        assert lease.lost
        print('R3-1 PASS:',mode,'new claimed tuple unchanged',row())
PY
~~~

实际 stdout：

~~~text
R3-3 PASS: transaction takeover preserves NEW; non-bool None/1/string rejected
R3-1 PASS: stop new claimed tuple unchanged ('claimed', 'new-owner', 1, 'lease_expired')
R3-1 PASS: drain new claimed tuple unchanged ('claimed', 'new-owner', 1, 'lease_expired')
~~~

stderr 另有明确 fenced stale lease rollback skipped、drain rolled_back=0，无异常逃逸。说明原“事务外二写覆盖新检查点”和“旧 stop/drain 撤销新租约”均未回归。

七项 P1 的其余边界由本轮独立完整 pytest 与 13 个针对集成重跑覆盖：冻结 checkpoint 身份、finally compare-and-remove、promotion OSError 后真实 worker 继续重试、跨 runtime boot nonce 防 ABA、真实 ja/zh copyback、失租/roots/symlink 拒绝、实际 cross-FS。上一轮全部原反例的独立实证保留在 [第四轮报告](</home/base/repo/video-stt-whisper-server/docs/superpowers/executions/2026-10-23-sol-final-review-round4.md>)；不覆盖第三轮失败历史。

## 4. 隔离启动、鉴权和探针冒烟

本轮亲自执行下列程序，不读取真实运行配置、不起对外服务器：

~~~bash
PYTHONDONTWRITEBYTECODE=1 /home/base/repo/video-stt-whisper-server/.venv/bin/python - <<'PY'
import configparser, os, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
with tempfile.TemporaryDirectory(prefix='sol-final-smoke-') as d:
    p=Path(d); cp=configparser.ConfigParser(); cp.read('config.example.ini',encoding='utf-8')
    for k,v in {'db_path':p/'svc.db','log_root':p/'logs','artifact_root':p/'artifacts','model_path':p/'missing-model'}.items(): cp['runtime'][k]=str(v)
    cp['security']['api_token']='sol-final-smoke-not-a-real-secret'
    cfg=p/'config.ini'
    with cfg.open('w',encoding='utf-8') as f: cp.write(f)
    os.environ['WHISPER_STT_CONFIG']=str(cfg)
    from whisper_stt_service.service.bootstrap import build_app
    app=build_app(); client=TestClient(app)
    headers={'X-API-Token':'sol-final-smoke-not-a-real-secret'}
    result={
      'wrong_token':client.get('/queue/summary',headers={'X-API-Token':'wrong'}).status_code,
      'queue':client.get('/queue/summary',headers=headers).status_code,
      'health':client.get('/healthz',headers=headers).status_code,
      'ready_missing_model':client.get('/readyz',headers=headers).status_code,
      'metrics':client.get('/metrics',headers=headers).status_code,
      'docs_disabled':client.get('/docs',headers=headers).status_code}
    assert result=={'wrong_token':401,'queue':200,'health':200,'ready_missing_model':503,'metrics':200,'docs_disabled':404},result
    assert not (p/'missing-model').exists()
    print('isolated bootstrap PASS:',result,'model_dir_created=False')
PY
~~~

exit 0；实际返回与 assert 完全一致。日志实际落盘、SQLite journal_mode=wal、迁移 1/2 应用成功、索引 query plan 输出，auth 日志有 request_id 且无 token 明文。没有创建缺失模型目录伪装 ready。

## 5. 远端 CI：历史失败保留，绿色逐 SHA 核实

本代理亲自调用 gh API 查询 runs、jobs、各步骤 conclusion，不把父陈述当成远端证据：

~~~bash
gh api 'repos/japan-media-skill-hub/video-stt-translate-server/actions/runs?per_page=12' --jq '.workflow_runs[] | [.id,.head_sha,.head_branch,.status,.conclusion] | @tsv'
for r in 39981535390 39995654486 39996457310 39997343133; do
  gh api repos/japan-media-skill-hub/video-stt-translate-server/actions/runs/$r/jobs --jq '.jobs[] | [.name,.conclusion,([.steps[] | select(.conclusion=="failure") | .name] | join(","))] | @tsv'
done
for r in 39997953791 39997946922 39997927908; do
  gh api repos/japan-media-skill-hub/video-stt-translate-server/actions/runs/$r/jobs --jq '.jobs[] | {name,conclusion,steps:[.steps[]|{name,conclusion}]}'
done
~~~

均 exit 0：

| run | SHA / 触发 | 独立查询结果 |
|---|---|---|
| [39981535390](https://github.com/japan-media-skill-hub/video-stt-translate-server/actions/runs/39981535390) | bba96a0 | failure；失败步骤 Verify committed lockfile is reproducible，保留历史 |
| [39995654486](https://github.com/japan-media-skill-hub/video-stt-translate-server/actions/runs/39995654486) | 66678d0 | failure；失败步骤 Run unit tests (CPU subset)，保留历史 |
| [39996457310](https://github.com/japan-media-skill-hub/video-stt-translate-server/actions/runs/39996457310) | 2623545 | completed success |
| [39997343133](https://github.com/japan-media-skill-hub/video-stt-translate-server/actions/runs/39997343133) | 5e67c7b | completed success |
| [39997927908](https://github.com/japan-media-skill-hub/video-stt-translate-server/actions/runs/39997927908) | c88cc80 / feature | completed success |
| [39997946922](https://github.com/japan-media-skill-hub/video-stt-translate-server/actions/runs/39997946922) | c88cc80 / main | completed success |
| [39997953791](https://github.com/japan-media-skill-hub/video-stt-translate-server/actions/runs/39997953791) | c88cc80 / tag | completed success |

三个 c88cc80 run 的 jobs/steps 均核实：secret-scan + scanner selftest、committed lock check、CPU 源覆盖/sync、CPU subset、**full suite**、compileall、service smoke 全部 success。不是仅子集绿色。故“两个新提交 CI 绿”已经满足，并新增第三个绿色 SHA；同一 SHA 的三个触发不冒充三个不同绿色提交。

中间 README-only 提交 f495fe0 的三个 run：39998637164（feature）、39998653629（main）、39998665037（tag）；首次复核 in_progress，结束前再次 API 复核全部 completed success。最终文案提交 fd383c9 的 feature run 39998978213 已独立 API 复核 completed success；新 main run 39999279981 / tag run 39999284932 首次仍 in_progress；后续独立复核 tag 为 completed success，而 main 为 completed failure（restart fixture 竞态），完整保留于末尾，不用 tag 的成功掩盖 main 失败。

### 本轮本地锁检查的真实限制

实际尝试：

~~~bash
XDG=$(mktemp -d /tmp/sol-final-xdg-XXXXXX)
env -u UV_INDEX -u UV_DEFAULT_INDEX XDG_CONFIG_HOME="$XDG" UV_PROJECT_ENVIRONMENT=/home/base/repo/video-stt-whisper-server/.venv UV_PYTHON_DOWNLOADS=never uv lock --check --python /home/base/repo/video-stt-whisper-server/.venv/bin/python
~~~

**exit 2，沙箱拒绝**：Could not acquire lock / Read-only file system at /home/base/.cache/uv/.tmp… 。未绕过重试、未请求扩大权限；同组 set -e 后的 root lock check 未执行，不能声称本轮 root check exit 0。本地限制不是锁不一致证据；已独立确认远端 child committed-lock gate success。root 归一/check 的先前证据与跟踪状态保留为交付记录，不冒充本代理重验。

## 6. README 中英与主 docs 00–04 一致性抽查

实际读取 [英文 README](</home/base/repo/video-stt-whisper-server/whisper-stt/README.md>)、[中文 README](</home/base/repo/video-stt-whisper-server/whisper-stt/README.zh-CN.md>)、[00 索引](</home/base/repo/video-stt-whisper-server/docs/00-index.md>)、[01 记忆](</home/base/repo/video-stt-whisper-server/docs/01-project-memory.md>)、[02 运维](</home/base/repo/video-stt-whisper-server/docs/02-operations-runbook.md>)、[03 架构](</home/base/repo/video-stt-whisper-server/docs/03-architecture-and-key-features.md>)、[04 排错](</home/base/repo/video-stt-whisper-server/docs/04-troubleshooting.md>)，并对照配置、测试与运行结果。

- 并发默认 2（旧 16 只作为升级提醒/历史，不是当前默认承诺）、批次检查点、wav 输入、fail-closed、探针/metrics/retry/cancel 与实际一致；roadmap 的本轮实现项已勾选。
- 中英 README 与主文档均**明确真实 2h/GPU 峰值未验收、供应商侧轮换无证据**；没有用短片 CPU/manual/API smoke 宣称其完成。
- 初读仍有 tag pending、根文件 staged 未提交等时序滞后；父在 f495fe0 与主文档定稿修订中已记载 c88cc80 三个绿色 run、tag push/后续重指及 ee1cf98/4ee839d。最终身份以本报告独立 API/ls-remote 复核为准；文本记录旧 tag object 并说明父将重指，是历史/时序说明，不是当前 tag API 的替代。
- CI 历史两次 failure、2623545/5e67c7b/c88cc80 三个不同 SHA 的 success 如实保留；没有把失败 run 覆盖成成功。
- **本轮发现并已关闭的文案差异**：原 README 的“checkpoint only promoted together with artifact”（中文对应句）不够精确；父已在 fd383c9 修复。本代理实际重新读取 [英文 checkpoint 段](</home/base/repo/video-stt-whisper-server/whisper-stt/README.md#L375-L381>)及[中文对应段](</home/base/repo/video-stt-whisper-server/whisper-stt/README.zh-CN.md#L364-L367>)，现明确每个完成批次在 with_task_lease 内立即写 canonical，不等任务成功；仅无 fenced hook 的旧 repo 兼容分支暂存后 promotion。与实际 [runtime publisher](</home/base/repo/video-stt-whisper-server/whisper-stt/whisper_stt_service/service/runtime.py#L1845-L1919>)一致，非阻塞文案项已关闭。
- 多文件 rename 是 SQLite 租约互斥下的逐文件原子替换，不是跨文件系统事务；不可宣称故障可 FS 整体回滚。

## 7. SPEC A–I 最终矩阵

“通过”限本轮实现/发布交付范围；“条件通过”是已通过可执行契约，外部真实环境仍未验证，按用户指令作为后续项，不冲销整体结论。

| SPEC 区域 | 判断 | 本轮独立证据与缺口 |
|---|---|---|
| **A 生命周期 A.1–A.7** | **通过** | 完整 532 覆盖 heartbeat/reaper/attempt 预算、fencing/cascade、启动恢复、bounded drain、retry/cancel；手写 R3-1 stop/drain 真 SQLite 原反例均保持新 owner tuple；13 集成覆盖 nonce ABA、finally compare-remove、promotion 异常后 worker 存活并重试。未用本地 claimed 全局数冒充安全退出。 |
| **B API/DAG B.1–B.3** | **通过** | 完整套件覆盖 by-path 200、DAG version/单 ASR/extract/translate 依赖拒绝及合法 DAG、每阶段 io 与产物唯一所有权、旧 job retry 校验；13 集成驱动真实仓储/发布路径，不只 schema mock。 |
| **C 翻译 C.1–C.7** | **通过** | 全套覆盖三重分批、受限并发/顺序、配置、source hash checkpoint、partial 保留原文/strict、4xx/5xx/幂等键/重试审计、原子写；手写 R3-3 事务后接管反例保留 NEW，非 bool callback 拒绝；13 集成真实 sink/cross-FS/失租/目录 symlink，5 profile 用例保留用户 fallback。真实 2h 成本/质量非本项 fake 证据可代替。 |
| **D 模型缓存与资源** | **条件通过** | 完整测试实际包含 cache key、一次冷加载、LRU/引用、并发 semaphore、WhisperX/align 缓存与惰性迭代许可测试；已运行通过。GPU 显存峰值及真实同卡长期压力未验证，不能声称峰值不随 worker 线性增长已获 GPU 实测。 |
| **E extract→ASR wav 契约** | **条件通过** | 完整 wav/script/executor/IO 测试通过，manual 源中先 extract 再 ASR，不回退视频；现有短片 CPU 结果作为历史 smoke 而非本轮重新执行。真实 2h 完整媒体链路仍缺素材，后续跟踪。 |
| **F SQLite** | **通过** | 完整迁移/WAL/PRAGMA/DELETE fallback/fail-fast/只读/EXPLAIN 测试通过；本轮真实 SQLite 两组 P1 及独立 bootstrap 实际 WAL、迁移版本 1/2、query plan 日志确认。网络盘回退是受控测试，不冒称在真实 NFS 上压测。task_deps 优化为 SPEC 按需项，不强制本轮实现。 |
| **G 可观测性** | **通过** | 全套 request-id/effective-config/log/metrics/throughput/audit 测试通过；独立 bootstrap 返回 health/queue/metrics=200、缺模型 ready=503、未创建模型目录，实际 service 日志落盘含 request_id；远端 CI smoke 同样 success。 |
| **H 安全与暴露面** | **条件通过** | 全套 token/roots/常量时间比较/docs/launcher 测试及独立 wrong-token=401、docs=404；13 集成覆盖实际 copyback roots、文件/目录 symlink 与旧租约拒绝；主/子 secret scan+selftest 通过。供应商 HF/API token 撤销轮换需用户人工，未完成/无证据，按直接指令作为发布后安全跟踪，绝不视为本地扫描已替代撤销。 |
| **I 仓库/CI/文档** | **通过（新增 CI 竞态已修复闭环）** | 根清单/锁/docs 已跟踪，child clean，无源内 scratch/secret，manual 迁移/旧源移除、无子 venv、用户 .codegraph/fallback 保留；v0.4.0 缺失远端已由父补齐并复核，v0.5.0 annotated tag / main / 本地 SHA 一致；历史三个不同 SHA CI 绿；新增 fd383c9 main 的 restart 竞态由官方 da43057 修复，不削弱断言；最终 699bb85 仅测试同步+README 差异，生产实现不变，独立全量/五轮 restart 及 feature/main/tag 远端全绿。root 本地 lock 检查沙箱限制如实保留；checkpoint 文案差异已关闭。 |

相关可定位测试：[租约/回写集成](</home/base/repo/video-stt-whisper-server/whisper-stt/tests/integration/test_runtime_lease_identity_and_copyback.py>)、[真实跨 FS 集成](</home/base/repo/video-stt-whisper-server/whisper-stt/tests/integration/test_runtime_cross_filesystem_copyback.py>)、[翻译可靠性](</home/base/repo/video-stt-whisper-server/whisper-stt/tests/unit/test_translate_reliability.py>)、[DB migrations](</home/base/repo/video-stt-whisper-server/whisper-stt/tests/unit/test_db_migrations.py>)、[model cache](</home/base/repo/video-stt-whisper-server/whisper-stt/tests/unit/test_model_cache.py>)、[observability audit](</home/base/repo/video-stt-whisper-server/whisper-stt/tests/unit/test_observability_audit.py>)；它们均在本轮完整 pytest 实际执行，不仅静态浏览测试名。

## 8. 发布后外部跟踪：明确未验证，非本次失败

1. **真实 2h 长片链路**：本代理对已读 [E2E 媒体清单](</home/base/repo/video-stt-whisper-server/whisper-stt/tests/e2e/video_paths.txt>)四条配置路径逐一 Path.is_file，实际结果 [False, False, False, False]。本轮挂载目录存在且有 DOWNLOAD_BAK/JELLYFIN/WEBDAV/iocage 四个目录项，**不再把历史“空挂载”说成当前实态**。递归媒体 glob 工具超时，未据此断言整台机器绝无其他长片；确定的是这四条验收样本不可用。需用户提供可读真实 2h 路径后测墙钟、批次/请求/token、SRT 行数/末时间戳与 kill -9 恢复。未请求额外付费运行。
2. **NVML/GPU**：实际 nvidia-smi exit **255**，本轮原文 Failed to initialize NVML: Generic operating system error / Failed to properly shut down NVML: Generic operating system error。此前记录 NVML GPU access blocked by OS；当前同样无法采样，不能凭 fake/cache 测试宣布 GPU 峰值验收完成。
3. **供应商侧 token 轮换**：本地 token 文档删除/忽略与 secret scan 不是撤销证明。HF_TOKEN 与 LLM API key 必须人工 provider 端撤销/轮换，验证旧 token 失效，并只记录脱敏完成证据；本轮无 provider-side 操作证据。
4. **短片历史证据边界**：父交付的 CPU 30s 抽取+STT manual 2 passed、5 段真实 API 1 请求/679 tokens/17.49s、复跑 0 请求/0.009s，本代理本轮未再次发付费请求，故仅列为既有 smoke，不冒称自己重跑，更不代替 2h/GPU/轮换。

## 9. 中途新增 CI 竞态：发现与独立因果实验（历史保留，现已闭环）

收尾独立 API 新发现：run 39999279981 @ fd383c9 main **completed failure**；失败在 CPU subset 的 test_restart_recovery_counts_attempt（原测试第 774 行），assert restarted.startup_stats()["recovered"] >= 1 实际 0 >= 1。相同 SHA feature run 39998978213 为 success，不能因此隐去 main 失败。实际执行 gh api .../actions/runs/39999279981/jobs 和 gh run view 39999279981 --repo japan-media-skill-hub/video-stt-translate-server --log-failed（exit 0）核实，后续 full/compileall/smoke 步骤 skipped。

本代理读取原测试 740–783 行和 FakeExecutors._maybe_hang：先 hang_events.pop、hang.set、fake.clear，再 restarted.start；旧 worker 被放活后可在新恢复前完成，故 recovered=0 合理，测试未真实维持“僵尸 claimed”前提。该名用例在第三轮已有一次不稳定记录，本轮远端再次暴露。已立即通知父，由官方 DeepSeek Flash 修同步、不削弱 recovered/attempt 断言。当时因此暂不通过，待官方修复、重复测试、新发布 SHA/tag/CI 复核；现已全部补齐，证据见第 10 节，不改写本次失败历史。

竞态修复前当时核实主仓库 f7e607d7264de58e489437d2ec13e5b56d152610，gitlink 为 fd383c9；子树 clean。该段为历史快照，最终主仓库/gitlink 身份见第 1/10 节。

### 新 CI 失败的独立确定性因果实验（原 fd383c9 测试）

本代理仅用 pytest plugin 控制旧线程的调度顺序，不改实现或测试源：将原例 fake.clear 包成“等待刚被 hang.set 放行的旧 extract 已 succeeded，再返回”。这不是修复，是确定性暴露原例未保持 crash 前提。实际命令：

~~~bash
PYTHONDONTWRITEBYTECODE=1 /home/base/repo/video-stt-whisper-server/.venv/bin/python - <<'PY'
import pytest
class ForceOldCompletion:
    def pytest_runtest_call(self,item):
        if item.name!='test_restart_recovery_counts_attempt': return
        stack=item.funcargs['stack']; original=stack.fake.clear
        def clear_after_old_completed():
            original()
            def old_done():
                with stack.repo.db.connect() as conn:
                    rows=conn.execute("SELECT status FROM tasks WHERE stage='extract'").fetchall()
                return bool(rows) and all(row['status']=='succeeded' for row in rows)
            item.module.wait_until(old_done,description='deterministic scheduling: released old worker finishes before restart')
            print('SCHEDULE PROOF: old extract succeeded before restarted.start()')
        item.funcargs['monkeypatch'].setattr(stack.fake,'clear',clear_after_old_completed) if 'monkeypatch' in item.funcargs else stack.monkeypatch.setattr(stack.fake,'clear',clear_after_old_completed)
result=pytest.main(['-q','-p','no:cacheprovider','tests/integration/test_runtime_fake_executors.py::test_restart_recovery_counts_attempt'],plugins=[ForceOldCompletion()])
assert int(result)==1, f'expected original fixture assertion failure, got {result}'
print('EXPECTED FAILURE CONFIRMED: unmodified production recovery is zero after old claimed already succeeded')
PY
~~~

实际 stdout 含 SCHEDULE PROOF；内部 pytest 精确 **1 failed in 2.60s**，仍是第 774 行 recovered=0>=1，非其他异常；外层验证该预期失败后 exit 0。证明旧测试允许“旧 claimed 在重启前已完成”独自导致 CI 失败，不能误报产品 startup recovery 漏计，也不能把此次负例记作通过用例。官方仍须修正同步并重新过门禁。

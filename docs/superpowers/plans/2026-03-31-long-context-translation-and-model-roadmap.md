# Long Context Translation And Model Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前字幕翻译从按条目数量切批改为按 30 分钟时间窗切分，并补强面向剧情连续性的翻译提示词，同时补充 large-v2 / large-v3 模型路径与音频预处理 roadmap 文档。

**Architecture:** 复用现有 SRT 解析与翻译执行链路，在服务端与独立 CLI 翻译脚本之间抽出共享的翻译时间窗/提示词构造逻辑。服务配置继续沿用现有 `config.ini`，新增以时间窗为核心的翻译切分参数，并在文档中记录本轮冻结项与下一轮音频预处理方向。

**Tech Stack:** Python 3.10+, requests, pytest, Faster-Whisper, configparser

---

## 文件结构与职责

- 新建 `whisper-stt/whisper_stt_service/translation_runtime.py`：共享 SRT 解析、30 分钟切分、提示词构造、JSON 解析。
- 修改 `whisper-stt/whisper_stt_service/executors.py`：服务翻译阶段改用共享时间窗与新提示词。
- 修改 `whisper-stt/whisper_stt/translate_srt_ja_to_zh.py`：独立翻译脚本改用同一套切分与提示词逻辑。
- 新建 `whisper-stt/tests/unit/test_translation_runtime.py`：覆盖时间窗切分与提示词要求。
- 修改 `whisper-stt/README.md`：补充 30 分钟翻译窗口说明。
- 新建 `docs/superpowers/specs/2026-03-31-long-context-translation-roadmap.md`：记录 large-v2 / large-v3 路径、当前冻结项、音频预处理 roadmap。

### Task 1: 共享翻译时间窗规则

**Files:**
- Create: `whisper-stt/tests/unit/test_translation_runtime.py`
- Create: `whisper-stt/whisper_stt_service/translation_runtime.py`

- [ ] **Step 1: 写失败测试（30 分钟时间窗切分）**

```python
from whisper_stt_service.translation_runtime import SrtEntry, build_time_batches


def test_build_time_batches_groups_entries_by_30_minute_windows() -> None:
    entries = [
        SrtEntry(index=1, timestamp="00:00:01,000 --> 00:00:02,000", text="a"),
        SrtEntry(index=2, timestamp="00:29:59,000 --> 00:30:01,000", text="b"),
        SrtEntry(index=3, timestamp="00:30:00,000 --> 00:30:02,000", text="c"),
    ]

    batches = build_time_batches(entries, chunk_minutes=30)

    assert [len(batch) for batch in batches] == [2, 1]
    assert [entry.index for entry in batches[0]] == [1, 2]
    assert [entry.index for entry in batches[1]] == [3]
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest whisper-stt/tests/unit/test_translation_runtime.py::test_build_time_batches_groups_entries_by_30_minute_windows -v`
Expected: FAIL，提示 `ModuleNotFoundError` 或 `ImportError`

- [ ] **Step 3: 写最小实现（共享时间窗切分）**

```python
from dataclasses import dataclass


@dataclass
class SrtEntry:
    index: int
    timestamp: str
    text: str


def build_time_batches(entries: list[SrtEntry], chunk_minutes: int) -> list[list[SrtEntry]]:
    chunk_seconds = max(chunk_minutes, 1) * 60
    batches: dict[int, list[SrtEntry]] = {}
    for entry in entries:
        start_seconds = _parse_srt_timestamp_range(entry.timestamp)[0]
        window_no = int(start_seconds // chunk_seconds)
        batches.setdefault(window_no, []).append(entry)
    return [batches[key] for key in sorted(batches)]
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `pytest whisper-stt/tests/unit/test_translation_runtime.py::test_build_time_batches_groups_entries_by_30_minute_windows -v`
Expected: PASS

### Task 2: 共享剧情连续性提示词

**Files:**
- Modify: `whisper-stt/tests/unit/test_translation_runtime.py`
- Modify: `whisper-stt/whisper_stt_service/translation_runtime.py`

- [ ] **Step 1: 写失败测试（提示词包含上下文要求）**

```python
from whisper_stt_service.translation_runtime import SrtEntry, build_translate_messages


def test_build_translate_messages_mentions_plot_reasoning_and_consistency() -> None:
    messages = build_translate_messages(
        [SrtEntry(index=1, timestamp="00:00:01,000 --> 00:00:02,000", text="行こう")]
    )

    system_text = messages[0]["content"]
    user_text = messages[1]["content"]
    assert "context" in system_text.lower()
    assert "plot" in system_text.lower()
    assert "consistent" in system_text.lower()
    assert '"id"' in user_text
```
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest whisper-stt/tests/unit/test_translation_runtime.py::test_build_translate_messages_mentions_plot_reasoning_and_consistency -v`
Expected: FAIL，提示 `build_translate_messages` 未定义或断言失败

- [ ] **Step 3: 写最小实现（共享提示词构造）**

```python
def build_translate_messages(batch: list[SrtEntry]) -> list[dict[str, str]]:
    payload_items = [{"id": entry.index, "text": entry.text} for entry in batch]
    system_prompt = (
        "You are a professional subtitle translator. Use surrounding context and plot continuity to "
        "infer omitted subjects, preserve tone, and keep naming consistent across the whole chunk. "
        "Think carefully, but output ONLY JSON."
    )
    user_prompt = (
        "Translate the following JSON array from Japanese to natural Simplified Chinese subtitles. "
        "Return ONLY a JSON array with objects in the form {\"id\": <same id>, \"text_zh\": \"...\"}.\n\n"
        f"{json.dumps(payload_items, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `pytest whisper-stt/tests/unit/test_translation_runtime.py -v`
Expected: PASS

### Task 3: 接入服务与 CLI 翻译链路

**Files:**
- Modify: `whisper-stt/whisper_stt_service/executors.py`
- Modify: `whisper-stt/whisper_stt/translate_srt_ja_to_zh.py`

- [ ] **Step 1: 写失败测试（服务使用时间窗批次）**

```python
def test_run_translate_uses_time_window_batches(monkeypatch, tmp_path):
    ...
```
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest whisper-stt/tests/unit/test_translation_runtime.py -v`
Expected: FAIL，提示服务仍按条目数切分

- [ ] **Step 3: 写最小实现（替换批次来源与消息构造）**

```python
batches = build_time_batches(entries, chunk_minutes=chunk_minutes)
messages = build_translate_messages(batch)
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `pytest whisper-stt/tests/unit/test_translation_runtime.py -v`
Expected: PASS

### Task 4: 文档与 roadmap

**Files:**
- Modify: `whisper-stt/README.md`
- Create: `docs/superpowers/specs/2026-03-31-long-context-translation-roadmap.md`

- [ ] **Step 1: 写文档**

```md
- large-v2 路径
- large-v3 路径
- 本轮冻结：VAD、音频预处理
- 下一轮 roadmap：音轨判别、对白增强、降噪
- 翻译策略：30 分钟时间窗 + 剧情连续性 prompt
```

- [ ] **Step 2: 自检文档与实现一致**

Run: `pytest whisper-stt/tests/unit/test_translation_runtime.py -v`
Expected: PASS

# Readable Job And Task ID Design

## Background

The current `whisper-stt` service creates `job_id` and `task_id` values with plain `uuid4()` output. This is stable and unique, but it is hard to inspect from logs, API payloads, database records, and queue polling output because the identifier itself does not expose task intent.

The requested change is to replace the UUID-shaped IDs with human-readable IDs that still preserve operational uniqueness and remain safe for storage, log paths, and operational debugging.

## Goals

- Make `job_id` and `task_id` directly readable in API results, logs, and database rows.
- Encode type, task name, stage name for tasks, second-level timestamp, and a short uniqueness suffix in the ID itself.
- Keep the current database schema, API field names, enqueue flow, dependency wiring, and worker behavior unchanged outside the generation rule.
- Ensure the database and repository flow continue to support long string identifiers, including storage compatibility for IDs longer than 100 characters when needed.

## Non-Goals

- Do not rename API fields such as `job_id` or `task_id`.
- Do not add a second display-only identifier.
- Do not change DAG semantics, retry logic, archive behavior, or queue ordering.
- Do not introduce user-supplied custom job names in this change.

## Identifier Format

### `task_name` derivation

`task_name` is derived from the input video file name using the following steps:

1. Take the file stem from `video_path`.
2. Remove every character that is not a digit, uppercase letter, or lowercase letter.
3. If the cleaned string is longer than 64 characters, keep the last 64 characters.
4. If the cleaned string becomes empty, use `unnamed`.

This keeps IDs readable while avoiding punctuation, spaces, separators, and other characters that may reduce readability or create storage/path risks.

### Timestamp and suffix

- Timestamp format is fixed as `YYYYMMDDHHMMSS`.
- Uniqueness suffix uses the first 4 hexadecimal characters from `uuid4()`.

Because a 4-character suffix has a materially higher collision probability than a full UUID, enqueue should treat these IDs as human-readable keys with retry-on-conflict behavior instead of assuming a single generation attempt is sufficient.

### Final formats

- `job_id`: `job-<task_name>-job-<YYYYMMDDHHMMSS>-<uuid4_4>`
- `task_id`: `task-<task_name>-<stage>-<YYYYMMDDHHMMSS>-<uuid4_4>`

Example with source file name `[Final] 2026-04-05 demo_movie_v12 (1080p).mp4`:

- cleaned `task_name`: `Final20260405demomoviev121080p`
- `job_id`: `job-Final20260405demomoviev121080p-job-20260405120433-a1b2`
- `task_id`: `task-Final20260405demomoviev121080p-extract-20260405120433-c3d4`

## Architecture

The change stays inside the repository layer where IDs are currently created during enqueue. A small internal helper should centralize the readable ID generation so both `job_id` and `task_id` use the same sanitization, truncation, timestamp, and short-suffix rules.

The enqueue path should also add a small retry loop around ID creation and persistence so a rare primary-key collision on the short suffix does not fail the request outright.

`JobRepository.enqueue()` should continue to:

- create one `job_id`
- create one `task_id` per stage
- persist both as `TEXT`
- wire dependencies by `task_id`

No database migration is required because SQLite `TEXT` already supports long string values, and all dependent code already treats the identifiers as opaque strings.

## File Impact

### Implementation

- Modify `whisper-stt/whisper_stt_service/repo/job_repository.py`
  - Add helper logic for `task_name` cleaning and left-side truncation that retains the final 64 alphanumeric characters.
  - Add helper logic for timestamp formatting and short UUID suffix generation.
  - Add collision-safe retry logic for job/task insertion when a generated ID hits an existing primary key.
  - Replace direct `uuid.uuid4()` string IDs in `enqueue()`.

### Tests

- Modify `whisper-stt/tests/unit/test_repository_enqueue.py`
  - Add assertions for the new `job_id` format.
  - Add a long file name case proving the cleaned name keeps the final 64 alphanumeric characters.
  - Add a schema compatibility case proving the underlying tables still accept identifiers longer than 100 characters.
  - Keep the existing idempotent and rejection behavior assertions.

- Modify `whisper-stt/tests/unit/test_repository_dag_enqueue.py`
  - Add assertions for per-stage `task_id` formatting.
  - Verify `task_id` contains the stage name and the cleaned task name suffix behavior.
  - Verify dependency-related behavior still works with non-UUID task IDs.
  - Add a collision-retry case by forcing duplicate short suffix generation and verifying enqueue still succeeds.

- Modify `whisper-stt/tests/e2e/run_e2e_real_flow.py`
- Modify `whisper-stt/tests/e2e/run_e2e_explicit_dag_flow.py`
  - Keep abbreviated task display, but avoid implying the prefix is a UUID fragment.

## Data Flow

1. API submit request calls repository enqueue.
2. Repository derives `task_name` from `video_path`.
3. Repository creates a readable `job_id`.
4. Repository creates a readable `task_id` for each stage.
5. Repository persists job, task, dependency payload, and log paths using the readable IDs.
6. Existing API and worker code continue to pass the identifiers through unchanged.

## Error Handling And Edge Cases

- Empty or fully stripped file names fall back to `unnamed`.
- Extremely long file names are truncated from the left, preserving the rightmost 64 alphanumeric characters.
- Stage values remain the existing validated stage names, so no extra stage sanitization is required in this change.
- Same-second collisions are reduced by the 4-character UUID suffix, but this is much weaker than the current full-UUID approach.
- Enqueue must retry ID generation on primary-key conflict so rare collisions, repeated file names, and fully stripped names such as `unnamed` do not break job creation.

## Testing Strategy

Use TDD for the implementation:

1. Add a failing unit test for `job_id` format and cleaned file name behavior.
2. Run the targeted repository test and confirm it fails for the expected reason.
3. Implement the minimal helper logic and enqueue wiring.
4. Re-run the targeted test until it passes.
5. Add a failing unit test for `task_id` stage embedding and dependency compatibility.
6. Run the targeted DAG repository test and confirm it fails for the expected reason.
7. Implement the minimal task ID logic and retry-on-conflict handling.
8. Re-run the targeted DAG test until it passes.
9. Run the affected repository and API test set.
10. Update the e2e helper display labels if needed and run the relevant tests or checks that cover those scripts.

Expected assertions include:

- `job_id` matches the readable format.
- `task_id` matches the readable format for each stage.
- `task_name` keeps only `[0-9A-Za-z]`.
- `task_name` keeps the last 64 cleaned characters for overlong names.
- Underlying tables accept identifiers longer than 100 characters when directly persisted.
- Collision retry prevents enqueue failure when a generated short suffix conflicts with an existing ID.
- Idempotent enqueue, started-job rejection, and dependency payload behavior remain correct.

## Risks And Mitigations

- Longer IDs increase path length in log directories.
  - Mitigation: cap cleaned task name to 64 characters and test long-name scenarios.
- Short 4-character suffixes increase primary-key collision risk compared with full UUIDs.
  - Mitigation: retry ID generation on unique-key conflict and cover the retry path in tests.
- Existing test output or scripts may assume IDs look like UUIDs.
  - Mitigation: update wording and assertions to treat IDs as opaque readable strings.
- Readability could degrade if punctuation is removed too aggressively.
  - Mitigation: preserve the most informative rightmost alphanumeric section of long names, which typically contains version/date/batch suffixes.

## Acceptance Criteria

- New jobs return readable `job_id` values using the approved format.
- New tasks return readable `task_id` values using the approved format.
- `task_name` cleaning keeps only letters and digits and truncates from the left to retain the final 64 characters.
- Enqueue succeeds even when a generated short suffix collides with an existing primary key, by regenerating IDs and retrying.
- Generated IDs store and query correctly in the existing database tables.
- Existing schema continues to accept identifier values longer than 100 characters.
- Existing queue, DAG dependency, archive, and progress flows continue to work.
- Tests cover the new format and long-ID behavior.

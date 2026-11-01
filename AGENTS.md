# AGENTS


MUSTDO：在你写的代码中保留所有注解，不允许删除注解

在实施完成了readme中的roadmap功能后，请标注完成


## Repository layout

- Main repository (this root directory): `/home/base/repo/video-stt-whisper-server`
- Child repository (actual feature development code): `/home/base/repo/video-stt-whisper-server/whisper-stt`

## Remotes

- Main repository remote: `https://github.com/zztdandan/video-stt-server-harness.git`
- Child repository remote: `https://github.com/zztdandan/video-stt-translate-server.git`

## Working model

- Main repository is the agent working project (coordination, docs, and process conventions).
- Child repository is the concrete implementation project (feature code and delivery).

## Documentation rule

- All spec, plan, and execution-tracking documents must be stored under `/home/base/repo/video-stt-whisper-server/docs`.
- Do **not** place spec or execution documents inside the child repository (`/home/base/repo/video-stt-whisper-server/whisper-stt`).
- When creating Superpowers design/plan documents, use the main repository `docs/superpowers/...` path, not `whisper-stt/docs/...`.

## Worktree rule

- Use `.worktrees/` at the main repository level as the container for development worktrees.
- `.worktrees/` is ignored in the main repository to avoid workspace confusion.
- Do **not** create worktrees for the whole main repository.
- Only create and use worktrees for the child repository (`whisper-stt`) during feature development.

## Python venv rule (strict)

- All Python execution MUST use the main project virtual environment: `/home/base/repo/video-stt-whisper-server/.venv`.
- Child repository (`/home/base/repo/video-stt-whisper-server/whisper-stt`) and any worktree under `.worktrees/` MUST NOT create their own `.venv`.
- Child repository and worktrees MUST NOT use any local/independent venv; they must share and run with the main project `.venv` only.
- If commands are run via `uv`, they must be executed in a way that targets the main project `.venv` (avoid auto-creating per-project venv in child/worktree).

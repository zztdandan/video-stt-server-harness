# AGENTS

## Repository layout

- Main repository (this root directory): `/home/base/repo/video-stt-whisper-server`
- Child repository (actual feature development code): `/home/base/repo/video-stt-whisper-server/whisper-stt`

## Remotes

- Main repository remote: `https://github.com/zztdandan/video-stt-server-harness.git`
- Child repository remote: `https://github.com/zztdandan/video-stt-translate-server.git`

## Working model

- Main repository is the agent working project (coordination, docs, and process conventions).
- Child repository is the concrete implementation project (feature code and delivery).

## Worktree rule

- Use `.worktrees/` at the main repository level as the container for development worktrees.
- `.worktrees/` is ignored in the main repository to avoid workspace confusion.
- Do **not** create worktrees for the whole main repository.
- Only create and use worktrees for the child repository (`whisper-stt`) during feature development.

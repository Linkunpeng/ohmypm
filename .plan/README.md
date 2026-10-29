# .plan — development handoff files

These files are the hand-maintained working memory for agents developing ohmypm
itself (until ohmypm's own MCP memory takes over).

| File | Purpose |
|---|---|
| `roadmap.md` | Phases, scope, acceptance criteria, status per phase |
| `architecture.md` | Current architecture as built (short; details live in `docs/`) |
| `decisions.md` | Architecture decision log (append-only, numbered) |
| `progress.md` | What is done / verified, failed attempts, open issues |
| `handoff.md` | Where the last session stopped and what to do next |

Rules:
- Read `handoff.md` and `progress.md` before starting work.
- Update `progress.md` after each finished phase; update `handoff.md` before ending a session.
- Record failed attempts with their outcome; do not paste raw logs.
- Only mark items verified when a test or command actually proved them.

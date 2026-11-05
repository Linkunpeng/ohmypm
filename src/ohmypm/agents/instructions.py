"""Default global agent instructions (installed to ~/.config/ohmypm/agent-instructions.md)."""

TEMPLATE_VERSION = 1

DEFAULT_INSTRUCTIONS = """\
# ohmypm — project memory

ohmypm keeps a local development memory (records and a summary) for registered
projects. It stores nothing inside project directories. Use the `ohmypm` CLI
(or the ohmypm MCP tools, passing your absolute workspace path or the project
id explicitly). If `ohmypm` is missing or fails, continue your work without it.

## At the start of a session

1. Run `ohmypm status --json` in the workspace.
2. If `"registered": true`, run `ohmypm context` and read it before starting.
   For more: `ohmypm context --mode standard`, `ohmypm search "<terms>"`,
   `ohmypm log show <number>`.
3. If the directory is not registered, work normally. Do not register
   projects yourself unless the user asks (`ohmypm register`).

## While working: record only what has lasting value

```bash
ohmypm log add --type <type> --title "<specific title>" --author <agent-name> --stdin <<'EOF'
<concise Markdown>
EOF
```

| type        | use it for                                                                                  |
|-------------|---------------------------------------------------------------------------------------------|
| `milestone` | a completed stage: what was done, key implementation points, how it was verified, next step |
| `issue`     | a non-trivial problem: symptoms, relevant files, attempts (also failed ones), confirmed findings vs. hypotheses, next diagnostic step |
| `decision`  | a technical choice: options considered and the reason for the choice                       |
| `knowledge` | durable project facts, conventions, pitfalls                                                |
| `artifact`  | an important program, script or model: location, how to build, run and verify it           |
| `note`      | other context worth keeping                                                                 |

When an issue is solved: `ohmypm log edit <number> --status resolved --append --content "Fix: ..."`.
Mark unverified ideas as such (e.g. `--meta confidence=hypothesis`); never present guesses as facts.

Do not record: simple commands, file reads, temporary debug output, repetitive
intermediate states, or secrets of any kind (passwords, tokens, keys, credentials).

## At the end of a work phase

1. Record important results (`milestone`) and unresolved problems (`issue`)
   including the next steps.
2. If the project state changed meaningfully, update the summary:
   `ohmypm summary show`, revise, then `ohmypm summary set --stdin`
   (sections: Overview, Architecture, Current State, Important Decisions,
   Known Issues, Next Steps; only the sections you include are changed).

Keep records accurate, concise and in the user's language. Recording must not
disrupt the actual work: a few good records per session beat many small ones.
"""

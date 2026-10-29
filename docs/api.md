# REST API

Interactive docs: `http://127.0.0.1:8765/api/docs` (OpenAPI JSON at `/api/openapi.json`).

## Conventions

- **Auth**: `Authorization: Bearer <token>` on everything except `GET /api/health`.
  Roles: admin (`OHMYPM_API_TOKEN`), runner (`OHMYPM_RUNNER_TOKEN`, only `/api/runner/*` and reads),
  agent (run tokens / `OHMYPM_AGENT_TOKEN`; cannot create projects, manage profiles, resolve decisions…).
- **Errors**: always `{"error": {"code": "...", "message": "...", "details": ...}}`. Common codes:
  `unauthorized` 401, `forbidden` 403, `not_found` 404, `conflict`/`version_conflict`/`invalid_transition`/
  `dependencies_unmet`/`dependency_cycle`/`idempotency_key_reused`/`workspace_busy` 409,
  `validation_error`/`validation_failed`/`acceptance_not_met` 422, `internal_error` 500 (no internals leaked).
- **Pagination**: `?limit=50&offset=0&sort=-updated_at` → `{"items": [], "total", "limit", "offset"}`.
- **Idempotency**: send `Idempotency-Key: <uuid>` on `POST /api/projects|tasks|artifacts|runs` and
  `POST /api/tasks/{id}/checkpoints`. Same key + same body → the stored response; different body → 409.
- **Optimistic concurrency**: single-entity GETs return `ETag: W/"<version>"`; send it back as `If-Match`
  (or `expected_version` in the body) on PATCH / complete / resolve → 409 `version_conflict` if stale.
- **Paths**: the API never reads or writes arbitrary filesystem paths. Workspace and artifact paths are
  stored as data; only the runner resolves workspace paths on its own host.
- Tasks are cancelled, not deleted (history is preserved). Agent profiles can be deleted.

## Endpoints

| Method & path | Description |
|---|---|
| `GET /api/health` | Liveness + DB + schema revision (public) |
| `GET /api/whoami` | Current principal |
| `GET /api/dashboard` | Aggregates for the dashboard |
| `GET /api/search?q=&kind=` | Search projects, workspaces, tasks, decisions, artifacts, knowledge |
| `POST/GET /api/projects`, `GET/PATCH /api/projects/{id}` | Projects (POST accepts an existing PROJECT_ID as `id`) |
| `POST /api/workspaces/resolve` | Find-or-create `(host_id, root_path)`; links to `project_id` |
| `GET /api/workspaces`, `GET/PATCH /api/workspaces/{id}` | `?project_id=&anonymous=&host_id=&q=` |
| `POST/GET /api/tasks` | `?project_id=&anonymous=&workspace_id=&status=…&priority=&q=&ready=&tag=&parent_task_id=` |
| `GET /api/tasks/{id or T-n}` | Task detail incl. dependencies |
| `PATCH /api/tasks/{id}` | Update fields/status (not `completed`) |
| `POST /api/tasks/{id}/complete` | `{summary, results:[{criterion, passed, evidence}], force}` |
| `POST /api/tasks/{id}/cancel` | Cancel (also cancels queued/active runs) |
| `POST /api/tasks/{id}/dependencies`, `DELETE …/dependencies/{dep}` | Dependency edges |
| `GET /api/tasks/{id}/events` | Task history |
| `GET /api/tasks/{id}/context?mode=brief|standard|full&max_tokens=&checkpoint_id=` | ContextBuilder output (`markdown` + structured `data`) |
| `POST/GET /api/tasks/{id}/checkpoints`, `GET /api/checkpoints/{id}` | Append-only checkpoints |
| `GET /api/tasks/{id}/sessions`, `POST /api/sessions`, `POST /api/sessions/{id}/close` | Agent sessions |
| `POST/GET /api/decisions`, `GET /api/decisions/{id}` | Decisions |
| `POST /api/decisions/{id}/resolve` | `{selected_option, response, resume}` → `{decision, resumed_run}` |
| `POST /api/decisions/{id}/cancel` | Dismiss |
| `POST/GET /api/knowledge`, `GET/PATCH /api/knowledge/{id}` | Knowledge (`superseded_by` to retire) |
| `POST/GET /api/artifacts`, `GET/PATCH /api/artifacts/{id}` | Artifacts (detail includes versions) |
| `POST /api/runs` | Dispatch: `{task_id, agent_type | profile_id | profile_name, workspace_id, instructions, context_mode, session_id, resume_native, from_checkpoint_id, timeout_seconds, write_mode, force}` |
| `GET /api/runs`, `GET /api/runs/{id}` | `?task_id=&project_id=&status=&active=` |
| `POST /api/runs/{id}/cancel` | Queued → cancelled immediately; active → cancel requested |
| `GET /api/runs/{id}/events` | JSON (`?after_seq=&event_type=`) or **SSE** with `Accept: text/event-stream` |
| `GET /api/runners`, `GET /api/agents` | Runners and agent availability per runner |
| `GET/POST /api/agent-profiles`, `PATCH/DELETE /api/agent-profiles/{id}` | Profiles (options validated) |
| `POST /api/runner/register|heartbeat|claim` | Runner protocol (runner token) |
| `POST /api/runner/runs/{id}/progress|events|finish` | Runner protocol (header `X-Runner-Id`) |
| `/mcp` | MCP streamable HTTP endpoint (see [mcp.md](mcp.md)) |

## SSE

```
GET /api/runs/{id}/events
Accept: text/event-stream
Last-Event-ID: 41            # optional: replay from seq 42

retry: 2000

id: 42
event: run_event
data: {"id":…,"run_id":"…","seq":42,"event_type":"tool.started","timestamp":"…","payload":{…}}

event: end
data: {"status":"completed"}
```

Keep-alive comments are sent every 15 s. Disconnecting never affects the run. Browsers can't set headers
on `EventSource`, so the Web UI uses a fetch-based reader (`frontend/src/lib/sse.ts`).

## Normalized run event types

`run.queued`, `run.claimed`, `run.status`, `run.cancel_requested`, `agent.started`, `agent.message`,
`agent.thinking`, `agent.plan`, `agent.status`, `agent.usage`, `agent.result`, `agent.warning`,
`agent.error`, `agent.stderr`, `agent.output`, `tool.started`, `tool.completed`, `file.changed`,
`checkpoint.created`, `approval.requested`, `approval.denied`, `agent.completed`, `agent.failed`.

## Examples

```bash
H="Authorization: Bearer $OHMYPM_TOKEN"
curl -s -H "$H" -H 'Content-Type: application/json' -d '{"raw_request":"Fix the login bug","acceptance_criteria":["tests pass"]}' \
  http://127.0.0.1:8765/api/tasks
curl -s -H "$H" 'http://127.0.0.1:8765/api/tasks?ready=true&sort=priority'
curl -s -H "$H" 'http://127.0.0.1:8765/api/tasks/T-1/context?mode=standard' | jq -r .markdown
curl -N -H "$H" -H 'Accept: text/event-stream' http://127.0.0.1:8765/api/runs/<run-id>/events
```

# MineM Agent Runtime

MineM Agent Runtime is an internal backend capability module. It is not exposed in the React navigation and is not a user-facing product page.

## Positioning

The module provides a conservative engineering-governance layer inspired by Aider:

- understand the MineM source workspace
- build a lightweight repo map
- analyze a task and suggest impacted files
- recommend validation checks
- record checkpoints and audit logs
- run whitelisted validations

It does not apply patches automatically yet.

## Modules

- `minem/agent/workspace.py`: source file discovery and path classification
- `minem/agent/repo_map.py`: lightweight code map and symbol extraction
- `minem/agent/planner.py`: task-to-scope analysis rules
- `minem/agent/validator.py`: whitelisted validation commands
- `minem/agent/checkpoints.py`: git-state checkpoint records
- `minem/agent/audit.py`: JSONL audit log
- `minem/agent/runtime.py`: unified service facade

## Hidden API

These APIs are for internal automation and developer workflows only.

- `GET /api/internal/agent/map?focus=preview`
- `GET /api/internal/agent/audit?limit=50`
- `POST /api/internal/agent/analyze`
- `POST /api/internal/agent/checkpoint`
- `POST /api/internal/agent/validate`

HTTP access is disabled unless `MINEM_AGENT_INTERNAL_API=1` or `MINEM_AGENT_API_TOKEN` is configured. Docker defaults to disabled and binds the platform to `127.0.0.1`. When enabled, every request must include a caller-provided token through `X-MineM-Agent-Token` or `Authorization: Bearer ...`.

Example:

```bash
export MINEM_AGENT_API_TOKEN='replace-with-a-local-random-token'
curl -sS http://127.0.0.1:8790/api/internal/agent/map?focus=preview \
  -H "X-MineM-Agent-Token: ${MINEM_AGENT_API_TOKEN}"

curl -sS -X POST http://127.0.0.1:8790/api/internal/agent/analyze \
  -H "X-MineM-Agent-Token: ${MINEM_AGENT_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"task":"预览有问题，优化缩略图"}'
```

## CLI

```bash
python3 scripts/minem_agent.py analyze "预览有问题，优化缩略图"
python3 scripts/minem_agent.py validate --check python_compile
python3 scripts/minem_agent.py checkpoint --label before-preview-fix --task "预览优化"
python3 scripts/minem_agent.py audit --limit 20
```

## Validation Checks

Current whitelisted checks:

- `python_compile`
- `frontend_build`
- `api_contract`

No arbitrary shell command execution is exposed.
`api_contract` is additionally restricted to loopback base URLs.

## Next Steps

Recommended next phase:

1. Add a controlled patch proposal format.
2. Add patch dry-run and file ownership checks.
3. Add screenshot or thumbnail validation hooks for preview-related tasks.
4. Add rollback support based on checkpoint metadata or git commits.

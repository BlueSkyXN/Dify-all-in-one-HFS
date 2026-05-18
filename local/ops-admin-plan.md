# OPS and Admin Plan

## Goal

Keep `/_ops/*` as a mature read-only diagnostics surface, then add any future write operations under a separate `/_admin/*` boundary.

## Phase 1: OPS Read-Only Observability

Implemented in `docker/ops_service.py`:

- `/_ops/` single-file HTML/CSS/native JS dashboard.
- `/_ops/health` and `/healthz` aggregate health checks.
- `/_ops/status` supervisor status.
- `/_ops/system` CPU load, memory, disk, `/data`, uptime, and process count.
- `/_ops/logs` whitelist-only log tail.
- `/_ops/errors` service-grouped error summary with matched pattern and bounded response size.
- `/_ops/config` safe configuration summary and secret presence only.
- `/_ops/metrics` Prometheus-style text metrics.

OPS rules:

- No writes to business data.
- No restart, migration, cache clear, SQL, shell, or config mutation.
- No arbitrary file read; logs stay behind service whitelist.
- No arbitrary command from request parameters.

## Phase 2: Admin Controlled Actions

Future `/_admin/*` work should start with a controlled action catalog, not WebSSH:

```text
POST /_admin/actions/restart?service=dify-api
POST /_admin/actions/reload-nginx
POST /_admin/actions/run-migration
POST /_admin/actions/clear-cache
```

Minimum requirements:

- Default off with `ADMIN_ENABLED=false`.
- Independent `ADMIN_TOKEN`; never reuse `OPS_TOKEN`.
- Whitelist actions only.
- Require confirmation, for example `confirm=true`.
- Write audit logs.
- Return action id and result.
- Do not accept arbitrary shell commands from requests.

## Phase 3: WebSSH or Interactive Shell

Only consider after controlled actions are proven useful. Keep it independent from OPS and Admin action auth, default off, limited to Private/Protected deployments, with strong token, session timeout, audit logs, and explicit command-risk documentation.

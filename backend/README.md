# Go API gateway
Module root is `backend/backend` (go 1.22). Entry point `apps/api-gateway`. See `/BUILD.md` for commands, `/README.md#api-reference`
for routes, `/docs/AUDIT_FIXES.md` for what changed and why. Config is validated at startup; with `ENV=production` it refuses to
start without `JWT_SECRET` (≥32 chars, not a placeholder), `ENGINE_SECRET`, `DATABASE_URL`, `DATA_ENGINE_URL`, `ALLOWED_ORIGINS`.

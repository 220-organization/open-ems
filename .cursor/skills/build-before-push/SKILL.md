---
name: build-before-push
description: >-
  Run Open EMS pre-push checks before git commit or push (API startup + UI build).
  Use when the user asks to commit, push, create a PR, deploy, or merge; when
  app/ or ui/ changed; or when prod api container Restarting after deploy.
---

# Build Before Commit and Push (Open EMS)

**Order:** `checks` → `commit` → `push`. Never push until pre-push checks pass.

Deploy runs `docker compose up --build` on the server. A broken API (`Restarting`) or failed UI build takes the site down.

## When to apply

- User says: commit, push, commit and push, PR, deploy, merge
- Any change under `app/`, `db/`, `requirements.txt`, or `ui/`
- Prod symptom: `open-ems-api-1` **Restarting**, `Application startup failed`, `NameError` in `lifespan`
- CI/deploy log shows compile or container restart errors

## Workflow

1. Finish code edits (working tree may be dirty — **do not commit yet**).
2. From repo root `open-ems/`:

```bash
./scripts/check-before-push.sh
```

3. If the script fails, fix and re-run until exit 0.
4. **Only after checks pass:** `git add` → `git commit` (when user asked).
5. **Only after commit:** `git push`.

Include any fix-up changes in the same commit as the feature.

## What the script runs

### 1. API startup check (when `app/` changed)

```bash
./scripts/check-api-startup.sh
```

- Sets prod-like env (`HUAWEI_*`, `UBETTER_*`, `DEYE_*`) so **all lifespan scheduler branches** run
- Imports `app.main` and enters `lifespan` once, then shuts down
- Catches errors that plain `import app.main` misses, e.g.:

```
NameError: name 'huawei_power_snapshot_loop' is not defined
  File "app/main.py", line 154, in lifespan
```

Force even without app diff: `CHECK_API_STARTUP_FORCE=1 ./scripts/check-before-push.sh`

### 2. UI production build (when `ui/` changed)

```bash
./scripts/check-ui-production-build.sh
```

- `npm ci` in `ui/` if `node_modules` missing
- `NODE_OPTIONS=--max-old-space-size=4096`, `CI=true`, `GENERATE_SOURCEMAP=false`
- Same compile step as deploy (`Dockerfile.ui` / GitHub Actions runner)

Force UI build: `CHECK_UI_BUILD_FORCE=1 ./scripts/check-before-push.sh`

## Manual equivalents

```bash
# API only
./scripts/check-api-startup.sh

# UI only
./scripts/check-ui-production-build.sh

# Optional: targeted pytest after app changes
source .venv/bin/activate
PYTHONPATH=. pytest tests/ -q --tb=short
```

## Docker parity

- **API:** prod runs uvicorn → `lifespan` startup; local check mirrors that path.
- **UI:** deploy ships prebuilt `ui/build/` from GitHub Actions; local `npm run build` catches CRA/ESLint failures.

## Checklist

```
- [ ] ./scripts/check-before-push.sh passes
- [ ] API startup check OK when app/ touched (no NameError / import errors in lifespan)
- [ ] UI production build OK when ui/ touched
- [ ] Then git commit (if user asked)
- [ ] Then git push
```

## Related skill

- [branch-pr-before-push](../branch-pr-before-push/SKILL.md) — feature branch + PR workflow; uses this skill before commit

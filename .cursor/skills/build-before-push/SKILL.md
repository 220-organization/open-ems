---
name: build-before-push
description: >-
  Run the Open EMS UI production build (react-scripts build) before git commit or
  push. Use when the user asks to push, commit, create a PR, deploy, or merge;
  when UI files under open-ems/ui/ changed; or when prod Docker web build failed
  with react-scripts / OOM errors.
---

# Build Before Push (Open EMS)

Always run the **production UI build** before `git commit` or `git push` in this repo. Deploy runs `npm run build` inside `Dockerfile.ui` on the server; a failed build takes the site down after `docker compose down`.

## When to apply

- User says: push, commit, PR, deploy, merge
- Any change under `ui/src/`, `ui/public/`, or `ui/package*.json`
- CI/deploy log shows `[web ui-build] RUN npm run build` failed
- After kiosk / PowerFlow / marketplace UI work

Skip only if the change is **strictly** backend-only (`app/`, `db/`, no UI files) and the user confirms push without UI.

## Workflow

1. From repo root `open-ems/`:

```bash
./scripts/check-ui-production-build.sh
```

2. If the script fails:
   - Fix compile/ESLint errors reported by `react-scripts build`
   - Re-run until it exits 0
3. **Do not push** until the build passes.
4. Include any build-fix changes in the same commit as the feature when possible.

## What the script does

- `npm ci` in `ui/` if `node_modules` is missing (matches deploy lockfile check)
- `NODE_OPTIONS=--max-old-space-size=4096` (avoids local OOM during minification)
- `CI=true` — CRA fails the build on ESLint errors in production mode
- `GENERATE_SOURCEMAP=false` — faster local check (optional override via env)

## Manual equivalent

```bash
cd ui
export NODE_OPTIONS=--max-old-space-size=4096 CI=true GENERATE_SOURCEMAP=false
npm ci   # if needed
npm run build
```

## Docker parity

Server build: `Dockerfile.ui` → `COPY ui/` → `RUN npm run build`. This script validates the same step without Docker. Server OOM is a separate ops issue; compile errors must still be caught here.

## Backend-only changes

If only Python/SQL changed, optionally run targeted tests:

```bash
source .venv/bin/activate
pytest tests/ -q --tb=short
```

UI production build is not required when `ui/` did not change.

## Checklist before push

```
- [ ] ./scripts/check-ui-production-build.sh passes (when ui/ touched)
- [ ] No new ESLint/compile errors in build output
- [ ] Then commit / push
```

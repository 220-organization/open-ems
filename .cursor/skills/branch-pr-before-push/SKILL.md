---
name: branch-pr-before-push
description: >-
  Open EMS git workflow: always push to develop. Use only in the open-ems
  repository when the user asks to push, commit and push, ship changes, open a
  PR, or publish open-ems work. Do not apply in the parent activecharge
  monorepo or other projects. Runs check-before-push (API lifespan + UI build)
  before commit. A GitHub Action opens the develop → master pull request.
---

# Always push to develop (Open EMS)

**Scope:** `open-ems/` only (`git rev-parse --show-toplevel` must be the open-ems repo root).

Remote: `origin` → `220-organization/open-ems`.

**always push to develop**

Never push `main` or `master`. Production updates land when the develop → master pull request is merged. GitHub Actions (`.github/workflows/create-pr-develop-to-master.yml`) opens that PR after every push to `develop`. Do not create it with `gh pr create`.

Correct order: **develop → checks → commit → push develop**.

## When to apply

- User says: push, commit and push, ship, publish, open PR, merge request
- Finishing UI/backend work in `open-ems/`
- After implementing a feature before sharing with the team

**Do not apply** when:

- Working outside `open-ems/` (e.g. `activecharge/` root, `admin-portal/`, `src-js/`)
- User explicitly asks to push to `main` or `master` or to force-push (warn; follow their rule only if they insist)

## Preconditions

1. Confirm repo root:

```bash
cd open-ems   # or path ending in /open-ems
git rev-parse --show-toplevel
```

2. Be on `develop` and update it:

```bash
git fetch origin develop
git checkout develop
git pull --ff-only origin develop
```

If the checkout is a different local branch that the user asked to rename, rename it to `develop` instead of creating a feature branch.

## Workflow

Copy and track:

```
- [ ] On develop
- [ ] check-before-push passed (API startup if app/ touched; UI build if ui/ touched) — BEFORE commit
- [ ] Changes committed (if user asked)
- [ ] develop pushed with -u
```

### 1. Stay on develop

Do not create a feature branch. Do not check out `main` after the push.

```bash
git checkout develop
git pull --ff-only origin develop
```

### 2. Pre-push checks before commit

Run while changes are still uncommitted:

```bash
./scripts/check-before-push.sh
```

| Check | When | Catches |
|-------|------|---------|
| `check-api-startup.sh` | `app/` changed | `NameError` in `lifespan`, missing scheduler imports |
| `check-ui-production-build.sh` | `ui/` changed | CRA/ESLint compile errors |

Do not `git commit` or `git push` until checks pass.

### 3. Commit (only when user requests)

After checks pass:

```bash
git add <files>
git commit -m "..."
```

Follow repo commit style (imperative summary). Do not commit unless the user asked.

### 4. Push develop

```bash
git push -u origin develop
```

The Action creates or reuses the open pull request `develop` → `master`. After a successful push, give the user that PR URL when it exists, otherwise:

```text
https://github.com/220-organization/open-ems/compare/master...develop?expand=1
```

Stay on `develop`.

## Rules

| Rule | Detail |
|------|--------|
| always push to develop | `git push -u origin develop` is the only normal push |
| Build before commit | Run `./scripts/check-before-push.sh` before `git commit` when `app/` or `ui/` changed |
| Never push `main` or `master` | Forbidden unless the user explicitly overrides |
| Never force-push | Warn if requested |
| Never `git config` changes | Do not modify git config |
| No `--no-verify` | Unless the user explicitly requests |
| Do not open the PR by hand | `.github/workflows/create-pr-develop-to-master.yml` does it. Needs repo secret `GH_PAT` (classic PAT, `repo` scope) |
| Scope | Only `open-ems/` — ignore this skill for other repos in the monorepo |

## Quick reference

```bash
cd open-ems
git fetch origin develop
git checkout develop && git pull --ff-only origin develop
# ... edit files ...
./scripts/check-before-push.sh   # BEFORE commit (API startup + UI build as needed)
git add ...
git commit -m "..."
git push -u origin develop
```

## Related skill

- [build-before-push](../build-before-push/SKILL.md) — API startup + UI build; must run before commit/push
- [wire-integration-secrets](../wire-integration-secrets/SKILL.md) — when adding a new external API secret, wire docker-compose + deploy.yml or production stays `configured: false`

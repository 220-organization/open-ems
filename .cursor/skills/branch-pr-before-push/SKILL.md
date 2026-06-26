---
name: branch-pr-before-push
description: >-
  Open EMS git workflow: create a feature branch, open a GitHub PR, push the
  branch (never main), then checkout main. Use only in the open-ems repository
  when the user asks to push, commit and push, ship changes, open a PR, or
  publish open-ems work. Do not apply in the parent activecharge monorepo or
  other projects.
---

# Branch and PR Before Push (Open EMS)

**Scope:** `open-ems/` only (`git rev-parse --show-toplevel` must be the open-ems repo root).

Remote: `origin` → `220-organization/open-ems`. Default base branch: **`main`**.

Never push directly to `main`. Always: branch → commit → checks → push branch → PR → return to `main`.

## When to apply

- User says: push, commit and push, ship, publish, open PR, merge request
- Finishing UI/backend work in `open-ems/`
- After implementing a feature before sharing with the team

**Do not apply** when:

- Working outside `open-ems/` (e.g. `activecharge/` root, `admin-portal/`, `src-js/`)
- User explicitly asks to push to `main` or force-push (warn; follow their rule only if they insist)

## Preconditions

1. Confirm repo root:

```bash
cd open-ems   # or path ending in /open-ems
git rev-parse --show-toplevel
```

2. Fetch latest `main`:

```bash
git fetch origin main
```

## Workflow

Copy and track:

```
- [ ] On feature branch (not main)
- [ ] Changes committed (if user asked to commit)
- [ ] build-before-push passed (if ui/ touched)
- [ ] Branch pushed with -u
- [ ] PR created (gh pr create)
- [ ] Checked out main
```

### 1. Create feature branch

If on `main` or branch is wrong, create a new branch from `origin/main`:

```bash
git checkout main
git pull --ff-only origin main
git checkout -b <branch-name>
```

**Branch naming:** short kebab-case, topic-based — e.g. `kiosk-solar-forecast`, `fix-dam-chart-tooltip`. Avoid generic names like `fix` or `updates`.

If already on a suitable feature branch with unpushed work, keep it.

### 2. Commit (only when user requests)

Follow repo commit style (imperative, one line summary + optional body). Do not commit unless the user asked.

### 3. Pre-push checks

If any file under `ui/` changed, run **build-before-push**:

```bash
./scripts/check-ui-production-build.sh
```

Do not push until it passes.

### 4. Push branch and open PR

Run in parallel first to draft the PR:

```bash
git status
git diff
git log origin/main..HEAD --oneline
git branch -vv
```

Then sequentially:

```bash
git push -u origin HEAD
```

```bash
gh pr create --base main --title "<title>" --body "$(cat <<'EOF'
## Summary
- <bullet 1>
- <bullet 2>

## Test plan
- [ ] <how to verify>

EOF
)"
```

Return the PR URL to the user.

### 5. Checkout main after push

Always return the local workspace to `main`:

```bash
git checkout main
git pull --ff-only origin main
```

Leave the feature branch on the remote; local branch may stay or be deleted only if the user asks.

## Rules

| Rule | Detail |
|------|--------|
| Never push `main` | `git push origin main` is forbidden unless user explicitly overrides |
| Never force-push `main` | Warn if requested |
| Never `git config` changes | Do not modify git config |
| No `--no-verify` | Unless user explicitly requests |
| PR before “done” | Treat push without PR as incomplete for this workflow |
| Scope | Only `open-ems/` — ignore this skill for other repos in the monorepo |

## Quick reference

```bash
# Full flow (after changes are ready)
cd open-ems
git fetch origin main
git checkout main && git pull --ff-only origin main
git checkout -b my-feature
# ... commit when user asks ...
./scripts/check-ui-production-build.sh   # if ui/ changed
git push -u origin HEAD
gh pr create --base main --title "..." --body "..."
git checkout main && git pull --ff-only origin main
```

## Related skill

- [build-before-push](../build-before-push/SKILL.md) — required when `ui/` changed

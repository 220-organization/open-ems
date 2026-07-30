---
name: wire-integration-secrets
description: >-
  Wire Open EMS external API credentials into production deploy (settings,
  docker-compose, GitHub Actions secrets → server .env). Use when adding a new
  vendor/API integration (Deye, Ubetter, Huawei, GridLab, OREE, ENTSO-E, etc.),
  when introducing a new *_PASSWORD / *_TOKEN / *_API_KEY env var, or when
  production returns configured:false after a successful deploy.
---

# Wire Integration Secrets (Open EMS Deploy)

**Scope:** `open-ems/` only.

**Incident this prevents:** Code merges and deploys, but UI/API show
`{"configured":false,"items":[]}` because the secret never reached the `api`
container. GridLab (2026-07) failed this way: `GRIDLAB_PASSWORD` was in
`settings.py` / local `.env` only — missing from `docker-compose.yml` and
`.github/workflows/deploy.yml`.

## Rule

Every new secret env var used by `app/settings.py` must be wired in **all** of
these places in the **same PR** as the integration. Local `.env` alone is not
enough for production.

## Checklist (copy and complete)

```
- [ ] app/settings.py — read os.environ (or hardcode non-secrets)
- [ ] .env.example — document the var (empty placeholder for secrets)
- [ ] docker-compose.yml — api.environment: VAR: ${VAR:-}
- [ ] .github/workflows/deploy.yml — secrets.VAR in "Write Compose .env" env:
- [ ] .github/workflows/deploy.yml — printf '%s\n' "VAR=${VAR:-}" into open-ems-deploy.env
- [ ] deploy/github-actions-env.example.yaml — list secrets.VAR
- [ ] docs/… — note that the GitHub Actions secret must be set
- [ ] Remind user: add repository secret in GitHub Settings → Secrets → Actions
- [ ] After next deploy: curl /api/<vendor>/devices → configured:true (or equivalent)
```

## Required file edits

### 1. `docker-compose.yml` (`api` service)

```yaml
NEW_VENDOR_PASSWORD: ${NEW_VENDOR_PASSWORD:-}
```

Compose only interpolates vars listed here into the container.

### 2. `.github/workflows/deploy.yml`

In step **Write Compose .env on runner**:

1. Add to the step `env:` block:
   `NEW_VENDOR_PASSWORD: ${{ secrets.NEW_VENDOR_PASSWORD }}`
2. Add to the `printf` block that builds `/tmp/open-ems-deploy.env`:
   `printf '%s\n' "NEW_VENDOR_PASSWORD=${NEW_VENDOR_PASSWORD:-}"`

That file is scp’d to `/220/open-ems/.env` on the server.

### 3. `deploy/github-actions-env.example.yaml`

Document the secret name for operators.

### 4. GitHub secret (human step — agent cannot skip reminding)

Tell the user to add **Actions secret** `NEW_VENDOR_PASSWORD` before or right
after merge. Without it, redeploy still yields `configured: false`.

## Patterns already in repo

| Integration | Secret(s) |
|-------------|-----------|
| Deye | `DEYE_PASSWORD`, `DEYE_APP_SECRET`, … |
| Ubetter | `UBETTER_PASSWORD`, `UBETTER_220KM_PASSWORD` |
| Huawei | `HUAWEI_SYSTEM_CODE`, … |
| OREE / ENTSO-E | `OREE_API_KEY`, `ENTSOE_SECURITY_TOKEN` |
| GridLab | `GRIDLAB_PASSWORD` only (URL/user/device hardcoded) |

Copy the Ubetter / GridLab lines in `deploy.yml` and `docker-compose.yml` as the template.

## Verify before calling the integration “done”

1. Grep the new secret name across the repo — must hit **compose + deploy.yml + example yaml**.
2. After merge + Actions deploy (or local compose with `.env`):
   - `GET /api/<prefix>/devices` (or health/config endpoint) → `configured: true`
   - API logs show “configured”, not “not configured — set env: …”
3. Do not treat “Actions run green” as proof the secret is present — empty
   `${{ secrets.X }}` still produces an empty `.env` line.

## Do not

- Assume `.env.example` or local `.env` reaches production
- Rely on baking secrets into the Docker image
- Ship the integration PR without the deploy wiring (or a same-day follow-up PR
  before telling the user it is live)

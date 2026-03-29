# Open EMS

## Local development

From this directory:

```bash
./run-local.sh
```

The script starts PostgreSQL (Docker), runs Flyway migrations, then **uvicorn** on a free TCP port beginning at **9220** (change the base port with `PORT=8090 ./run-local.sh` if needed).

| What | URL |
|------|-----|
| Power flow UI | [http://localhost:9220/](http://localhost:9220/) (same page at `/power-flow`) |
| OpenAPI (Swagger UI) | [http://localhost:9220/docs](http://localhost:9220/docs) |
| Health | `GET http://localhost:9220/health` |

Default DB connection is `postgresql+asyncpg://openems:openems@127.0.0.1:5433/openems` (override with `DATABASE_URL`).

## Deploy (GitHub Actions + SSH)

Workflow `.github/workflows/deploy.yml` in **this repository** runs on push to `main`, `master`, or `preprod`: packs the tree (excluding `.git` / `.venv`), copies it over SSH, then runs `docker compose` on the server.

**Target OS (tested):** **Ubuntu 24.04.4 LTS** (Noble Numbat), x86_64 — same line as `docker.io` / `docker-compose-v2` from Ubuntu archives. On the server, print the exact image:

```bash
lsb_release -a
```

```bash
cat /etc/os-release
```

Example lines you should see on that host include `VERSION="24.04.4 LTS (Noble Numbat)"` and `VERSION_ID="24.04"`.

Deployment path on the server: `/220/open-ems`. The workflow connects as **`root`** over SSH (adjust user/host in `.github/workflows/deploy.yml` if you change that).

### 1. Generate SSH key pair (on your laptop or admin machine)

Use **Ed25519**, empty passphrase (typical for CI), and a dedicated key file:

```bash
mkdir -p ~/.ssh/open-ems-deploy
ssh-keygen -t ed25519 \
  -f ~/.ssh/open-ems-deploy/open_ems_deploy_ed25519 \
  -N "" \
  -C "open-ems-github-actions-deploy"
```

This creates:

- **Private key:** `~/.ssh/open-ems-deploy/open_ems_deploy_ed25519` — for GitHub only (never commit).
- **Public key:** `~/.ssh/open-ems-deploy/open_ems_deploy_ed25519.pub` — for the Ubuntu server.

Show the public key (one line) to copy:

```bash
cat ~/.ssh/open-ems-deploy/open_ems_deploy_ed25519.pub
```

### 2. Add the private key to GitHub (repository secret)

The workflow reads **`secrets.PRIVATE_KEY`**. Store the **entire** private key file as a **repository Actions secret** (not a variable):

1. GitHub → your repo → **Settings** → **Secrets and variables** → **Actions**.
2. **Secrets** tab → **New repository secret**.
3. **Name:** `PRIVATE_KEY`
4. **Secret:** paste the full contents of the private key file, including the header/footer lines:

   ```bash
   cat ~/.ssh/open-ems-deploy/open_ems_deploy_ed25519
   ```

   You must include:

   - `-----BEGIN OPENSSH PRIVATE KEY-----`
   - all lines in between
   - `-----END OPENSSH PRIVATE KEY-----`

5. Save (**Add secret**).

*(Optional: if you use **Environments** with protection rules, you can instead create an environment secret named `PRIVATE_KEY` and add `environment: …` to the job in `deploy.yml` — the default workflow expects a **repository** secret.)*

### 3. Add the public key to Ubuntu (`authorized_keys`)

SSH into the server as the same user GitHub Actions uses (here **`root`**), then:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
```

Append the **public** key line (replace the placeholder with your real `.pub` line):

```bash
echo 'ssh-ed25519 AAAA...your-public-key... open-ems-github-actions-deploy' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Or from your admin machine (if password SSH is still enabled once):

```bash
ssh-copy-id -i ~/.ssh/open-ems-deploy/open_ems_deploy_ed25519.pub root@YOUR_SERVER_IP
```

Test login with the **private** key only (no password):

```bash
ssh -i ~/.ssh/open-ems-deploy/open_ems_deploy_ed25519 -o IdentitiesOnly=yes root@YOUR_SERVER_IP 'echo ok'
```

### 4. What the workflow does on the server

- Ensures **Docker** and **`docker compose` v2** (installs `docker.io` / `docker-compose-v2` on Ubuntu if missing).
- Syncs the repo tarball and runs `docker compose down --remove-orphans` then `docker compose up -d --build` under `/220/open-ems`.

Optional: set `RUN_FLYWAY_ON_START=true` and `DATABASE_URL` in the API service environment if you run the app image against an external database (Flyway runs at container start via `scripts/render_flyway_migrate.py`). The default Compose stack uses the bundled `db` service and does not need those variables for migrations (Flyway runs as the `migrate` service).

- Health check: `GET /health`
- Published API port on the host: `8095` → container `8090` (see `docker-compose.yml`).

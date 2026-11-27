# Running the bot + Mini App

- [Part 1: local testing (Windows)](#part-1-local-testing-windows)
- [Part 2: production on Linux (Docker)](#part-2-production-on-linux-docker)
- [Part 3: production on Windows Server (IIS + existing PostgreSQL)](#part-3-production-on-windows-server-iis--existing-postgresql)

> **One bot token can only run in one place.** If the same token polls from your laptop and the
> server, Telegram returns `409 Conflict` and messages go to whichever one asked last. Create a second
> bot in @BotFather (e.g. `mytest_dev_bot`) for local testing and keep the main token for the server.

---

## Part 1: local testing (Windows)

You need 3 terminals: the bot, the Mini App server, and an HTTPS tunnel. Telegram only opens Mini
Apps over `https://`, and the tunnel gives your `localhost:8000` a temporary public https address.

### One-time setup

```powershell
winget install --id Cloudflare.cloudflared      # then open a NEW terminal so it's on PATH
```

Add these lines to `.env` (they are documented in `.env.example`):

```ini
WEBAPP_URL=
INIT_DATA_MAX_AGE=86400
```

### Every time you test

**Terminal 1: Mini App server**

```powershell
cd path\to\test-tg-bot
.venv\Scripts\activate
uvicorn webapp.main:app --port 8000 --reload
```

**Terminal 2: tunnel** (keep it open)

```powershell
cd path\to\test-tg-bot
.venv\Scripts\activate
python dev_tunnel.py
```

It starts `cloudflared`, waits until the tunnel is reachable, and writes the tunnel's real address into
`.env` as `WEBAPP_URL`. (Manual alternative: run `cloudflared tunnel --url http://localhost:8000`, wait
for the "Your quick Tunnel has been created!" box and copy *that exact* address into `.env`.)

**Terminal 3: bot** (start it *after* setting `WEBAPP_URL`; restart it whenever the URL changes)

```powershell
cd path\to\test-tg-bot
.venv\Scripts\activate
python -m bot
```

The log should say `Mini App enabled at https://...`.

**In Telegram:** open your bot and send `/start`. You'll see a **📱 Mini App** button in the menu, and
the button next to the message box opens it too. If the button doesn't appear, close the chat and
open it again (Telegram caches the menu button).

Notes:
- The quick-tunnel URL **changes every time** you restart `cloudflared`. Update `WEBAPP_URL` and
  restart the bot each time.
- When you're done, clear `WEBAPP_URL` and restart the bot. The menu button goes back to normal.
- Registering through the Mini App needs the bot running (terminal 3), because Telegram delivers
  the shared phone number to the bot.
- To work on the UI in a normal browser without Telegram: set `WEBAPP_DEV_USER_ID=<your Telegram id>`
  in `.env`, restart uvicorn, and open http://localhost:8000. Register in the bot first, because phone
  sharing only works inside Telegram. **Never set this variable on the server.**
- To open the app in Telegram's own debugger: Telegram Desktop → Settings → Advanced → Experimental
  → *Enable webview inspection*, then right-click inside the Mini App → Inspect.

---

## Part 2: production on Linux (Docker)

Everything runs in Docker: PostgreSQL, the bot, the Mini App (2 workers), and Caddy, which serves
HTTPS and gets and renews the certificate automatically.

```
Internet ──443──► caddy ──► webapp (uvicorn ×2) ──┐
Telegram ◄──polling── bot ─────────────────────────┼──► postgres (volume: pgdata)
```

### What you need

- A Linux server (e.g. Ubuntu 22.04/24.04, 1 GB RAM is enough) with a public IP.
- A **domain or subdomain**, e.g. `test.example.uz`, with a DNS **A record** pointing at the server's
  IP. Telegram requires HTTPS, and HTTPS requires a domain.
- Ports **80 and 443** open (80 is needed for the certificate challenge).

### 1. Install Docker (once)

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER      # log out and back in afterwards
```

### 2. Get the code

```bash
git clone <your-repo-url> testbot && cd testbot
```

(Or copy the project folder with `scp`/WinSCP. The question `.docx` files in `docs/` are needed for
the import.)

### 3. Configure

```bash
cp deploy/.env.example deploy/.env
nano deploy/.env
```

```ini
BOT_TOKEN=<production bot token>
DOMAIN=test.example.uz
POSTGRES_PASSWORD=<output of: openssl rand -hex 24>
EXAM_QUESTION_COUNT=25
```

`DATABASE_URL` and `WEBAPP_URL` are set automatically from these values.

### 4. Start

```bash
docker compose -f deploy/docker-compose.prod.yml up -d --build
docker compose -f deploy/docker-compose.prod.yml run --rm bot python import_docs.py   # load questions
```

The database schema is created automatically on first start (migrations).

### 5. Check

```bash
docker compose -f deploy/docker-compose.prod.yml ps          # all services "running"/"healthy"
docker compose -f deploy/docker-compose.prod.yml logs -f bot  # "Mini App enabled at https://..."
curl https://test.example.uz/healthz                          # {"ok":true}
```

Then send `/start` to the bot in Telegram.

Optional: in @BotFather → your bot → *Bot Settings → Configure Mini App → Enable*, set the same
`https://DOMAIN/` URL. The app then also opens from the bot's profile and from links like
`t.me/<bot>?startapp`.

### Everyday operations

All commands below are run from the project folder; `dc` is shorthand for
`docker compose -f deploy/docker-compose.prod.yml` (add `alias dc='docker compose -f deploy/docker-compose.prod.yml'`
to `~/.bashrc`).

| Task | Command |
|---|---|
| Deploy a new version | `git pull && dc up -d --build` (migrations run on start) |
| New/changed question docs | copy into `docs/`, then `dc up -d --build && dc run --rm bot python import_docs.py` |
| Logs | `dc logs -f bot` / `dc logs -f webapp` / `dc logs -f caddy` |
| Restart | `dc restart bot webapp` |
| Stop everything | `dc down` (data is kept in volumes; `down -v` would **delete** the database) |
| DB shell | `dc exec postgres psql -U testbot testbot` |

### Backups

```bash
# backup (run daily from cron, keep copies off the server)
docker compose -f deploy/docker-compose.prod.yml exec -T postgres pg_dump -U testbot -Fc testbot > backup_$(date +%F).dump

# restore into an empty database
docker compose -f deploy/docker-compose.prod.yml exec -T postgres pg_restore -U testbot -d testbot --clean < backup_2026-11-27.dump
```

Example crontab line (`crontab -e`): `0 3 * * * cd /home/USER/testbot && docker compose -f deploy/docker-compose.prod.yml exec -T postgres pg_dump -U testbot -Fc testbot > /home/USER/backups/testbot_$(date +\%F).dump`

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Conflict: terminated by other getUpdates request` in bot logs | The same token is running somewhere else (e.g. your laptop). Stop the other copy. |
| Caddy logs certificate errors | DNS doesn't point at the server yet, or port 80/443 is blocked by a firewall (`sudo ufw allow 80,443/tcp`). |
| Mini App says "open from the Telegram bot" | Opened in a normal browser. It only works inside Telegram. |
| Mini App shows an error right after opening | `BOT_TOKEN` differs between bot and webapp (both read `deploy/.env`, so restart both after changing it). |
| No 📱 Mini App button | Check that the bot log says `Mini App enabled at ...`, then reopen the chat in Telegram. |
| `Telegram network error (retrying automatically)` warnings | Brief connection drops, retried automatically. Only a concern if constant. |

### No domain?

A Cloudflare *named* tunnel (free Cloudflare account + a domain on Cloudflare) can replace Caddy, with
no open ports needed. The `trycloudflare.com` quick tunnel from Part 1 is for testing only: its URL
changes on every restart.

---

## Part 3: production on Windows Server (IIS + existing PostgreSQL)

Same pattern as a typical IIS deployment: a **git clone** (e.g. `C:\MyWebApps\exam-pilot-bot`) is
mirrored with robocopy into the **deploy folder** `C:\inetpub\exam-pilot-bot`, which is also the IIS
site folder. The bot and the Mini App run from the deploy folder as two Windows services
([NSSM](https://nssm.cc)), and IIS forwards your domain to the Mini App over HTTPS.

```
Telegram ──https──► IIS site C:\inetpub\exam-pilot-bot (web.config: proxy, Let's Encrypt via win-acme)
                     └─► ExamPilot-WebApp service (uvicorn, 127.0.0.1:8000)
Telegram ◄──polling── ExamPilot-Bot service (python -m bot)
                     both ──► PostgreSQL (existing)
```

One script does every deployment, first one included: **`deploy\windows\deploy.ps1`**, run from the
git clone in an elevated PowerShell. It stops the services, mirrors the code, refreshes `web.config`,
creates or updates `.venv` and the packages, migrates the database, imports `docs\*.docx`,
creates or updates the services, starts them, and smoke tests the result.

Files that exist **only in the deploy folder** and are never touched by robocopy: `.env` (secrets),
`.venv`, `logs`, `backups`, `data`, `.well-known` (win-acme).

### 1. Prerequisites (once)

| What | Where | Notes |
|---|---|---|
| Python 3.13 or 3.14 (64-bit) | python.org | e.g. `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe` |
| Git for Windows | git-scm.com | |
| NSSM 2.24 | nssm.cc/download | unzip, e.g. to `C:\tools\nssm\`, use `win64\nssm.exe` |
| IIS URL Rewrite 2.1 | iis.net/downloads/microsoft/url-rewrite | |
| IIS Application Request Routing 3.0 | iis.net/downloads/microsoft/application-request-routing | |
| win-acme | win-acme.com | free Let's Encrypt certificates for IIS, auto-renewal |

Turn on the ARR proxy (once):

```powershell
& "$env:windir\system32\inetsrv\appcmd.exe" set config -section:system.webServer/proxy /enabled:"True" /commit:apphost
```

Network: outbound HTTPS to `api.telegram.org` (the bot polls Telegram), inbound 80 and 443 for IIS.
Port 8000 stays internal.

### 2. Access to the private GitHub repository (once)

`git clone` answers **"Repository not found"** for a private repo when the server has no access to
it (no credentials, or a saved login of a different GitHub account, e.g. from another project).
Use a **read-only deploy key**, which gives the server access to this one repository only:

```powershell
ssh-keygen -t ed25519 -C "exam-pilot-bot deploy" -f "$HOME\.ssh\exam_pilot_deploy"   # press Enter twice (no passphrase)
Get-Content "$HOME\.ssh\exam_pilot_deploy.pub"                                       # copy this line
```

GitHub → repository → **Settings → Deploy keys → Add deploy key** → paste, leave *Allow write
access* unchecked. Then tell SSH to use that key for this repo. Add to `$HOME\.ssh\config`:

```
Host github-exampilot
    HostName github.com
    User git
    IdentityFile ~/.ssh/exam_pilot_deploy
    IdentitiesOnly yes
```

Clone over SSH, using that host alias (it doesn't affect your other repositories):

```powershell
cd C:\MyWebApps
git clone git@github-exampilot:<owner>/exam-pilot-bot.git
```

Alternative without SSH: create a fine-grained personal access token with read-only *Contents*
permission for this repository, and enter it as the password when `git clone https://...` asks. If
Git Credential Manager is already signed in to another account, first remove that entry from
Windows *Credential Manager → Windows Credentials → git:https://github.com*.

### 3. Database (once)

In `psql` as the postgres superuser (e.g. `"C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres`):

```sql
CREATE ROLE exampilot LOGIN PASSWORD 'choose-a-strong-password';
CREATE DATABASE exampilot OWNER exampilot ENCODING 'UTF8';
```

Letters and digits only for the password (it becomes part of a URL). Tables are created by the
deploy script.

### 4. First deployment

```powershell
cd C:\MyWebApps\exam-pilot-bot
powershell -ExecutionPolicy Bypass -File deploy\windows\deploy.ps1
```

The first run stops early and creates `C:\inetpub\exam-pilot-bot\.env` from the template. Fill it in:

```ini
BOT_TOKEN=<production bot token>
DATABASE_URL=postgresql+asyncpg://exampilot:choose-a-strong-password@localhost:5432/exampilot
EXAM_QUESTION_COUNT=25
WEBAPP_URL=
INIT_DATA_MAX_AGE=86400
WEBAPP_DEV_USER_ID=
```

Leave `WEBAPP_URL` empty until HTTPS works (step 5). Then run the script again with your paths:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\deploy.ps1 `
    -Python "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" `
    -Nssm "C:\tools\nssm\win64\nssm.exe" `
    -PostgresService "postgresql-x64-17"
```

`-PostgresService` is the PostgreSQL Windows service name (`Get-Service *postgres*`), so our services
start after the database. Other options: `-DeployDir` (default `C:\inetpub\exam-pilot-bot`),
`-Port` (8000), `-SkipImport`.

The chat bot now works. Send `/start` to it in Telegram.

### 5. IIS site + HTTPS (once)

1. IIS Manager → **Sites → Add Website**: name `exam-pilot-bot`, physical path
   `C:\inetpub\exam-pilot-bot`, binding **http** / port 80 / host name = your domain. Set its
   application pool's *.NET CLR version* to **No Managed Code**.
2. Run `wacs.exe` (win-acme) as Administrator → **N** (create certificate) → choose the site → accept
   the defaults. It validates the domain over port 80, adds the **https** binding and schedules
   renewals.
3. Open `https://<your-domain>/healthz` in a browser → `{"ok":true}`.
4. Set `WEBAPP_URL=https://<your-domain>/` in `C:\inetpub\exam-pilot-bot\.env` and run `deploy.ps1`
   again. Its smoke test now also checks the public URL, and the bot shows the **📱 Mini App**
   button.

Optional: @BotFather → your bot → *Bot Settings → Configure Mini App* → same URL.

### Deploying updates

Commit and push on your PC. On the server:

```powershell
cd C:\MyWebApps\exam-pilot-bot
git pull
powershell -ExecutionPolicy Bypass -File deploy\windows\deploy.ps1 -Python "..." -Nssm "..." -PostgresService "..."
```

If a step fails, the script stops with the error and the services stay stopped. Fix it, or go back
with `git checkout <previous-commit>` in the clone, and run the script again.

`deploy.ps1` must run from inside the clone (it uses `common.ps1` next to it and the code around it).
Don't copy it elsewhere. **One-click option:** copy `deploy\windows\desktop-deploy.example.ps1` to
the Desktop (e.g. as `exampilot-deploy.ps1`) and set your paths at the top once. Running it as
Administrator does `git pull` + `deploy.ps1` with those settings. It always calls the clone's
current `deploy.ps1`, so it never goes stale.

CI (`.github/workflows/ci.yml`) runs lint, the tests on Windows (Python 3.13 and 3.14) and the
tests against PostgreSQL on every push. Check it's green before you deploy. To automate deployment
later, add a job on a self-hosted Windows runner that checks out the code and runs `deploy.ps1`.

### Everyday operations

| Task | Command |
|---|---|
| Status | `Get-Service ExamPilot-*` |
| Restart | `Restart-Service ExamPilot-Bot, ExamPilot-WebApp` |
| Live logs | `Get-Content C:\inetpub\exam-pilot-bot\logs\bot.log -Tail 50 -Wait` (and `webapp.log`) |
| Stop / start | `Stop-Service ExamPilot-*` / `Start-Service ExamPilot-*` |
| Remove the services | `nssm remove ExamPilot-Bot confirm`, `nssm remove ExamPilot-WebApp confirm` |

Logs rotate at 10 MB.

### Backups

```powershell
powershell -ExecutionPolicy Bypass -File C:\MyWebApps\exam-pilot-bot\deploy\windows\backup.ps1 `
    -PgDump "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -Destination "D:\backups\exam-pilot-bot"
```

Keeps 14 days (`-KeepDays`). Schedule it daily in Task Scheduler (*Program* `powershell.exe`,
*Arguments* `-ExecutionPolicy Bypass -File C:\MyWebApps\exam-pilot-bot\deploy\windows\backup.ps1 -PgDump "..." -Destination "..."`,
run whether the user is logged on or not), and copy backups off the server. Restore:
`pg_restore -U exampilot -d exampilot --clean <file>.dump`.

### Troubleshooting (Windows)

| Symptom | Likely cause |
|---|---|
| `git clone`: *Repository not found* | No access to the private repo from the server. See step 2. |
| `https://domain/healthz` → **502.3** | ExamPilot-WebApp isn't running. See `logs\webapp.log`. |
| IIS shows its own 404/500 page for every URL | ARR proxy not enabled (`appcmd` in step 1), or URL Rewrite/ARR missing. |
| win-acme validation fails | DNS doesn't point at the server yet, or port 80 is blocked. |
| `Conflict: terminated by other getUpdates request` in `bot.log` | The same bot token also runs on your PC. Stop it there. |
| pip "access denied" during deploy | A process still uses `.venv`. Run `Stop-Service ExamPilot-*` and retry. |
| Garbled characters in logs | The services get `PYTHONUTF8=1` from `deploy.ps1`; rerun it if you created them by hand. |

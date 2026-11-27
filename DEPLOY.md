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

The bot and the Mini App run as two Windows services (managed by [NSSM](https://nssm.cc)). IIS serves
your domain over HTTPS and forwards requests to the Mini App, and both use your existing PostgreSQL.

```
Telegram ──https──► IIS (your domain, Let's Encrypt certificate via win-acme)
                     └─ reverse proxy ──► TestBot-WebApp service (uvicorn, 127.0.0.1:8000)
Telegram ◄──polling── TestBot-Bot service (python -m bot)
                     both ──► PostgreSQL
```

Scripts used below live in `deploy\windows\`: `install.ps1` (once), `update.ps1` (each deploy),
`backup.ps1` (daily), `web.config` (IIS). Run PowerShell **as Administrator** for all steps.

### 1. Install the prerequisites (once)

| What | Where | Notes |
|---|---|---|
| Python 3.13 (64-bit) | python.org → Windows installer | Choose *Install for all users*. Remember the path, e.g. `C:\Program Files\Python313\python.exe` |
| Git for Windows | git-scm.com | to clone and pull the code |
| NSSM 2.24 | nssm.cc/download | unzip, e.g. to `C:\tools\nssm\` (use `win64\nssm.exe`) |
| IIS URL Rewrite 2.1 | iis.net/downloads/microsoft/url-rewrite | |
| IIS Application Request Routing 3.0 | iis.net/downloads/microsoft/application-request-routing | |
| win-acme | win-acme.com | free Let's Encrypt certificates for IIS, renews automatically |

Turn on the ARR proxy (once, after installing ARR):

```powershell
& "$env:windir\system32\inetsrv\appcmd.exe" set config -section:system.webServer/proxy /enabled:"True" /commit:apphost
```

The server needs **outbound** HTTPS to `api.telegram.org` (the bot polls Telegram) and **inbound**
ports **80 and 443** for IIS. Port 8000 stays internal (the Mini App only listens on 127.0.0.1).

### 2. Create the database (once)

In `psql` as the postgres superuser (e.g. `"C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres`):

```sql
CREATE ROLE testbot LOGIN PASSWORD 'choose-a-strong-password';
CREATE DATABASE testbot OWNER testbot ENCODING 'UTF8';
```

Use letters and digits for the password (it becomes part of a URL). The tables are created by the
install script.

### 3. Get the code and configure (once)

```powershell
git clone <your-repo-url> C:\apps\testbot
cd C:\apps\testbot
copy .env.example .env
notepad .env
```

```ini
BOT_TOKEN=<production bot token>
DATABASE_URL=postgresql+asyncpg://testbot:choose-a-strong-password@localhost:5432/testbot
EXAM_QUESTION_COUNT=25
WEBAPP_URL=https://test.example.uz/
INIT_DATA_MAX_AGE=86400
WEBAPP_DEV_USER_ID=
```

`.env` stays only on the server (it's in `.gitignore`). Leave `WEBAPP_DEV_USER_ID` empty; the
scripts refuse to run if it's set.

### 4. Install the services (once)

```powershell
cd C:\apps\testbot
powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1 `
    -Python "C:\Program Files\Python313\python.exe" `
    -Nssm "C:\tools\nssm\win64\nssm.exe" `
    -PostgresService "postgresql-x64-17"
```

(`-PostgresService` is the name of your PostgreSQL Windows service; see `Get-Service *postgres*`. It
makes our services start after the database.)

The script creates `.venv`, installs packages, creates the tables, imports the questions from
`docs\`, registers **TestBot-Bot** and **TestBot-WebApp** (auto-start, restart on crash, logs in
`C:\apps\testbot\logs\`), starts them and checks that both are up.

### 5. IIS site + HTTPS (once)

1. Create the site folder and copy the proxy config into it:
   ```powershell
   New-Item -ItemType Directory -Force C:\inetpub\testbot
   Copy-Item C:\apps\testbot\deploy\windows\web.config C:\inetpub\testbot\
   ```
2. IIS Manager → **Sites → Add Website**: name `testbot`, physical path `C:\inetpub\testbot`,
   binding **http**, port 80, host name `test.example.uz` (your domain). In *Application Pools*, set
   the `testbot` pool's *.NET CLR version* to **No Managed Code**.
3. Run `wacs.exe` (win-acme) as Administrator → **N** (create certificate) → pick the `testbot` site
   → accept the defaults. It validates the domain over port 80, adds the **https** binding to the
   site and schedules automatic renewal.
4. Check from any browser: `https://test.example.uz/healthz` → `{"ok":true}`.

Then restart the bot so it picks up the Mini App URL (`Restart-Service TestBot-Bot`) and check that
`logs\bot.log` says `Mini App enabled at https://test.example.uz/`.

Optional: in @BotFather → your bot → *Bot Settings → Configure Mini App*, set the same URL.

### Deploying updates (every time)

On your PC: commit and push. On the server:

```powershell
cd C:\apps\testbot
git pull
powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1
```

`update.ps1` stops both services, installs any new packages, applies database migrations, starts the
services and checks them. If you added or changed question files in `docs\`, add `-ImportDocs`.
If a step fails, the services stay stopped and the error is shown. Fix it (or go back with
`git checkout <previous-commit>`) and run the script again.

### Everyday operations

| Task | Command |
|---|---|
| Status | `Get-Service TestBot-*` |
| Restart | `Restart-Service TestBot-Bot, TestBot-WebApp` |
| Live logs | `Get-Content C:\apps\testbot\logs\bot.log -Tail 50 -Wait` (same for `webapp.log`) |
| Stop / start | `Stop-Service TestBot-*` / `Start-Service TestBot-*` |
| Remove the services | `nssm remove TestBot-Bot confirm` and `nssm remove TestBot-WebApp confirm` |

Logs rotate automatically at 10 MB.

### Backups

```powershell
powershell -ExecutionPolicy Bypass -File C:\apps\testbot\deploy\windows\backup.ps1 `
    -PgDump "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -Destination "D:\backups\testbot"
```

It keeps 14 days by default (`-KeepDays`). To run it daily, create a Task Scheduler task with
*Program* `powershell.exe` and *Arguments* `-ExecutionPolicy Bypass -File C:\apps\testbot\deploy\windows\backup.ps1 -PgDump "..." -Destination "..."`, set to run whether the
user is logged on or not. Copy backups off the server too. Restore with
`pg_restore -U testbot -d testbot --clean <file>.dump`.

### Troubleshooting (Windows)

| Symptom | Likely cause |
|---|---|
| `https://domain/healthz` gives **502.3** | The TestBot-WebApp service isn't running. See `logs\webapp.log`. |
| IIS shows its own 404/500 page for everything | ARR proxy not enabled (step 1 `appcmd` command), or URL Rewrite/ARR not installed. |
| win-acme validation fails | DNS doesn't point at the server yet, or port 80 is blocked by a firewall. |
| `Conflict: terminated by other getUpdates request` in `bot.log` | The same token is also running on your PC. Stop it there. |
| `update.ps1` fails at "Installing Python packages" with access denied | A service was still running. Run `Stop-Service TestBot-*` and retry. |
| Garbled/missing characters in logs | Services get `PYTHONUTF8=1` from `install.ps1`; rerun it if you created the services by hand. |

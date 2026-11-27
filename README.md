# Test Bot (Telegram bot + Mini App)

Exam preparation in Telegram, available both as a classic chat bot and as a Mini App. Both share
one database and one account per user. Users register once, pick a theme (subject), then:

- **Practice**: as many questions as they want (presets or any number). Questions and answer
  options are shuffled, and each answer is checked right away (✅/❌ + correct answer).
- **Exam**: 25 random questions with shuffled options. No per-question feedback; at the end they
  see the score and a review of every mistake.
- **Top results**: per theme, each registered user's best exam (score, then speed), top 10 + your rank.
- **Group battles**: add the bot to a group and run live quiz battles: 25 questions × 30 s, speed
  points, live reveal + top 3, final ranking and private reviews. See [BATTLE_MODE.md](BATTLE_MODE.md).

Interface languages: Uzbek, Russian, English. Question content is shown as written in the source documents.

## Accounts

- **Registration** (required before anything else): full name, phone number (only via Telegram's
  "share contact", so it's verified) and group.
- **Login** is the Telegram account itself. `/logout` signs out (and stops a running test), and
  "🔐 Log in" signs back in with one tap. The login state is shared between the bot and the Mini App.
- Profile → Edit asks for name and group again (the phone is kept).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate on Linux)
pip install -r requirements.txt
copy .env.example .env          # then set BOT_TOKEN (from @BotFather) and DATABASE_URL
```

## Importing questions

Put `.docx` files in `docs/`. Each file is a table: **column 1 = question, column 2 = correct
answer, remaining columns = wrong answers**. Each file becomes one theme, named from the file name
(`5-Kurs Dasturiy tizimlarni loyihalash KT uz IX.docx` → `Dasturiy tizimlarni loyihalash`).

```bash
python import_docs.py                                  # all .docx in docs/
python import_docs.py docs/new.docx --theme "Name"     # one file, custom theme name
python import_docs.py --dry-run                        # parse + show warnings, no DB writes
```

Re-running is safe. New questions are added, edited answers are updated, and questions removed
from the doc are deactivated (kept so past results stay valid).

## Running

```bash
python -m bot                                   # the chat bot
uvicorn webapp.main:app --port 8000             # the Mini App (API + frontend)
```

The Mini App needs a public **https** URL in `WEBAPP_URL`. **[DEPLOY.md](DEPLOY.md)** has step-by-step
instructions for local testing (with a tunnel) and for production on Linux (Docker + Caddy) or
Windows Server (IIS + NSSM services + existing PostgreSQL).
[MINI_APP.md](MINI_APP.md) covers the Mini App architecture and API.

## Database

| Environment | `DATABASE_URL` |
|---|---|
| Development | `sqlite+aiosqlite:///./data/bot.db` (default) |
| Production  | `postgresql+asyncpg://user:password@host:5432/dbname` |

The schema is managed by **Alembic** (`migrations/`). Pending migrations run automatically when the
bot, the Mini App or the importer starts. Manual commands:

```bash
alembic upgrade head                               # apply migrations
alembic revision --autogenerate -m "add X"         # after changing bot/models.py
alembic check                                      # models and migrations in sync?
```

`docker compose up -d` starts a local PostgreSQL matching the commented example in `.env.example`.

Tables: `themes`, `questions`, `options` (`is_correct`, original `position`), `users` (Telegram id,
language, registration data, login flag), `quiz_sessions` (mode, progress, score),
`session_questions` (the question, shuffled option order and the user's answer for each session).

## Tests & linting

```bash
pip install -r requirements-dev.txt
pytest                 # unit + flow tests (SQLite, fake Telegram; no network needed)
ruff check .           # lint (config in pyproject.toml)
# against PostgreSQL (uses a throwaway database: tables are dropped!):
docker compose up -d
set TEST_DATABASE_URL=postgresql+asyncpg://testbot:testbot@localhost:5432/testbot && pytest
```

## Bot commands

Private chat: `/start` main menu · `/stop` stop current test · `/results` my results · `/top` top results ·
`/profile` profile · `/language` change language · `/logout` log out · `/help`

Groups: `/battle` start a battle · `/battle_stop` cancel it (starter or admin) · `/language` group
language (admins) · `/help`

## Layout

```
bot/
  __main__.py   bot entry point (python -m bot)
  config.py     env settings
  db.py         engine/session setup + automatic migrations
  models.py     SQLAlchemy models
  services.py   quiz, registration and leaderboard logic, shared by the bot and the Mini App
  handlers.py   Telegram handlers for private chats (menus, quiz, registration)
  battle.py     group battle rules (lobby, scoring, reveal, standings), no Telegram code
  group_handlers.py  Telegram handlers for group battles (lobby, timers, results)
  i18n.py       uz / ru / en interface texts (also served to the Mini App)
webapp/
  main.py       FastAPI app: /api/* + static frontend
  auth.py       Telegram initData signature validation
  static/       Mini App frontend (HTML/CSS/JS, no build step)
migrations/     Alembic migrations
deploy/         production: Linux Docker stack + Caddy, and deploy/windows/ (IIS + NSSM scripts)
Dockerfile      image used by the bot and the Mini App
docker-compose.yml  local PostgreSQL for development
docs/           question banks (.docx), one file per theme
import_docs.py  .docx → DB importer
dev_tunnel.py   local helper: HTTPS tunnel for testing the Mini App in Telegram
tests/
pyproject.toml  project metadata, pytest and ruff settings
.github/workflows/ci.yml  CI: lint, tests on Windows (3.13/3.14) and against PostgreSQL
```

More documentation: [DEPLOY.md](DEPLOY.md) (local testing & production), [MINI_APP.md](MINI_APP.md)
(Mini App architecture & API), [BATTLE_MODE.md](BATTLE_MODE.md) (group battles).

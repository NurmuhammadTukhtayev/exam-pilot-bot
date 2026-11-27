# Mini App plan

Goal: the same test experience in two front doors, the classic chat bot and a Telegram Mini App,
sharing one database, one set of rules and one account per Telegram user. A user can start an exam in
the bot and continue it in the Mini App (or the other way round).

Status: **phases 1–3 are built** (shared core, API, frontend). Phase 4 (deployment) is a checklist
for the server.

## Architecture

```
                 Telegram
        ┌───────────┴────────────┐
   chat updates             Mini App (WebView)
        │                         │  HTTPS + initData signature
        ▼                         ▼
  python -m bot             uvicorn webapp.main:app
  (python-telegram-bot)     (FastAPI: /api/* + static frontend)
        │                         │
        └──────► bot/services.py ◄┘   quiz rules, registration, leaderboard
                       │
                 bot/models.py  ──►  SQLite (dev) / PostgreSQL (prod)
                       │
                 migrations/ (Alembic, run automatically on startup)
```

- **One core, two adapters.** All rules live in `bot/services.py`: random question selection, option
  shuffling, answer checking, double-tap protection, summaries and the leaderboard. The bot handlers
  and the API only translate between Telegram or HTTP and those functions. A rule change applies to
  both clients.
- **Two processes.** The bot (long polling) and the API run separately and share only the database.
  The API can scale to several workers, and either one can restart without affecting the other.
- **Shared state.** Quiz sessions, answers, registration and login status are stored in the database,
  so both clients always see the same progress.

## Authentication

| | Classic bot | Mini App |
|---|---|---|
| Identity | Telegram user id on every update | `Telegram.WebApp.initData`, sent as `Authorization: tma <initData>` |
| Verification | Done by Telegram | HMAC-SHA256 with the bot token (`webapp/auth.py`), max age `INIT_DATA_MAX_AGE` |
| Registration | Chat steps: name → phone (contact button) → group | Form (name, group) + `requestContact()` |
| Logout/login | `/logout`, "🔐 Log in" button | Profile → Log out, "Log in" button |

The phone number is accepted **only through Telegram's contact sharing**, so it is verified by
Telegram. In the Mini App, `requestContact()` makes Telegram send the contact to the bot as a chat
message. The bot's contact handler stores it, and the app polls `/api/me` until it appears. **The bot
must be running for Mini App registration to complete.**

Exam integrity: the API never sends which option is correct before an answer is given. In exam mode it
doesn't reveal correctness, the running score or the mistakes review until the exam is finished or
stopped (`/api/quiz/{id}/summary` returns 409 while the exam is active).

## API (all JSON; everything except `/api/texts` needs initData)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/texts/{lang}` | Interface texts (uz/ru/en), the same source as the bot (`bot/i18n.py`) |
| GET | `/api/me` | Profile, registration step, login state, active session |
| POST | `/api/language` | Set language |
| POST | `/api/register` | Name + group (the phone comes via the bot) |
| POST | `/api/profile/edit` | Restart registration (phone kept) |
| POST | `/api/login`, `/api/logout` | Toggle login (logout stops the active test) |
| GET | `/api/themes` | Themes with question counts (registered + logged in only) |
| POST | `/api/quiz` | Start practice (`count`) or exam |
| GET | `/api/quiz/active` | Resume the active test |
| POST | `/api/quiz/{id}/answer` | Answer; practice gets `correct_index`, exam gets nothing |
| POST | `/api/quiz/stop` | Stop and get a partial summary |
| GET | `/api/quiz/{id}/summary` | Result (+ mistakes review for exams) |
| GET | `/api/results` | Recent finished tests |
| GET | `/api/leaderboard/{theme_id}` | Top 10 best exam attempts + your rank |

## Frontend (`webapp/static/`)

Plain HTML/CSS/JS with no build step, served by FastAPI. It uses Telegram's theme colours (light and
dark follow the user's Telegram theme), the native BackButton, haptics and confirm dialogs. Screens
match the bot: language, registration, logged out, home (continue + themes), mode, question count,
question (practice: instant ✅/❌ + Next; exam: auto-advance), result + mistakes review, top
results, my results and profile.

Content from the database is always inserted as text, never as HTML.

## Phases

1. ✅ **Shared core**: services extracted, registration/login/leaderboard added, Alembic migrations.
2. ✅ **API**: FastAPI app, initData validation, access rules, exam-integrity rules, tests
   (`tests/test_webapp.py`).
3. ✅ **Frontend**: all screens, checked in a real browser (light/dark, full practice + exam +
   leaderboard + profile flow).
4. ⬜ **Deployment**: Docker Compose stack (PostgreSQL + bot + Mini App + Caddy for HTTPS) is ready
   in `deploy/`. Step-by-step instructions are in [DEPLOY.md](DEPLOY.md).
5. ⬜ **Later / nice to have**
   - Admin tools: import new docs from Telegram, see per-group statistics.
   - Leaderboard filters by group; weekly leaderboards.
   - Rate limiting on the API (e.g. at the reverse proxy).
   - Exam timer, if wanted (`started_at` is already stored).

## Local development

See [DEPLOY.md](DEPLOY.md), Part 1 (tunnel setup, browser dev mode, debugging).

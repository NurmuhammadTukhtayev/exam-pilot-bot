# Group battle mode

Live quiz battles inside Telegram groups: members join a lobby, then everyone answers the same 25
questions at the same time, 30 seconds each. Faster correct answers earn more points.

## Rules (agreed)

| Topic | Decision |
|---|---|
| Format | **Live in the group chat.** Every player answers the same question at the same time. |
| Who starts | **Any group member** (must be registered in the bot). One battle per group at a time. |
| Who plays | **Registered users only.** An unregistered member who taps Join gets a link to register in DM. |
| Joining | **Lobby** with [Join] [Start] [Cancel]. The starter can start once ≥ 2 players joined; otherwise it **auto-starts after 2 minutes**, or is cancelled if < 2 players. |
| Questions | **25 random questions × 30 s** from the theme the starter picks. Same questions and option order for everyone. |
| Scoring | **Speed points (Kahoot-style):** correct = `round(1000 × (1 − t / 60s))` → 500–1000 points (t = seconds taken; instant ≈ 1000, last second ≈ 500); wrong or no answer = 0. |
| After each question | **Reveal:** the question message shows ✅ the correct answer, how many got it right, and the **top 3 so far**. Then the next question. |
| Early advance | If every player has answered, reveal immediately instead of waiting out 30 s. |
| End | Final ranking posted in the group. Each player gets a **private mistakes review in DM**. |
| Language | Group messages use the **group's language (default Uzbek)**, changeable with `/language` in the group. Private popups ("Answer saved: B") use each player's own language. |
| Leaderboards | Battle results are **separate**: they don't affect the per-theme "Top results". |

### Small rules I chose (⚠️ my default, tell me to change any)

- ⚠️ Ranking ties: more points → more correct answers → lower total answer time → joined earlier.
- ⚠️ An answer can't be changed once given (like the regular exam).
- ⚠️ Correctness isn't shown in the answer popup; it's revealed for everyone when the question closes.
- ⚠️ **Cancel:** the starter or any group admin (Cancel button or `/battle_stop`).
- ⚠️ **Group language:** only group admins can change it.
- ⚠️ A 5-second pause after each reveal, so people can read the scoreboard (this also keeps the bot
  under Telegram's limit of ~20 messages/minute per group).
- ⚠️ When the bot is added to a group it posts a short intro with a [⚔️ Start battle] button. In the
  group it only reacts to `/battle`, `/battle_stop`, `/language`, `/help` and its own buttons.

## How it looks

```
⚔️ Battle lobby · Bulutli texnologiyalar
25 questions · 30 s each · started by Ali Valiyev
Players (3): Ali Valiyev, Bob Jones, Nodira K.
[➕ Join] [▶️ Start] [✖️ Cancel]          auto-start in 2:00
        │  Start / timer
        ▼
⚔️ Battle · Bulutli texnologiyalar — Question 3/25 · ⏱ 30 s
<question>  A) …  B) …  C) …  D) …
[A] [B] [C] [D]                          Answered: 5/8
        │  30 s or everyone answered
        ▼  (same message is edited)
✅ A) …   ▫️ B) …   ▫️ C) …   ▫️ D) …
Correct: 4/8
🥇 Ali 2 870 · 🥈 Nodira 2 410 · 🥉 Bob 1 930
        │  5 s pause, next question … after 25:
        ▼
🏁 Battle results: full ranking (points, correct/25)
+ DM to each player: score, rank, mistakes review
```

## Technical design

**Data (migration 0003)**

| Table | Purpose |
|---|---|
| `group_chats` | Group id, title, language |
| `battles` | Group, theme, starter, status (`lobby` → `running` → `finished` / `cancelled`), current question, question start/deadline, lobby deadline, message ids |
| `battle_questions` | The 25 questions, shared option order, message id, `revealed` flag |
| `battle_players` | Who joined, points, correct count, total answer time |
| `battle_answers` | One row per player per question (unique), option, correctness, points, time taken |

**Code**

- `bot/battle.py` holds the battle rules with no Telegram code: join/start/answer/reveal/advance/
  cancel, scoring, standings, review. It is unit-tested with a controllable clock.
- `bot/group_handlers.py` handles group commands, the lobby/question/reveal messages and timers
  (python-telegram-bot `JobQueue`).
- Existing private-chat handlers are restricted to private chats, so registration prompts never
  appear in groups.

**Reliability**

- All battle state lives in the database. A **watchdog** checks active battles every 3 seconds and
  redoes any step that didn't happen: a question that failed to post (e.g. a network timeout), an
  overdue reveal, a lost "next question" timer, or an expired lobby. The same mechanism resumes
  battles after a bot restart.
- Every battle step runs under a per-battle lock, so the timer, early advance, buttons and watchdog
  never interleave. Edits and deletes are retried on network errors.
- Known limit (unstable networks): if Telegram delivers a question but the bot only gets a network
  error back, the bot can't know that message's id, so the watchdog posts the question again. The
  stray copy has identical buttons: a tap on it counts normally and deletes the copy. Longer request
  timeouts make this rarer. A copy nobody taps stays in the chat (without working buttons after the
  question closes).
- "Reveal" is idempotent (a conditional database update), so the timer and early advance can't both
  reveal the same question. A unique constraint stops double answers from fast taps.
- Answers are timed on the server (time from posting the question to receiving the tap). Network
  delay applies to everyone equally.
- `AIORateLimiter` keeps the bot within Telegram's flood limits. The "Answered: x/y" counter is
  updated at most every 5 seconds.

**Chat cleanup**

- When the next question is posted, the previous question message is deleted. At the end the last
  question and the lobby message are deleted too, so only the **results** stay in the chat. A
  cancelled battle leaves one "Battle cancelled" message. Bots can delete their own messages in
  groups without admin rights (for up to 48 hours).

**Telegram setup**

- Nothing to change in BotFather. Adding bots to groups is allowed by default, and privacy mode can
  stay ON because the bot only needs commands and button taps.
- To register, an unregistered user tapping Join is sent to `t.me/<bot>?start=battle` (the bot's
  private chat).

## Phases

1. ✅ Data model + migration 0003, battle rules + unit tests (`tests/test_battle.py`).
2. ✅ Group handlers: intro, /battle, theme picker, lobby, questions, reveal, results, DM review,
   cancel, group language, restart recovery (`bot/group_handlers.py`).
3. ✅ Flow tests with a fake Telegram: lobby → 25 questions → results, timers, cancel, restart
   (`tests/test_group_battle.py`). Private handlers are now restricted to private chats.
4. ⬜ Manual test in a real group (you), then deploy.

### Manual test checklist (real Telegram)

1. Restart the bot (`python -m bot`). Migration 0003 is applied automatically.
2. Create a test group, add the bot. The intro with **⚔️ Start battle** should appear.
3. Have a second account in the group (both registered in the bot's private chat).
4. `/battle` → pick a theme → second account taps **Join** → starter taps **Start**.
5. Play a few questions: popups, the "Answered x/y" counter, reveal + top 3, early advance.
6. `/battle_stop` (as the starter or an admin) to end early, or play to the end and check the DMs.

Not included (not requested): Mini App battles, all-time group rankings.

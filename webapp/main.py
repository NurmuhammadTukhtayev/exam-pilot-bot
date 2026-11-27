"""Mini App backend: JSON API + static frontend.

Run:  uvicorn webapp.main:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot import services as svc
from bot.config import Settings, get_settings
from bot.db import create_engine, create_sessionmaker, init_db
from bot.i18n import LANGUAGES, all_texts, normalize_language
from bot.models import QuizSession, SessionQuestion, User
from webapp.auth import InitDataError, validate_init_data

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


# ---------------------------------------------------------------- request bodies

class LanguageIn(BaseModel):
    language: str


class RegisterIn(BaseModel):
    full_name: str
    group_name: str


class StartQuizIn(BaseModel):
    theme_id: int
    mode: Literal["practice", "exam"]
    count: int | None = None  # practice only; exam always uses EXAM_QUESTION_COUNT


class AnswerIn(BaseModel):
    position: int
    option_index: int


# ---------------------------------------------------------------- serializers

def user_out(user: User, active: QuizSession | None, settings: Settings) -> dict:
    return {
        "id": user.id,
        "first_name": user.first_name,
        "language": user.language,
        "full_name": user.full_name,
        "phone": user.phone,
        "group_name": user.group_name,
        "registered": user.is_registered,
        "logged_in": user.is_logged_in,
        "registration_step": svc.registration_step(user),
        "exam_count": settings.exam_question_count,
        "active_session": None if active is None else {
            "id": active.id, "mode": active.mode, "theme_name": active.theme.name,
            "current_index": active.current_index, "total": active.total,
        },
    }


def question_out(item: SessionQuestion) -> dict:
    # Never include which option is correct here.
    return {
        "position": item.position,
        "text": item.question.text,
        "options": [o.text for o in svc.ordered_options(item)],
    }


async def quiz_state(db: AsyncSession, session: QuizSession) -> dict:
    item = None
    if session.status == svc.ACTIVE:
        item = await svc.get_item(db, session.id, session.current_index)
    reveal_score = session.mode == svc.PRACTICE or session.status != svc.ACTIVE
    return {
        "id": session.id,
        "mode": session.mode,
        "status": session.status,
        "theme": {"id": session.theme_id, "name": session.theme.name},
        "total": session.total,
        "current_index": session.current_index,
        "correct_count": session.correct_count if reveal_score else None,
        "question": question_out(item) if item else None,
    }


def summary_out(summary: svc.SessionSummary) -> dict:
    s = summary.session
    return {
        "id": s.id,
        "mode": s.mode,
        "status": s.status,
        "theme": {"id": s.theme_id, "name": s.theme.name},
        "total": s.total,
        "answered": summary.answered,
        "correct": s.correct_count,
        "base": summary.base,
        "percent": summary.percent,
        "mistakes": [m.__dict__ for m in summary.mistakes] if s.mode == svc.EXAM else [],
    }


# ---------------------------------------------------------------- app factory

def create_app(settings: Settings | None = None, sessionmaker: async_sessionmaker | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = None
        if sessionmaker is None:
            engine = create_engine(settings.database_url)
            await init_db(engine)
            app.state.sessionmaker = create_sessionmaker(engine)
        if settings.webapp_dev_user_id:
            log.warning("WEBAPP_DEV_USER_ID is set: unauthenticated requests act as user %s. "
                        "Never enable this in production!", settings.webapp_dev_user_id)
        yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(title="Test Bot Mini App", lifespan=lifespan, docs_url=None, redoc_url=None)
    if sessionmaker is not None:
        app.state.sessionmaker = sessionmaker

    # ---- dependencies

    async def get_db(request: Request):
        async with request.app.state.sessionmaker() as db:
            yield db

    Db = Annotated[AsyncSession, Depends(get_db)]

    async def telegram_user(authorization: Annotated[str | None, Header()] = None) -> dict:
        scheme, _, init_data = (authorization or "").partition(" ")
        if scheme.lower() == "tma" and init_data:
            try:
                return validate_init_data(init_data, settings.bot_token, settings.init_data_max_age)
            except InitDataError as e:
                raise HTTPException(401, "invalid_init_data") from e
        if settings.webapp_dev_user_id:
            return {"id": settings.webapp_dev_user_id, "first_name": "Dev"}
        raise HTTPException(401, "not_authenticated")

    async def current_user(db: Db, tg: Annotated[dict, Depends(telegram_user)]) -> User:
        user = await db.get(User, int(tg["id"]))
        if user is None:
            user = await svc.upsert_user(db, int(tg["id"]), tg.get("username"), tg.get("first_name"))
        return user

    CurrentUser = Annotated[User, Depends(current_user)]

    async def active_user(user: CurrentUser) -> User:
        if not user.is_registered:
            raise HTTPException(403, "not_registered")
        if not user.is_logged_in:
            raise HTTPException(403, "logged_out")
        return user

    ActiveUser = Annotated[User, Depends(active_user)]

    async def me(db: AsyncSession, user: User) -> dict:
        return user_out(user, await svc.get_active_session(db, user.id), settings)

    async def own_session(db: AsyncSession, user: User, session_id: int) -> QuizSession:
        session = await db.get(QuizSession, session_id)
        if session is None or session.user_id != user.id:
            raise HTTPException(404, "session_not_found")
        await db.refresh(session, ["theme"])
        return session

    # ---- public

    @app.get("/api/texts/{lang}")
    async def texts(lang: str):
        return {"language": normalize_language(lang), "languages": LANGUAGES, "texts": all_texts(lang)}

    # ---- account

    @app.get("/api/me")
    async def get_me(db: Db, user: CurrentUser):
        return await me(db, user)

    @app.post("/api/language")
    async def set_language(body: LanguageIn, db: Db, user: CurrentUser):
        if body.language not in LANGUAGES:
            raise HTTPException(400, "invalid_language")
        await svc.set_language(db, user.id, body.language)
        user.language = body.language
        return await me(db, user)

    @app.post("/api/register")
    async def register(body: RegisterIn, db: Db, user: CurrentUser):
        full_name = svc.clean_full_name(body.full_name)
        if full_name is None:
            raise HTTPException(400, "invalid_name")
        group_name = svc.clean_group(body.group_name)
        if group_name is None:
            raise HTTPException(400, "invalid_group")
        # The phone number arrives separately: the app calls Telegram.WebApp.requestContact(), Telegram
        # delivers the contact to the bot, and the bot's contact handler stores it (bot.handlers.on_contact).
        await svc.update_registration(db, user, full_name=full_name, group_name=group_name)
        return await me(db, user)

    @app.post("/api/profile/edit")
    async def edit_profile(db: Db, user: ActiveUser):
        await svc.restart_registration(db, user)
        return await me(db, user)

    @app.post("/api/login")
    async def login(db: Db, user: CurrentUser):
        if not user.is_registered:
            raise HTTPException(403, "not_registered")
        await svc.set_logged_in(db, user, True)
        return await me(db, user)

    @app.post("/api/logout")
    async def logout(db: Db, user: CurrentUser):
        await svc.set_logged_in(db, user, False)
        return await me(db, user)

    # ---- quiz

    @app.get("/api/themes")
    async def themes(db: Db, _: ActiveUser):
        return [
            {"id": t.id, "name": t.name, "question_count": t.question_count,
             "exam_count": min(settings.exam_question_count, t.question_count)}
            for t in await svc.list_themes(db)
        ]

    @app.post("/api/quiz")
    async def start_quiz(body: StartQuizIn, db: Db, user: ActiveUser):
        if await svc.get_theme(db, body.theme_id) is None:
            raise HTTPException(404, "theme_not_found")
        count = settings.exam_question_count if body.mode == svc.EXAM else body.count
        if count is None or count < 1:
            raise HTTPException(400, "invalid_count")
        session = await svc.start_quiz(db, user.id, body.theme_id, body.mode, count)
        if session is None:
            raise HTTPException(400, "no_questions")
        await db.refresh(session, ["theme"])
        return await quiz_state(db, session)

    @app.get("/api/quiz/active")
    async def active_quiz(db: Db, user: ActiveUser):
        session = await svc.get_active_session(db, user.id)
        return None if session is None else await quiz_state(db, session)

    @app.post("/api/quiz/{session_id}/answer")
    async def answer(session_id: int, body: AnswerIn, db: Db, user: ActiveUser):
        result = await svc.answer(db, user.id, session_id, body.position, body.option_index)
        if result is None:
            raise HTTPException(409, "stale_answer")
        options = svc.ordered_options(result.item)
        feedback = {"chosen_index": body.option_index}
        if result.session.mode == svc.PRACTICE:
            feedback["is_correct"] = result.is_correct
            feedback["correct_index"] = options.index(result.correct)
        return {"feedback": feedback, "state": await quiz_state(db, result.session)}

    @app.post("/api/quiz/stop")
    async def stop_quiz(db: Db, user: ActiveUser):
        session = await svc.stop_active(db, user.id)
        if session is None:
            return None
        return summary_out(await svc.session_summary(db, session.id))

    @app.get("/api/quiz/{session_id}/summary")
    async def quiz_summary(session_id: int, db: Db, user: ActiveUser):
        session = await own_session(db, user, session_id)
        if session.status == svc.ACTIVE:
            raise HTTPException(409, "session_active")  # no peeking at exam answers mid-exam
        return summary_out(await svc.session_summary(db, session_id))

    @app.get("/api/results")
    async def results(db: Db, user: ActiveUser):
        return [
            {"id": s.id, "mode": s.mode, "theme_name": s.theme.name, "correct": s.correct_count,
             "total": s.total, "finished_at": (s.finished_at or s.started_at).isoformat()}
            for s in await svc.recent_results(db, user.id)
        ]

    @app.get("/api/leaderboard/{theme_id}")
    async def leaderboard(theme_id: int, db: Db, user: ActiveUser):
        theme = await svc.get_theme(db, theme_id)
        if theme is None:
            raise HTTPException(404, "theme_not_found")
        top, mine = await svc.leaderboard(db, theme_id, user.id)

        def entry(e: svc.LeaderboardEntry) -> dict:
            return {"rank": e.rank, "name": e.name, "group": e.group, "correct": e.correct, "total": e.total,
                    "percent": e.percent, "duration": svc.format_duration(e.seconds), "is_me": e.user_id == user.id}

        return {"theme": {"id": theme.id, "name": theme.name},
                "top": [entry(e) for e in top], "me": entry(mine) if mine else None}

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()

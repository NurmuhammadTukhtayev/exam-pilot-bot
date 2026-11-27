import json
import time

import httpx
import pytest

from bot import services as svc
from bot.config import Settings
from bot.models import User
from webapp.auth import InitDataError, sign_init_data, validate_init_data
from webapp.main import create_app

TOKEN = "123456:TEST-token"


def init_data(user_id=42, first_name="Ali", auth_date=None, token=TOKEN):
    fields = {
        "auth_date": str(int(auth_date or time.time())),
        "query_id": "AAH",
        "user": json.dumps({"id": user_id, "first_name": first_name, "language_code": "en"}),
    }
    return sign_init_data(fields, token)


def make_client(sessionmaker, **settings_overrides):
    settings = Settings(bot_token=TOKEN, database_url="", exam_question_count=25, **settings_overrides)
    app = create_app(settings, sessionmaker)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def auth(user_id=42):
    return {"Authorization": f"tma {init_data(user_id)}"}


async def register(client, sessionmaker, user_id=42, name="Ali Valiyev", group="G1"):
    h = auth(user_id)
    assert (await client.post("/api/language", json={"language": "en"}, headers=h)).status_code == 200
    me = (await client.post("/api/register", json={"full_name": name, "group_name": group}, headers=h)).json()
    assert me["registered"] is False and me["registration_step"] == "phone"
    # The phone arrives through the bot (requestContact -> contact message -> bot.handlers.on_contact).
    async with sessionmaker() as db:
        user = await db.get(User, user_id)
        await svc.update_registration(db, user, phone="+998901234567")
    me = (await client.get("/api/me", headers=h)).json()
    assert me["registered"] is True
    return h


# ---------------------------------------------------------------- initData validation

def test_validate_init_data():
    user = validate_init_data(init_data(), TOKEN, max_age=3600)
    assert user["id"] == 42
    with pytest.raises(InitDataError):
        validate_init_data(init_data(token="other:token"), TOKEN, max_age=3600)
    with pytest.raises(InitDataError):
        validate_init_data(init_data(auth_date=time.time() - 7200), TOKEN, max_age=3600)
    with pytest.raises(InitDataError):
        validate_init_data(init_data().replace("Ali", "Bob"), TOKEN, max_age=3600)
    with pytest.raises(InitDataError):
        validate_init_data("", TOKEN, max_age=3600)


async def test_auth_required_and_dev_fallback(sessionmaker):
    async with make_client(sessionmaker) as c:
        assert (await c.get("/api/me")).status_code == 401
        bad = {"Authorization": "tma " + init_data(token="x:y")}
        assert (await c.get("/api/me", headers=bad)).status_code == 401
        assert (await c.get("/api/me", headers=auth())).json()["id"] == 42
        assert (await c.get("/")).status_code == 200  # static index served without auth
    async with make_client(sessionmaker, webapp_dev_user_id=7) as c:
        assert (await c.get("/api/me")).json()["id"] == 7


# ---------------------------------------------------------------- account

async def test_registration_gate_and_validation(seeded):
    async with make_client(seeded) as c:
        h = auth()
        assert (await c.get("/api/themes", headers=h)).json() == {"detail": "not_registered"}
        r = await c.post("/api/register", json={"full_name": "x", "group_name": "G"}, headers=h)
        assert r.status_code == 400 and r.json()["detail"] == "invalid_name"
        r = await c.post("/api/register", json={"full_name": "Ali Valiyev", "group_name": " "}, headers=h)
        assert r.json()["detail"] == "invalid_group"
        await register(c, seeded)
        assert len((await c.get("/api/themes", headers=h)).json()) == 3


async def test_logout_login_and_edit(seeded):
    async with make_client(seeded) as c:
        h = await register(c, seeded)
        theme_id = (await c.get("/api/themes", headers=h)).json()[0]["id"]
        await c.post("/api/quiz", json={"theme_id": theme_id, "mode": "exam"}, headers=h)

        me = (await c.post("/api/logout", headers=h)).json()
        assert me["logged_in"] is False and me["active_session"] is None  # logout stops the test
        assert (await c.get("/api/themes", headers=h)).json() == {"detail": "logged_out"}
        assert (await c.post("/api/login", headers=h)).json()["logged_in"] is True

        me = (await c.post("/api/profile/edit", headers=h)).json()
        assert me["registered"] is False and me["phone"] == "+998901234567"
        me = (await c.post("/api/register", json={"full_name": "New Name", "group_name": "G2"}, headers=h)).json()
        assert me["registered"] is True and me["full_name"] == "New Name"


# ---------------------------------------------------------------- quiz

async def test_practice_flow(seeded):
    async with make_client(seeded) as c:
        h = await register(c, seeded)
        theme_id = (await c.get("/api/themes", headers=h)).json()[0]["id"]
        state = (await c.post("/api/quiz", json={"theme_id": theme_id, "mode": "practice", "count": 3},
                              headers=h)).json()
        assert state["total"] == 3 and state["correct_count"] == 0
        assert set(state["question"]) == {"position", "text", "options"}  # nothing reveals the answer

        for _ in range(3):
            q = state["question"]
            r = await c.post(f"/api/quiz/{state['id']}/answer", json={"position": q["position"], "option_index": 0},
                             headers=h)
            body = r.json()
            assert set(body["feedback"]) == {"chosen_index", "is_correct", "correct_index"}
            again = await c.post(f"/api/quiz/{state['id']}/answer",
                                 json={"position": q["position"], "option_index": 0}, headers=h)
            assert again.status_code == 409
            state = body["state"]
        assert state["status"] == "finished" and state["question"] is None

        summary = (await c.get(f"/api/quiz/{state['id']}/summary", headers=h)).json()
        assert summary["total"] == 3 and summary["mistakes"] == []  # review is exam-only
        assert len((await c.get("/api/results", headers=h)).json()) == 1


async def test_exam_hides_answers_until_finished(seeded):
    async with make_client(seeded) as c:
        h = await register(c, seeded)
        other = await register(c, seeded, user_id=43, name="Bob Jones", group="G2")
        theme_id = (await c.get("/api/themes", headers=h)).json()[0]["id"]
        state = (await c.post("/api/quiz", json={"theme_id": theme_id, "mode": "exam", "count": 3},
                              headers=h)).json()
        assert state["total"] == 25 and state["correct_count"] is None
        assert (await c.get(f"/api/quiz/{state['id']}/summary", headers=h)).status_code == 409
        assert (await c.get(f"/api/quiz/{state['id']}/summary", headers=other)).status_code == 404
        # another user can't answer my exam
        r = await c.post(f"/api/quiz/{state['id']}/answer", json={"position": 0, "option_index": 0}, headers=other)
        assert r.status_code == 409

        for _ in range(25):
            q = state["question"]
            body = (await c.post(f"/api/quiz/{state['id']}/answer",
                                 json={"position": q["position"], "option_index": 1}, headers=h)).json()
            assert body["feedback"] == {"chosen_index": 1}
            state = body["state"]
            if state["question"] is not None:
                assert state["correct_count"] is None

        summary = (await c.get(f"/api/quiz/{state['id']}/summary", headers=h)).json()
        assert summary["status"] == "finished" and summary["base"] == 25
        assert len(summary["mistakes"]) == 25 - summary["correct"]

        board = (await c.get(f"/api/leaderboard/{theme_id}", headers=other)).json()
        assert [e["name"] for e in board["top"]] == ["Ali Valiyev"]
        assert board["top"][0]["is_me"] is False and board["me"] is None
        mine = (await c.get(f"/api/leaderboard/{theme_id}", headers=h)).json()
        assert mine["me"]["rank"] == 1 and mine["top"][0]["is_me"] is True


async def test_stop_returns_partial_summary(seeded):
    async with make_client(seeded) as c:
        h = await register(c, seeded)
        theme_id = (await c.get("/api/themes", headers=h)).json()[0]["id"]
        state = (await c.post("/api/quiz", json={"theme_id": theme_id, "mode": "exam"}, headers=h)).json()
        await c.post(f"/api/quiz/{state['id']}/answer", json={"position": 0, "option_index": 0}, headers=h)
        summary = (await c.post("/api/quiz/stop", headers=h)).json()
        assert summary["status"] == "stopped" and summary["answered"] == 1 and summary["base"] == 1
        assert (await c.get("/api/quiz/active", headers=h)).json() is None
        assert (await c.post("/api/quiz/stop", headers=h)).json() is None

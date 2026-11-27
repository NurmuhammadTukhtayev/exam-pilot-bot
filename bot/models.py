from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Theme(Base):
    """A subject / test bank, e.g. one imported .docx file."""

    __tablename__ = "themes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    source_file: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    questions: Mapped[list["Question"]] = relationship(back_populates="theme")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("theme_id", "text", name="uq_question_theme_text"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    # Row number in the source document (1-based), handy for tracing back typos.
    source_row: Mapped[int | None] = mapped_column(Integer)
    # Questions removed from the source doc are deactivated, not deleted, so history stays valid.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    theme: Mapped[Theme] = relationship(back_populates="questions")
    options: Mapped[list["Option"]] = relationship(
        back_populates="question", order_by="Option.position", cascade="all, delete-orphan"
    )


class Option(Base):
    __tablename__ = "options"
    __table_args__ = (UniqueConstraint("question_id", "position", name="uq_option_question_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    # Position as written in the source doc (0 = first column = correct answer).
    position: Mapped[int] = mapped_column(Integer)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)

    question: Mapped[Question] = relationship(back_populates="options")


class User(Base):
    __tablename__ = "users"

    # Telegram user id (can exceed 32-bit).
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str | None] = mapped_column(String(8))
    # Registration data. The user counts as registered once registered_at is set.
    full_name: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(32))  # only accepted via Telegram contact sharing
    group_name: Mapped[str | None] = mapped_column(String(50))
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Telegram identity is the login; this flag lets users log out (/logout) and back in.
    is_logged_in: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def is_registered(self) -> bool:
        return self.registered_at is not None

    @property
    def display_name(self) -> str:
        return self.full_name or self.first_name or self.username or str(self.id)


class QuizSession(Base):
    __tablename__ = "quiz_sessions"
    __table_args__ = (Index("ix_quiz_sessions_theme_mode_status", "theme_id", "mode", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(16))  # "practice" | "exam"
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | finished | stopped
    total: Mapped[int] = mapped_column(Integer)
    current_index: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    # Practice "in order": number (1-based, document order) of the first question. None = random questions.
    start_number: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def in_order(self) -> bool:
        return self.start_number is not None

    def question_number(self, position: int) -> int | None:
        """Document number (#) of the question at `position`, for in-order practice."""
        return self.start_number + position if self.start_number is not None else None

    theme: Mapped[Theme] = relationship()
    items: Mapped[list["SessionQuestion"]] = relationship(
        back_populates="session", order_by="SessionQuestion.position", cascade="all, delete-orphan"
    )


class SessionQuestion(Base):
    """One question inside a quiz session, with its shuffled option order and the user's answer."""

    __tablename__ = "session_questions"
    __table_args__ = (UniqueConstraint("session_id", "position", name="uq_session_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("quiz_sessions.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    # Option ids in the order shown to the user (A, B, C, D ...).
    option_order: Mapped[list[int]] = mapped_column(JSON)
    selected_option_id: Mapped[int | None] = mapped_column(ForeignKey("options.id", ondelete="SET NULL"))
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session: Mapped[QuizSession] = relationship(back_populates="items")
    question: Mapped[Question] = relationship()


# ---------------------------------------------------------------- group battles

class GroupChat(Base):
    __tablename__ = "group_chats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)  # Telegram chat id
    title: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(8), default="uz", server_default="uz")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Battle(Base):
    __tablename__ = "battles"
    __table_args__ = (Index("ix_battles_chat_status", "chat_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("group_chats.id", ondelete="CASCADE"))
    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id", ondelete="CASCADE"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="lobby")  # lobby | running | finished | cancelled
    question_count: Mapped[int] = mapped_column(Integer)
    seconds_per_question: Mapped[int] = mapped_column(Integer)
    current_index: Mapped[int] = mapped_column(Integer, default=-1)  # -1 while in the lobby
    lobby_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    question_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    question_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lobby_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    theme: Mapped[Theme] = relationship()
    questions: Mapped[list["BattleQuestion"]] = relationship(
        back_populates="battle", order_by="BattleQuestion.position", cascade="all, delete-orphan"
    )
    players: Mapped[list["BattlePlayer"]] = relationship(
        back_populates="battle", order_by="BattlePlayer.joined_at", cascade="all, delete-orphan"
    )


class BattleQuestion(Base):
    __tablename__ = "battle_questions"
    __table_args__ = (UniqueConstraint("battle_id", "position", name="uq_battle_question_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    battle_id: Mapped[int] = mapped_column(ForeignKey("battles.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    option_order: Mapped[list[int]] = mapped_column(JSON)  # same shuffled order for every player
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    revealed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    battle: Mapped[Battle] = relationship(back_populates="questions")
    question: Mapped[Question] = relationship()


class BattlePlayer(Base):
    __tablename__ = "battle_players"
    __table_args__ = (UniqueConstraint("battle_id", "user_id", name="uq_battle_player"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    battle_id: Mapped[int] = mapped_column(ForeignKey("battles.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    points: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    total_ms: Mapped[int] = mapped_column(Integer, default=0)  # sum of answer times (tie-break)

    battle: Mapped[Battle] = relationship(back_populates="players")
    user: Mapped[User] = relationship()


class BattleAnswer(Base):
    __tablename__ = "battle_answers"
    __table_args__ = (UniqueConstraint("battle_id", "position", "user_id", name="uq_battle_answer"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    battle_id: Mapped[int] = mapped_column(ForeignKey("battles.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    option_id: Mapped[int | None] = mapped_column(ForeignKey("options.id", ondelete="SET NULL"))
    option_index: Mapped[int] = mapped_column(Integer)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    points: Mapped[int] = mapped_column(Integer)
    answer_ms: Mapped[int] = mapped_column(Integer)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

"""user registration (full name, phone, group) and login flag

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("full_name", sa.String(100), nullable=True))
        batch.add_column(sa.Column("phone", sa.String(32), nullable=True))
        batch.add_column(sa.Column("group_name", sa.String(50), nullable=True))
        batch.add_column(sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("is_logged_in", sa.Boolean(), nullable=False, server_default=sa.true()))
    # Leaderboard query: finished exams per theme.
    op.create_index("ix_quiz_sessions_theme_mode_status", "quiz_sessions", ["theme_id", "mode", "status"])


def downgrade() -> None:
    op.drop_index("ix_quiz_sessions_theme_mode_status", table_name="quiz_sessions")
    with op.batch_alter_table("users") as batch:
        for column in ("is_logged_in", "registered_at", "group_name", "phone", "full_name"):
            batch.drop_column(column)

"""Saved speech settings: models, voice, speed and turn length.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def _updated_at() -> sa.Column[datetime]:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "speech_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stt_model", sa.String(length=200), nullable=False),
        sa.Column("tts_model", sa.String(length=200), nullable=False),
        sa.Column("tts_voice", sa.String(length=100), nullable=False),
        sa.Column("tts_speed", sa.Float(), nullable=False),
        sa.Column("max_turn_s", sa.Integer(), nullable=False),
        _updated_at(),
        sa.CheckConstraint("id = 1", name=op.f("ck_speech_settings_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_speech_settings")),
    )


def downgrade() -> None:
    op.drop_table("speech_settings")

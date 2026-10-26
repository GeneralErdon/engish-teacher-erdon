"""Saved speech settings: the speech recognition engine, and the whisper.cpp model.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # A row saved before reads back as Speaches, the only engine there was, with no whisper.cpp
    # model chosen yet (""): the api reads that as the configured one, `VT_STT_GPU_MODEL`.
    with op.batch_alter_table("speech_settings") as batch:
        batch.add_column(
            sa.Column("stt_engine", sa.String(length=20), server_default="openai", nullable=False)
        )
        batch.add_column(
            sa.Column("stt_gpu_model", sa.String(length=200), server_default="", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("speech_settings") as batch:
        batch.drop_column("stt_gpu_model")
        batch.drop_column("stt_engine")

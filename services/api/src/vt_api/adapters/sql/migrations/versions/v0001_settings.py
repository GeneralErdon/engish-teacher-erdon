"""Settings saved from the UI: chat model providers (sealed API keys) and the learner profile.

Revision ID: 0001
Revises:
Create Date: 2026-10-22
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def _updated_at() -> sa.Column[datetime]:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "llm_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("active", sa.String(length=40), nullable=False),
        _updated_at(),
        sa.CheckConstraint("id = 1", name=op.f("ck_llm_settings_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_settings")),
    )
    op.create_table(
        "llm_providers",
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("api_key", sa.LargeBinary(), nullable=True),
        _updated_at(),
        sa.PrimaryKeyConstraint("kind", name=op.f("pk_llm_providers")),
    )
    op.create_table(
        "learner_profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=2), nullable=False),
        sa.Column("explanations", sa.String(length=10), nullable=False),
        _updated_at(),
        sa.CheckConstraint("id = 1", name=op.f("ck_learner_profile_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learner_profile")),
    )


def downgrade() -> None:
    op.drop_table("learner_profile")
    op.drop_table("llm_providers")
    op.drop_table("llm_settings")

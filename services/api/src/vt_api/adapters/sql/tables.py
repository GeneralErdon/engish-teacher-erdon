"""Tables, in portable SQL (SQLite now, Postgres later). Changes go through a migration in
`migrations/versions`; a test checks that the two agree."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, LargeBinary, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Named constraints, so later migrations can alter them on any engine.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LlmSettingsRow(Base):
    """Which provider answers. A single row."""

    __tablename__ = "llm_settings"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    active: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[datetime] = _updated_at()


class LlmProviderRow(Base):
    """One configured provider."""

    __tablename__ = "llm_providers"

    kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    base_url: Mapped[str] = mapped_column(String(2048))
    model: Mapped[str] = mapped_column(String(200))
    api_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    """Sealed with `SecretBox`, bound to `kind` and `base_url`; `None` without a key."""
    updated_at: Mapped[datetime] = _updated_at()


class LearnerProfileRow(Base):
    """Level and explanation language. A single row."""

    __tablename__ = "learner_profile"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(2))
    explanations: Mapped[str] = mapped_column(String(10))
    updated_at: Mapped[datetime] = _updated_at()

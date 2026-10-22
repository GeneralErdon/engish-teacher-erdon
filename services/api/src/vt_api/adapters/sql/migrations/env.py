"""Alembic environment. Migrations run inside the api at startup (`database.migrate`), on the
encrypted connection it passes in: there is no `alembic.ini` and no URL to configure."""

from alembic import context

from vt_api.adapters.sql.tables import Base

context.configure(
    connection=context.config.attributes["connection"],
    target_metadata=Base.metadata,
    # SQLite cannot ALTER most things: Alembic copies the table instead.
    render_as_batch=True,
)
with context.begin_transaction():
    context.run_migrations()

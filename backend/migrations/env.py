from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import settings
from app.db import Base
from app import models  # noqa: F401

fileConfig(context.config.config_file_name, disable_existing_loggers=False)


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


provided = context.config.attributes.get("connection")
if provided is not None:
    migrate(provided)
else:
    config = settings()
    engine = create_engine(config.migration_database_url or config.database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        migrate(connection)

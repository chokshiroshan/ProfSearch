"""Database engine and session helpers."""

from __future__ import annotations

from sqlalchemy import event, inspect, text
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from profsearch.config import Settings
from profsearch.db.models import Base
from profsearch.db.vectors import initialize_vector_support


def _set_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-25600")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()


def create_sqlalchemy_engine(settings: Settings):
    db_url = f"sqlite:///{settings.db_path}"
    engine = create_engine(
        db_url,
        future=True,
        echo=settings.database.echo,
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", _set_pragmas)
    return engine


def ensure_indexes(engine) -> None:
    """Create any indexes defined on models that don't already exist."""
    from sqlalchemy.schema import CreateTable

    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            for index in table.indexes:
                connection.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {index.name} ON {table.name} ({', '.join(index.columns.keys())})")
                )


def create_session_factory(settings: Settings) -> sessionmaker[Session]:
    engine = create_sqlalchemy_engine(settings)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def _ensure_professor_dedupe_columns(engine) -> None:
    inspector = inspect(engine)
    if "professors" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("professors")}
    with engine.begin() as connection:
        if "duplicate_of_professor_id" not in columns:
            connection.execute(text("ALTER TABLE professors ADD COLUMN duplicate_of_professor_id INTEGER"))
        if "duplicate_reason" not in columns:
            connection.execute(text("ALTER TABLE professors ADD COLUMN duplicate_reason VARCHAR(64)"))


def _ensure_profile_text_columns(engine) -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        if "faculty_candidates" in inspector.get_table_names():
            candidate_columns = {column["name"] for column in inspector.get_columns("faculty_candidates")}
            if "profile_text" not in candidate_columns:
                connection.execute(text("ALTER TABLE faculty_candidates ADD COLUMN profile_text TEXT"))
        if "professors" in inspector.get_table_names():
            professor_columns = {column["name"] for column in inspector.get_columns("professors")}
            if "profile_text" not in professor_columns:
                connection.execute(text("ALTER TABLE professors ADD COLUMN profile_text TEXT"))


def initialize_database(settings: Settings):
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlalchemy_engine(settings)
    Base.metadata.create_all(engine)
    _ensure_professor_dedupe_columns(engine)
    _ensure_profile_text_columns(engine)
    initialize_vector_support(engine, settings.database.sqlite_vec_extension, settings.embeddings.dimension)
    ensure_indexes(engine)
    return engine

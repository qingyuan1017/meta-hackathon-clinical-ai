from collections.abc import Generator

from sqlalchemy import create_engine, update
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
settings.ensure_directories()
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def initialize_database() -> None:
    from .models import Job

    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        session.execute(
            update(Job)
            .where(Job.status.in_(["queued", "running"]))
            .values(status="failed", error="The API restarted before this job completed.")
        )
        session.commit()

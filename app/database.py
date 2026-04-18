from datetime import datetime
from pathlib import Path
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import BACKUPS_DIR, DB_PATH

SQLITE_BUSY_TIMEOUT_MS = 5000


def _sqlite_connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    connection.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    return connection


def _configure_sqlite_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=NORMAL")


def verify_sqlite_integrity() -> tuple[bool, str]:
    with _sqlite_connect() as connection:
        _configure_sqlite_connection(connection)
        result = connection.execute("PRAGMA integrity_check").fetchone()
    detail = str(result[0]) if result and result[0] is not None else "unknown"
    return detail.lower() == "ok", detail


def get_sqlite_runtime_status() -> dict[str, str | bool | int]:
    with _sqlite_connect() as connection:
        _configure_sqlite_connection(connection)
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()
        integrity_result = connection.execute("PRAGMA integrity_check").fetchone()

    integrity_detail = str(integrity_result[0]) if integrity_result and integrity_result[0] is not None else "unknown"
    return {
        "journal_mode": str(journal_mode[0]) if journal_mode and journal_mode[0] is not None else "unknown",
        "busy_timeout_ms": int(busy_timeout[0]) if busy_timeout and busy_timeout[0] is not None else 0,
        "integrity_ok": integrity_detail.lower() == "ok",
        "integrity_detail": integrity_detail,
        "db_path": str(DB_PATH),
        "backups_dir": str(BACKUPS_DIR),
    }


def initialize_sqlite_runtime() -> dict[str, str | bool | int]:
    status = get_sqlite_runtime_status()
    if not status["integrity_ok"]:
        raise RuntimeError(f"SQLite 完整性检查失败：{status['integrity_detail']}")
    return status


def create_sqlite_backup() -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUPS_DIR / f"invoice_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    with _sqlite_connect() as source_connection:
        _configure_sqlite_connection(source_connection)
        with sqlite3.connect(backup_path) as target_connection:
            source_connection.backup(target_connection)
    return backup_path

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def set_sqlite_pragmas(dbapi_connection, _connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        _configure_sqlite_connection(dbapi_connection)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


initialize_sqlite_runtime()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

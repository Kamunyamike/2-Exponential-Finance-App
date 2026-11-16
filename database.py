"""Persistence layer for recorded weekly balances and challenge settings.

Storage backend is chosen at start-up:

1. ``DATABASE_URL`` environment variable, or
2. ``DATABASE_URL`` in Streamlit secrets (``.streamlit/secrets.toml`` locally,
   or the *Secrets* box on Streamlit Community Cloud), or
3. a local SQLite file at ``data/tracker.db`` (the default).

SQLite is permanent on your own computer, but on Streamlit Community Cloud the
container's disk is wiped whenever the app restarts, sleeps or is redeployed.
For permanent cloud storage, point ``DATABASE_URL`` at a free hosted
PostgreSQL database (see README). The same code works for both because it uses
SQLAlchemy Core.

Balances are stored as exact decimal strings, so values never lose precision.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent / "data" / "tracker.db"
MAX_NOTE_LENGTH = 500

metadata = sa.MetaData()

weekly_balances = sa.Table(
    "weekly_balances",
    metadata,
    sa.Column("week", sa.Integer, primary_key=True, autoincrement=False),
    sa.Column("actual_balance", sa.String(64), nullable=False),
    sa.Column("note", sa.String(MAX_NOTE_LENGTH), nullable=False, default=""),
    sa.Column("updated_at", sa.String(40), nullable=False),
)

app_settings = sa.Table(
    "app_settings",
    metadata,
    sa.Column("key", sa.String(64), primary_key=True),
    sa.Column("value", sa.String(128), nullable=False),
)


class DatabaseError(RuntimeError):
    """Raised when the database cannot be reached or a query fails."""


def _normalize_url(url: str) -> str:
    url = url.strip()
    # Many hosts hand out "postgres://" URLs; SQLAlchemy needs a driver name.
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def resolve_database_url(explicit: Optional[str] = None) -> str:
    """Return the database URL from argument, env var, Streamlit secrets or default."""
    if explicit:
        return _normalize_url(explicit)

    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            import streamlit as st

            url = st.secrets.get("DATABASE_URL")
        except Exception:  # no secrets file, or not running under Streamlit
            url = None
    if not url:
        return f"sqlite:///{DEFAULT_SQLITE_PATH}"
    return _normalize_url(str(url))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _to_decimal(value) -> Decimal:
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise DatabaseError(f"Invalid stored balance: {value!r}") from None
    if not dec.is_finite() or dec < 0:
        raise DatabaseError(f"Invalid balance: {value!r}")
    return dec


class TrackerDB:
    """Small repository class wrapping all database access."""

    def __init__(self, url: Optional[str] = None) -> None:
        self.url = resolve_database_url(url)
        parsed = sa.engine.make_url(self.url)
        self.backend = parsed.get_backend_name()

        connect_args = {}
        if self.backend == "sqlite":
            connect_args["check_same_thread"] = False
            if parsed.database and parsed.database != ":memory:":
                Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)

        try:
            self.engine = sa.create_engine(
                self.url, pool_pre_ping=True, connect_args=connect_args
            )
            metadata.create_all(self.engine)
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Could not open the database ({self.backend}): {exc}") from exc

    # -- helpers -----------------------------------------------------------
    @contextmanager
    def _transaction(self) -> Iterator[sa.Connection]:
        try:
            with self.engine.begin() as conn:
                yield conn
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Database operation failed: {exc}") from exc

    @property
    def is_sqlite(self) -> bool:
        return self.backend == "sqlite"

    @property
    def description(self) -> str:
        if self.is_sqlite:
            return "Local SQLite file (data/tracker.db)"
        return f"External {self.backend} database"

    # -- weekly balances ---------------------------------------------------
    def list_balances(self) -> List[Dict]:
        with self._transaction() as conn:
            rows = conn.execute(
                sa.select(weekly_balances).order_by(weekly_balances.c.week)
            ).mappings().all()
        return [
            {
                "week": int(r["week"]),
                "actual_balance": _to_decimal(r["actual_balance"]),
                "note": r["note"] or "",
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def get_balance(self, week: int) -> Optional[Dict]:
        with self._transaction() as conn:
            row = conn.execute(
                sa.select(weekly_balances).where(weekly_balances.c.week == int(week))
            ).mappings().first()
        if row is None:
            return None
        return {
            "week": int(row["week"]),
            "actual_balance": _to_decimal(row["actual_balance"]),
            "note": row["note"] or "",
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _upsert_balance(conn: sa.Connection, week: int, balance: Decimal, note: str) -> None:
        values = {
            "actual_balance": format(_to_decimal(balance), "f"),
            "note": (note or "").strip()[:MAX_NOTE_LENGTH],
            "updated_at": _now(),
        }
        result = conn.execute(
            sa.update(weekly_balances).where(weekly_balances.c.week == week).values(**values)
        )
        if result.rowcount == 0:
            conn.execute(sa.insert(weekly_balances).values(week=week, **values))

    def upsert_balance(self, week: int, balance: Decimal, note: str = "") -> None:
        """Insert or update the actual balance for ``week``."""
        if isinstance(week, bool) or int(week) < 0:
            raise DatabaseError("Week must be a non-negative integer.")
        with self._transaction() as conn:
            self._upsert_balance(conn, int(week), balance, note)

    def import_balances(self, records: Iterable[Tuple[int, Decimal, str]]) -> int:
        """Upsert many balances in one transaction. Returns the number written."""
        count = 0
        with self._transaction() as conn:
            for week, balance, note in records:
                self._upsert_balance(conn, int(week), balance, note)
                count += 1
        return count

    def delete_balance(self, week: int) -> bool:
        with self._transaction() as conn:
            result = conn.execute(
                sa.delete(weekly_balances).where(weekly_balances.c.week == int(week))
            )
        return result.rowcount > 0

    def clear_balances(self) -> int:
        with self._transaction() as conn:
            result = conn.execute(sa.delete(weekly_balances))
        return result.rowcount or 0

    # -- settings ----------------------------------------------------------
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._transaction() as conn:
            value = conn.execute(
                sa.select(app_settings.c.value).where(app_settings.c.key == key)
            ).scalar()
        return default if value is None else value

    def set_setting(self, key: str, value: str) -> None:
        with self._transaction() as conn:
            result = conn.execute(
                sa.update(app_settings).where(app_settings.c.key == key).values(value=str(value))
            )
            if result.rowcount == 0:
                conn.execute(sa.insert(app_settings).values(key=key, value=str(value)))

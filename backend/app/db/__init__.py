"""Database package.

Two SQLite pragmas are set on every connection. Production is Postgres, but the SQLite
path is what tests and a Docker-less demo run on, and without these it behaves
differently enough to hide real bugs and invent fake ones.

- foreign_keys: SQLite ignores foreign keys unless asked. Without it the test suite
  silently accepts writes that Postgres rejects, so a test that should fail passes.
- journal_mode=WAL and busy_timeout: SQLite allows a single writer, so the background
  task that resolves a voice call collided with the request that was still writing and
  died with "database is locked", losing the call. WAL lets a writer and readers coexist
  and the timeout makes a brief overlap wait rather than fail. Found exactly that way.

  The timeout is 30 seconds rather than the 5 it started at. An evaluation holds its
  write transaction open across the CAMARA calls, and when the sandbox is returning 500s
  those retries push a single request past 13 seconds. Five was not enough, and the
  symptom was a voice call that silently never resolved. Postgres does not care, but
  SQLite is what a Docker-less demo machine falls back to, which is the worst place to
  discover this.

The driver check is by module name, not isinstance: under aiosqlite the object handed to
this event is SQLAlchemy's async adapter, not a raw sqlite3.Connection.
"""

from sqlalchemy import event
from sqlalchemy.engine import Engine


def _is_sqlite(dbapi_connection) -> bool:
    cls = type(dbapi_connection)
    return "sqlite" in f"{cls.__module__}.{cls.__name__}".lower()


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_connection, _connection_record):
    if not _is_sqlite(dbapi_connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
    except Exception:  # noqa: BLE001 - an in-memory database cannot use WAL, and does not need to
        pass
    cursor.close()

"""Database package.

SQLite ignores foreign keys unless the pragma is set per connection. Without this, the
test suite would silently accept writes that Postgres rejects — tests must fail the same
way production does. Registered here because the package is imported before any module
inside it, so it applies to every engine including ones built inside test fixtures.

Note the driver check is by module name, not isinstance: under aiosqlite the object
handed to this event is SQLAlchemy's async adapter, not a raw sqlite3.Connection.
"""

from sqlalchemy import event
from sqlalchemy.engine import Engine


def _is_sqlite(dbapi_connection) -> bool:
    cls = type(dbapi_connection)
    return "sqlite" in f"{cls.__module__}.{cls.__name__}".lower()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    if not _is_sqlite(dbapi_connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

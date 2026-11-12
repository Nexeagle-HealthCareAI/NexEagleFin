from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


_connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# The ledger is append-only. On PostgreSQL the database itself refuses
# UPDATE and DELETE on ledger rows, so an application bug cannot rewrite history.
POSTGRES_GUARDS = """
CREATE OR REPLACE FUNCTION nexeaglefin_ledger_readonly() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'ledger rows are append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS journal_line_readonly ON journal_line;
CREATE TRIGGER journal_line_readonly BEFORE UPDATE OR DELETE ON journal_line
  FOR EACH ROW EXECUTE FUNCTION nexeaglefin_ledger_readonly();

DROP TRIGGER IF EXISTS journal_entry_readonly ON journal_entry;
CREATE TRIGGER journal_entry_readonly BEFORE UPDATE OR DELETE ON journal_entry
  FOR EACH ROW EXECUTE FUNCTION nexeaglefin_ledger_readonly();
"""


def init_db(bind=None):
    bind = bind or engine
    from . import models  # noqa: F401  (registers tables)

    Base.metadata.create_all(bind)
    if bind.dialect.name == "postgresql":
        with bind.begin() as conn:
            conn.execute(text(POSTGRES_GUARDS))

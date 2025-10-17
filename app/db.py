from __future__ import annotations

from datetime import datetime, date
from pathlib import Path

from sqlalchemy import create_engine, Column, String, Text, DateTime, Date
from sqlalchemy.orm import sessionmaker, declarative_base

# ------------------------------------------------------------------------------
# Storage locations
# ------------------------------------------------------------------------------
DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "papers.db"

# ------------------------------------------------------------------------------
# SQLAlchemy setup
# ------------------------------------------------------------------------------
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    future=True,
)
Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

# ------------------------------------------------------------------------------
# Model
# ------------------------------------------------------------------------------
class PaperORM(Base):
    __tablename__ = "papers"

    id = Column(String, primary_key=True)                 # stable hash-based id
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)

    file_hash = Column(String, nullable=True)

    title = Column(String, nullable=True)
    authors_json = Column(Text, nullable=True)            # JSON list of authors
    year = Column(String, nullable=True)

    abstract = Column(Text, nullable=True)
    data_src = Column(String, nullable=True)

    path = Column(String, nullable=True)                  # e.g. "uploads/foo.pdf"
    thumb_path = Column(String, nullable=True)            # e.g. "thumbs/foo.png"

    # Metadata enrichment
    doi = Column(String, nullable=True, index=True)
    arxiv_id = Column(String, nullable=True, index=True)
    venue = Column(String, nullable=True)
    published_at = Column(Date, nullable=True)
    url = Column(String, nullable=True)

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
def _existing_columns_sqlite(table_name: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").all()
    return {r[1] for r in rows}

def _ensure_columns_sqlite():
    cols = _existing_columns_sqlite("papers")
    alters: list[tuple[str, str]] = []
    if "doi" not in cols:
        alters.append(("doi", "ALTER TABLE papers ADD COLUMN doi TEXT"))
    if "arxiv_id" not in cols:
        alters.append(("arxiv_id", "ALTER TABLE papers ADD COLUMN arxiv_id TEXT"))
    if "venue" not in cols:
        alters.append(("venue", "ALTER TABLE papers ADD COLUMN venue TEXT"))
    if "published_at" not in cols:
        alters.append(("published_at", "ALTER TABLE papers ADD COLUMN published_at DATE"))
    if "url" not in cols:
        alters.append(("url", "ALTER TABLE papers ADD COLUMN url TEXT"))
    if "created_at" not in cols:
        alters.append(("created_at", "ALTER TABLE papers ADD COLUMN created_at DATETIME"))
    if alters:
        with engine.begin() as conn:
            for _, ddl in alters:
                conn.exec_driver_sql(ddl)

def init_db():
    Base.metadata.create_all(engine)
    _ensure_columns_sqlite()
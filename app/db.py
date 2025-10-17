import json
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import DATABASE_URL, DATA_DIR

Base = declarative_base()
engine = create_engine(DATABASE_URL, future=True)
Session = sessionmaker(bind=engine)

class PaperORM(Base):
    __tablename__ = "papers"
    id = Column(String, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    file_hash = Column(String, index=True)
    title = Column(String)
    authors_json = Column(Text)   # JSON list[str]
    year = Column(String)
    abstract = Column(Text)
    abstract_source = Column(String)
    path = Column(String)         # relative under /media
    thumb_path = Column(String)   # relative under /media

def init_db():
    Base.metadata.create_all(engine)
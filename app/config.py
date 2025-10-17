from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]     # .../PaperShelf/app -> .../PaperShelf
DATA_DIR = ROOT_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
THUMBS_DIR = DATA_DIR / "thumbs"
TEMPLATES_DIR = ROOT_DIR / "templates"

# Ensure folders exist at startup
for p in (DATA_DIR, UPLOADS_DIR, THUMBS_DIR, TEMPLATES_DIR):
    p.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{(DATA_DIR / 'papers.db').as_posix()}"
from pathlib import Path

# Root (project) dir = parent of this 'app' package
BASE_DIR = Path(__file__).resolve().parents[1]

DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
THUMBS_DIR = DATA_DIR / "thumbs"
TEMPLATES_DIR = BASE_DIR / "templates"

for d in (DATA_DIR, UPLOADS_DIR, THUMBS_DIR):
    d.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{(DATA_DIR / 'papers.db').as_posix()}"
# 📚 PaperShelf

**PaperShelf** is a lightweight, local-first research paper organizer built with **FastAPI** and **Tailwind CSS**.  
It automatically extracts metadata (title, authors, year, abstract) and generates thumbnails from uploaded PDF papers, enabling quick search and visual browsing — all offline.

---

## 🚀 Features

- 🧠 **Automatic Metadata Extraction** – Detects title, authors, and year from PDF text.
- 🖼️ **First-Page Thumbnail Preview** – Renders the first page as a visual reference.
- 🔍 **Instant Search** – Search by title or abstract in real time.
- 📁 **Local Storage** – Everything stays inside your `data/` folder (SQLite + files).
- 🧹 **One-Click Cleanup (Dev)** – Reset database and remove uploaded files easily.
- 🧩 **Extensible** – Modular service structure (FastAPI + SQLAlchemy + Jinja2).

---

## 🗂️ Project Structure

```
PaperShelf/
├─ app/
│  ├─ api.py              # FastAPI routes and Jinja2 rendering
│  ├─ config.py           # Global paths & constants
│  ├─ db.py               # SQLAlchemy ORM and DB session
│  ├─ services/
│  │  └─ indexer.py       # PDF indexing, hashing, metadata extraction
│  └─ utils/
│     └─ pdf_tools.py     # PDF text/thumbnail/abstract utilities
├─ data/
│  ├─ uploads/            # Uploaded PDF files
│  ├─ thumbs/             # Auto-generated thumbnails
│  └─ papers.db           # SQLite database
├─ templates/
│  ├─ base.html           # Base layout (Tailwind + Alpine)
│  ├─ index.html          # Home/Search page
│  └─ _paper_card.html    # Individual paper card
├─ main.py                # Application entry point
├─ requirements.txt       # Dependencies
└─ README.md              # Project documentation
```

---

## 🧩 Tech Stack

| Component | Technology |
|------------|-------------|
| Backend | [FastAPI](https://fastapi.tiangolo.com/), [SQLAlchemy](https://www.sqlalchemy.org/) |
| Frontend | [Jinja2](https://jinja.palletsprojects.com/), [Tailwind CSS](https://tailwindcss.com/), [Alpine.js](https://alpinejs.dev/) |
| PDF Tools | [PyMuPDF](https://pymupdf.readthedocs.io/), [OCRmyPDF](https://ocrmypdf.readthedocs.io/), [pytesseract](https://github.com/madmaze/pytesseract) |
| Database | SQLite (via SQLAlchemy ORM) |
| Deployment | [Uvicorn](https://www.uvicorn.org/) |

---

## ⚙️ Installation & Setup

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/kazisr/PaperShelf.git
cd PaperShelf
```

### 2️⃣ Create a Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3️⃣ Install Dependencies

```bash
pip install -r requirements.txt
```

> **Note:**  
> `ocrmypdf` and `pytesseract` require system packages:  
> - **Tesseract OCR**  
> - **Ghostscript / qpdf** (for OCRmyPDF)  
> Install them via your package manager:
> ```bash
> sudo apt install tesseract-ocr ghostscript qpdf
> ```

### 4️⃣ Run the Application

```bash
uvicorn main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

---

## 🧪 Usage

1. Upload one or more PDF files from the top bar.  
2. The system:
   - Extracts title, authors, year, and abstract (heuristically)
   - Generates a thumbnail (first page)
   - Stores metadata in `data/papers.db`
3. Use the search box to find papers by title or abstract.

---

## 🔧 API Endpoints

| Method | Endpoint | Description |
|---------|-----------|-------------|
| `GET` | `/` | Home page (HTML view) |
| `GET` | `/api/search?q=` | Search papers by title/abstract |
| `POST` | `/upload` | Upload a PDF file |
| `POST` | `/dev/clean` | Wipe DB and uploaded files (for development) |

---

## 📊 Database Model

| Field | Type | Description |
|--------|------|-------------|
| `id` | string | Unique paper ID (UUID) |
| `file_hash` | string | MD5 of the PDF file |
| `title` | string | Paper title |
| `authors_json` | JSON text | Author list |
| `year` | string | Publication year |
| `abstract` | text | Extracted abstract |
| `abstract_source` | string | e.g., “system” |
| `path` | string | Relative path to PDF |
| `thumb_path` | string | Thumbnail image path |

---

## 🧭 Folder Paths

Defined in `app/config.py`:

| Folder | Description |
|---------|-------------|
| `data/` | Main data folder |
| `data/uploads/` | PDF storage |
| `data/thumbs/` | Thumbnails |
| `data/papers.db` | SQLite database |

---

## 💡 Future Enhancements

- [ ] DOI / arXiv metadata auto-fetch  
- [ ] Author / Year filters in search  
- [ ] Bulk import from folder  
- [ ] Tag-based organization  
- [ ] CSV export of library  
- [ ] Full-text OCR search (using SQLite FTS5)  
- [ ] Dark/light theme toggle  

---

## 🧑‍💻 Author

**Kazi Shahrier Rafid**  
Research Student, Kanazawa University  
📧 kazisr@stu.kanazawa-u.ac.jp
🌐 [github.com/kazisr](https://github.com/kazisr)

---

## 📜 License

This project is open-source and available under the [MIT License](LICENSE).

---

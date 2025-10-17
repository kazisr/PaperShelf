# 📚 PaperShelf

**PaperShelf** is a lightweight, local-first research paper organizer built with **FastAPI** and **Tailwind CSS**.  
It automatically extracts metadata (title, authors, year, abstract) and generates thumbnails from uploaded PDF papers, enabling quick search and visual browsing — all offline.

---

## 🚀 Features

- 🧠 **Intelligent Metadata Extraction** – Automatically detects title, authors, and publication year from PDF text using layout analysis.
- 🖼️ **Smart Thumbnails** – Generates responsive first-page previews.
- 🧩 **Compact & Polished Cards** – Each paper card features rounded corners, hover elevation, and improved readability.
- 🧾 **Data Source Tagging** – Displays combined sources (e.g., `System + Crossref-doi`) instead of DOI link.
- 📥 **Smart Upload Area** – Drag-and-drop uploader appears only when no papers are present.
- 🔍 **Instant Search & Filter** – Find papers by title, author, or abstract in real time.
- 📁 **Local Storage** – All data (PDFs, metadata, and previews) stay local in `data/` (SQLite + files).
- 🧹 **One-Click Cleanup (Dev)** – Easily reset or clear the library for development.
- ⚙️ **Modular Architecture** – Built with FastAPI + SQLAlchemy + Jinja2 for extensibility.

---

**Latest UI Improvements:**
- Improved paper card UI with cleaner layout, responsive thumbnail.
- Dynamic card resizing for better grid presentation (smaller footprint, hover effects).
- Adaptive image height for different screen sizes (mobile, tablet, desktop).
- Drag & Drop upload area hidden automatically when papers are present.
- DOI button replaced with `data_source` label display.

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

> **No additional setup is required for the latest UI features.** All UI improvements are handled via frontend code and CSS.

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

| Field          | Type | Description |
|----------------|------|-------------|
| `id`           | string | Unique paper ID (UUID) |
| `file_hash`    | string | MD5 of the PDF file |
| `title`        | string | Paper title |
| `authors_json` | JSON text | Author list |
| `year`         | string | Publication year |
| `abstract`     | text | Extracted abstract |
| `data_src`     | string | e.g., “system” |
| `path`         | string | Relative path to PDF |
| `thumb_path`   | string | Thumbnail image path |

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

- [ ] 📚 Add folder-based organization for collections or projects.
- [ ] 🔖 Integrate external metadata (Crossref, Arxiv) for improved accuracy.
- [ ] 🌙 Add dark/light theme toggle with persistent preference.
- [ ] 🧭 Implement advanced search filters (year, author, venue).
- [ ] 🔗 Enable automatic PDF linking for detected DOIs or arXiv IDs.
- [ ] 🧠 Add semantic search and AI-based summarization support.
- [ ] 📊 Add dashboard analytics for reading and citation tracking.

---

### UI Customization Notes
- Thumbnail height automatically adjusts via CSS media queries.
- Each paper card now supports `data_source` field (e.g., `System`, `Crossref-doi`, `Arxiv-id`, etc.).
- The upload dropzone is only visible when there are no papers.
- All cards include hover elevation, rounded corners, and improved readability.

---

### Changelog

#### vNext (2025-10)
- Refined UI with responsive image area.
- Compact card design.
- Added `data_source` tag replacing DOI button.
- Added auto-hide for drag & drop area when papers exist.

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

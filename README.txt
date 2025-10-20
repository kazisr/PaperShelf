PaperShelf — Smart Research Paper Organizer
===========================================

PaperShelf is a minimalist web app built with Flask, Jinja2, and TailwindCSS, designed to manage,
search, and preview research papers locally or online. Upload your PDFs, view metadata cards,
and filter by author, year, or venue — all in a clean Material 3–style interface.

------------------------------------------------------------
Features
------------------------------------------------------------
- Upload and auto-list PDF files (drag & drop or folder import)
- Dynamic search by paper title, author, year, and venue
- Material 3–inspired responsive UI (with dark mode)
- Live filtering
- SQLite database for metadata persistence

------------------------------------------------------------
Project Structure
------------------------------------------------------------
PaperShelf/
├── app/                      # Core Flask app package
│   ├── api.py                # Web routes
│   ├── models.py             # Paper database models
│   ├── utils/                # Helper utilities
│   └── __init__.py
│
├── templates/                # HTML templates
│   ├── base.html
│   ├── index.html
│   └── _paper_card.html
│
├── data/                     # Database & uploaded files
│   ├── papers.db
│   ├── uploads/
│   └── thumbs/
│
├── static/                   # CSS / JS (if any custom)
│
├── config.py                 # App paths & directories
├── main.py                   # Flask app launcher
├── wsgi.py                   # WSGI entrypoint for deployment
├── requirements.txt           # Dependencies list
└── README.txt

------------------------------------------------------------
Local Setup
------------------------------------------------------------
1. Clone or unzip the project:
   git clone https://github.com/yourname/papershelf.git
   cd papershelf

2. Create a virtual environment:
   python -m venv .venv
   source .venv/bin/activate   (Windows: .venv\Scripts\activate)

3. Install dependencies:
   pip install -r requirements.txt

4. Run locally:
   python main.py
   Open in browser: http://127.0.0.1:5000/

------------------------------------------------------------
Deploying on PythonAnywhere
------------------------------------------------------------
1. Upload your project folder (PaperShelf/) to /home/yourusername/
2. In the Web tab, choose "Manual configuration (Flask)"
3. Set WSGI file path:
   /home/yourusername/PaperShelf/wsgi.py
4. Set virtualenv path:
   /home/yourusername/PaperShelf/.venv
5. Reload your web app.

Your site will be live at:
   https://yourusername.pythonanywhere.com

------------------------------------------------------------
Requirements
------------------------------------------------------------
flask>=3.0.0
jinja2>=3.1.3
gunicorn>=21.2.0

------------------------------------------------------------
Author
------------------------------------------------------------
Kazi Shahrier Rafid
Research Student
Kanazawa University — Frontier Engineering (MEng)
Email: kazi.rafid@seu.edu.bd

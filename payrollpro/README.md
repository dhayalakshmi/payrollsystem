# Payroll System
Flask + SQLite. Run: `pip install -r requirements.txt`, then `python app.py` -> http://127.0.0.1:8000

Demo logins (loaded automatically at startup - only missing demo records are added, existing data is kept; set SEED_DEMO=0 to disable):
- Admin: hr@admin.ac.in / Admin@123
- Employees (20 demo employees across 8 departments, with pending leave and attendance requests): aarav.sharma@example.com, priya.nair@example.com, karthik.raj@example.com, divya.menon@example.com ... / Welcome@123
To reset everything, delete payroll.db and restart.

New users: any email ending @admin.ac.in becomes an admin; others are employees.
Online link: deploy to Render / Railway / PythonAnywhere (start command `gunicorn app:app`), set SECRET_KEY and keep payroll.db on a persistent disk (or set DB_PATH).

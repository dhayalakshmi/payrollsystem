"""Payroll System - Flask + SQLite payroll system. Run: python app.py -> http://127.0.0.1:8000"""
import os, re, sqlite3, secrets, csv, io
from datetime import date, datetime, timedelta
from functools import wraps
from flask import (Flask, g, render_template, request, redirect, url_for,
                   session, flash, abort, Response)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DB_PATH", os.path.join(BASE, "payroll.db"))
ADMIN_DOMAIN = "@admin.ac.in"
WORKDAYS = 26
EARN = ("basic_salary", "hra", "allowances", "bonus", "overtime")
DED = ("pf", "ptax", "itax", "insurance", "other_ded")
app = Flask(__name__)
# Behind Render's HTTPS proxy: trust X-Forwarded-Proto/Host so request.is_secure is correct.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
# Session cookie hardening (Secure only on the HTTPS deployment, so local http://127.0.0.1 testing still works).
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER") or os.environ.get("COOKIE_SECURE") == "1"))
kf = os.path.join(BASE, ".secret")
if not os.path.exists(kf):
    open(kf, "w").write(secrets.token_hex(32))
app.secret_key = os.environ.get("SECRET_KEY") or open(kf).read()

SCHEMA = """
create table if not exists users(id integer primary key, email text unique, pw text, role text,
 name text, phone text, dob text, address text, bank_acc text, emergency text,
 department text default '', designation text default '', basic_salary real default 0,
 profile_done integer default 0, joined text);
create table if not exists attendance(id integer primary key, user_id int, date text,
 check_in text, check_out text, status text default 'pending', unique(user_id,date));
create table if not exists leaves(id integer primary key, user_id int, type text, start text,
 end text, reason text, status text default 'pending', created text);
create table if not exists payslips(id integer primary key, user_id int, month text, basic real,
 allow real, pf real, ptax real, lop real, unpaid int, present int, net real, created text,
 unique(user_id,month));
"""
R = "real default 0"
ADD = {"users": {"ifsc": "text default ''", "hra": R, "allowances": R, "bonus": R, "overtime": R, "pf": R,
                 "ptax": "real default 200", "itax": R, "insurance": R, "other_ded": R},
       "payslips": {"hra": R, "bonus": R, "overtime": R, "gross": R, "itax": R, "insurance": R, "other": R, "total_ded": R}}

def init_db():
    with sqlite3.connect(DB) as c:
        c.executescript(SCHEMA)
        for t, cols in ADD.items():
            have = {r[1] for r in c.execute(f"pragma table_info({t})")}
            for k, v in cols.items():
                if k not in have: c.execute(f"alter table {t} add column {k} {v}")

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close(_):
    d = g.pop("db", None)
    if d: d.close()

def q(sql, a=(), one=False):
    r = db().execute(sql, a).fetchall()
    return (r[0] if r else None) if one else r

def x(sql, a=()):
    c = db().execute(sql, a); db().commit(); return c.lastrowid

# ---------- validation ----------
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")
NAME_RE = re.compile(r"[A-Za-z][A-Za-z .'-]{1,59}")
PHONE_RE = re.compile(r"[6-9]\d{9}")
IFSC_RE = re.compile(r"[A-Z]{4}0[A-Z0-9]{6}")
PW_MSG = "Use 8+ characters with an uppercase letter, a lowercase letter, a number and a special character."

def pw_error(p):
    ok = len(p) >= 8 and re.search(r"[A-Z]", p) and re.search(r"[a-z]", p) and re.search(r"\d", p) and re.search(r"[^A-Za-z0-9]", p)
    return None if ok else PW_MSG

def fake_account(s):
    for i in range(len(s) - 4):
        w = [int(c) for c in s[i:i + 5]]
        if all(w[j + 1] - w[j] == 1 for j in range(4)) or all(w[j] - w[j + 1] == 1 for j in range(4)): return True
    return bool(re.search(r"(\d)\1{5}", s))

def validate_profile(f):
    e = {}
    if not NAME_RE.fullmatch(f.get("name", "").strip()): e["name"] = "Enter your full name (letters only)."
    ph = f.get("phone", "").strip()
    if not PHONE_RE.fullmatch(ph): e["phone"] = "Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9."
    em = f.get("emergency", "").strip()
    if not PHONE_RE.fullmatch(em): e["emergency"] = "Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9."
    elif em == ph: e["emergency"] = "Emergency contact must be different from your own number."
    try:
        age = (date.today() - date.fromisoformat(f.get("dob", ""))).days / 365.25
        if not 18 <= age <= 70: e["dob"] = "Age must be between 18 and 70 years."
    except ValueError: e["dob"] = "Enter a valid date of birth."
    if len(f.get("address", "").strip()) < 10: e["address"] = "Enter your complete address."
    acc = f.get("bank_acc", "").strip()
    if not re.fullmatch(r"\d{9,18}", acc): e["bank_acc"] = "Account number must be 9 to 18 digits."
    elif fake_account(acc): e["bank_acc"] = "This account number looks invalid. Enter your actual account number."
    if not IFSC_RE.fullmatch(f.get("ifsc", "").strip().upper()): e["ifsc"] = "Enter a valid IFSC code (e.g. HDFC0001234)."
    return e

def num(v):
    try: return max(0.0, round(float(v), 2))
    except (TypeError, ValueError): return 0.0

def inr(v):
    v = float(v or 0); i, d = f"{abs(v):.2f}".split(".")
    if len(i) > 3: i = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", i[:-3]) + "," + i[-3:]
    return ("-" if v < 0 else "") + "₹" + i + ("" if d == "00" else "." + d)

@app.context_processor
def inject():
    return dict(user=g.get("user"), inr=inr, empid=lambda i: f"EMP{int(i):03d}",
                mname=lambda m: datetime.strptime(m, "%Y-%m").strftime("%B %Y"))

def login_required(role=None):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = q("select * from users where id=?", (session.get("uid"),), True)
            if not u: return redirect(url_for("login"))
            if role and u["role"] != role: abort(403)
            if u["role"] == "employee" and not u["profile_done"] and request.endpoint not in ("profile", "logout"):
                return redirect(url_for("profile"))
            g.user = u
            return f(*a, **k)
        return w
    return deco

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
       "form-action 'self'; frame-ancestors 'none'")

@app.after_request
def security_headers(r):
    h = r.headers
    csp = CSP + ("; upgrade-insecure-requests" if request.is_secure else "")
    h["Content-Security-Policy"] = csp
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "strict-origin-when-cross-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Cross-Origin-Resource-Policy"] = "same-origin"
    if request.is_secure:  # HSTS only means something over HTTPS
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.endpoint != "static":  # payroll data must not be cached by browsers/proxies
        h["Cache-Control"] = "no-store"
    return r

@app.errorhandler(403)
def forbidden(_): return render_template("msg.html", text="403 - You don't have access to this page."), 403

@app.route("/")
def home(): return redirect(url_for("dashboard"))

@app.route("/login", methods=["GET", "POST"])
def login():
    f, err = request.form, {}
    if request.method == "POST":
        email, pw = f["email"].strip().lower(), f["password"]
        if not EMAIL_RE.match(email): err["email"] = "Enter a valid email address."
        if pw_error(pw): err["password"] = PW_MSG
        if not err:
            u = q("select * from users where email=?", (email,), True)
            if u and check_password_hash(u["pw"], pw):
                session.clear(); session["uid"] = u["id"]
                return redirect(url_for("dashboard"))
            err["form"] = "Incorrect email or password."
    return render_template("auth.html", mode="login", f=f, err=err)

@app.route("/register", methods=["GET", "POST"])
def register():
    f, err = request.form, {}
    if request.method == "POST":
        email, name = f["email"].strip().lower(), f["name"].strip()
        if not NAME_RE.fullmatch(name): err["name"] = "Enter your full name (letters only)."
        if not EMAIL_RE.match(email): err["email"] = "Enter a valid email address."
        elif q("select 1 from users where email=?", (email,), True): err["email"] = "This email is already registered."
        if pw_error(f["password"]): err["password"] = PW_MSG
        if f["password"] != f["confirm"]: err["confirm"] = "Passwords do not match."
        if not err:
            admin = email.endswith(ADMIN_DOMAIN)
            uid = x("insert into users(email,pw,role,name,profile_done,joined) values(?,?,?,?,?,?)",
                    (email, generate_password_hash(f["password"]), "admin" if admin else "employee", name,
                     1 if admin else 0, date.today().isoformat()))
            session.clear(); session["uid"] = uid
            return redirect(url_for("dashboard"))
    return render_template("auth.html", mode="register", f=f, err=err)

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

def month_now(): return date.today().strftime("%Y-%m")

def leave_days(uid, month, unpaid_only=False):
    y, m = map(int, month.split("-")); s = date(y, m, 1); e = date(y + (m == 12), m % 12 + 1, 1) - timedelta(1); n = 0
    sql = "select start,end from leaves where user_id=? and status='approved'" + (" and type='Unpaid'" if unpaid_only else "")
    for l in q(sql, (uid,)):
        a, b = max(date.fromisoformat(l["start"]), s), min(date.fromisoformat(l["end"]), e)
        if b >= a: n += (b - a).days + 1
    return n

def att_stats(uid, month=None):
    m = month or month_now()
    c = lambda st: q("select count(*) c from attendance where user_id=? and status=? and date like ?", (uid, st, m + "%"), True)["c"]
    p, a, lv = c("approved"), c("rejected"), leave_days(uid, m)
    return dict(total=WORKDAYS, present=p, absent=a, leave=lv, pct=round(p / (p + a + lv) * 100, 1) if p + a + lv else 0.0)

@app.route("/dashboard")
@login_required()
def dashboard():
    u = g.user; today = date.today().strftime("%A, %d %B %Y")
    if u["role"] == "admin":
        last = q("select max(month) m from payslips", one=True)["m"] or month_now()
        s = dict(emps=q("select count(*) c from users where role='employee'", one=True)["c"],
                 leaves=q("select count(*) c from leaves where status='pending'", one=True)["c"],
                 att=q("select count(*) c from attendance where status='pending'", one=True)["c"],
                 net=q("select coalesce(sum(net),0) c from payslips where month=?", (last,), True)["c"], lm=last)
        trend = q("select month, sum(net) t from payslips group by month order by month desc limit 6")[::-1]
        dept = q("select coalesce(nullif(department,''),'Unassigned') d, count(*) c from users where role='employee' group by d order by c desc")
        return render_template("dashboard.html", s=s, today=today, trend=trend, mx=max([t["t"] for t in trend] or [1]) or 1,
                               dept=dept, total=sum(d["c"] for d in dept) or 1)
    return render_template("dashboard.html", today=today, st=att_stats(u["id"]),
        tod=q("select * from attendance where user_id=? and date=?", (u["id"], date.today().isoformat()), True),
        slip=q("select * from payslips where user_id=? order by month desc", (u["id"],), True),
        pend=q("select count(*) c from leaves where user_id=? and status='pending'", (u["id"],), True)["c"])

@app.route("/profile", methods=["GET", "POST"])
@login_required("employee")
def profile():
    err, p = {}, g.user
    if request.method == "POST":
        f = request.form; err = validate_profile(f)
        if not err:
            x("update users set name=?,phone=?,dob=?,address=?,bank_acc=?,ifsc=?,emergency=?,profile_done=1 where id=?",
              (f["name"].strip(), f["phone"].strip(), f["dob"], f["address"].strip(), f["bank_acc"].strip(),
               f["ifsc"].strip().upper(), f["emergency"].strip(), g.user["id"]))
            flash("Details saved successfully.", "ok"); return redirect(url_for("dashboard"))
        p = {**dict(g.user), **f.to_dict()}
    return render_template("profile.html", p=p, err=err)

@app.route("/salary")
@login_required("employee")
def salary():
    u = g.user; gross = sum(u[k] or 0 for k in EARN); ded = sum(u[k] or 0 for k in DED)
    return render_template("salary.html", gross=gross, ded=ded, net=gross - ded)

STATUSES = ("pending", "approved", "rejected")

def status_arg():
    st = request.args.get("status"); return st if st in STATUSES else None

def counts(table, uid=None):
    r = q(f"select status, count(*) c from {table}" + (" where user_id=?" if uid else "") + " group by status", (uid,) if uid else ())
    d = {i["status"]: i["c"] for i in r}; d["all"] = sum(d.values()); return d

@app.route("/attendance")
@login_required()
def attendance():
    st_f, adm = status_arg(), g.user["role"] == "admin"
    if adm:
        rows = q("select a.*,u.name from attendance a join users u on u.id=a.user_id" + (" where a.status=?" if st_f else "") + " order by a.status='pending' desc, a.date desc limit 200", (st_f,) if st_f else ())
    else:
        rows = q("select * from attendance where user_id=?" + (" and status=?" if st_f else "") + " order by date desc limit 60", (g.user["id"], st_f) if st_f else (g.user["id"],))
    return render_template("attendance.html", rows=rows, tod=q("select * from attendance where user_id=? and date=?", (g.user["id"], date.today().isoformat()), True),
                           st=att_stats(g.user["id"]) if not adm else None, sel=st_f, cnt=counts("attendance", None if adm else g.user["id"]))

@app.route("/attendance/mark", methods=["POST"])
@login_required("employee")
def mark():
    d, t = date.today().isoformat(), datetime.now().strftime("%H:%M")
    row = q("select * from attendance where user_id=? and date=?", (g.user["id"], d), True)
    if request.form["a"] == "in" and not row:
        x("insert into attendance(user_id,date,check_in) values(?,?,?)", (g.user["id"], d, t)); flash("Checked in. Awaiting admin approval.", "ok")
    elif request.form["a"] == "out" and row and not row["check_out"]:
        x("update attendance set check_out=? where id=?", (t, row["id"])); flash("Checked out.", "ok")
    return redirect(request.referrer or url_for("attendance"))

@app.route("/leave", methods=["GET", "POST"])
@login_required()
def leave():
    u = g.user
    if request.method == "POST" and u["role"] == "employee":
        f = request.form
        if not f["start"] or not f["end"] or f["end"] < f["start"]:
            flash("Choose a valid date range.", "err")
        else:
            x("insert into leaves(user_id,type,start,end,reason,created) values(?,?,?,?,?,?)",
              (u["id"], f["type"], f["start"], f["end"], f["reason"].strip(), date.today().isoformat()))
            flash("Leave request submitted.", "ok"); return redirect(url_for("leave"))
    st_f = status_arg()
    if u["role"] == "admin":
        rows = q("select l.*,u.name from leaves l join users u on u.id=l.user_id" + (" where l.status=?" if st_f else "") + " order by l.status='pending' desc, l.id desc", (st_f,) if st_f else ())
    else:
        rows = q("select * from leaves where user_id=?" + (" and status=?" if st_f else "") + " order by id desc", (u["id"], st_f) if st_f else (u["id"],))
    return render_template("leave.html", rows=rows, sel=st_f, cnt=counts("leaves", None if u["role"] == "admin" else u["id"]))

@app.route("/decide/<kind>/<int:rid>", methods=["POST"])
@login_required("admin")
def decide(kind, rid):
    if kind not in ("attendance", "leave") or request.form["a"] not in ("approved", "rejected"): abort(400)
    x(f"update {'leaves' if kind == 'leave' else 'attendance'} set status=? where id=?", (request.form["a"], rid))
    flash(f"Request {request.form['a']}.", "ok")
    return redirect(request.referrer or url_for(kind))

@app.route("/employees")
@login_required("admin")
def employees():
    s = "%" + request.args.get("s", "").strip() + "%"
    rows = q("select * from users where role='employee' and (name like ? or email like ? or department like ?) order by id", (s, s, s))
    return render_template("employees.html", rows=rows, gross=lambda e: sum(e[k] or 0 for k in EARN))

@app.route("/employees/<int:eid>", methods=["GET", "POST"])
@login_required("admin")
def employee(eid):
    e = q("select * from users where id=? and role='employee'", (eid,), True) or abort(404)
    if request.method == "POST":
        f = request.form
        x(f"update users set department=?,designation=?,{','.join(k + '=?' for k in EARN + DED)} where id=?",
          (f["department"].strip(), f["designation"].strip(), *[num(f.get(k)) for k in EARN + DED], eid))
        flash("Employee updated.", "ok"); return redirect(url_for("employee", eid=eid))
    return render_template("employee.html", e=e, st=att_stats(eid),
                           slips=q("select * from payslips where user_id=? order by month desc", (eid,)))

def generate(month, ids=None):
    n = 0
    for e in q("select * from users where role='employee' and basic_salary>0"):
        if ids is not None and e["id"] not in ids: continue
        gross = sum(e[k] or 0 for k in EARN); ded = sum(e[k] or 0 for k in DED)
        un = leave_days(e["id"], month, True)
        pr = q("select count(*) c from attendance where user_id=? and status='approved' and date like ?", (e["id"], month + "%"), True)["c"]
        lop = round(gross / WORKDAYS * un, 2)
        x("insert or replace into payslips(user_id,month,basic,hra,allow,bonus,overtime,gross,pf,ptax,itax,insurance,other,total_ded,lop,unpaid,present,net,created) values(" + ",".join("?" * 19) + ")",
          (e["id"], month, e["basic_salary"], e["hra"], e["allowances"], e["bonus"], e["overtime"], gross, e["pf"], e["ptax"],
           e["itax"], e["insurance"], e["other_ded"], ded, lop, un, pr, round(gross - ded - lop, 2), date.today().isoformat()))
        n += 1
    return n

@app.route("/payslips", methods=["GET", "POST"])
@login_required()
def payslips():
    u = g.user
    if u["role"] == "admin":
        if request.method == "POST":
            month = request.form["month"] or month_now(); n = generate(month)
            flash(f"Payroll generated for {n} employee(s).", "ok" if n else "err")
            return redirect(url_for("payslips", m=month))
        months = [r["month"] for r in q("select distinct month from payslips order by month desc")]
        sel = request.args.get("m") or (months[0] if months else month_now())
        rows = q("select p.*,u.name,u.department from payslips p join users u on u.id=p.user_id where p.month=? order by u.name", (sel,))
        tot = {k: sum(r[k] or 0 for r in rows) for k in ("gross", "total_ded", "lop", "net")}
        return render_template("payslips.html", rows=rows, months=months, sel=sel, tot=tot, month=month_now())
    return render_template("payslips.html", rows=q("select * from payslips where user_id=? order by month desc", (u["id"],)))

@app.route("/payslip/<int:pid>")
@login_required()
def payslip(pid):
    p = q("select p.*,u.name,u.email,u.department,u.designation,u.bank_acc,u.ifsc from payslips p join users u on u.id=p.user_id where p.id=?", (pid,), True) or abort(404)
    if g.user["role"] != "admin" and p["user_id"] != g.user["id"]: abort(403)
    return render_template("payslip.html", p=p)

@app.route("/export/<month>")
@login_required("admin")
def export(month):
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["Employee", "Email", "Month", "Gross", "Deductions", "Loss of pay", "Net"])
    for r in q("select p.*,u.name,u.email from payslips p join users u on u.id=p.user_id where month=?", (month,)):
        w.writerow([r["name"], r["email"], r["month"], r["gross"], r["total_ded"], r["lop"], r["net"]])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=payroll_{month}.csv"})

STREETS = ["Gandhi Street, T. Nagar", "Lake View Road, Adyar", "Anna Nagar East", "Velachery Main Road", "OMR, Sholinganallur", "Mount Road, Guindy", "Besant Nagar 2nd Avenue", "Kilpauk Garden Road"]
BANKS = ["HDFC", "SBIN", "ICIC", "UTIB", "KKBK", "CNRB"]
# name, department, designation, basic salary, bonus, overtime
MORE = [("Divya Menon", "Engineering", "Senior Software Engineer", 62000, 4000, 0), ("Rohan Verma", "Engineering", "Software Engineer", 48000, 2000, 1200),
        ("Sneha Iyer", "Engineering", "QA Engineer", 36000, 1500, 600), ("Arjun Reddy", "Engineering", "DevOps Engineer", 54000, 2500, 900),
        ("Kavya Rao", "Design", "UI/UX Designer", 44000, 1800, 0), ("Meera Krishnan", "Human Resources", "HR Manager", 52000, 3000, 0),
        ("Vikram Singh", "Finance", "Senior Accountant", 41000, 2000, 500), ("Lakshmi Narayanan", "Finance", "Payroll Analyst", 34000, 1200, 400),
        ("Nikhil Joshi", "Sales", "Sales Executive", 30000, 3500, 0), ("Ananya Das", "Sales", "Sales Manager", 58000, 5000, 0),
        ("Imran Khan", "Sales", "Business Development Executive", 33000, 2800, 0), ("Pooja Patel", "Marketing", "Marketing Executive", 31000, 1500, 0),
        ("Suresh Babu", "Marketing", "Content Strategist", 35000, 1500, 0), ("Deepak Kumar", "Operations", "Operations Manager", 56000, 3000, 800),
        ("Fatima Begum", "Operations", "Operations Executive", 29000, 1000, 700), ("Harini Subramanian", "Support", "Support Lead", 40000, 2000, 600),
        ("Manoj Pillai", "Support", "Support Executive", 26000, 800, 900)]

def demo_row(i, name, dept, desig, basic, bonus, ot):
    em = name.lower().replace(" ", ".") + "@example.com"
    return (name, em, f"{[6, 7, 8, 9][i % 4]}{(i * 7391825 + 123456789) % 10**9:09d}", date(1987 + i % 12, 1 + i % 12, 5 + i % 20).isoformat(),
            f"{10 + i}, {STREETS[i % len(STREETS)]}, Chennai 6000{10 + i:02d}", f"{(i + 3) * 7919374852 % 10**12:012d}",
            f"{BANKS[i % len(BANKS)]}0{1000 + i * 37:06d}", f"{[6, 7, 8, 9][(i + 1) % 4]}{(i * 5190331 + 987654321) % 10**9:09d}", dept, desig,
            basic, round(basic * .4), round(basic * .12), bonus, ot, round(basic * .12), 200, round(basic * .05) if basic > 45000 else 0, 700, 0)

def seed_demo():
    """Tops up demo data: 1 admin + 20 employees with last month's payslips, pending leave and attendance requests.
    Only adds what is missing (matched by email), so it is safe to run on an existing database."""
    with app.app_context():
        today = date.today(); first = today.replace(day=1); last = first - timedelta(1); lm = last.strftime("%Y-%m")
        if not q("select 1 from users where role='admin'", one=True):
            x("insert into users(email,pw,role,name,profile_done,joined) values(?,?,?,?,1,?)",
              ("hr@admin.ac.in", generate_password_hash("Admin@123"), "admin", "HR Admin", first.isoformat()))
        rows = [("Aarav Sharma", "aarav.sharma@example.com", "9840217365", "1995-04-12", "12, Gandhi Street, T. Nagar, Chennai 600017", "50100238746512", "HDFC0001234", "9841356742", "Engineering", "Software Engineer", 45000, 18000, 6000, 3000, 0, 5400, 200, 2500, 800, 0),
                ("Priya Nair", "priya.nair@example.com", "9790458213", "1993-09-23", "45, Lake View Road, Adyar, Chennai 600020", "31829047561", "SBIN0004567", "9444120987", "Human Resources", "HR Executive", 32000, 12800, 4000, 1500, 800, 3840, 200, 800, 600, 1000),
                ("Karthik Raj", "karthik.raj@example.com", "9884671250", "1990-01-30", "8, Anna Nagar East, Chennai 600102", "917020045681934", "ICIC0002345", "9003245871", "Finance", "Accounts Officer", 38000, 15200, 5000, 2000, 1200, 4560, 200, 1600, 700, 0)]
        rows += [demo_row(i + 3, *m) for i, m in enumerate(MORE)]
        new = {}
        for d in rows:
            if q("select 1 from users where email=?", (d[1],), True): continue
            new[d[1]] = x("insert into users(email,pw,role,name,phone,dob,address,bank_acc,ifsc,emergency,department,designation,basic_salary,hra,allowances,bonus,overtime,pf,ptax,itax,insurance,other_ded,profile_done,joined) values(" + ",".join("?" * 24) + ")",
                          (d[1], generate_password_hash("Welcome@123"), "employee", d[0], d[2], d[3], d[4], d[5], d[6], d[7], d[8], d[9], *d[10:], 1, first.replace(month=1, day=1).isoformat()))
        if not new: return
        L = lambda day: date(last.year, last.month, day)
        P = lambda a, b=None: (today + timedelta(a), today + timedelta(b if b is not None else a))
        # email -> [(type, start, end, reason, status)]
        leaves = {"priya.nair@example.com": [("Unpaid", L(10), L(11), "Family function", "approved")],
                  "karthik.raj@example.com": [("Casual", L(17), L(17), "Personal work", "approved"), ("Casual", *P(7, 8), "Travel", "pending")],
                  "divya.menon@example.com": [("Casual", *P(3, 4), "Family visit", "pending")], "rohan.verma@example.com": [("Sick", *P(0, 1), "Fever and cold", "pending")],
                  "ananya.das@example.com": [("Earned", *P(10, 14), "Annual vacation", "pending")], "nikhil.joshi@example.com": [("Casual", *P(5), "Bank work", "pending")],
                  "pooja.patel@example.com": [("Unpaid", *P(6, 7), "Personal reasons", "pending")], "deepak.kumar@example.com": [("Earned", *P(14, 16), "Wedding in family", "pending")],
                  "harini.subramanian@example.com": [("Sick", *P(0), "Migraine", "pending")], "kavya.rao@example.com": [("Casual", *P(2), "Passport appointment", "pending")],
                  "sneha.iyer@example.com": [("Casual", L(6), L(6), "Personal work", "approved")], "arjun.reddy@example.com": [("Sick", L(21), L(22), "Viral fever", "approved")],
                  "vikram.singh@example.com": [("Casual", L(20), L(20), "Personal work", "rejected")], "imran.khan@example.com": [("Unpaid", L(5), L(6), "Out of station", "approved")],
                  "suresh.babu@example.com": [("Earned", L(12), L(14), "Short trip", "approved")], "fatima.begum@example.com": [("Sick", L(18), L(18), "Dental visit", "rejected")]}
        checkin = {"aarav.sharma@example.com": "09:05", "meera.krishnan@example.com": "09:02", "lakshmi.narayanan@example.com": "09:12", "manoj.pillai@example.com": "09:20",
                   "fatima.begum@example.com": "08:58", "suresh.babu@example.com": "09:31", "arjun.reddy@example.com": "09:08"}
        for em, uid in new.items():
            skip = set()
            for t, a, b, why, st in leaves.get(em, []):
                x("insert into leaves(user_id,type,start,end,reason,status,created) values(?,?,?,?,?,?,?)",
                  (uid, t, a.isoformat(), b.isoformat(), why, st, min(today, a - timedelta(3)).isoformat()))
                if st == "approved" and a.month == last.month: skip |= {(a + timedelta(k)).day for k in range((b - a).days + 1)}
            d = last.replace(day=1)
            while d <= last:
                if d.weekday() != 6 and d.day not in skip:
                    x("insert or ignore into attendance(user_id,date,check_in,check_out,status) values(?,?,?,?,'approved')", (uid, d.isoformat(), f"09:{(d.day * 7) % 25:02d}", f"18:{(d.day * 5) % 30:02d}"))
                d += timedelta(1)
            if em in checkin: x("insert or ignore into attendance(user_id,date,check_in) values(?,?,?)", (uid, today.isoformat(), checkin[em]))
        generate(lm, set(new.values()))

init_db()
if os.environ.get("SEED_DEMO", "1") == "1": seed_demo()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))

"""PayrollPro - Flask + SQLite payroll system. Run: python app.py -> http://127.0.0.1:8000"""
import os, re, sqlite3, secrets, csv, io
from datetime import date, datetime, timedelta
from functools import wraps
from flask import (Flask, g, render_template, request, redirect, url_for,
                   session, flash, abort, Response)
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DB_PATH", os.path.join(BASE, "payroll.db"))
ADMIN_DOMAIN = "@admin.ac.in"
WORKDAYS = 26
EARN = ("basic_salary", "hra", "allowances", "bonus", "overtime")
DED = ("pf", "ptax", "itax", "insurance", "other_ded")
app = Flask(__name__)
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
            dept=dept, total=sum(d["c"] for d in dept) or 1,
            pl=q("select l.*,u.name from leaves l join users u on u.id=l.user_id where l.status='pending' order by l.id desc limit 5"),
            pa=q("select a.*,u.name from attendance a join users u on u.id=a.user_id where a.status='pending' order by a.date desc limit 5"),
            latest=q("select p.*,u.name,u.department from payslips p join users u on u.id=p.user_id where p.month=? order by u.name", (last,)))
    return render_template("dashboard.html", today=today, st=att_stats(u["id"]),
        tod=q("select * from attendance where user_id=? and date=?", (u["id"], date.today().isoformat()), True),
        slip=q("select * from payslips where user_id=? order by month desc", (u["id"],), True),
        pend=q("select count(*) c from leaves where user_id=? and status='pending'", (u["id"],), True)["c"],
        recent=q("select * from leaves where user_id=? order by id desc limit 4", (u["id"],)))

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

@app.route("/attendance")
@login_required()
def attendance():
    if g.user["role"] == "admin":
        rows = q("select a.*,u.name from attendance a join users u on u.id=a.user_id order by a.status='pending' desc, a.date desc limit 200")
    else:
        rows = q("select * from attendance where user_id=? order by date desc limit 60", (g.user["id"],))
    return render_template("attendance.html", rows=rows, tod=q("select * from attendance where user_id=? and date=?", (g.user["id"], date.today().isoformat()), True),
                           st=att_stats(g.user["id"]) if g.user["role"] == "employee" else None)

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
    if u["role"] == "admin":
        rows = q("select l.*,u.name from leaves l join users u on u.id=l.user_id order by l.status='pending' desc, l.id desc")
    else:
        rows = q("select * from leaves where user_id=? order by id desc", (u["id"],))
    return render_template("leave.html", rows=rows)

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

def generate(month):
    n = 0
    for e in q("select * from users where role='employee' and basic_salary>0"):
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

def seed_demo():
    """Loads 1 admin + 3 sample employees with last month's payslips when the database is empty."""
    with app.app_context():
        if q("select 1 from users limit 1", one=True): return
        first = date.today().replace(day=1); last = first - timedelta(1); lm = last.strftime("%Y-%m")
        x("insert into users(email,pw,role,name,profile_done,joined) values(?,?,?,?,1,?)",
          ("hr@admin.ac.in", generate_password_hash("Admin@123"), "admin", "HR Admin", first.isoformat()))
        demo = [("Aarav Sharma", "aarav.sharma@example.com", "9840217365", "1995-04-12", "12, Gandhi Street, T. Nagar, Chennai 600017", "50100238746512", "HDFC0001234", "9841356742", "Engineering", "Software Engineer", 45000, 18000, 6000, 3000, 0, 5400, 200, 2500, 800, 0),
                ("Priya Nair", "priya.nair@example.com", "9790458213", "1993-09-23", "45, Lake View Road, Adyar, Chennai 600020", "31829047561", "SBIN0004567", "9444120987", "Human Resources", "HR Executive", 32000, 12800, 4000, 1500, 800, 3840, 200, 800, 600, 1000),
                ("Karthik Raj", "karthik.raj@example.com", "9884671250", "1990-01-30", "8, Anna Nagar East, Chennai 600102", "917020045681934", "ICIC0002345", "9003245871", "Finance", "Accounts Officer", 38000, 15200, 5000, 2000, 1200, 4560, 200, 1600, 700, 0)]
        ids = []
        for d in demo:
            ids.append(x("insert into users(email,pw,role,name,phone,dob,address,bank_acc,ifsc,emergency,department,designation,basic_salary,hra,allowances,bonus,overtime,pf,ptax,itax,insurance,other_ded,profile_done,joined) values(" + ",".join("?" * 24) + ")",
                         (d[1], generate_password_hash("Welcome@123"), "employee", d[0], d[2], d[3], d[4], d[5], d[6], d[7], d[8], d[9], *d[10:], 1, first.replace(month=1, day=1).isoformat())))
        skip = {1: {10, 11}, 2: {17}}
        for i, uid in enumerate(ids):
            d = last.replace(day=1)
            while d <= last:
                if d.weekday() != 6 and d.day not in skip.get(i, ()):
                    x("insert into attendance(user_id,date,check_in,check_out,status) values(?,?,?,?,'approved')", (uid, d.isoformat(), f"09:{(d.day * 7) % 25:02d}", f"18:{(d.day * 5) % 30:02d}"))
                d += timedelta(1)
        L = "insert into leaves(user_id,type,start,end,reason,status,created) values(?,?,?,?,?,?,?)"
        x(L, (ids[1], "Unpaid", f"{lm}-10", f"{lm}-11", "Family function", "approved", f"{lm}-05"))
        x(L, (ids[2], "Casual", f"{lm}-17", f"{lm}-17", "Personal work", "approved", f"{lm}-14"))
        x(L, (ids[2], "Casual", (date.today() + timedelta(7)).isoformat(), (date.today() + timedelta(8)).isoformat(), "Travel", "pending", date.today().isoformat()))
        x("insert into attendance(user_id,date,check_in) values(?,?,?)", (ids[0], date.today().isoformat(), "09:05"))
        generate(lm)

init_db()
if os.environ.get("SEED_DEMO", "1") == "1": seed_demo()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))

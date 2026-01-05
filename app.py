from __future__ import annotations

import os
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, redirect, render_template_string, request, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash


APP_TITLE = "Pontaje & Lucrări"
DATABASE_URL = os.environ.get("DATABASE_URL")
FLASK_SECRET = os.environ.get("FLASK_SECRET", "change-me")

def normalize_db_url(url: str | None) -> str:
    if not url:
        return "sqlite:///local-dev.sqlite3"
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


app = Flask(__name__)
app.secret_key = FLASK_SECRET
app.config["SQLALCHEMY_DATABASE_URI"] = normalize_db_url(DATABASE_URL)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


# ----------------- Helpers -----------------

def d(x) -> Decimal:
    return Decimal(str(x or 0))

def money(x) -> str:
    if x is None:
        return "0.00"
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return f"{x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"

def pct(x: Decimal) -> str:
    return f"{(x * Decimal('100')).quantize(Decimal('0'), rounding=ROUND_HALF_UP)}%"

def is_admin() -> bool:
    return current_user.is_authenticated and getattr(current_user, "role", "") == "admin"


# ----------------- Models -----------------

class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")  # admin/user


class CompanyProfile(db.Model):
    """
    Date furnizor (firma ta) pentru factură.
    Păstrăm un singur rând (id=1).
    """
    __tablename__ = "company_profile"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, default="Firma Mea SRL")
    cui = db.Column(db.String(50), default="RO12345678")
    reg_com = db.Column(db.String(50), default="J00/0000/2020")
    address = db.Column(db.String(300), default="Adresa firmei")
    phone = db.Column(db.String(50), default="")
    email = db.Column(db.String(100), default="")
    iban = db.Column(db.String(64), default="")
    bank = db.Column(db.String(100), default="")
    capital_social = db.Column(db.String(50), default="")
    vat_payer = db.Column(db.Boolean, default=True)   # plătitor TVA?
    invoice_series = db.Column(db.String(20), default="AA")  # serie factură
    invoice_start_no = db.Column(db.Integer, default=1)      # număr start
    footer_notes = db.Column(db.String(400), default="")


class Client(db.Model):
    __tablename__ = "clients"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    cui = db.Column(db.String(50))
    reg_com = db.Column(db.String(50))
    address = db.Column(db.String(300))
    contact = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(100))


class Job(db.Model):
    __tablename__ = "jobs"
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    start_date = db.Column(db.String(20))
    due_date = db.Column(db.String(20))
    status = db.Column(db.String(20), nullable=False, default="OPEN")
    hourly_rate = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    vat_rate = db.Column(db.Numeric(6, 4), nullable=False, default=Decimal("0.19"))
    currency = db.Column(db.String(10), nullable=False, default="RON")
    client = db.relationship("Client")


class Timesheet(db.Model):
    __tablename__ = "timesheets"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    work_date = db.Column(db.String(20), nullable=False)
    worker = db.Column(db.String(100))
    task = db.Column(db.String(200))
    hours = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    rate_override = db.Column(db.Numeric(12, 2))


class Expense(db.Model):
    __tablename__ = "expenses"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    exp_date = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(50))
    description = db.Column(db.String(250), nullable=False)
    qty = db.Column(db.Numeric(12, 2), nullable=False, default=1)
    unit = db.Column(db.String(20), nullable=False, default="buc")
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    markup_percent = db.Column(db.Numeric(8, 2), nullable=False, default=0)
    billable = db.Column(db.Boolean, nullable=False, default=True)


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    pay_date = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    method = db.Column(db.String(50))
    notes = db.Column(db.String(200))


class Invoice(db.Model):
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    series = db.Column(db.String(20), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    inv_no = db.Column(db.String(50), unique=True, nullable=False)  # ex: AA-2026-0001

    issue_date = db.Column(db.String(20), nullable=False)
    due_date = db.Column(db.String(20))
    payment_method = db.Column(db.String(50), default="OP")  # OP / Cash / Card
    place = db.Column(db.String(100), default="")            # locul emiterii (opțional)
    notes = db.Column(db.String(400), default="")


class InvoiceLine(db.Model):
    __tablename__ = "invoice_lines"
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    line_type = db.Column(db.String(20), nullable=False)  # LABOR/EXPENSE
    description = db.Column(db.String(250), nullable=False)
    qty = db.Column(db.Numeric(12, 2), nullable=False, default=1)
    unit = db.Column(db.String(20), nullable=False, default="buc")
    unit_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)  # fără TVA
    line_total = db.Column(db.Numeric(12, 2), nullable=False, default=0)  # fără TVA


# ----------------- Auth -----------------

@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


def ensure_seed_users():
    admin_u = os.environ.get("ADMIN_USER", "admin")
    admin_p = os.environ.get("ADMIN_PASS", "admin1234")
    user2_u = os.environ.get("USER2_USER", "user")
    user2_p = os.environ.get("USER2_PASS", "user1234")

    if not User.query.filter_by(username=admin_u).first():
        db.session.add(User(username=admin_u, password_hash=generate_password_hash(admin_p), role="admin"))
    if not User.query.filter_by(username=user2_u).first():
        db.session.add(User(username=user2_u, password_hash=generate_password_hash(user2_p), role="user"))
    db.session.commit()


def ensure_company_profile():
    cp = CompanyProfile.query.get(1)
    if not cp:
        cp = CompanyProfile(id=1)
        db.session.add(cp)
        db.session.commit()
    return cp


# ----------------- Business logic -----------------

def compute_job_totals(job: Job) -> dict:
    ts = Timesheet.query.filter_by(job_id=job.id).all()
    labor_hours = sum([d(t.hours) for t in ts], Decimal("0"))
    labor_total = Decimal("0")
    for t in ts:
        rate = d(t.rate_override) if t.rate_override is not None else d(job.hourly_rate)
        labor_total += d(t.hours) * rate

    ex = Expense.query.filter_by(job_id=job.id).all()
    exp_cost_total = sum([d(e.qty) * d(e.unit_cost) for e in ex], Decimal("0"))
    exp_billable_total = Decimal("0")
    for e in ex:
        if e.billable:
            unit_price = d(e.unit_cost) * (Decimal("1") + d(e.markup_percent) / Decimal("100"))
            exp_billable_total += d(e.qty) * unit_price

    subtotal = labor_total + exp_billable_total
    vat = subtotal * d(job.vat_rate)
    total = subtotal + vat
    paid = sum([d(p.amount) for p in Payment.query.filter_by(job_id=job.id).all()], Decimal("0"))
    receivable = total - paid

    return {
        "labor_hours": labor_hours,
        "labor_total": labor_total,
        "exp_cost_total": exp_cost_total,
        "exp_billable_total": exp_billable_total,
        "subtotal": subtotal,
        "vat": vat,
        "total": total,
        "paid": paid,
        "receivable": receivable,
    }


def next_invoice_number(series: str) -> int:
    year = date.today().year
    last = Invoice.query.filter_by(series=series).filter(Invoice.inv_no.like(f"{series}-{year}-%")) \
        .order_by(Invoice.number.desc()).first()
    cp = ensure_company_profile()
    if not last:
        return int(cp.invoice_start_no or 1)
    return int(last.number) + 1


def make_inv_no(series: str, number: int) -> str:
    year = date.today().year
    return f"{series}-{year}-{number:04d}"


# ----------------- UI -----------------

BASE_HTML = """
<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { padding-bottom: 40px; }
    .mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
    @media print {
      .no-print { display:none !important; }
      body { padding: 0; }
      .card { border: none !important; }
    }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark no-print">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('index') }}">{{ app_title }}</a>
    <div class="navbar-nav">
      {% if current_user.is_authenticated %}
        <a class="nav-link" href="{{ url_for('clients') }}">Clienți</a>
        <a class="nav-link" href="{{ url_for('jobs') }}">Lucrări</a>
        <a class="nav-link" href="{{ url_for('receivables') }}">De încasat</a>
        <a class="nav-link" href="{{ url_for('company') }}">Firmă</a>
        <a class="nav-link" href="{{ url_for('logout') }}">Logout ({{ current_user.username }})</a>
      {% endif %}
    </div>
  </div>
</nav>

<div class="container mt-4">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="alert alert-info no-print">{{ messages[0] }}</div>
    {% endif %}
  {% endwith %}
  {{ body|safe }}
</div>
</body>
</html>
"""

def render_page(body_html: str, title: str):
    return render_template_string(
        BASE_HTML,
        body=body_html,
        title=title,
        app_title=APP_TITLE,
        current_user=current_user,
    )


@app.before_request
def setup_once():
    db.create_all()
    ensure_seed_users()
    ensure_company_profile()


# ----------------- Auth routes -----------------

@app.get("/login")
def login():
    body = """
    <div class="row justify-content-center">
      <div class="col-md-5">
        <h3>Autentificare</h3>
        <form method="post" action="/login" class="card card-body">
          <div class="mb-2"><label class="form-label">User</label><input name="username" class="form-control" required></div>
          <div class="mb-2"><label class="form-label">Parolă</label><input name="password" type="password" class="form-control" required></div>
          <button class="btn btn-primary">Intră</button>
        </form>
      </div>
    </div>
    """
    return render_page(body, f"{APP_TITLE} — Login")


@app.post("/login")
def login_post():
    u = request.form.get("username", "").strip()
    p = request.form.get("password", "")
    user = User.query.filter_by(username=u).first()
    if not user or not check_password_hash(user.password_hash, p):
        flash("Date de login greșite.")
        return redirect(url_for("login"))
    login_user(user)
    return redirect(url_for("index"))


@app.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ----------------- Company profile -----------------

@app.get("/company")
@login_required
def company():
    cp = ensure_company_profile()
    body = f"""
    <h3>Date firmă (Furnizor)</h3>
    <form method="post" action="{url_for('company_save')}" class="card card-body">
      <div class="row">
        <div class="col-md-6 mb-2"><label class="form-label">Denumire *</label><input name="name" class="form-control" value="{cp.name}" required></div>
        <div class="col-md-3 mb-2"><label class="form-label">CUI</label><input name="cui" class="form-control" value="{cp.cui or ''}"></div>
        <div class="col-md-3 mb-2"><label class="form-label">Reg. Com.</label><input name="reg_com" class="form-control" value="{cp.reg_com or ''}"></div>
      </div>

      <div class="mb-2"><label class="form-label">Adresă</label><input name="address" class="form-control" value="{cp.address or ''}"></div>

      <div class="row">
        <div class="col-md-4 mb-2"><label class="form-label">Telefon</label><input name="phone" class="form-control" value="{cp.phone or ''}"></div>
        <div class="col-md-4 mb-2"><label class="form-label">Email</label><input name="email" class="form-control" value="{cp.email or ''}"></div>
        <div class="col-md-4 mb-2"><label class="form-label">Capital social</label><input name="capital_social" class="form-control" value="{cp.capital_social or ''}"></div>
      </div>

      <div class="row">
        <div class="col-md-6 mb-2"><label class="form-label">IBAN</label><input name="iban" class="form-control" value="{cp.iban or ''}"></div>
        <div class="col-md-6 mb-2"><label class="form-label">Bancă</label><input name="bank" class="form-control" value="{cp.bank or ''}"></div>
      </div>

      <div class="row">
        <div class="col-md-3 mb-2">
          <label class="form-label">Plătitor TVA</label>
          <select name="vat_payer" class="form-select">
            <option value="1" {"selected" if cp.vat_payer else ""}>Da</option>
            <option value="0" {"" if cp.vat_payer else "selected"}>Nu</option>
          </select>
        </div>
        <div class="col-md-3 mb-2"><label class="form-label">Serie facturi</label><input name="invoice_series" class="form-control" value="{cp.invoice_series or 'AA'}"></div>
        <div class="col-md-3 mb-2"><label class="form-label">Nr start</label><input name="invoice_start_no" type="number" class="form-control" value="{cp.invoice_start_no or 1}"></div>
        <div class="col-md-3 mb-2"></div>
      </div>

      <div class="mb-2"><label class="form-label">Note footer factură</label><input name="footer_notes" class="form-control" value="{cp.footer_notes or ''}"></div>

      <button class="btn btn-primary">Salvează</button>
    </form>
    """
    return render_page(body, f"{APP_TITLE} — Firmă")


@app.post("/company/save")
@login_required
def company_save():
    cp = ensure_company_profile()
    cp.name = request.form.get("name", "").strip()
    cp.cui = request.form.get("cui", "").strip()
    cp.reg_com = request.form.get("reg_com", "").strip()
    cp.address = request.form.get("address", "").strip()
    cp.phone = request.form.get("phone", "").strip()
    cp.email = request.form.get("email", "").strip()
    cp.capital_social = request.form.get("capital_social", "").strip()
    cp.iban = request.form.get("iban", "").strip()
    cp.bank = request.form.get("bank", "").strip()
    cp.vat_payer = (request.form.get("vat_payer", "1") == "1")
    cp.invoice_series = request.form.get("invoice_series", "AA").strip() or "AA"
    cp.invoice_start_no = int(request.form.get("invoice_start_no", "1") or 1)
    cp.footer_notes = request.form.get("footer_notes", "").strip()
    db.session.commit()
    flash("Date firmă salvate.")
    return redirect(url_for("company"))


# ----------------- App routes (minimal: index/clients/jobs/job detail + invoice) -----------------

@app.get("/")
@login_required
def index():
    open_jobs = Job.query.filter_by(status="OPEN").count()
    clients_count = Client.query.count()
    total_receivable = Decimal("0")
    cur = "RON"
    for j in Job.query.all():
        t = compute_job_totals(j)
        total_receivable += t["receivable"]
        cur = j.currency

    body = f"""
    <div class="row g-3">
      <div class="col-md-4"><div class="card"><div class="card-body"><div class="text-muted">Clienți</div><div class="display-6">{clients_count}</div></div></div></div>
      <div class="col-md-4"><div class="card"><div class="card-body"><div class="text-muted">Lucrări deschise</div><div class="display-6">{open_jobs}</div></div></div></div>
      <div class="col-md-4"><div class="card"><div class="card-body"><div class="text-muted">Total de încasat</div><div class="display-6">{money(total_receivable)} {cur}</div></div></div></div>
    </div>
    """
    return render_page(body, f"{APP_TITLE} — Acasă")


@app.get("/clients")
@login_required
def clients():
    rows = Client.query.order_by(Client.id.desc()).all()
    tr = ""
    for r in rows:
        tr += f"""
        <tr>
          <td class="mono">{r.id}</td><td>{r.name}</td><td>{r.cui or ""}</td><td>{r.reg_com or ""}</td><td>{r.address or ""}</td>
        </tr>
        """
    body = f"""
    <div class="row g-4">
      <div class="col-lg-5">
        <h4>Adaugă client</h4>
        <form method="post" action="{url_for('clients_add')}" class="card card-body">
          <div class="mb-2"><label class="form-label">Denumire *</label><input name="name" class="form-control" required></div>
          <div class="row">
            <div class="col-6 mb-2"><label class="form-label">CUI</label><input name="cui" class="form-control"></div>
            <div class="col-6 mb-2"><label class="form-label">Reg. Com.</label><input name="reg_com" class="form-control"></div>
          </div>
          <div class="mb-2"><label class="form-label">Adresă</label><input name="address" class="form-control"></div>
          <div class="row">
            <div class="col-6 mb-2"><label class="form-label">Telefon</label><input name="phone" class="form-control"></div>
            <div class="col-6 mb-2"><label class="form-label">Email</label><input name="email" class="form-control"></div>
          </div>
          <div class="mb-2"><label class="form-label">Contact</label><input name="contact" class="form-control"></div>
          <button class="btn btn-primary">Salvează</button>
        </form>
      </div>
      <div class="col-lg-7">
        <h4>Clienți</h4>
        <div class="table-responsive">
          <table class="table table-striped align-middle">
            <thead><tr><th>ID</th><th>Denumire</th><th>CUI</th><th>Reg. Com.</th><th>Adresă</th></tr></thead>
            <tbody>{tr or "<tr><td colspan='5' class='text-muted'>Niciun client.</td></tr>"}</tbody>
          </table>
        </div>
      </div>
    </div>
    """
    return render_page(body, f"{APP_TITLE} — Clienți")


@app.post("/clients/add")
@login_required
def clients_add():
    c = Client(
        name=request.form.get("name", "").strip(),
        cui=request.form.get("cui", "").strip() or None,
        reg_com=request.form.get("reg_com", "").strip() or None,
        address=request.form.get("address", "").strip() or None,
        phone=request.form.get("phone", "").strip() or None,
        email=request.form.get("email", "").strip() or None,
        contact=request.form.get("contact", "").strip() or None,
    )
    db.session.add(c)
    db.session.commit()
    flash("Client adăugat.")
    return redirect(url_for("clients"))


@app.get("/jobs")
@login_required
def jobs():
    clients_ = Client.query.order_by(Client.name.asc()).all()
    jobs_ = Job.query.order_by(Job.id.desc()).all()

    opts = '<option value="" selected disabled>Alege...</option>'
    for c in clients_:
        opts += f'<option value="{c.id}">{c.name}</option>'

    tr = ""
    for j in jobs_:
        t = compute_job_totals(j)
        tr += f"""
        <tr>
          <td class="mono">{j.id}</td>
          <td><a href="{url_for('job_detail', job_id=j.id)}">{j.title}</a></td>
          <td>{j.client.name}</td>
          <td>{j.status}</td>
          <td>{money(j.hourly_rate)}</td>
          <td>{pct(d(j.vat_rate))}</td>
          <td><b>{money(t["receivable"])}</b> {j.currency}</td>
        </tr>
        """

    body = f"""
    <div class="row g-4">
      <div class="col-lg-5">
        <h4>Adaugă lucrare</h4>
        <form method="post" action="{url_for('jobs_add')}" class="card card-body">
          <div class="mb-2"><label class="form-label">Client *</label><select name="client_id" class="form-select" required>{opts}</select></div>
          <div class="mb-2"><label class="form-label">Titlu *</label><input name="title" class="form-control" required></div>
          <div class="row">
            <div class="col-6 mb-2"><label class="form-label">Tarif orar *</label><input name="hourly_rate" type="number" step="0.01" class="form-control" required></div>
            <div class="col-6 mb-2"><label class="form-label">TVA (ex: 0.19)</label><input name="vat_rate" type="number" step="0.01" class="form-control" value="0.19"></div>
          </div>
          <div class="mb-2"><label class="form-label">Monedă</label><input name="currency" class="form-control" value="RON"></div>
          <button class="btn btn-primary">Salvează</button>
        </form>
      </div>

      <div class="col-lg-7">
        <h4>Lucrări</h4>
        <div class="table-responsive">
          <table class="table table-striped align-middle">
            <thead><tr><th>ID</th><th>Lucrare</th><th>Client</th><th>Status</th><th>Tarif</th><th>TVA</th><th>De încasat</th></tr></thead>
            <tbody>{tr or "<tr><td colspan='7' class='text-muted'>Nicio lucrare.</td></tr>"}</tbody>
          </table>
        </div>
      </div>
    </div>
    """
    return render_page(body, f"{APP_TITLE} — Lucrări")


@app.post("/jobs/add")
@login_required
def jobs_add():
    j = Job(
        client_id=int(request.form["client_id"]),
        title=request.form.get("title", "").strip(),
        hourly_rate=d(request.form.get("hourly_rate", "0")),
        vat_rate=d(request.form.get("vat_rate", "0.19")),
        currency=request.form.get("currency", "RON").strip() or "RON",
    )
    db.session.add(j)
    db.session.commit()
    flash("Lucrare adăugată.")
    return redirect(url_for("jobs"))


@app.get("/job/<int:job_id>")
@login_required
def job_detail(job_id: int):
    job = Job.query.get_or_404(job_id)
    t = compute_job_totals(job)

    invoices = Invoice.query.filter_by(job_id=job_id).order_by(Invoice.id.desc()).all()
    inv_rows = ""
    for inv in invoices:
        inv_rows += f"<tr><td class='mono'>{inv.inv_no}</td><td>{inv.issue_date}</td><td>{inv.due_date or ''}</td><td><a class='btn btn-sm btn-outline-primary' href='{url_for('invoice_view', invoice_id=inv.id)}'>Vezi/Print</a></td></tr>"
    if not inv_rows:
        inv_rows = "<tr><td colspan='4' class='text-muted'>Nicio factură încă.</td></tr>"

    body = f"""
    <div class="d-flex align-items-center justify-content-between">
      <div>
        <h3 class="mb-0">{job.title}</h3>
        <div class="text-muted">Client: <b>{job.client.name}</b> · TVA: <b>{pct(d(job.vat_rate))}</b> · Monedă: <b>{job.currency}</b></div>
      </div>
      <div class="no-print">
        <a class="btn btn-outline-secondary" href="{url_for('jobs')}">Înapoi</a>
      </div>
    </div>

    <hr/>

    <div class="row g-3">
      <div class="col-md-3"><div class="card"><div class="card-body"><div class="text-muted">Subtotal</div><div class="h4">{money(t["subtotal"])} {job.currency}</div></div></div></div>
      <div class="col-md-3"><div class="card"><div class="card-body"><div class="text-muted">TVA</div><div class="h4">{money(t["vat"])} {job.currency}</div></div></div></div>
      <div class="col-md-3"><div class="card"><div class="card-body"><div class="text-muted">Total</div><div class="h4">{money(t["total"])} {job.currency}</div></div></div></div>
      <div class="col-md-3"><div class="card border-danger"><div class="card-body"><div class="text-muted">De încasat</div><div class="h4 text-danger">{money(t["receivable"])} {job.currency}</div></div></div></div>
    </div>

    <div class="row g-4 mt-2">
      <div class="col-lg-6">
        <h5>Generează factură fiscală</h5>
        <form method="post" action="{url_for('invoice_generate', job_id=job_id)}" class="card card-body">
          <div class="row">
            <div class="col-6 mb-2"><label class="form-label">Data emiterii</label><input name="issue_date" class="form-control" value="{date.today().isoformat()}"></div>
            <div class="col-6 mb-2"><label class="form-label">Scadență</label><input name="due_date" class="form-control" placeholder="YYYY-MM-DD"></div>
          </div>
          <div class="row">
            <div class="col-6 mb-2">
              <label class="form-label">Metodă plată</label>
              <select name="payment_method" class="form-select">
                <option value="OP" selected>OP</option>
                <option value="Cash">Cash</option>
                <option value="Card">Card</option>
              </select>
            </div>
            <div class="col-6 mb-2"><label class="form-label">Loc emitere</label><input name="place" class="form-control" placeholder="ex: București"></div>
          </div>
          <div class="mb-2"><label class="form-label">Note</label><input name="notes" class="form-control" placeholder="Conform deviz / contract..."></div>
          <button class="btn btn-success">Generează</button>
          <div class="small text-muted mt-2">Liniile se generează din manoperă + cheltuieli facturabile.</div>
        </form>
      </div>

      <div class="col-lg-6">
        <h5>Facturi existente</h5>
        <div class="table-responsive">
          <table class="table table-sm table-striped align-middle">
            <thead><tr><th>Nr</th><th>Emitere</th><th>Scadență</th><th></th></tr></thead>
            <tbody>{inv_rows}</tbody>
          </table>
        </div>
      </div>
    </div>
    """
    return render_page(body, f"{APP_TITLE} — {job.title}")


# ----------------- Invoice generation & view -----------------

@app.post("/job/<int:job_id>/invoice/generate")
@login_required
def invoice_generate(job_id: int):
    job = Job.query.get_or_404(job_id)
    cp = ensure_company_profile()

    series = (cp.invoice_series or "AA").strip()
    number = next_invoice_number(series)
    inv_no = make_inv_no(series, number)

    issue_date = request.form.get("issue_date", date.today().isoformat()).strip()
    due_date = request.form.get("due_date", "").strip() or None
    payment_method = request.form.get("payment_method", "OP").strip() or "OP"
    place = request.form.get("place", "").strip() or ""
    notes = request.form.get("notes", "").strip() or ""

    inv = Invoice(
        job_id=job_id,
        series=series,
        number=number,
        inv_no=inv_no,
        issue_date=issue_date,
        due_date=due_date,
        payment_method=payment_method,
        place=place,
        notes=notes,
    )
    db.session.add(inv)
    db.session.flush()  # inv.id

    totals = compute_job_totals(job)

    # Linie manoperă (cantitate = ore, preț = medie)
    if totals["labor_total"] > 0:
        hours = totals["labor_hours"] if totals["labor_hours"] > 0 else Decimal("0")
        unit_price = (totals["labor_total"] / hours) if hours > 0 else totals["labor_total"]
        db.session.add(
            InvoiceLine(
                invoice_id=inv.id,
                line_type="LABOR",
                description="Manoperă (ore lucrate)",
                qty=hours,
                unit="ore",
                unit_price=unit_price,
                line_total=totals["labor_total"],
            )
        )

    # Linii materiale/cheltuieli facturabile
    exps = Expense.query.filter_by(job_id=job_id).all()
    for e in exps:
        if not e.billable:
            continue
        unit_price = d(e.unit_cost) * (Decimal("1") + d(e.markup_percent) / Decimal("100"))
        line_total = d(e.qty) * unit_price
        db.session.add(
            InvoiceLine(
                invoice_id=inv.id,
                line_type="EXPENSE",
                description=e.description,
                qty=d(e.qty),
                unit=e.unit,
                unit_price=unit_price,
                line_total=line_total,
            )
        )

    db.session.commit()
    flash(f"Factură fiscală generată: {inv_no}")
    return redirect(url_for("invoice_view", invoice_id=inv.id))


@app.get("/invoice/<int:invoice_id>")
@login_required
def invoice_view(invoice_id: int):
    inv = Invoice.query.get_or_404(invoice_id)
    job = Job.query.get_or_404(inv.job_id)
    client = job.client
    cp = ensure_company_profile()

    lines = InvoiceLine.query.filter_by(invoice_id=invoice_id).all()

    subtotal = sum([d(l.line_total) for l in lines], Decimal("0"))
    vat_rate = d(job.vat_rate) if cp.vat_payer else Decimal("0")
    vat = subtotal * vat_rate
    total = subtotal + vat

    rows = ""
    i = 1
    for l in lines:
        rows += f"""
        <tr>
          <td class="text-muted">{i}</td>
          <td>{l.description}</td>
          <td class="text-end">{money(l.qty)}</td>
          <td>{l.unit}</td>
          <td class="text-end">{money(l.unit_price)}</td>
          <td class="text-end">{money(l.line_total)}</td>
        </tr>
        """
        i += 1

    vat_label = pct(vat_rate) if cp.vat_payer else "NEPLĂTITOR TVA"

    body = f"""
    <div class="no-print d-flex justify-content-between align-items-center mb-3">
      <a class="btn btn-outline-secondary" href="{url_for('job_detail', job_id=job.id)}">Înapoi la lucrare</a>
      <button class="btn btn-primary" onclick="window.print()">Print / Save as PDF</button>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="d-flex justify-content-between">
          <div>
            <h3 class="mb-0">FACTURĂ FISCALĂ</h3>
            <div class="text-muted">Serie: <span class="mono">{inv.series}</span> · Număr: <span class="mono">{inv.number}</span></div>
            <div class="text-muted">Nr complet: <span class="mono">{inv.inv_no}</span></div>
            <div class="text-muted">Data emiterii: {inv.issue_date}</div>
            <div class="text-muted">Scadență: {inv.due_date or "-"}</div>
            <div class="text-muted">Metodă plată: {inv.payment_method}</div>
            <div class="text-muted">Loc emitere: {inv.place or "-"}</div>
          </div>
          <div class="text-end">
            <div class="fw-bold">{job.currency}</div>
            <div class="text-muted">TVA: {vat_label}</div>
          </div>
        </div>

        <hr/>

        <div class="row">
          <div class="col-md-6">
            <div class="fw-bold mb-1">Furnizor</div>
            <div>{cp.name}</div>
            <div class="small text-muted">CUI: {cp.cui or "-"} · Reg. Com.: {cp.reg_com or "-"}</div>
            <div class="small text-muted">{cp.address or ""}</div>
            <div class="small text-muted">{cp.phone or ""} {cp.email or ""}</div>
            <div class="small text-muted">IBAN: {cp.iban or "-"} · Bancă: {cp.bank or "-"}</div>
            <div class="small text-muted">Capital social: {cp.capital_social or "-"}</div>
          </div>

          <div class="col-md-6 text-end">
            <div class="fw-bold mb-1">Cumpărător</div>
            <div>{client.name}</div>
            <div class="small text-muted">CUI: {client.cui or "-"} · Reg. Com.: {client.reg_com or "-"}</div>
            <div class="small text-muted">{client.address or ""}</div>
            <div class="small text-muted">{client.phone or ""} {client.email or ""}</div>
            <div class="small text-muted">Contact: {client.contact or "-"}</div>
          </div>
        </div>

        <hr/>

        <div class="table-responsive">
          <table class="table table-sm">
            <thead>
              <tr>
                <th>#</th>
                <th>Descriere</th>
                <th class="text-end">Cant</th>
                <th>UM</th>
                <th class="text-end">Preț (fără TVA)</th>
                <th class="text-end">Valoare (fără TVA)</th>
              </tr>
            </thead>
            <tbody>
              {rows or "<tr><td colspan='6' class='text-muted'>Nicio linie.</td></tr>"}
            </tbody>
          </table>
        </div>

        <div class="row mt-3">
          <div class="col-md-6">
            <div class="small text-muted">{inv.notes or ""}</div>
            <div class="small text-muted">{cp.footer_notes or ""}</div>
          </div>
          <div class="col-md-6">
            <table class="table table-sm">
              <tr><td class="text-end">Subtotal (fără TVA)</td><td class="text-end">{money(subtotal)} {job.currency}</td></tr>
              <tr><td class="text-end">TVA ({vat_label})</td><td class="text-end">{money(vat)} {job.currency}</td></tr>
              <tr class="fw-bold"><td class="text-end">TOTAL</td><td class="text-end">{money(total)} {job.currency}</td></tr>
            </table>
          </div>
        </div>

        <div class="row mt-4">
          <div class="col-6">
            <div class="small text-muted">Semnătură furnizor: ____________________</div>
          </div>
          <div class="col-6 text-end">
            <div class="small text-muted">Semnătură client: ____________________</div>
          </div>
        </div>

      </div>
    </div>
    """
    return render_page(body, f"Factura {inv.inv_no}")


@app.get("/receivables")
@login_required
def receivables():
    jobs = Job.query.order_by(Job.id.desc()).all()
    tr = ""
    total_all = Decimal("0")
    cur = "RON"
    for j in jobs:
        t = compute_job_totals(j)
        total_all += t["receivable"]
        cur = j.currency
        tr += f"""
        <tr>
          <td class="mono">{j.id}</td>
          <td><a href="{url_for('job_detail', job_id=j.id)}">{j.title}</a></td>
          <td>{j.client.name}</td>
          <td>{j.status}</td>
          <td class="text-end">{money(t["total"])} {cur}</td>
          <td class="text-end">{money(t["paid"])} {cur}</td>
          <td class="text-end"><b>{money(t["receivable"])} {cur}</b></td>
        </tr>
        """

    body = f"""
    <div class="d-flex align-items-center justify-content-between">
      <h3 class="mb-0">De încasat</h3>
      <div class="h5 mb-0">Total: <span class="text-danger">{money(total_all)} {cur}</span></div>
    </div>
    <hr/>
    <div class="table-responsive">
      <table class="table table-striped align-middle">
        <thead><tr><th>ID</th><th>Lucrare</th><th>Client</th><th>Status</th><th class="text-end">Total</th><th class="text-end">Plătit</th><th class="text-end">De încasat</th></tr></thead>
        <tbody>{tr or "<tr><td colspan='7' class='text-muted'>Nimic.</td></tr>"}</tbody>
      </table>
    </div>
    """
    return render_page(body, f"{APP_TITLE} — De încasat")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
# alias pentru gunicorn: app:app
try:
    app
except NameError:
    app = locals().get("application") or locals().get("server")

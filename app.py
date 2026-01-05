from __future__ import annotations

import os
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

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
    """Acceptă 100,50 / 100.50 / 1.234,56 / 1 234,56."""
    s = str(x or "0").strip()
    s = s.replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def money(x) -> str:
    if x is None:
        return "0.00"
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return f"{x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def pct(x: Decimal) -> str:
    return f"{(x * Decimal('100')).quantize(Decimal('0'), rounding=ROUND_HALF_UP)}%"


# ----------------- Models -----------------

class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")  # admin/user


class CompanyProfile(db.Model):
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
    vat_payer = db.Column(db.Boolean, default=True)
    invoice_series = db.Column(db.String(20), default="AA")
    invoice_start_no = db.Column(db.Integer, default=1)
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
    inv_no = db.Column(db.String(50), unique=True, nullable=False)

    issue_date = db.Column(db.String(20), nullable=False)
    due_date = db.Column(db.String(20))
    payment_method = db.Column(db.String(50), default="OP")
    place = db.Column(db.String(100), default="")
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
        "exp_billable_total": exp_billable_total,
        "subtotal": subtotal,
        "vat": vat,
        "total": total,
        "paid": paid,
        "receivable": receivable,
    }


def next_invoice_number(series: str) -> int:
    year = date.today().year
    last = (
        Invoice.query.filter_by(series=series)
        .filter(Invoice.inv_no.like(f"{series}-{year}-%"))
        .order_by(Invoice.number.desc())
        .first()
    )
    cp = ensure_company_profile()
    if not last:
        return int(cp.invoice_start_no or 1)
    return int(last.number) + 1


def make_inv_no(series: str, number: int) -> str:
    year = date.today().year
    return f"{series}-{year}-{number:04d}"


# ----------------- UI Base -----------------

BASE_HTML = """
<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>

  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">

  <style>
    body { background: #f7f7fb; }
    .mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
    .card { border: 0; box-shadow: 0 6px 18px rgba(0,0,0,.06); border-radius: 14px; }
    .btn { border-radius: 12px; }
    .table { margin-bottom: 0; }
    .table thead th { font-size: .85rem; color: #6c757d; font-weight: 600; }
    .sidebar { width: 260px; }
    .sidebar .nav-link { border-radius: 12px; padding: .55rem .75rem; color: #212529; }
    .sidebar .nav-link.active { background: #111827; color: white; }
    .content { padding: 22px; }
    .search-input { border-radius: 12px; }
    .pill { border-radius: 999px; padding: .25rem .6rem; border: 1px solid rgba(0,0,0,.08); background: #fff; font-size: .9rem; }
    @media (max-width: 991px) { .sidebar { width: 100%; } .content { padding: 14px; } }
    @media print {
      .no-print { display:none !important; }
      body { background: white; }
      .card { box-shadow: none; }
    }
  </style>
</head>

<body>

<nav class="navbar navbar-dark bg-dark sticky-top no-print">
  <div class="container-fluid">
    <button class="btn btn-dark d-lg-none" data-bs-toggle="offcanvas" data-bs-target="#offcanvasMenu">
      <i class="bi bi-list"></i>
    </button>

    <a class="navbar-brand d-flex align-items-center ms-2" href="{{ url_for('index') }}">
      <img src="{{ url_for('static', filename='logo.png') }}" onerror="this.style.display='none'" alt="Logo" height="26" class="me-2">
      <i class="bi bi-clipboard-check me-2"></i>
      {{ app_title }}
    </a>

    <div class="d-flex align-items-center gap-2">
      {% if current_user.is_authenticated %}
        <span class="text-white-50 small d-none d-md-inline">Autentificat: <b class="text-white">{{ current_user.username }}</b></span>
        <a class="btn btn-outline-light btn-sm" href="{{ url_for('logout') }}"><i class="bi bi-box-arrow-right me-1"></i>Logout</a>
      {% endif %}
    </div>
  </div>
</nav>

<div class="container-fluid">
  <div class="row g-3">
    <!-- Sidebar desktop -->
    <div class="col-lg-3 d-none d-lg-block no-print">
      <div class="p-3 sidebar">
        <div class="card">
          <div class="card-body">
            <div class="nav flex-column gap-1">
              <a class="nav-link {% if request.path == '/' %}active{% endif %}" href="{{ url_for('index') }}">
                <i class="bi bi-speedometer2 me-2"></i>Dashboard
              </a>
              <a class="nav-link {% if request.path.startswith('/clients') %}active{% endif %}" href="{{ url_for('clients') }}">
                <i class="bi bi-people me-2"></i>Clienți
              </a>
              <a class="nav-link {% if request.path.startswith('/jobs') or request.path.startswith('/job/') %}active{% endif %}" href="{{ url_for('jobs') }}">
                <i class="bi bi-briefcase me-2"></i>Lucrări
              </a>
              <a class="nav-link {% if request.path.startswith('/receivables') %}active{% endif %}" href="{{ url_for('receivables') }}">
                <i class="bi bi-cash-coin me-2"></i>De încasat
              </a>
              <a class="nav-link {% if request.path.startswith('/company') %}active{% endif %}" href="{{ url_for('company') }}">
                <i class="bi bi-building me-2"></i>Firmă
              </a>
            </div>
          </div>
        </div>

        <div class="small text-muted mt-3">
          Tip: la sume poți scrie <span class="mono">100,50</span> sau <span class="mono">100.50</span>.
        </div>
      </div>
    </div>

    <!-- Offcanvas menu mobil -->
    <div class="offcanvas offcanvas-start no-print" tabindex="-1" id="offcanvasMenu">
      <div class="offcanvas-header">
        <h5 class="offcanvas-title">{{ app_title }}</h5>
        <button type="button" class="btn-close" data-bs-dismiss="offcanvas"></button>
      </div>
      <div class="offcanvas-body">
        <div class="nav flex-column gap-1">
          <a class="nav-link" href="{{ url_for('index') }}"><i class="bi bi-speedometer2 me-2"></i>Dashboard</a>
          <a class="nav-link" href="{{ url_for('clients') }}"><i class="bi bi-people me-2"></i>Clienți</a>
          <a class="nav-link" href="{{ url_for('jobs') }}"><i class="bi bi-briefcase me-2"></i>Lucrări</a>
          <a class="nav-link" href="{{ url_for('receivables') }}"><i class="bi bi-cash-coin me-2"></i>De încasat</a>
          <a class="nav-link" href="{{ url_for('company') }}"><i class="bi bi-building me-2"></i>Firmă</a>
        </div>
      </div>
    </div>

    <!-- Content -->
    <div class="col-lg-9">
      <div class="content">

        {% with messages = get_flashed_messages() %}
          {% if messages %}
            <div class="toast-container position-fixed top-0 end-0 p-3 no-print" style="z-index:1100;">
              <div class="toast show" role="alert">
                <div class="toast-header">
                  <i class="bi bi-info-circle me-2"></i>
                  <strong class="me-auto">Info</strong>
                  <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
                </div>
                <div class="toast-body">{{ messages[0] }}</div>
              </div>
            </div>
          {% endif %}
        {% endwith %}

        {{ body|safe }}
      </div>
    </div>
  </div>
</div>

<!-- Confirm delete modal -->
<div class="modal fade no-print" id="confirmDeleteModal" tabindex="-1">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title"><i class="bi bi-exclamation-triangle me-2"></i>Confirmare</h5>
        <button class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">Sigur vrei să ștergi? Acțiunea nu poate fi anulată.</div>
      <div class="modal-footer">
        <button class="btn btn-light" data-bs-dismiss="modal">Renunță</button>
        <a class="btn btn-danger" id="confirmDeleteBtn" href="#">Șterge</a>
      </div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>

<script>
  // Confirm delete (linkuri cu data-confirm="delete")
  const deleteModal = new bootstrap.Modal(document.getElementById('confirmDeleteModal'));
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[data-confirm="delete"]');
    if (!a) return;
    e.preventDefault();
    document.getElementById('confirmDeleteBtn').href = a.href;
    deleteModal.show();
  });

  // Table search (input data-table-search="#tableId")
  document.addEventListener('input', (e) => {
    const inp = e.target.closest('input[data-table-search]');
    if (!inp) return;
    const table = document.querySelector(inp.getAttribute('data-table-search'));
    if (!table) return;
    const q = inp.value.toLowerCase().trim();
    table.querySelectorAll('tbody tr').forEach(tr => {
      tr.style.display = tr.innerText.toLowerCase().includes(q) ? '' : 'none';
    });
  });

  // Normalize decimal inputs on submit (100,50 -> 100.50 ; 1.234,56 -> 1234.56)
  function normalizeDecimal(s) {
    if (!s) return s;
    s = s.replaceAll(' ', '');
    if (s.includes(',') && s.includes('.')) {
      s = s.replaceAll('.', '').replaceAll(',', '.');
    } else {
      s = s.replaceAll(',', '.');
    }
    return s;
  }

  document.addEventListener('submit', (e) => {
    const form = e.target.closest('form');
    if (!form) return;
    form.querySelectorAll('input[data-decimal]').forEach(inp => {
      inp.value = normalizeDecimal(inp.value);
    });
  });
</script>

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
        request=request,
    )


@app.before_request
def setup_once():
    db.create_all()
    ensure_seed_users()
    ensure_company_profile()


# ----------------- Routes: Auth -----------------

@app.get("/login")
def login():
    body = """
    <div class="row justify-content-center">
      <div class="col-md-6 col-lg-5">
        <div class="card">
          <div class="card-body">
            <h3 class="mb-1">Autentificare</h3>
            <div class="text-muted mb-3">Intră în aplicație</div>
            <form method="post" action="/login">
              <div class="mb-2">
                <label class="form-label">User</label>
                <input name="username" class="form-control" required>
              </div>
              <div class="mb-3">
                <label class="form-label">Parolă</label>
                <input name="password" type="password" class="form-control" required>
              </div>
              <button class="btn btn-dark w-100"><i class="bi bi-box-arrow-in-right me-1"></i>Intră</button>
            </form>
          </div>
        </div>
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


# ----------------- Dashboard -----------------

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
    <div class="d-flex align-items-center justify-content-between mb-3">
      <div>
        <h2 class="mb-0">Dashboard</h2>
        <div class="text-muted">Privire rapidă peste firmă</div>
      </div>
      <div class="no-print d-flex gap-2">
        <a class="btn btn-dark" href="{url_for('jobs')}"><i class="bi bi-plus-lg me-1"></i>Lucrare nouă</a>
        <a class="btn btn-outline-dark" href="{url_for('clients')}"><i class="bi bi-person-plus me-1"></i>Client</a>
      </div>
    </div>

    <div class="row g-3">
      <div class="col-md-4">
        <div class="card"><div class="card-body">
          <div class="text-muted">Clienți</div>
          <div class="display-6">{clients_count}</div>
        </div></div>
      </div>
      <div class="col-md-4">
        <div class="card"><div class="card-body">
          <div class="text-muted">Lucrări deschise</div>
          <div class="display-6">{open_jobs}</div>
        </div></div>
      </div>
      <div class="col-md-4">
        <div class="card border-0"><div class="card-body">
          <div class="text-muted">Total de încasat</div>
          <div class="display-6 text-danger">{money(total_receivable)} {cur}</div>
        </div></div>
      </div>
    </div>
    """
    return render_page(body, f"{APP_TITLE} — Dashboard")


# ----------------- Company -----------------

@app.get("/company")
@login_required
def company():
    cp = ensure_company_profile()
    body = f"""
    <div class="d-flex align-items-center justify-content-between mb-3">
      <div>
        <h2 class="mb-0">Firmă</h2>
        <div class="text-muted">Date furnizor pentru factură</div>
      </div>
    </div>

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
      </div>

      <div class="mb-2"><label class="form-label">Note footer factură</label><input name="footer_notes" class="form-control" value="{cp.footer_notes or ''}"></div>

      <button class="btn btn-dark"><i class="bi bi-save me-1"></i>Salvează</button>
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


# ----------------- Clients -----------------

@app.get("/clients")
@login_required
def clients():
    rows = Client.query.order_by(Client.id.desc()).all()
    tr = ""
    for r in rows:
        tr += f"""
        <tr>
          <td class="mono">{r.id}</td>
          <td>{r.name}</td>
          <td>{r.cui or ""}</td>
          <td class="text-muted small">{(r.address or "")}</td>
        </tr>
        """

    body = f"""
    <div class="d-flex align-items-center justify-content-between mb-3">
      <div>
        <h2 class="mb-0">Clienți</h2>
        <div class="text-muted">Gestionare clienți</div>
      </div>
      <div class="no-print">
        <button class="btn btn-dark" data-bs-toggle="modal" data-bs-target="#modalClient">
          <i class="bi bi-person-plus me-1"></i>Adaugă client
        </button>
      </div>
    </div>

    <div class="card mb-3">
      <div class="card-body">
        <input class="form-control search-input" placeholder="Caută client…" data-table-search="#clientsTable">
      </div>
    </div>

    <div class="card">
      <div class="card-body table-responsive">
        <table class="table table-striped align-middle" id="clientsTable">
          <thead><tr><th>ID</th><th>Denumire</th><th>CUI</th><th>Adresă</th></tr></thead>
          <tbody>{tr or "<tr><td colspan='4' class='text-muted'>Niciun client.</td></tr>"}</tbody>
        </table>
      </div>
    </div>

    <!-- Modal add client -->
    <div class="modal fade no-print" id="modalClient" tabindex="-1">
      <div class="modal-dialog modal-dialog-centered modal-lg">
        <form class="modal-content" method="post" action="{url_for('clients_add')}">
          <div class="modal-header">
            <h5 class="modal-title"><i class="bi bi-person-plus me-2"></i>Adaugă client</h5>
            <button class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="row">
              <div class="col-md-8 mb-2"><label class="form-label">Denumire *</label><input name="name" class="form-control" required></div>
              <div class="col-md-4 mb-2"><label class="form-label">CUI</label><input name="cui" class="form-control"></div>
            </div>
            <div class="row">
              <div class="col-md-6 mb-2"><label class="form-label">Reg. Com.</label><input name="reg_com" class="form-control"></div>
              <div class="col-md-6 mb-2"><label class="form-label">Contact</label><input name="contact" class="form-control"></div>
            </div>
            <div class="mb-2"><label class="form-label">Adresă</label><input name="address" class="form-control"></div>
            <div class="row">
              <div class="col-md-6 mb-2"><label class="form-label">Telefon</label><input name="phone" class="form-control"></div>
              <div class="col-md-6 mb-2"><label class="form-label">Email</label><input name="email" class="form-control"></div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-light" data-bs-dismiss="modal">Renunță</button>
            <button class="btn btn-dark">Salvează</button>
          </div>
        </form>
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
        contact=request.form.get("contact", "").strip() or None,
        phone=request.form.get("phone", "").strip() or None,
        email=request.form.get("email", "").strip() or None,
    )
    db.session.add(c)
    db.session.commit()
    flash("Client adăugat.")
    return redirect(url_for("clients"))


# ----------------- Jobs -----------------

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
        badge = "bg-success" if j.status == "OPEN" else "bg-secondary"
        tr += f"""
        <tr>
          <td class="mono">{j.id}</td>
          <td>
            <div class="fw-semibold"><a href="{url_for('job_detail', job_id=j.id)}">{j.title}</a></div>
            <div class="text-muted small">{j.client.name}</div>
          </td>
          <td><span class="badge {badge}">{j.status}</span></td>
          <td class="text-end">{money(d(j.hourly_rate))}</td>
          <td class="text-end">{pct(d(j.vat_rate))}</td>
          <td class="text-end"><span class="pill text-danger fw-semibold">{money(t["receivable"])} {j.currency}</span></td>
        </tr>
        """

    body = f"""
    <div class="d-flex align-items-center justify-content-between mb-3">
      <div>
        <h2 class="mb-0">Lucrări</h2>
        <div class="text-muted">Pontaje, materiale, plăți și facturi</div>
      </div>
      <div class="no-print">
        <button class="btn btn-dark" data-bs-toggle="modal" data-bs-target="#modalJob">
          <i class="bi bi-plus-lg me-1"></i>Lucrare nouă
        </button>
      </div>
    </div>

    <div class="card mb-3">
      <div class="card-body">
        <input class="form-control search-input" placeholder="Caută lucrare/client…" data-table-search="#jobsTable">
      </div>
    </div>

    <div class="card">
      <div class="card-body table-responsive">
        <table class="table table-striped align-middle" id="jobsTable">
          <thead>
            <tr>
              <th>ID</th><th>Lucrare</th><th>Status</th>
              <th class="text-end">Tarif</th><th class="text-end">TVA</th><th class="text-end">De încasat</th>
            </tr>
          </thead>
          <tbody>{tr or "<tr><td colspan='6' class='text-muted'>Nicio lucrare.</td></tr>"}</tbody>
        </table>
      </div>
    </div>

    <!-- Modal add job -->
    <div class="modal fade no-print" id="modalJob" tabindex="-1">
      <div class="modal-dialog modal-dialog-centered modal-lg">
        <form class="modal-content" method="post" action="{url_for('jobs_add')}">
          <div class="modal-header">
            <h5 class="modal-title"><i class="bi bi-briefcase me-2"></i>Adaugă lucrare</h5>
            <button class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="row">
              <div class="col-md-7 mb-2">
                <label class="form-label">Client *</label>
                <select name="client_id" class="form-select" required>{opts}</select>
              </div>
              <div class="col-md-5 mb-2">
                <label class="form-label">Titlu lucrare *</label>
                <input name="title" class="form-control" required>
              </div>
            </div>
            <div class="row">
              <div class="col-md-4 mb-2"><label class="form-label">Tarif orar *</label><input name="hourly_rate" class="form-control" inputmode="decimal" data-decimal required placeholder="ex: 150,00"></div>
              <div class="col-md-4 mb-2"><label class="form-label">TVA</label><input name="vat_rate" class="form-control" inputmode="decimal" data-decimal value="0.19" placeholder="0.19"></div>
              <div class="col-md-4 mb-2"><label class="form-label">Monedă</label><input name="currency" class="form-control" value="RON"></div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-light" data-bs-dismiss="modal">Renunță</button>
            <button class="btn btn-dark">Salvează</button>
          </div>
        </form>
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


# ----------------- Job detail (TAB-uri + Modale) -----------------

@app.get("/job/<int:job_id>")
@login_required
def job_detail(job_id: int):
    job = Job.query.get_or_404(job_id)
    cp = ensure_company_profile()
    t = compute_job_totals(job)

    times = Timesheet.query.filter_by(job_id=job_id).order_by(Timesheet.work_date.desc(), Timesheet.id.desc()).all()
    exps = Expense.query.filter_by(job_id=job_id).order_by(Expense.exp_date.desc(), Expense.id.desc()).all()
    pays = Payment.query.filter_by(job_id=job_id).order_by(Payment.pay_date.desc(), Payment.id.desc()).all()
    invoices = Invoice.query.filter_by(job_id=job_id).order_by(Invoice.id.desc()).all()

    status_badge = "bg-success" if job.status == "OPEN" else "bg-secondary"

    # rows
    ts_rows = ""
    for r in times:
        rate = money(d(r.rate_override)) if r.rate_override is not None else ""
        ts_rows += f"""
        <tr>
          <td>{r.work_date}</td>
          <td>{r.worker or ""}</td>
          <td class="text-muted small">{r.task or ""}</td>
          <td class="text-end">{money(d(r.hours))}</td>
          <td class="text-end">{rate}</td>
          <td class="text-end">
            <a class="btn btn-sm btn-outline-danger" data-confirm="delete" href="{url_for('delete_time', job_id=job_id, ts_id=r.id)}">
              <i class="bi bi-trash"></i>
            </a>
          </td>
        </tr>
        """
    if not ts_rows:
        ts_rows = "<tr><td colspan='6' class='text-muted'>Nu ai pontaje încă. Apasă „Adaugă pontaj”.</td></tr>"

    exp_rows = ""
    for r in exps:
        exp_rows += f"""
        <tr>
          <td>{r.exp_date}</td>
          <td>{r.category or ""}</td>
          <td class="text-muted small">{r.description}</td>
          <td class="text-end">{money(d(r.qty))}</td>
          <td>{r.unit}</td>
          <td class="text-end">{money(d(r.unit_cost))}</td>
          <td class="text-end">{money(d(r.markup_percent))}%</td>
          <td><span class="badge {'bg-success' if r.billable else 'bg-secondary'}">{'DA' if r.billable else 'NU'}</span></td>
          <td class="text-end">
            <a class="btn btn-sm btn-outline-danger" data-confirm="delete" href="{url_for('delete_exp', job_id=job_id, exp_id=r.id)}">
              <i class="bi bi-trash"></i>
            </a>
          </td>
        </tr>
        """
    if not exp_rows:
        exp_rows = "<tr><td colspan='9' class='text-muted'>Nu ai materiale/cheltuieli încă. Apasă „Adaugă material”.</td></tr>"

    pay_rows = ""
    for r in pays:
        pay_rows += f"""
        <tr>
          <td>{r.pay_date}</td>
          <td class="text-end fw-semibold">{money(d(r.amount))}</td>
          <td>{r.method or ""}</td>
          <td class="text-muted small">{r.notes or ""}</td>
          <td class="text-end">
            <a class="btn btn-sm btn-outline-danger" data-confirm="delete" href="{url_for('delete_pay', job_id=job_id, pay_id=r.id)}">
              <i class="bi bi-trash"></i>
            </a>
          </td>
        </tr>
        """
    if not pay_rows:
        pay_rows = "<tr><td colspan='5' class='text-muted'>Nu ai plăți încă. Apasă „Adaugă plată”.</td></tr>"

    inv_rows = ""
    for inv in invoices:
        inv_rows += f"""
        <tr>
          <td class="mono">{inv.inv_no}</td>
          <td>{inv.issue_date}</td>
          <td>{inv.due_date or ""}</td>
          <td>{inv.payment_method or ""}</td>
          <td class="text-end">
            <a class="btn btn-sm btn-outline-primary" href="{url_for('invoice_view', invoice_id=inv.id)}">
              <i class="bi bi-printer me-1"></i>Vezi/Print
            </a>
          </td>
        </tr>
        """
    if not inv_rows:
        inv_rows = "<tr><td colspan='5' class='text-muted'>Nu ai facturi încă. Apasă „Generează factură”.</td></tr>"

    body = f"""
    <div class="d-flex align-items-start justify-content-between mb-3">
      <div>
        <div class="d-flex align-items-center gap-2">
          <h2 class="mb-0">{job.title}</h2>
          <span class="badge {status_badge}">{job.status}</span>
        </div>
        <div class="text-muted">
          Client: <b>{job.client.name}</b> · TVA: <b>{pct(d(job.vat_rate))}</b> · Monedă: <b>{job.currency}</b>
        </div>
      </div>
      <div class="no-print d-flex gap-2">
        <a class="btn btn-outline-dark" href="{url_for('jobs')}"><i class="bi bi-arrow-left me-1"></i>Înapoi</a>
        <a class="btn btn-dark" href="{url_for('toggle_job', job_id=job_id)}"><i class="bi bi-arrow-repeat me-1"></i>OPEN/CLOSED</a>
      </div>
    </div>

    <div class="row g-3 mb-3">
      <div class="col-md-3"><div class="card"><div class="card-body"><div class="text-muted">Subtotal</div><div class="h4 mb-0">{money(t["subtotal"])} {job.currency}</div></div></div></div>
      <div class="col-md-3"><div class="card"><div class="card-body"><div class="text-muted">TVA</div><div class="h4 mb-0">{money(t["vat"])} {job.currency}</div></div></div></div>
      <div class="col-md-3"><div class="card"><div class="card-body"><div class="text-muted">Total</div><div class="h4 mb-0">{money(t["total"])} {job.currency}</div></div></div></div>
      <div class="col-md-3"><div class="card"><div class="card-body"><div class="text-muted">De încasat</div><div class="h4 mb-0 text-danger">{money(t["receivable"])} {job.currency}</div></div></div></div>
    </div>

    <ul class="nav nav-pills gap-2 no-print" role="tablist">
      <li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#tabPontaj"><i class="bi bi-clock me-1"></i>Pontaj</button></li>
      <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tabMateriale"><i class="bi bi-box-seam me-1"></i>Materiale</button></li>
      <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tabPlati"><i class="bi bi-cash-coin me-1"></i>Plăți</button></li>
      <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tabFacturi"><i class="bi bi-receipt me-1"></i>Facturi</button></li>
    </ul>

    <div class="tab-content mt-3">
      <!-- Pontaj -->
      <div class="tab-pane fade show active" id="tabPontaj">
        <div class="card mb-3">
          <div class="card-body d-flex justify-content-between align-items-center gap-2">
            <input class="form-control search-input" placeholder="Caută în pontaj…" data-table-search="#tsTable">
            <button class="btn btn-dark no-print" data-bs-toggle="modal" data-bs-target="#modalPontaj"><i class="bi bi-plus-lg me-1"></i>Adaugă pontaj</button>
          </div>
        </div>
        <div class="card">
          <div class="card-body table-responsive">
            <table class="table table-striped align-middle" id="tsTable">
              <thead><tr><th>Data</th><th>Muncitor</th><th>Activitate</th><th class="text-end">Ore</th><th class="text-end">Override</th><th class="text-end"></th></tr></thead>
              <tbody>{ts_rows}</tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Materiale -->
      <div class="tab-pane fade" id="tabMateriale">
        <div class="card mb-3">
          <div class="card-body d-flex justify-content-between align-items-center gap-2">
            <input class="form-control search-input" placeholder="Caută în materiale…" data-table-search="#expTable">
            <button class="btn btn-dark no-print" data-bs-toggle="modal" data-bs-target="#modalExp"><i class="bi bi-plus-lg me-1"></i>Adaugă material</button>
          </div>
        </div>
        <div class="card">
          <div class="card-body table-responsive">
            <table class="table table-striped align-middle" id="expTable">
              <thead><tr><th>Data</th><th>Cat.</th><th>Descriere</th><th class="text-end">Cant</th><th>UM</th><th class="text-end">Cost</th><th class="text-end">Adaos</th><th>Fact</th><th class="text-end"></th></tr></thead>
              <tbody>{exp_rows}</tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Plăți -->
      <div class="tab-pane fade" id="tabPlati">
        <div class="card mb-3">
          <div class="card-body d-flex justify-content-between align-items-center gap-2">
            <input class="form-control search-input" placeholder="Caută în plăți…" data-table-search="#payTable">
            <button class="btn btn-dark no-print" data-bs-toggle="modal" data-bs-target="#modalPay"><i class="bi bi-plus-lg me-1"></i>Adaugă plată</button>
          </div>
        </div>
        <div class="card">
          <div class="card-body table-responsive">
            <table class="table table-striped align-middle" id="payTable">
              <thead><tr><th>Data</th><th class="text-end">Suma</th><th>Metodă</th><th>Note</th><th class="text-end"></th></tr></thead>
              <tbody>{pay_rows}</tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Facturi -->
      <div class="tab-pane fade" id="tabFacturi">
        <div class="card mb-3">
          <div class="card-body d-flex justify-content-between align-items-center gap-2">
            <input class="form-control search-input" placeholder="Caută în facturi…" data-table-search="#invTable">
            <button class="btn btn-success no-print" data-bs-toggle="modal" data-bs-target="#modalInv"><i class="bi bi-receipt me-1"></i>Generează factură</button>
          </div>
        </div>
        <div class="card">
          <div class="card-body table-responsive">
            <table class="table table-striped align-middle" id="invTable">
              <thead><tr><th>Nr</th><th>Emitere</th><th>Scadență</th><th>Plată</th><th class="text-end"></th></tr></thead>
              <tbody>{inv_rows}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- MODAL Pontaj -->
    <div class="modal fade no-print" id="modalPontaj" tabindex="-1">
      <div class="modal-dialog modal-dialog-centered modal-lg">
        <form class="modal-content" method="post" action="{url_for('add_time', job_id=job_id)}">
          <div class="modal-header">
            <h5 class="modal-title"><i class="bi bi-clock me-2"></i>Adaugă pontaj</h5>
            <button class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="row">
              <div class="col-md-4 mb-2"><label class="form-label">Data</label><input name="work_date" class="form-control" value="{date.today().isoformat()}"></div>
              <div class="col-md-4 mb-2"><label class="form-label">Muncitor</label><input name="worker" class="form-control"></div>
              <div class="col-md-4 mb-2"><label class="form-label">Ore *</label><input name="hours" class="form-control" inputmode="decimal" data-decimal required placeholder="ex: 5,5"></div>
            </div>
            <div class="mb-2"><label class="form-label">Activitate</label><input name="task" class="form-control"></div>
            <div class="mb-2"><label class="form-label">Tarif override (opțional)</label><input name="rate_override" class="form-control" inputmode="decimal" data-decimal placeholder="ex: 180,00"></div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-light" data-bs-dismiss="modal">Renunță</button>
            <button class="btn btn-dark">Salvează</button>
          </div>
        </form>
      </div>
    </div>

    <!-- MODAL Material -->
    <div class="modal fade no-print" id="modalExp" tabindex="-1">
      <div class="modal-dialog modal-dialog-centered modal-lg">
        <form class="modal-content" method="post" action="{url_for('add_exp', job_id=job_id)}">
          <div class="modal-header">
            <h5 class="modal-title"><i class="bi bi-box-seam me-2"></i>Adaugă material/cheltuială</h5>
            <button class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="row">
              <div class="col-md-4 mb-2"><label class="form-label">Data</label><input name="exp_date" class="form-control" value="{date.today().isoformat()}"></div>
              <div class="col-md-4 mb-2"><label class="form-label">Categorie</label><input name="category" class="form-control" value="MATERIAL"></div>
              <div class="col-md-4 mb-2"><label class="form-label">Facturabil</label>
                <select name="billable" class="form-select">
                  <option value="1" selected>Da</option>
                  <option value="0">Nu</option>
                </select>
              </div>
            </div>
            <div class="mb-2"><label class="form-label">Descriere *</label><input name="description" class="form-control" required></div>
            <div class="row">
              <div class="col-md-3 mb-2"><label class="form-label">Cant</label><input name="qty" class="form-control" inputmode="decimal" data-decimal value="1"></div>
              <div class="col-md-3 mb-2"><label class="form-label">UM</label><input name="unit" class="form-control" value="buc"></div>
              <div class="col-md-3 mb-2"><label class="form-label">Cost/unit *</label><input name="unit_cost" class="form-control" inputmode="decimal" data-decimal required placeholder="ex: 12,50"></div>
              <div class="col-md-3 mb-2"><label class="form-label">Adaos %</label><input name="markup_percent" class="form-control" inputmode="decimal" data-decimal value="0"></div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-light" data-bs-dismiss="modal">Renunță</button>
            <button class="btn btn-dark">Salvează</button>
          </div>
        </form>
      </div>
    </div>

    <!-- MODAL Plată -->
    <div class="modal fade no-print" id="modalPay" tabindex="-1">
      <div class="modal-dialog modal-dialog-centered">
        <form class="modal-content" method="post" action="{url_for('add_pay', job_id=job_id)}">
          <div class="modal-header">
            <h5 class="modal-title"><i class="bi bi-cash-coin me-2"></i>Adaugă plată</h5>
            <button class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="mb-2"><label class="form-label">Data</label><input name="pay_date" class="form-control" value="{date.today().isoformat()}"></div>
            <div class="mb-2"><label class="form-label">Sumă *</label><input name="amount" class="form-control" inputmode="decimal" data-decimal required placeholder="ex: 100,50"></div>
            <div class="mb-2"><label class="form-label">Metodă</label><input name="method" class="form-control" placeholder="Cash / OP / Card"></div>
            <div class="mb-2"><label class="form-label">Note</label><input name="notes" class="form-control"></div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-light" data-bs-dismiss="modal">Renunță</button>
            <button class="btn btn-dark">Salvează</button>
          </div>
        </form>
      </div>
    </div>

    <!-- MODAL Factură -->
    <div class="modal fade no-print" id="modalInv" tabindex="-1">
      <div class="modal-dialog modal-dialog-centered modal-lg">
        <form class="modal-content" method="post" action="{url_for('invoice_generate', job_id=job_id)}">
          <div class="modal-header">
            <h5 class="modal-title"><i class="bi bi-receipt me-2"></i>Generează factură fiscală</h5>
            <button class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="row">
              <div class="col-md-6 mb-2"><label class="form-label">Data emiterii</label><input name="issue_date" class="form-control" value="{date.today().isoformat()}"></div>
              <div class="col-md-6 mb-2"><label class="form-label">Scadență</label><input name="due_date" class="form-control" placeholder="YYYY-MM-DD"></div>
            </div>
            <div class="row">
              <div class="col-md-6 mb-2">
                <label class="form-label">Metodă plată</label>
                <select name="payment_method" class="form-select">
                  <option value="OP" selected>OP</option>
                  <option value="Cash">Cash</option>
                  <option value="Card">Card</option>
                </select>
              </div>
              <div class="col-md-6 mb-2"><label class="form-label">Loc emitere</label><input name="place" class="form-control" placeholder="ex: București"></div>
            </div>
            <div class="mb-2"><label class="form-label">Note</label><input name="notes" class="form-control" placeholder="Conform deviz / contract..."></div>
            <div class="small text-muted">Liniile se generează din manoperă + cheltuieli facturabile.</div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-light" data-bs-dismiss="modal">Renunță</button>
            <button class="btn btn-success">Generează</button>
          </div>
        </form>
      </div>
    </div>
    """
    return render_page(body, f"{APP_TITLE} — {job.title}")


@app.get("/job/<int:job_id>/toggle")
@login_required
def toggle_job(job_id: int):
    job = Job.query.get_or_404(job_id)
    job.status = "CLOSED" if job.status == "OPEN" else "OPEN"
    db.session.commit()
    flash(f"Status schimbat: {job.status}")
    return redirect(url_for("job_detail", job_id=job_id))


# ----------------- CRUD: Time/Expense/Payment -----------------

@app.post("/job/<int:job_id>/add-time")
@login_required
def add_time(job_id: int):
    Job.query.get_or_404(job_id)
    hours = d(request.form.get("hours", "0"))
    if hours <= 0:
        flash("Ore invalide. Exemplu: 5,5")
        return redirect(url_for("job_detail", job_id=job_id))
    ro = request.form.get("rate_override", "").strip()
    t = Timesheet(
        job_id=job_id,
        work_date=request.form.get("work_date", date.today().isoformat()).strip(),
        worker=request.form.get("worker", "").strip() or None,
        task=request.form.get("task", "").strip() or None,
        hours=hours,
        rate_override=d(ro) if ro else None,
    )
    db.session.add(t)
    db.session.commit()
    flash("Pontaj adăugat.")
    return redirect(url_for("job_detail", job_id=job_id))


@app.get("/job/<int:job_id>/delete-time/<int:ts_id>")
@login_required
def delete_time(job_id: int, ts_id: int):
    Timesheet.query.filter_by(id=ts_id, job_id=job_id).delete()
    db.session.commit()
    flash("Pontaj șters.")
    return redirect(url_for("job_detail", job_id=job_id))


@app.post("/job/<int:job_id>/add-exp")
@login_required
def add_exp(job_id: int):
    Job.query.get_or_404(job_id)
    unit_cost = d(request.form.get("unit_cost", "0"))
    qty = d(request.form.get("qty", "1"))
    if qty <= 0 or unit_cost < 0:
        flash("Cantitate/cost invalid.")
        return redirect(url_for("job_detail", job_id=job_id))

    e = Expense(
        job_id=job_id,
        exp_date=request.form.get("exp_date", date.today().isoformat()).strip(),
        category=request.form.get("category", "MATERIAL").strip() or None,
        description=request.form.get("description", "").strip(),
        qty=qty,
        unit=request.form.get("unit", "buc").strip() or "buc",
        unit_cost=unit_cost,
        markup_percent=d(request.form.get("markup_percent", "0")),
        billable=(request.form.get("billable", "1") == "1"),
    )
    db.session.add(e)
    db.session.commit()
    flash("Material/cheltuială adăugată.")
    return redirect(url_for("job_detail", job_id=job_id))


@app.get("/job/<int:job_id>/delete-exp/<int:exp_id>")
@login_required
def delete_exp(job_id: int, exp_id: int):
    Expense.query.filter_by(id=exp_id, job_id=job_id).delete()
    db.session.commit()
    flash("Cheltuială ștearsă.")
    return redirect(url_for("job_detail", job_id=job_id))


@app.post("/job/<int:job_id>/add-pay")
@login_required
def add_pay(job_id: int):
    Job.query.get_or_404(job_id)
    amt = d(request.form.get("amount", "0"))
    if amt <= 0:
        flash("Suma introdusă nu este validă. Exemplu: 100,50")
        return redirect(url_for("job_detail", job_id=job_id))

    p = Payment(
        job_id=job_id,
        pay_date=request.form.get("pay_date", date.today().isoformat()).strip(),
        amount=amt,
        method=request.form.get("method", "").strip() or None,
        notes=request.form.get("notes", "").strip() or None,
    )
    db.session.add(p)
    db.session.commit()
    flash("Plată adăugată.")
    return redirect(url_for("job_detail", job_id=job_id))


@app.get("/job/<int:job_id>/delete-pay/<int:pay_id>")
@login_required
def delete_pay(job_id: int, pay_id: int):
    Payment.query.filter_by(id=pay_id, job_id=job_id).delete()
    db.session.commit()
    flash("Plată ștearsă.")
    return redirect(url_for("job_detail", job_id=job_id))


# ----------------- Receivables -----------------

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
          <td><a href="{url_for('job_detail', job_id=j.id)}">{j.title}</a><div class="text-muted small">{j.client.name}</div></td>
          <td>{j.status}</td>
          <td class="text-end">{money(t["total"])} {cur}</td>
          <td class="text-end">{money(t["paid"])} {cur}</td>
          <td class="text-end"><b class="text-danger">{money(t["receivable"])} {cur}</b></td>
        </tr>
        """

    body = f"""
    <div class="d-flex align-items-center justify-content-between mb-3">
      <div>
        <h2 class="mb-0">De încasat</h2>
        <div class="text-muted">Situație pe toate lucrările</div>
      </div>
      <div class="h4 mb-0">Total: <span class="text-danger">{money(total_all)} {cur}</span></div>
    </div>

    <div class="card mb-3">
      <div class="card-body">
        <input class="form-control search-input" placeholder="Caută lucrare/client…" data-table-search="#recTable">
      </div>
    </div>

    <div class="card">
      <div class="card-body table-responsive">
        <table class="table table-striped align-middle" id="recTable">
          <thead><tr><th>ID</th><th>Lucrare</th><th>Status</th><th class="text-end">Total</th><th class="text-end">Plătit</th><th class="text-end">De încasat</th></tr></thead>
          <tbody>{tr or "<tr><td colspan='6' class='text-muted'>Nimic.</td></tr>"}</tbody>
        </table>
      </div>
    </div>
    """
    return render_page(body, f"{APP_TITLE} — De încasat")


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
    db.session.flush()

    totals = compute_job_totals(job)

    # Linie manoperă
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

    # Linii cheltuieli facturabile
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
    flash(f"Factură generată: {inv_no}")
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
          <td class="text-end">{money(d(l.qty))}</td>
          <td>{l.unit}</td>
          <td class="text-end">{money(d(l.unit_price))}</td>
          <td class="text-end">{money(d(l.line_total))}</td>
        </tr>
        """
        i += 1

    vat_label = pct(vat_rate) if cp.vat_payer else "NEPLĂTITOR TVA"

    body = f"""
    <div class="no-print d-flex justify-content-between align-items-center mb-3">
      <a class="btn btn-outline-dark" href="{url_for('job_detail', job_id=job.id)}"><i class="bi bi-arrow-left me-1"></i>Înapoi</a>
      <button class="btn btn-dark" onclick="window.print()"><i class="bi bi-printer me-1"></i>Print / Save PDF</button>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-start">
          <div>
            <div class="d-flex align-items-center gap-2">
              <img src="{url_for('static', filename='logo.png')}" onerror="this.style.display='none'" alt="Logo" height="40">
              <h3 class="mb-0">FACTURĂ FISCALĂ</h3>
            </div>
            <div class="text-muted mt-1">Serie: <span class="mono">{inv.series}</span> · Număr: <span class="mono">{inv.number}</span></div>
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
          <div class="col-6"><div class="small text-muted">Semnătură furnizor: ____________________</div></div>
          <div class="col-6 text-end"><div class="small text-muted">Semnătură client: ____________________</div></div>
        </div>
      </div>
    </div>
    """
    return render_page(body, f"Factura {inv.inv_no}")


# ----------------- Run local -----------------

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

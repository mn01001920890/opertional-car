# ======================================================
# 🚗 Flask Authorization System — Weekly Authorizations + Accounting + Cash Receipts
# ======================================================

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import selectinload
from sqlalchemy import or_, and_, func, exists, desc
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import os
import traceback

app = Flask(__name__)

# ---------------- Favicon ----------------
@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )

# ---------------- DB Config (Vercel/Neon) ----------------
def normalize_database_url(url: str) -> str:
    if not url:
        return url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
DATABASE_URL = normalize_database_url(DATABASE_URL)

if not DATABASE_URL:
    raise ValueError("❌ لم يتم ضبط متغير البيئة DATABASE_URL (أو POSTGRES_URL) في Vercel")

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# تحسين ثبات الاتصال
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 280,
    "pool_size": 5,
    "max_overflow": 10,
}

db = SQLAlchemy(app)

# ---------------- Helpers ----------------
def get_friday_end(base_dt: datetime) -> datetime:
    """
    تحسب نهاية يوم الجمعة الأولى بعد التاريخ المعطى (تشمل نفس اليوم لو هو جمعة).
    """
    weekday = base_dt.weekday()  # Monday=0 ... Friday=4 ... Sunday=6
    if weekday <= 4:
        days_to_friday = 4 - weekday
    else:
        days_to_friday = 7 - (weekday - 4)

    friday = base_dt + timedelta(days=days_to_friday)
    friday_end = friday.replace(hour=23, minute=59, second=59, microsecond=0)
    return friday_end


def safe_decimal(val, default=None):
    if val in (None, "", " "):
        return default
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return default


def parse_int(val, default=None, min_val=None, max_val=None):
    try:
        n = int(val)
        if min_val is not None and n < min_val:
            n = min_val
        if max_val is not None and n > max_val:
            n = max_val
        return n
    except Exception:
        return default


def parse_bool(val, default=False):
    """
    يدعم قيم true/false وكذلك عربي شائع.
    """
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "y", "on", "t", "نعم", "اه", "أه", "تمام", "صح", "قيد", "محاسبي")


# ---------------- Models ----------------
class Authorization(db.Model):
    __tablename__ = "authorizations"

    id = db.Column(db.Integer, primary_key=True)

    issue_date = db.Column(db.DateTime, default=datetime.utcnow)
    driver_name = db.Column(db.String(100), nullable=False)
    driver_license_no = db.Column(db.String(60))

    driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"), nullable=True)

    car_number = db.Column(db.String(50), nullable=False)
    car_model = db.Column(db.String(50))
    car_type = db.Column(db.String(50))

    start_date = db.Column(db.DateTime)
    daily_rent = db.Column(db.Numeric(10, 2))
    details = db.Column(db.Text)
    status = db.Column(db.String(50))

    end_date = db.Column(db.DateTime, nullable=True)
    close_date = db.Column(db.DateTime, nullable=True)

    closed_amount = db.Column(db.Numeric(12, 2), nullable=True)
    closing_note = db.Column(db.Text)

    __table_args__ = (
        db.Index("ix_auth_close_date", "close_date"),
        db.Index("ix_auth_car_number", "car_number"),
        db.Index("ix_auth_driver_license_no", "driver_license_no"),
        db.Index("ix_auth_issue_date", "issue_date"),
    )

    def to_dict(self, light: bool = False):
        """
        light=True  => يقلل حجم الداتا للعرض السريع في جداول كبيرة
        """
        rental_days = None
        planned_amount = None

        base_start = self.start_date or self.issue_date

        if base_start and self.end_date and self.daily_rent is not None:
            try:
                start_d = base_start.date()
                end_d = self.end_date.date()
                days = (end_d - start_d).days + 1
                if days < 0:
                    days = 0
                rental_days = days
                planned_amount = float(self.daily_rent) * days
            except Exception:
                pass

        base = {
            "id": self.id,
            "issue_date": self.issue_date.strftime("%Y-%m-%d %H:%M:%S") if self.issue_date else "",
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.strftime("%Y-%m-%d %H:%M:%S") if self.end_date else "",
            "planned_end_date": self.end_date.strftime("%Y-%m-%d %H:%M:%S") if self.end_date else "",
            "close_date": self.close_date.strftime("%Y-%m-%d %H:%M:%S") if self.close_date else "",
            "driver_name": self.driver_name,
            "driver_license_no": self.driver_license_no,
            "driver_id": self.driver_id,
            "car_number": self.car_number,
            "car_model": self.car_model,
            "car_type": self.car_type,
            "daily_rent": float(self.daily_rent or 0),
            "status": self.status,
            "rental_days": rental_days,
            "planned_amount": planned_amount,
            "closed_amount": float(self.closed_amount or 0) if self.closed_amount is not None else None,
        }

        if not light:
            base["details"] = self.details
            base["closing_note"] = self.closing_note

        return base


class Car(db.Model):
    __tablename__ = "cars"

    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(80))
    car_type = db.Column(db.String(80))
    status = db.Column(db.String(50), default="متاحة")
    daily_rent = db.Column(db.Numeric(10, 2))

    __table_args__ = (
        db.Index("ix_cars_plate", "plate"),
        db.Index("ix_cars_status", "status"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "plate": self.plate,
            "model": self.model,
            "car_type": self.car_type,
            "status": self.status,
            "daily_rent": float(self.daily_rent or 0),
        }


class Driver(db.Model):
    __tablename__ = "drivers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(50))
    license_no = db.Column(db.String(60))

    authorizations = db.relationship("Authorization", backref="driver", lazy="selectin")

    __table_args__ = (
        db.Index("ix_drivers_name", "name"),
        db.Index("ix_drivers_license_no", "license_no"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "license_no": self.license_no,
        }


# ===== Accounting Models =====
class Account(db.Model):
    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    type = db.Column(db.String(50))

    parent_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)
    is_group = db.Column(db.Boolean, default=False)

    related_driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"), nullable=True)
    related_car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=True)

    related_driver = db.relationship("Driver", backref="accounts", lazy="selectin")
    related_car = db.relationship("Car", backref="accounts", lazy="selectin")

    parent = db.relationship("Account", remote_side=[id], backref="children", lazy="selectin")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "related_driver_id": self.related_driver_id,
            "related_car_id": self.related_car_id,
            "parent_id": self.parent_id,
            "is_group": self.is_group,
        }


class CashReceipt(db.Model):
    __tablename__ = "cash_receipts"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"), nullable=True)
    driver_name = db.Column(db.String(100))
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    description = db.Column(db.String(255))
    ref_authorization_id = db.Column(db.Integer, db.ForeignKey("authorizations.id"), nullable=True)

    driver = db.relationship("Driver", backref="cash_receipts", lazy="selectin")
    authorization = db.relationship("Authorization", backref="cash_receipts", lazy="selectin")

    __table_args__ = (
        db.Index("ix_cash_receipts_date", "date"),
        db.Index("ix_cash_receipts_driver_id", "driver_id"),
        db.Index("ix_cash_receipts_ref_authorization_id", "ref_authorization_id"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.strftime("%Y-%m-%d %H:%M:%S") if self.date else "",
            "driver_id": self.driver_id,
            "driver_name": self.driver_name,
            "amount": float(self.amount or 0),
            "description": self.description,
            "ref_authorization_id": self.ref_authorization_id,
        }


class JournalEntry(db.Model):
    __tablename__ = "journal_entries"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    description = db.Column(db.String(255))
    ref_authorization_id = db.Column(db.Integer, db.ForeignKey("authorizations.id"), nullable=True)
    ref_receipt_id = db.Column(db.Integer, db.ForeignKey("cash_receipts.id"), nullable=True)

    authorization = db.relationship("Authorization", backref="journal_entries", lazy="selectin")
    receipt = db.relationship("CashReceipt", backref="journal_entries", lazy="selectin")

    lines = db.relationship(
        "JournalLine",
        back_populates="journal_entry",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.Index("ix_journal_entries_date", "date"),
        db.Index("ix_journal_entries_ref_auth", "ref_authorization_id"),
        db.Index("ix_journal_entries_ref_receipt", "ref_receipt_id"),
    )

    def to_dict(self, with_lines: bool = False):
        source_type = "manual"
        ref_text = "قيد يدوي"

        if self.ref_receipt_id:
            source_type = "receipt"
            if self.ref_authorization_id:
                ref_text = f"سند تحصيل رقم {self.ref_receipt_id} عن تفويض رقم {self.ref_authorization_id}"
            else:
                ref_text = f"سند تحصيل رقم {self.ref_receipt_id}"
        elif self.ref_authorization_id:
            source_type = "auth_close"
            ref_text = f"تفويض رقم {self.ref_authorization_id}"

        driver_name = None
        car_number = None

        auth = self.authorization
        receipt = self.receipt

        if auth:
            driver_name = auth.driver_name
            car_number = auth.car_number
        elif receipt:
            driver_name = receipt.driver_name or (receipt.driver.name if receipt.driver else None)
            if receipt.authorization:
                car_number = receipt.authorization.car_number

        base = {
            "id": self.id,
            "date": self.date.strftime("%Y-%m-%d %H:%M:%S") if self.date else "",
            "description": self.description,
            "ref_authorization_id": self.ref_authorization_id,
            "ref_receipt_id": self.ref_receipt_id,
            "source_type": source_type,
            "driver_name": driver_name,
            "car_number": car_number,
            "ref_text": ref_text,
        }
        if with_lines:
            base["lines"] = [ln.to_dict() for ln in (self.lines or [])]
        return base


class JournalLine(db.Model):
    __tablename__ = "journal_lines"

    id = db.Column(db.Integer, primary_key=True)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id"), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    debit = db.Column(db.Numeric(12, 2), default=0)
    credit = db.Column(db.Numeric(12, 2), default=0)

    journal_entry = db.relationship("JournalEntry", back_populates="lines", lazy="selectin")
    account = db.relationship("Account", backref="lines", lazy="selectin")

    __table_args__ = (
        db.Index("ix_journal_lines_entry_id", "journal_entry_id"),
        db.Index("ix_journal_lines_account_id", "account_id"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "journal_entry_id": self.journal_entry_id,
            "account_id": self.account_id,
            "account_name": self.account.name if self.account else None,
            "account_code": str(self.account.id) if self.account else None,
            "debit": float(self.debit or 0),
            "credit": float(self.credit or 0),
        }


# ---------------- Accounting Helpers ----------------
def ensure_driver_root_account():
    root = Account.query.filter_by(name="حساب السائقين", is_group=True).first()
    if root:
        return root

    root = Account(
        name="حساب السائقين",
        type="asset",
        parent_id=None,
        is_group=True,
    )
    db.session.add(root)
    db.session.flush()
    return root


def ensure_driver_sub_account(driver: Driver):
    if not driver:
        return None

    existing = Account.query.filter_by(related_driver_id=driver.id).first()
    if existing:
        return existing

    root = ensure_driver_root_account()
    acc_name = f"سائق: {driver.name}" if driver.name else f"سائق رقم {driver.id}"

    acc = Account(
        name=acc_name,
        type="asset",
        parent_id=root.id if root else None,
        is_group=False,
        related_driver_id=driver.id,
    )
    db.session.add(acc)
    db.session.flush()
    return acc


def ensure_core_accounts():
    changed = False

    cash = Account.query.filter_by(name="الصندوق").first()
    if not cash:
        cash = Account(name="الصندوق", type="asset", is_group=False)
        db.session.add(cash)
        changed = True

    revenue = Account.query.filter_by(name="إيراد إيجار سيارات").first()
    if not revenue:
        revenue = Account(name="إيراد إيجار سيارات", type="revenue", is_group=False)
        db.session.add(revenue)
        changed = True

    root = Account.query.filter_by(name="حساب السائقين", is_group=True).first()
    if not root:
        _ = ensure_driver_root_account()
        changed = True

    if changed:
        db.session.commit()


def create_journal_for_closed_authorization(auth, total_amount):
    """
    ينشئ قيد يومية عند إقفال التفويض:
    من حـ/ حساب السائق (مدين)
    إلى حـ/ إيراد إيجار سيارات (دائن)

    ✅ يرجّع رقم القيد (journal_entry_id)
    """
    try:
        if not total_amount or total_amount <= 0:
            return None

        revenue_account = Account.query.filter_by(name="إيراد إيجار سيارات").first()
        if not revenue_account:
            return None

        driver_account = None
        if auth and auth.driver_id:
            driver_account = ensure_driver_sub_account(auth.driver)

        if not driver_account:
            driver_account = ensure_driver_root_account()

        if not driver_account:
            return None

        je = JournalEntry(
            date=datetime.utcnow(),
            description=f"قيد إقفال تفويض رقم {auth.id}" if auth else "قيد إقفال تفويض",
            ref_authorization_id=auth.id if auth else None,
        )
        db.session.add(je)
        db.session.flush()

        amount_dec = Decimal(str(total_amount))

        line1 = JournalLine(
            journal_entry_id=je.id,
            account_id=driver_account.id,
            debit=amount_dec,
            credit=Decimal("0"),
        )

        line2 = JournalLine(
            journal_entry_id=je.id,
            account_id=revenue_account.id,
            debit=Decimal("0"),
            credit=amount_dec,
        )

        db.session.add_all([line1, line2])
        return je.id
    except Exception:
        traceback.print_exc()
        return None


def create_journal_for_cash_receipt(receipt: CashReceipt):
    """
    ينشئ قيد يومية لسند تحصيل نقدي:
    من حـ/ الصندوق (مدين)
    إلى حـ/ حساب السائق (دائن)

    ✅ يرجّع رقم القيد (journal_entry_id)
    """
    try:
        if not receipt or not receipt.amount or receipt.amount <= 0:
            return None

        cash_account = Account.query.filter_by(name="الصندوق").first()
        if not cash_account:
            return None

        driver_account = None
        if receipt.driver_id:
            driver_account = ensure_driver_sub_account(receipt.driver)

        if not driver_account:
            driver_account = ensure_driver_root_account()

        if not driver_account:
            return None

        je = JournalEntry(
            date=receipt.date or datetime.utcnow(),
            description=receipt.description or f"سند تحصيل نقدي رقم {receipt.id}",
            ref_authorization_id=receipt.ref_authorization_id,
            ref_receipt_id=receipt.id,
        )
        db.session.add(je)
        db.session.flush()

        amount_dec = Decimal(str(receipt.amount))

        line1 = JournalLine(
            journal_entry_id=je.id,
            account_id=cash_account.id,
            debit=amount_dec,
            credit=Decimal("0"),
        )

        line2 = JournalLine(
            journal_entry_id=je.id,
            account_id=driver_account.id,
            debit=Decimal("0"),
            credit=amount_dec,
        )

        db.session.add_all([line1, line2])
        return je.id
    except Exception:
        traceback.print_exc()
        return None


# ---------------- Routes (Pages) ----------------
@app.route("/")
def index_page():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard_page():
    return render_template("dashboard.html")


@app.route("/issue")
def issue_page():
    return render_template("issue.html")


@app.route("/view")
def view_page():
    return render_template("view.html")


@app.route("/cars")
def cars_page():
    return render_template("cars.html")


@app.route("/drivers")
def drivers_page():
    return render_template("drivers.html")


@app.route("/rented")
def rented_cars_page():
    return render_template("rented.html")


@app.route("/cars-status")
def cars_status_page():
    return render_template("cars-status.html")


@app.route("/accounts")
def accounts_page():
    return render_template("accounts.html")


@app.route("/ledger")
def ledger_page():
    return render_template("ledger.html")


@app.route("/general")
def general_journal_page():
    return render_template("general.html")


@app.route("/receipt")
def receipt_page():
    return render_template("receipt.html")


@app.route("/operations")
def operations_page():
    return render_template("operations.html")


@app.route("/journal-list")
def journal_list_page():
    return render_template("journal-list.html")


@app.route("/receipts-list")
def receipts_list_page():
    return render_template("receipts-list.html")


# ---------------- Health / Debug ----------------
@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})


@app.route("/api/debug/dburl")
def api_debug_dburl():
    return jsonify({"DATABASE_URL_present": bool(os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL"))})


# ---------------- APIs ----------------
@app.route("/api/issue", methods=["POST"])
def add_authorization():
    try:
        data = request.get_json() or {}

        driver_name = (data.get("driver_name") or "").strip()
        car_plate = (data.get("car_number") or "").strip()

        if not driver_name:
            return jsonify({"error": "برجاء اختيار السائق"}), 400
        if not car_plate:
            return jsonify({"error": "برجاء اختيار السيارة"}), 400

        car = Car.query.filter_by(plate=car_plate).first()
        if not car:
            return jsonify({"error": "السيارة غير موجودة في قاعدة البيانات"}), 400
        if (car.status or "").strip() != "متاحة":
            return jsonify({"error": f"السيارة غير متاحة حالياً (الحالة: {car.status})"}), 400

        open_auth = (
            Authorization.query.filter_by(car_number=car_plate)
            .filter(Authorization.close_date.is_(None))
            .first()
        )
        if open_auth:
            return jsonify({"error": "هناك تفويض مفتوح لهذه السيارة بالفعل"}), 400

        driver_obj = Driver.query.filter_by(name=driver_name).first()
        driver_license_no = driver_obj.license_no if driver_obj and driver_obj.license_no else None

        issue_date = datetime.utcnow()

        start_date = None
        sd = (data.get("start_date") or "").strip()
        if sd:
            try:
                start_date = datetime.fromisoformat(sd)
            except Exception:
                return jsonify({"error": "صيغة التاريخ غير صحيحة. استخدم ISO 8601 مثل 2025-11-12T10:30"}), 400

        if not start_date:
            start_date = issue_date

        planned_end = get_friday_end(start_date)

        car_model = data.get("car_model") or car.model
        car_type = data.get("car_type") or car.car_type

        daily_rent = car.daily_rent
        if data.get("daily_rent") not in (None, "", " "):
            daily_rent_dec = safe_decimal(data.get("daily_rent"))
            if daily_rent_dec is None:
                return jsonify({"error": "قيمة الإيجار اليومي غير صحيحة"}), 400
            daily_rent = daily_rent_dec

        new_auth = Authorization(
            driver_name=driver_name,
            driver_license_no=driver_license_no,
            driver_id=driver_obj.id if driver_obj else None,
            car_number=car_plate,
            car_model=car_model,
            car_type=car_type,
            issue_date=issue_date,
            start_date=start_date,
            daily_rent=daily_rent,
            details=data.get("details"),
            status="مؤجرة",
            end_date=planned_end,
            close_date=None,
        )

        db.session.add(new_auth)
        car.status = "مؤجرة"
        db.session.commit()

        return jsonify({"message": "✅ Authorization added successfully", "authorization": new_auth.to_dict()}), 201

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": f"Server/DB error: {str(e)}"}), 500


@app.route("/api/authorizations", methods=["GET"])
def get_authorizations():
    """
    - ?status=active  → close_date IS NULL
    - ?status=closed  → close_date IS NOT NULL
    - ?car_number=123 → contains
    - ?license_no=ABC → contains
    - ?limit=200&offset=0 → (اختياري للسرعة) يرجّع جزء فقط
    - ?light=1 → (اختياري) يقلل الداتا للعرض السريع
    """
    query = Authorization.query

    status_param = (request.args.get("status") or "").strip().lower()
    if status_param == "active":
        query = query.filter(Authorization.close_date.is_(None))
    elif status_param == "closed":
        query = query.filter(Authorization.close_date.is_not(None))

    car_number = (request.args.get("car_number") or "").strip()
    if car_number:
        query = query.filter(Authorization.car_number.ilike(f"%{car_number}%"))

    license_no = (request.args.get("license_no") or "").strip()
    if license_no:
        query = query.filter(Authorization.driver_license_no.ilike(f"%{license_no}%"))

    light = parse_bool(request.args.get("light"), default=False)

    limit = parse_int(request.args.get("limit"), default=None, min_val=1, max_val=5000)
    offset = parse_int(request.args.get("offset"), default=0, min_val=0)

    query = query.order_by(Authorization.id.desc())

    if limit is not None:
        auths = query.offset(offset).limit(limit).all()
    else:
        auths = query.all()

    return jsonify([a.to_dict(light=light) for a in auths])


# ✅ UPDATED: closed authorizations (fast + summary + close_date order)
@app.route("/api/authorizations/closed", methods=["GET"])
def get_closed_authorizations():
    """
    Closed Authorizations (FAST):
    - Order: close_date DESC (newest first)
    - Pagination: limit/offset
    - light=1 (optional)
    - q=... (server search)
    Returns:
      { items: [...], total: N, journal_yes: N, journal_no: N }
    """
    q_raw = (request.args.get("q") or "").strip()
    light = parse_bool(request.args.get("light"), default=False)

    limit = parse_int(request.args.get("limit"), default=200, min_val=1, max_val=5000)
    offset = parse_int(request.args.get("offset"), default=0, min_val=0)

    query = Authorization.query.filter(Authorization.close_date.is_not(None))

    if q_raw:
        like = f"%{q_raw}%"
        filters = [
            Authorization.driver_name.ilike(like),
            Authorization.car_number.ilike(like),
            Authorization.driver_license_no.ilike(like),
            Authorization.status.ilike(like),
            Authorization.details.ilike(like),
            Authorization.closing_note.ilike(like),
        ]
        if q_raw.isdigit():
            try:
                q_id = int(q_raw)
                filters.append(Authorization.id == q_id)
            except Exception:
                pass

        query = query.filter(or_(*filters))

    total = query.with_entities(func.count(Authorization.id)).scalar() or 0

    journal_exists = exists().where(
        and_(
            JournalEntry.ref_authorization_id == Authorization.id,
            JournalEntry.ref_receipt_id.is_(None),   # قيد إقفال تفويض فقط
        )
    )

    journal_yes = query.filter(journal_exists).with_entities(func.count(Authorization.id)).scalar() or 0
    journal_no = max(total - journal_yes, 0)

    order_expr = desc(Authorization.close_date)
    if hasattr(order_expr, "nullslast"):
        order_expr = order_expr.nullslast()

    query = query.order_by(order_expr, Authorization.id.desc())

    auths = query.offset(offset).limit(limit).all()

    return jsonify({
        "items": [a.to_dict(light=light) for a in auths],
        "total": int(total),
        "journal_yes": int(journal_yes),
        "journal_no": int(journal_no),
    })


@app.route("/api/authorizations/active", methods=["GET"])
def get_active_authorizations():
    auths = (
        Authorization.query.filter(Authorization.close_date.is_(None))
        .order_by(Authorization.id.desc())
        .all()
    )
    return jsonify([a.to_dict() for a in auths])


@app.route("/api/authorizations/<int:auth_id>/end", methods=["PATCH"])
def end_authorization(auth_id):
    """
    إنهاء تفويض:
    - يقفل التفويض الحالي
    - (اختياري) ينشئ قيد إقفال تفويض لو with_journal = true
    - renew = true  ⇒ إنشاء تفويض جديد للأسبوع التالي + السيارة تظل "مؤجرة"
    - renew = false ⇒ لا تفويض جديد + السيارة "متاحة"
    - يرجع suggested_receipt لفتح سند تحصيل تلقائي.
    - ✅ يرجع journal_entry_id لو اتعمل قيد (مهم للطباعة/العمليات)

    ✅ تعديل مهم:
    - القيد المحاسبي لن يُنشأ إلا إذا تم إرسال with_journal=true صراحةً.
    """
    auth = Authorization.query.get(auth_id)
    if not auth:
        return jsonify({"error": "التفويض غير موجود"}), 404
    if auth.close_date:
        return jsonify({"error": "التفويض منتهي بالفعل"}), 400

    car = Car.query.filter_by(plate=auth.car_number).first()

    try:
        data = request.get_json(silent=True) or {}

        renew_raw = data.get("renew")
        if renew_raw is None:
            renew_raw = data.get("renew_option")

        renew = True
        if isinstance(renew_raw, bool):
            renew = renew_raw
        elif isinstance(renew_raw, (int, float)):
            renew = bool(renew_raw)
        elif isinstance(renew_raw, str):
            renew = renew_raw.strip().lower() in ("1", "true", "yes", "y", "renew", "تجديد")

        with_journal_raw = data.get("with_journal")
        if with_journal_raw is None:
            with_journal_raw = data.get("accounting_option")

        # ✅ مهم جدًا: الافتراضي False (يعني لا قيد إلا إذا تم اختياره)
        with_journal = False
        if with_journal_raw is not None:
            if isinstance(with_journal_raw, bool):
                with_journal = with_journal_raw
            elif isinstance(with_journal_raw, (int, float)):
                with_journal = bool(with_journal_raw)
            elif isinstance(with_journal_raw, str):
                with_journal = with_journal_raw.strip().lower() in (
                    "1", "true", "yes", "y", "with_journal", "journal",
                    "قيد", "محاسبي", "عمل قيد", "عمل قيد محاسبي"
                )

        closing_note = (data.get("closing_note") or "").strip() or None
        closed_amount_input = data.get("closed_amount")

        close_dt = datetime.utcnow()
        auth.close_date = close_dt
        auth.status = "منتهية"

        if not auth.end_date:
            base_for_end = auth.start_date or auth.issue_date
            if base_for_end:
                auth.end_date = get_friday_end(base_for_end)

        rental_days = None
        auto_amount = None
        base_start = auth.start_date or auth.issue_date
        if base_start and auth.end_date and auth.daily_rent is not None:
            start_d = base_start.date()
            end_d = auth.end_date.date()
            days = (end_d - start_d).days + 1
            if days < 0:
                days = 0
            rental_days = days
            auto_amount = float(auth.daily_rent) * days

        final_amount = auto_amount
        closed_amount_dec = None

        if closed_amount_input not in (None, "", " "):
            tmp = safe_decimal(closed_amount_input)
            if tmp is not None and tmp > 0:
                closed_amount_dec = tmp
                final_amount = float(tmp)

        if closed_amount_dec is None and auto_amount is not None:
            closed_amount_dec = Decimal(str(round(auto_amount, 2)))

        auth.closed_amount = closed_amount_dec
        auth.closing_note = closing_note

        journal_entry_id = None
        if with_journal and final_amount and final_amount > 0:
            journal_entry_id = create_journal_for_closed_authorization(auth, final_amount)

        new_auth = None

        if renew:
            if auth.end_date:
                new_issue = auth.end_date + timedelta(days=1)
            else:
                new_issue = close_dt + timedelta(days=1)

            new_issue = new_issue.replace(hour=9, minute=0, second=0, microsecond=0)
            new_end = get_friday_end(new_issue)

            new_auth = Authorization(
                driver_name=auth.driver_name,
                driver_license_no=auth.driver_license_no,
                driver_id=auth.driver_id,
                car_number=auth.car_number,
                car_model=auth.car_model,
                car_type=auth.car_type,
                issue_date=new_issue,
                start_date=new_issue,
                daily_rent=auth.daily_rent,
                details=auth.details,
                status="مؤجرة",
                end_date=new_end,
                close_date=None,
            )
            db.session.add(new_auth)

            if car:
                car.status = "مؤجرة"
        else:
            if car:
                car.status = "متاحة"

        db.session.commit()

        suggested_receipt = {
            "authorization_id": auth.id,
            "driver_id": auth.driver_id,
            "driver_name": auth.driver_name,
            "default_amount": final_amount,
            "description": f"سداد عن تفويض رقم {auth.id}",
        }

        if renew and with_journal:
            message = "✅ تم إقفال التفويض وإنشاء تفويض جديد للأسبوع التالي مع تسجيل قيد محاسبي"
        elif renew and not with_journal:
            message = "✅ تم إقفال التفويض وإنشاء تفويض جديد للأسبوع التالي بدون تسجيل أي قيد محاسبي"
        elif (not renew) and with_journal:
            message = "✅ تم إقفال التفويض وتحويل السيارة إلى متاحة مع تسجيل قيد محاسبي"
        else:
            message = "✅ تم إقفال التفويض وتحويل السيارة إلى متاحة بدون تسجيل أي قيد محاسبي"

        return jsonify({
            "message": message,
            "closed_authorization": auth.to_dict(),
            "new_authorization": new_auth.to_dict() if new_auth else None,
            "rental_days": rental_days,
            "total_amount": final_amount,
            "renew": renew,
            "with_journal": with_journal,
            "journal_entry_id": journal_entry_id,
            "suggested_receipt": suggested_receipt,
        }), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": f"DB error: {str(e)}"}), 500


# ----- Cars APIs -----
@app.route("/api/cars", methods=["GET"])
def list_cars():
    cars = Car.query.order_by(Car.id.desc()).all()
    return jsonify([c.to_dict() for c in cars])


@app.route("/api/cars", methods=["POST"])
def add_car():
    try:
        data = request.get_json() or {}
        plate = (data.get("plate") or "").strip()
        if not plate:
            return jsonify({"error": "رقم اللوحة مطلوب"}), 400

        daily_rent_dec = safe_decimal(data.get("daily_rent"))

        car = Car(
            plate=plate,
            model=data.get("model"),
            car_type=data.get("car_type"),
            daily_rent=daily_rent_dec,
            status=data.get("status") or "متاحة",
        )
        db.session.add(car)
        db.session.commit()
        return jsonify({"message": "✅ Car added", "car": car.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/cars/status", methods=["GET"])
def cars_status():
    cars = Car.query.all()
    total = len(cars)
    available = len([c for c in cars if (c.status or "").strip() == "متاحة"])
    rented = len([c for c in cars if (c.status or "").strip() == "مؤجرة"])
    repair = len([c for c in cars if (c.status or "").strip() == "تحت الصيانة"])
    return jsonify({"total": total, "available": available, "rented": rented, "repair": repair})


# ----- Drivers APIs -----
@app.route("/api/drivers", methods=["GET"])
def list_drivers():
    drivers = Driver.query.order_by(Driver.id.desc()).all()
    return jsonify([d.to_dict() for d in drivers])


@app.route("/api/drivers", methods=["POST"])
def add_driver():
    try:
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "اسم السائق مطلوب"}), 400

        existing = Driver.query.filter_by(name=name).first()
        if existing:
            return jsonify({"error": "هذا السائق مسجَّل بالفعل"}), 400

        new_driver = Driver(name=name, phone=data.get("phone"), license_no=data.get("license_no"))
        db.session.add(new_driver)
        db.session.commit()
        return jsonify({"message": "✅ Driver added", "driver": new_driver.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ----- Accounts APIs -----
@app.route("/api/accounts", methods=["GET", "POST"])
def accounts_api():
    if request.method == "GET":
        accounts = Account.query.order_by(Account.id.asc()).all()
        return jsonify([acc.to_dict() for acc in accounts])

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "اسم الحساب مطلوب"}), 400

    existing = Account.query.filter_by(name=name).first()
    if existing:
        return jsonify({"error": "هذا الحساب موجود بالفعل"}), 400

    acc = Account(
        name=name,
        type=data.get("type"),
        related_driver_id=data.get("related_driver_id"),
        related_car_id=data.get("related_car_id"),
        parent_id=data.get("parent_id"),
        is_group=bool(data.get("is_group")) if data.get("is_group") is not None else False,
    )
    try:
        db.session.add(acc)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"DB error: {str(e)}"}), 500

    return jsonify({"message": "✅ تم إضافة الحساب بنجاح", "account": acc.to_dict()}), 201


@app.route("/api/accounts/driver", methods=["POST"])
def create_driver_account_api():
    data = request.get_json() or {}

    driver_id = data.get("driver_id")
    if not driver_id:
        return jsonify({"error": "driver_id مطلوب"}), 400

    driver = Driver.query.get(driver_id)
    if not driver:
        return jsonify({"error": "السائق غير موجود في قاعدة البيانات"}), 404

    existing = Account.query.filter_by(related_driver_id=driver.id).first()
    if existing:
        return jsonify({"message": "✅ الحساب الخاص بالسائق موجود بالفعل", "account": existing.to_dict(), "already_exists": True}), 200

    try:
        acc = ensure_driver_sub_account(driver)
        db.session.commit()
        return jsonify({"message": "✅ تم إنشاء حساب فرعي للسائق في شجرة الحسابات", "account": acc.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": f"DB error: {str(e)}"}), 500


# ----- Ledger API -----
@app.route("/api/accounts/<int:account_id>/ledger", methods=["GET"])
def get_account_ledger(account_id):
    account = Account.query.get(account_id)
    if not account:
        return jsonify({"error": "الحساب غير موجود"}), 404

    lines = (
        JournalLine.query
        .options(selectinload(JournalLine.journal_entry))
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .filter(JournalLine.account_id == account_id)
        .order_by(JournalEntry.date.asc(), JournalLine.id.asc())
        .all()
    )

    running_balance = Decimal("0")
    ledger_rows = []

    for line in lines:
        je = line.journal_entry
        debit = line.debit or Decimal("0")
        credit = line.credit or Decimal("0")
        running_balance += debit - credit

        ledger_rows.append({
            "entry_id": je.id,
            "date": je.date.strftime("%Y-%m-%d %H:%M:%S") if je.date else "",
            "description": je.description,
            "debit": float(debit or 0),
            "credit": float(credit or 0),
            "balance": float(running_balance),
        })

    return jsonify({"account": account.to_dict(), "lines": ledger_rows})


# ----- General Journal APIs -----
@app.route("/api/journal_entries", methods=["GET", "POST"])
def journal_entries_api():
    if request.method == "GET":
        entries = (
            JournalEntry.query
            .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
            .order_by(JournalEntry.date.desc(), JournalEntry.id.desc())
            .all()
        )
        return jsonify([e.to_dict(with_lines=True) for e in entries])

    data = request.get_json() or {}
    desc_txt = (data.get("description") or "").strip()
    date_str = (data.get("date") or "").strip()
    lines_data = data.get("lines") or []

    if not lines_data:
        return jsonify({"error": "لا يوجد بنود في القيد"}), 400

    je_date = datetime.utcnow()
    if date_str:
        try:
            je_date = datetime.fromisoformat(date_str)
        except Exception:
            return jsonify({"error": "صيغة التاريخ غير صحيحة. استخدم YYYY-MM-DD"}), 400

    cleaned = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    for i, ln in enumerate(lines_data, start=1):
        acc_id = ln.get("account_id")
        if not acc_id:
            continue

        acc = Account.query.get(acc_id)
        if not acc:
            return jsonify({"error": f"السطر رقم {i}: الحساب غير موجود"}), 400

        if getattr(acc, "is_group", False):
            return jsonify({"error": f"السطر رقم {i}: لا يمكن استخدام حساب تجميعي (اختر حساب تفصيلي)"}), 400

        debit_dec = safe_decimal(ln.get("debit"), default=Decimal("0")) or Decimal("0")
        credit_dec = safe_decimal(ln.get("credit"), default=Decimal("0")) or Decimal("0")

        if debit_dec < 0 or credit_dec < 0:
            return jsonify({"error": f"السطر رقم {i}: لا يمكن إدخال قيم سالبة"}), 400

        if debit_dec != 0 and credit_dec != 0:
            return jsonify({"error": f"السطر رقم {i}: يجب إدخال (مدين أو دائن) فقط وليس الاثنين"}), 400

        if debit_dec == 0 and credit_dec == 0:
            continue

        total_debit += debit_dec
        total_credit += credit_dec
        cleaned.append((acc.id, debit_dec, credit_dec))

    if not cleaned:
        return jsonify({"error": "كل البنود فارغة — أدخل على الأقل سطر واحد فيه مدين أو دائن"}), 400

    if (total_debit - total_credit).copy_abs() > Decimal("0.005"):
        return jsonify({
            "error": "القيد غير متوازن: إجمالي المدين لا يساوي إجمالي الدائن",
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
        }), 400

    je = JournalEntry(date=je_date, description=desc_txt)
    db.session.add(je)
    db.session.flush()

    try:
        for (acc_id, d, c) in cleaned:
            line = JournalLine(
                journal_entry_id=je.id,
                account_id=acc_id,
                debit=d,
                credit=c,
            )
            db.session.add(line)

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": f"DB error: {str(e)}"}), 500

    return jsonify({
        "message": "✅ تم إنشاء قيد اليومية بنجاح",
        "id": je.id,
        "journal_entry": je.to_dict(with_lines=True),
    }), 201


@app.route("/api/journal_entries/<int:entry_id>", methods=["GET"])
def journal_entry_get_one(entry_id):
    entry = (
        JournalEntry.query
        .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
        .filter_by(id=entry_id)
        .first()
    )
    if not entry:
        return jsonify({"error": "القيد غير موجود"}), 404
    return jsonify(entry.to_dict(with_lines=True))


@app.route("/api/journal_entries/manual", methods=["GET"])
def manual_journal_entries_api():
    entries = (
        JournalEntry.query
        .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
        .filter(JournalEntry.ref_authorization_id.is_(None))
        .filter(JournalEntry.ref_receipt_id.is_(None))
        .order_by(JournalEntry.date.desc(), JournalEntry.id.desc())
        .all()
    )
    return jsonify([e.to_dict(with_lines=True) for e in entries])


@app.route("/api/journal_entries/auth_close_map", methods=["GET"])
def auth_close_journal_map():
    raw = (request.args.get("auth_ids") or "").strip()
    if not raw:
        return jsonify({"map": {}})

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    ids = []
    for p in parts[:500]:
        if p.isdigit():
            ids.append(int(p))

    if not ids:
        return jsonify({"map": {}})

    q = (
        JournalEntry.query
        .filter(JournalEntry.ref_authorization_id.in_(ids))
        .filter(JournalEntry.ref_receipt_id.is_(None))
        .order_by(
            JournalEntry.ref_authorization_id.asc(),
            JournalEntry.date.desc(),
            JournalEntry.id.desc(),
        )
        .distinct(JournalEntry.ref_authorization_id)
    )

    rows = q.all()

    mp = {}
    for je in rows:
        aid = je.ref_authorization_id
        if not aid:
            continue
        mp[str(aid)] = {
            "has": True,
            "statement": je.description or f"قيد إقفال تفويض رقم {aid}",
            "journal_entry_id": je.id,
        }

    for aid in ids:
        k = str(aid)
        if k not in mp:
            mp[k] = {"has": False, "statement": "", "journal_entry_id": None}

    return jsonify({"map": mp})


# ----- Cash Receipts APIs -----
@app.route("/api/receipts", methods=["GET", "POST"])
def receipts_api():
    if request.method == "GET":
        receipts = CashReceipt.query.order_by(CashReceipt.date.desc(), CashReceipt.id.desc()).all()
        return jsonify([r.to_dict() for r in receipts])

    data = request.get_json() or {}

    driver_name = (data.get("driver_name") or "").strip()
    driver_id = data.get("driver_id")
    auth_id = data.get("authorization_id")
    desc_txt = (data.get("description") or "").strip()
    amount_val = data.get("amount")
    date_str = (data.get("date") or "").strip()

    if amount_val in (None, "", " "):
        return jsonify({"error": "قيمة المبلغ مطلوبة"}), 400

    amount_dec = safe_decimal(amount_val)
    if amount_dec is None:
        return jsonify({"error": "قيمة المبلغ غير صحيحة"}), 400
    if amount_dec <= 0:
        return jsonify({"error": "قيمة المبلغ يجب أن تكون أكبر من صفر"}), 400

    rc_date = datetime.utcnow()
    if date_str:
        try:
            rc_date = datetime.fromisoformat(date_str)
        except Exception:
            return jsonify({"error": "صيغة التاريخ غير صحيحة. استخدم ISO 8601"}), 400

    driver_obj = None
    if driver_id:
        driver_obj = Driver.query.get(driver_id)
    elif driver_name:
        driver_obj = Driver.query.filter_by(name=driver_name).first()

    if driver_obj and not driver_name:
        driver_name = driver_obj.name

    auth_obj = None
    if auth_id:
        auth_obj = Authorization.query.get(auth_id)

    receipt = CashReceipt(
        date=rc_date,
        driver_id=driver_obj.id if driver_obj else None,
        driver_name=driver_name or (driver_obj.name if driver_obj else None),
        amount=amount_dec,
        description=desc_txt or (f"سداد عن تفويض رقم {auth_obj.id}" if auth_obj else "سند تحصيل نقدي"),
        ref_authorization_id=auth_obj.id if auth_obj else None,
    )

    try:
        db.session.add(receipt)
        db.session.flush()

        # سند التحصيل دائمًا يسجل قيد (طبيعي لأنه سند محاسبي)
        journal_entry_id = create_journal_for_cash_receipt(receipt)

        db.session.commit()

        return jsonify({
            "message": "✅ تم إنشاء سند التحصيل النقدي وتسجيل القيد المحاسبي",
            "id": receipt.id,
            "receipt": receipt.to_dict(),
            "journal_entry_id": journal_entry_id,
        }), 201

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": f"DB error: {str(e)}"}), 500


@app.route("/api/receipts/<int:receipt_id>", methods=["GET"])
def receipt_get_one(receipt_id):
    rc = CashReceipt.query.filter_by(id=receipt_id).first()
    if not rc:
        return jsonify({"error": "السند غير موجود"}), 404
    return jsonify(rc.to_dict())


# ---------------- Auto create tables + ensure core accounts ----------------
with app.app_context():
    try:
        db.create_all()
        ensure_core_accounts()
    except Exception as e:
        print("❌ DB init error:", e)
        traceback.print_exc()


# ---------------- Run (local) ----------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)

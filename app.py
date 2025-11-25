# ======================================================
# 🚗 Flask Authorization System — Weekly Authorizations + Accounting + Cash Receipts
# ======================================================

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
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
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if not DATABASE_URL:
    raise ValueError("❌ لم يتم ضبط متغير البيئة DATABASE_URL (أو POSTGRES_URL) في Vercel")

# إصلاح مخطط الرابط القديم إن وجد
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


# ---------------- Helpers ----------------
def get_friday_end(base_dt: datetime) -> datetime:
    """
    تحسب نهاية يوم الجمعة الأولى بعد التاريخ المعطى (تشمل نفس اليوم لو هو جمعة).
    """
    weekday = base_dt.weekday()  # Monday=0 ... Friday=4 ... Sunday=6
    if weekday <= 4:  # قبل الجمعة أو نفس اليوم
        days_to_friday = 4 - weekday
    else:  # بعد الجمعة (سبت أو أحد)
        days_to_friday = 7 - (weekday - 4)

    friday = base_dt + timedelta(days=days_to_friday)
    friday_end = friday.replace(hour=23, minute=59, second=59, microsecond=0)
    return friday_end


# ---------------- Models ----------------
class Authorization(db.Model):
    __tablename__ = "authorizations"

    id = db.Column(db.Integer, primary_key=True)

    issue_date = db.Column(db.DateTime, default=datetime.utcnow)  # تاريخ إصدار التفويض
    driver_name = db.Column(db.String(100), nullable=False)
    driver_license_no = db.Column(db.String(60))  # رقم رخصة السائق (للبحث السريع)

    # 🔹 ربط التفويض بسائق محدد
    driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"), nullable=True)

    car_number = db.Column(db.String(50), nullable=False)
    car_model = db.Column(db.String(50))
    car_type = db.Column(db.String(50))

    start_date = db.Column(db.DateTime)  # تاريخ بداية التفويض (فعلي)
    daily_rent = db.Column(db.Numeric(10, 2))
    details = db.Column(db.Text)
    status = db.Column(db.String(50))  # مؤجرة / منتهية

    # نستخدم end_date كتاريخ نهاية التفويض (الجمعة) وليس تاريخ الإقفال
    end_date = db.Column(db.DateTime, nullable=True)  # تاريخ نهاية التفويض (الجمعة)
    close_date = db.Column(db.DateTime, nullable=True)  # تاريخ الإقفال الفعلي (زر الإنهاء)

    # 🔹 قيمة التفويض النهائية + ملاحظة الإقفال
    closed_amount = db.Column(db.Numeric(12, 2), nullable=True)
    closing_note = db.Column(db.Text)

    def to_dict(self):
        """
        حساب عدد الأيام والمبلغ:
        من start_date (لو موجود، وإلا issue_date) → end_date (الجمعة)
        مع تجاهل الساعات + إضافة يوم.
        """
        rental_days = None
        planned_amount = None

        # الأساس في العد = start_date لو موجود، غير كده نرجع لـ issue_date
        base_start = self.start_date or self.issue_date

        if base_start and self.end_date and self.daily_rent is not None:
            try:
                start_d = base_start.date()
                end_d = self.end_date.date()
                days = (end_d - start_d).days + 1  # +1 عشان يشمل يوم البداية
                if days < 0:
                    days = 0
                rental_days = days
                planned_amount = float(self.daily_rent) * days
            except Exception:
                pass

        return {
            "id": self.id,
            # 4 تواريخ أساسية
            "issue_date": self.issue_date.strftime("%Y-%m-%d %H:%M:%S") if self.issue_date else "",
            "start_date": self.start_date.isoformat() if self.start_date else None,
            # نستخدم end_date كتاريخ نهاية الجمعة (planned_end_date)
            "end_date": self.end_date.strftime("%Y-%m-%d %H:%M:%S") if self.end_date else "",
            "planned_end_date": self.end_date.strftime("%Y-%m-%d %H:%M:%S") if self.end_date else "",
            "close_date": self.close_date.strftime("%Y-%m-%d %H:%M:%S") if self.close_date else "",
            # بيانات السائق
            "driver_name": self.driver_name,
            "driver_license_no": self.driver_license_no,
            "driver_id": self.driver_id,
            # بيانات السيارة
            "car_number": self.car_number,
            "car_model": self.car_model,
            "car_type": self.car_type,
            # مالية
            "daily_rent": float(self.daily_rent or 0),
            "details": self.details,
            "status": self.status,
            # معلومات مساعدة للحسابات
            "rental_days": rental_days,
            "planned_amount": planned_amount,
            # بيانات الإقفال
            "closed_amount": float(self.closed_amount or 0) if self.closed_amount is not None else None,
            "closing_note": self.closing_note,
        }


class Car(db.Model):
    __tablename__ = "cars"

    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(80))
    car_type = db.Column(db.String(80))
    status = db.Column(db.String(50), default="متاحة")  # متاحة / مؤجرة / تحت الصيانة
    daily_rent = db.Column(db.Numeric(10, 2))

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

    # 🔹 كل التفويضات المرتبطة بالسائق
    authorizations = db.relationship("Authorization", backref="driver", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "license_no": self.license_no,
        }


# ===== Accounting Models =====
class Account(db.Model):
    """
    جدول الحسابات (دليل الحسابات المبسط)
    مثال: "حساب السائقين", "إيراد إيجار سيارات", "الصندوق"
    """
    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    type = db.Column(db.String(50))  # asset / liability / revenue / expense ...

    # 🔹 دعم شجرة الحسابات (حساب أب / فرعي)
    parent_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)
    is_group = db.Column(db.Boolean, default=False)

    related_driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"), nullable=True)
    related_car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=True)

    related_driver = db.relationship("Driver", backref="accounts", lazy=True)
    related_car = db.relationship("Car", backref="accounts", lazy=True)

    # 🔹 علاقة الأب / الأبناء داخل نفس الجدول
    parent = db.relationship(
        "Account",
        remote_side=[id],
        backref="children",
        lazy=True,
    )

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
    """
    سند تحصيل نقدي cash_receipts
    يمثل قبض نقدي من السائق (أو العميل) عن تفويض معيّن.
    """
    __tablename__ = "cash_receipts"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"), nullable=True)
    driver_name = db.Column(db.String(100))
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    description = db.Column(db.String(255))
    ref_authorization_id = db.Column(db.Integer, db.ForeignKey("authorizations.id"), nullable=True)

    driver = db.relationship("Driver", backref="cash_receipts", lazy=True)
    authorization = db.relationship("Authorization", backref="cash_receipts", lazy=True)

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
    """
    رأس اليومية journal_entries
    """
    __tablename__ = "journal_entries"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    description = db.Column(db.String(255))
    ref_authorization_id = db.Column(db.Integer, db.ForeignKey("authorizations.id"), nullable=True)
    ref_receipt_id = db.Column(db.Integer, db.ForeignKey("cash_receipts.id"), nullable=True)

    authorization = db.relationship("Authorization", backref="journal_entries", lazy=True)
    receipt = db.relationship("CashReceipt", backref="journal_entries", lazy=True)

    def to_dict(self, with_lines: bool = False):
        """
        تم توسيع الـ dict عشان نخدم صفحة العمليات:
        - source_type: auth_close / receipt / manual
        - driver_name / car_number لو متاحة من التفويض أو السند
        - ref_text: نص عربي بسيط يوضح المرجع
        """
        # تحديد نوع المصدر
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

        # محاولة جلب اسم السائق ورقم السيارة من العلاقات
        driver_name = None
        car_number = None

        auth = self.authorization
        receipt = self.receipt

        if auth:
            driver_name = auth.driver_name
            car_number = auth.car_number
        elif receipt:
            # من السند نفسه
            driver_name = receipt.driver_name or (receipt.driver.name if receipt.driver else None)
            # لو السند مربوط بتفويض نجيب رقم العربية
            if receipt.authorization:
                car_number = receipt.authorization.car_number

        base = {
            "id": self.id,
            "date": self.date.strftime("%Y-%m-%d %H:%M:%S") if self.date else "",
            "description": self.description,
            "ref_authorization_id": self.ref_authorization_id,
            "ref_receipt_id": self.ref_receipt_id,
            # الحقول الجديدة لصفحة العمليات
            "source_type": source_type,     # auth_close / receipt / manual
            "driver_name": driver_name,     # لو متوفر
            "car_number": car_number,       # لو متوفر
            "ref_text": ref_text,           # نص المرجع بالعربي
        }
        if with_lines:
            base["lines"] = [ln.to_dict() for ln in self.lines]
        return base


class JournalLine(db.Model):
    """
    بنود اليومية journal_lines
    """
    __tablename__ = "journal_lines"

    id = db.Column(db.Integer, primary_key=True)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id"), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    debit = db.Column(db.Numeric(12, 2), default=0)
    credit = db.Column(db.Numeric(12, 2), default=0)

    journal_entry = db.relationship("JournalEntry", backref="lines", lazy=True)
    account = db.relationship("Account", backref="lines", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "journal_entry_id": self.journal_entry_id,
            "account_id": self.account_id,
            # ✅ عشان صفحة العمليات تقدر تعرض اسم الحساب وكوده
            "account_name": self.account.name if self.account else None,
            "account_code": str(self.account.id) if self.account else None,
            "debit": float(self.debit or 0),
            "credit": float(self.credit or 0),
        }


# ---------------- Accounting Helpers ----------------
def ensure_driver_root_account():
    """
    يتأكد إن حساب (مجموعة) رئيسي للسائقين موجود،
    ولو مش موجود ينشئ: "حساب السائقين" من نوع أصل (asset).
    """
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
    """
    يتأكد إن لكل سائق حساب فرعي مربوط بـ related_driver_id.
    لو مش موجود ينشئه تحت حساب "حساب السائقين" الرئيسي.
    """
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


def create_journal_for_closed_authorization(auth, total_amount):
    """
    ينشئ قيد يومية عند إقفال التفويض:
    من حـ/ السائق (الفرعي إن وجد) أو حـ/ السائقين العام (مدين)
    إلى حـ/ إيراد إيجار سيارات (دائن)
    """
    try:
        if not total_amount or total_amount <= 0:
            return

        revenue_account = Account.query.filter_by(name="سلف سائقين").first()
        if not revenue_account:
            # لو حساب الإيراد مش موجود ما نعملش قيد
            return

        driver_account = None
        if auth and auth.driver_id:
            # نحاول نستخدم حساب السائق الفرعي
            driver_account = ensure_driver_sub_account(auth.driver)

        if not driver_account:
            # fallback على الحساب العام للسائقين
            driver_account = ensure_driver_root_account()

        if not driver_account:
            return

        je = JournalEntry(
            date=datetime.utcnow(),
            description=f"قيد إقفال تفويض رقم {auth.id}" if auth else "قيد إقفال تفويض",
            ref_authorization_id=auth.id if auth else None,
        )
        db.session.add(je)
        db.session.flush()  # عشان je.id يتولد

        amount_dec = Decimal(str(total_amount))

        # من حـ/ السائق / السائقين (مدين)
        line1 = JournalLine(
            journal_entry_id=je.id,
            account_id=driver_account.id,
            debit=amount_dec,
            credit=Decimal("0"),
        )

        # إلى حـ/ إيراد إيجار سيارات (دائن)
        line2 = JournalLine(
            journal_entry_id=je.id,
            account_id=revenue_account.id,
            debit=Decimal("0"),
            credit=amount_dec,
        )

        db.session.add_all([line1, line2])
        # مفيش commit هنا؛ الـ Route نفسه هو اللي بيعمل commit
    except Exception:
        traceback.print_exc()


def create_journal_for_cash_receipt(receipt: CashReceipt):
    """
    ينشئ قيد يومية لسند تحصيل نقدي:
    من حـ/ الصندوق (مدين)
    إلى حـ/ حساب السائق (الفرعي إن وجد) أو حـ/ السائقين العام (دائن)
    """
    try:
        if not receipt or not receipt.amount or receipt.amount <= 0:
            return

        cash_account = Account.query.filter_by(name="الصندوق").first()
        if not cash_account:
            # بدون حساب الصندوق ما نقدرش نعمل قيد
            return

        driver_account = None
        if receipt.driver_id:
            driver_account = ensure_driver_sub_account(receipt.driver)

        if not driver_account:
            driver_account = ensure_driver_root_account()

        if not driver_account:
            return

        je = JournalEntry(
            date=receipt.date or datetime.utcnow(),
            description=receipt.description or f"سند تحصيل نقدي رقم {receipt.id}",
            ref_authorization_id=receipt.ref_authorization_id,
            ref_receipt_id=receipt.id,
        )
        db.session.add(je)
        db.session.flush()

        amount_dec = Decimal(str(receipt.amount))

        # من حـ/ الصندوق (مدين)
        line1 = JournalLine(
            journal_entry_id=je.id,
            account_id=cash_account.id,
            debit=amount_dec,
            credit=Decimal("0"),
        )

        # إلى حـ/ حساب السائق (دائن)
        line2 = JournalLine(
            journal_entry_id=je.id,
            account_id=driver_account.id,
            debit=Decimal("0"),
            credit=amount_dec,
        )

        db.session.add_all([line1, line2])
        # الـ commit في الـ Route
    except Exception:
        traceback.print_exc()


# ---------------- Routes (Pages) ----------------
@app.route("/")
def index_page():
    return render_template("index.html")


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

                    @app.route("/receipts-list")
                    def operations_page():
                        return render_template("receipts-list.html")

                    @app.route("/journal-list")
                    def operations_page():
                        return render_template("journal-list.html")


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})


@app.route("/api/debug/dburl")
def api_debug_dburl():
    return jsonify(
        {"DATABASE_URL_present": bool(os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL"))}
    )


# ---------------- APIs ----------------
# إصدار تفويض جديد
@app.route("/api/issue", methods=["POST"])
def add_authorization():
    try:
        data = request.get_json() or {}

        # 0) تحقق من الحقول الأساسية
        driver_name = (data.get("driver_name") or "").strip()
        car_plate = (data.get("car_number") or "").strip()
        if not driver_name:
            return jsonify({"error": "برجاء اختيار السائق"}), 400
        if not car_plate:
            return jsonify({"error": "برجاء اختيار السيارة"}), 400

        # 1) السيارة + حالتها
        car = Car.query.filter_by(plate=car_plate).first()
        if not car:
            return jsonify({"error": "السيارة غير موجودة في قاعدة البيانات"}), 400
        if (car.status or "").strip() != "متاحة":
            return jsonify({"error": f"السيارة غير متاحة حالياً (الحالة: {car.status})"}), 400

        # 2) منع ازدواج التفويض المفتوح (بناء على close_date)
        open_auth = (
            Authorization.query.filter_by(car_number=car_plate)
            .filter(Authorization.close_date.is_(None))
            .first()
        )
        if open_auth:
            return jsonify({"error": "هناك تفويض مفتوح لهذه السيارة بالفعل"}), 400

        # 3) جلب رقم رخصة السائق (اختياري)
        driver_obj = Driver.query.filter_by(name=driver_name).first()
        driver_license_no = driver_obj.license_no if driver_obj and driver_obj.license_no else None

        # 4) تجهيز التاريخ
        issue_date = datetime.utcnow()

        start_date = None
        sd = (data.get("start_date") or "").strip()
        if sd:
            try:
                start_date = datetime.fromisoformat(sd)
            except Exception:
                return jsonify(
                    {
                        "error": "صيغة التاريخ غير صحيحة. استخدم ISO 8601 مثل 2025-11-12T10:30",
                    }
                ), 400
        # لو ما فيش start_date نستخدم issue_date
        if not start_date:
            start_date = issue_date

        # 5) حساب نهاية التفويض: أول جمعة بعد تاريخ بداية التفويض (start_date)
        planned_end = get_friday_end(start_date)

        # 6) الموديل/النوع/الإيجار
        car_model = data.get("car_model") or car.model
        car_type = data.get("car_type") or car.car_type

        # الإيجار اليومي: لو مبعوت استخدمه بعد تحويله لDecimal، وإلا خُد من العربية
        daily_rent = car.daily_rent
        if data.get("daily_rent") not in (None, "", " "):
            try:
                daily_rent = Decimal(str(data.get("daily_rent")))
            except (InvalidOperation, ValueError, TypeError):
                return jsonify({"error": "قيمة الإيجار اليومي غير صحيحة"}), 400

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
            end_date=planned_end,  # تاريخ الجمعة (planned_end_date)
            close_date=None,
        )

        try:
            db.session.add(new_auth)
            car.status = "مؤجرة"
            db.session.commit()
            return jsonify(
                {
                    "message": "✅ Authorization added successfully",
                    "authorization": new_auth.to_dict(),
                }
            ), 201
        except Exception as e:
            db.session.rollback()
            traceback.print_exc()
            return jsonify({"error": f"DB error: {str(e)}"}), 500

    except Exception as outer:
        traceback.print_exc()
        return jsonify({"error": f"Server error: {str(outer)}"}), 500


# جلب كل التفويضات (مع فلترة اختيارية)
@app.route("/api/authorizations", methods=["GET"])
def get_authorizations():
    """
    إرجاع قائمة التفويضات مع دعم فلترة اختيارية:
    - ?status=active  → تفويضات مفتوحة (close_date IS NULL)
    - ?status=closed  → تفويضات مغلقة (close_date IS NOT NULL)
    - ?car_number=123 → البحث برقم السيارة (contains)
    - ?license_no=ABC → البحث برقم رخصة السائق (contains)
    """
    query = Authorization.query

    status_param = (request.args.get("status") or "").strip().lower()
    if status_param == "active":
        query = query.filter(Authorization.close_date.is_(None))
    elif status_param == "closed":
        query = query.filter(Authorization.close_date.is_not(None))

    car_number = (request.args.get("car_number") or "").strip()
    if car_number:
        like = f"%{car_number}%"
        query = query.filter(Authorization.car_number.ilike(like))

    license_no = (request.args.get("license_no") or "").strip()
    if license_no:
        like = f"%{license_no}%"
        query = query.filter(Authorization.driver_license_no.ilike(like))

    auths = query.order_by(Authorization.id.desc()).all()
    return jsonify([a.to_dict() for a in auths])


@app.route("/api/authorizations/closed", methods=["GET"])
def get_closed_authorizations():
    """تفويضات مغلقة فقط (close_date IS NOT NULL)."""
    auths = (
        Authorization.query.filter(Authorization.close_date.is_not(None))
        .order_by(Authorization.id.desc())
        .all()
    )
    return jsonify([a.to_dict() for a in auths])


@app.route("/api/authorizations/active", methods=["GET"])
def get_active_authorizations():
    """تفويضات مفتوحة فقط (close_date IS NULL)."""
    auths = (
        Authorization.query.filter(Authorization.close_date.is_(None))
        .order_by(Authorization.id.desc())
        .all()
    )
    return jsonify([a.to_dict() for a in auths])


# إنهاء تفويض (يستخدم من زر الإنهاء) ✅ نسخة محدثة مع اختيار التجديد
@app.route("/api/authorizations/<int:auth_id>/end", methods=["PATCH"])
def end_authorization(auth_id):
    """
    إنهاء تفويض:
    - يقفل التفويض الحالي (close_date, closed_amount, closing_note, status="منتهية")
    - ينشئ قيد إقفال تفويض في اليومية (دايمًا لو فيه مبلغ)
    - حسب اختيار الفرونت إند:
        * renew = true  ⇒ إنشاء تفويض جديد للأسبوع التالي + تظل السيارة "مؤجرة"
        * renew = false ⇒ عدم إنشاء تفويض جديد + تحويل السيارة إلى "متاحة"
    - يرجع أيضًا suggested_receipt عشان تفتح بها شاشة سند تحصيل تلقائي.
    """
    auth = Authorization.query.get(auth_id)
    if not auth:
        return jsonify({"error": "التفويض غير موجود"}), 404
    if auth.close_date:
        return jsonify({"error": "التفويض منتهي بالفعل"}), 400

    car = Car.query.filter_by(plate=auth.car_number).first()

    try:
        # 🔹 قراءة بيانات الإقفال من الطلب
        data = request.get_json(silent=True) or {}

        # ✅ اختيار التجديد أو لا:
        #  - renew (bool) أو renew_option في الـ body
        renew_raw = data.get("renew")
        if renew_raw is None:
            renew_raw = data.get("renew_option")  # اسم بديل لو حبيت تستخدمه في الفرونت

        # القيمة الافتراضية = True عشان توافق السلوك القديم (تجديد تلقائي)
        renew = True
        if isinstance(renew_raw, bool):
            renew = renew_raw
        elif isinstance(renew_raw, (int, float)):
            renew = bool(renew_raw)
        elif isinstance(renew_raw, str):
            renew = renew_raw.strip().lower() in ("1", "true", "yes", "y", "renew", "تجديد")

        closing_note = (data.get("closing_note") or "").strip() or None
        closed_amount_input = data.get("closed_amount")

        # تاريخ الإقفال الفعلي
        close_dt = datetime.utcnow()
        auth.close_date = close_dt
        auth.status = "منتهية"

        # لو end_date (نهاية الجمعة) مش متخزّن لأي سبب، نحسبه الآن من start_date أو issue_date
        if not auth.end_date:
            base_for_end = auth.start_date or auth.issue_date
            if base_for_end:
                auth.end_date = get_friday_end(base_for_end)

        # ✅ حساب عدد الأيام والمبلغ المحاسبي (start_date → end_date)
        rental_days = None
        auto_amount = None
        base_start = auth.start_date or auth.issue_date
        if base_start and auth.end_date and auth.daily_rent is not None:
            start_d = base_start.date()
            end_d = auth.end_date.date()
            days = (end_d - start_d).days + 1  # +1 يشمل يوم البداية
            if days < 0:
                days = 0
            rental_days = days
            auto_amount = float(auth.daily_rent) * days

        # 🔹 تحديد المبلغ النهائي: يدوي من المودال أو المحسوب تلقائيًا
        final_amount = auto_amount
        closed_amount_dec = None

        if closed_amount_input not in (None, "", " "):
            try:
                closed_amount_dec = Decimal(str(closed_amount_input))
                if closed_amount_dec <= 0:
                    closed_amount_dec = None
                else:
                    final_amount = float(closed_amount_dec)
            except (InvalidOperation, ValueError, TypeError):
                closed_amount_dec = None

        # لو ما تمش إدخال مبلغ يدوي صالح، نخزن المحسوب تلقائيًا داخل closed_amount لو موجود
        if closed_amount_dec is None and auto_amount is not None:
            closed_amount_dec = Decimal(str(round(auto_amount, 2)))

        # حفظ المبلغ والملاحظة في جدول التفويض
        auth.closed_amount = closed_amount_dec
        auth.closing_note = closing_note

        # 🎯 إنشاء قيد اليومية لهذا التفويض المقفول (لو فيه مبلغ نهائي)
        if final_amount and final_amount > 0:
            create_journal_for_closed_authorization(auth, final_amount)

        new_auth = None  # احتمال يكون فيه تفويض جديد أو لا حسب الاختيار

        # 🔁 لو اختارت تجديد: نعمل تفويض جديد للأسبوع القادم ونخلي العربية "مؤجرة"
        if renew:
            if auth.end_date:
                new_issue = auth.end_date + timedelta(days=1)  # السبت التالي
            else:
                new_issue = close_dt + timedelta(days=1)

            # نخلي الساعة 09:00 (تقديرية)
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

            # السيارة تظل "مؤجرة"
            if car:
                car.status = "مؤجرة"
        else:
            # ❌ عدم التجديد → السيارة ترجع "متاحة"
            if car:
                car.status = "متاحة"

        db.session.commit()

        # 🔗 تجهيز بيانات سند تحصيل تلقائي (الفرونت إند يفتح /receipt بهذه البيانات)
        suggested_receipt = {
            "authorization_id": auth.id,
            "driver_id": auth.driver_id,
            "driver_name": auth.driver_name,
            "default_amount": final_amount,
            "description": f"سداد عن تفويض رقم {auth.id}",
        }

        if renew:
            message = "✅ تم إقفال التفويض وإنشاء تفويض جديد للأسبوع التالي مع تسجيل قيد اليومية"
        else:
            message = "✅ تم إقفال التفويض وتحويل السيارة إلى متاحة مع تسجيل قيد اليومية (بدون إنشاء تفويض جديد)"

        response = {
            "message": message,
            "closed_authorization": auth.to_dict(),
            "new_authorization": new_auth.to_dict() if new_auth else None,
            "rental_days": rental_days,
            "total_amount": final_amount,
            "renew": renew,
            "suggested_receipt": suggested_receipt,
        }

        return jsonify(response), 200

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

        car = Car(
            plate=plate,
            model=data.get("model"),
            car_type=data.get("car_type"),
            daily_rent=Decimal(str(data.get("daily_rent"))) if data.get("daily_rent") else None,
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
    """
    GET  → يرجع قائمة الحسابات (لـ Dropdown + جدول العرض)
    POST → إضافة حساب جديد (من صفحة accounts.html)
    """
    if request.method == "GET":
        accounts = Account.query.order_by(Account.id.asc()).all()
        return jsonify([acc.to_dict() for acc in accounts])

    # POST
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "اسم الحساب مطلوب"}), 400

    # منع تكرار الاسم
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
    """
    إنشاء حساب فرعي لسائق داخل شجرة حساب "حساب السائقين".
    تُستخدم من صفحة drivers.html بعد إضافة السائق.
    """
    data = request.get_json() or {}

    driver_id = data.get("driver_id")
    if not driver_id:
        return jsonify({"error": "driver_id مطلوب"}), 400

    driver = Driver.query.get(driver_id)
    if not driver:
        return jsonify({"error": "السائق غير موجود في قاعدة البيانات"}), 404

    # لو الحساب موجود مسبقاً، نرجّعه بدل ما نكرّره
    existing = Account.query.filter_by(related_driver_id=driver.id).first()
    if existing:
        return jsonify(
            {
                "message": "✅ الحساب الخاص بالسائق موجود بالفعل",
                "account": existing.to_dict(),
                "already_exists": True,
            }
        ), 200

    try:
        acc = ensure_driver_sub_account(driver)
        db.session.commit()
        return jsonify(
            {
                "message": "✅ تم إنشاء حساب فرعي للسائق في شجرة الحسابات",
                "account": acc.to_dict(),
            }
        ), 201
    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": f"DB error: {str(e)}"}), 500


# ----- Ledger API -----



@app.route("/api/accounts/<int:account_id>/ledger", methods=["GET"])
def get_account_ledger(account_id):
    """
    دفتر أستاذ مبسط لحساب واحد:
    يرجع جميع بنود اليومية المرتبطة بالحساب مع رصيد تراكمي.
    """
    account = Account.query.get(account_id)
    if not account:
        return jsonify({"error": "الحساب غير موجود"}), 404

    # نرتّب حسب تاريخ القيد ثم رقم السطر
    lines = (
        JournalLine.query.join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
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

        ledger_rows.append(
            {
                "entry_id": je.id,
                "date": je.date.strftime("%Y-%m-%d %H:%M:%S") if je.date else "",
                "description": je.description,
                "debit": float(debit or 0),
                "credit": float(credit or 0),
                "balance": float(running_balance),
            }
        )

    return jsonify({"account": account.to_dict(), "lines": ledger_rows})


# ----- General Journal APIs (لليومية العامة) -----



@app.route("/api/journal_entries", methods=["GET", "POST"])
def journal_entries_api():
    """
    GET  → قائمة بسيطة بقيود اليومية (تستخدمها صفحة general.html و operations.html)
    POST → إنشاء قيد يدوي (من صفحة اليومية العامة)
    """
    if request.method == "GET":
        entries = JournalEntry.query.order_by(JournalEntry.date.desc(), JournalEntry.id.desc()).all()
        return jsonify([e.to_dict(with_lines=True) for e in entries])

    # POST – إنشاء قيد يدوي
    data = request.get_json() or {}
    desc = (data.get("description") or "").strip()
    date_str = (data.get("date") or "").strip()
    lines_data = data.get("lines") or []

    if not lines_data:
        return jsonify({"error": "لا يوجد بنود في القيد"}), 400

    # تحويل التاريخ لو مبعوت، وإلا نستخدم الآن
    je_date = datetime.utcnow()
    if date_str:
        try:
            je_date = datetime.fromisoformat(date_str)
        except Exception:
            return jsonify({"error": "صيغة التاريخ غير صحيحة. استخدم ISO 8601"}), 400

    je = JournalEntry(date=je_date, description=desc)
    db.session.add(je)
    db.session.flush()

    try:
        for ln in lines_data:
            acc_id = ln.get("account_id")
            if not acc_id:
                continue
            acc = Account.query.get(acc_id)
            if not acc:
                continue

            debit_val = ln.get("debit") or 0
            credit_val = ln.get("credit") or 0

            try:
                debit_dec = (
                    Decimal(str(debit_val)) if debit_val not in (None, "", " ") else Decimal("0")
                )
                credit_dec = (
                    Decimal(str(credit_val)) if credit_val not in (None, "", " ") else Decimal("0")
                )
            except (InvalidOperation, ValueError, TypeError):
                continue

            line = JournalLine(
                journal_entry_id=je.id,
                account_id=acc.id,
                debit=debit_dec,
                credit=credit_dec,
            )
            db.session.add(line)

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": f"DB error: {str(e)}"}), 500

    return jsonify(
        {"message": "✅ تم إنشاء قيد اليومية بنجاح", "journal_entry": je.to_dict(with_lines=True)}
    ), 201


# 🔹 API جديد: قيود يدوية فقط (بدون تفويض وبدون سند تحصيل)
@app.route("/api/journal_entries/manual", methods=["GET"])
def manual_journal_entries_api():
    """
    يرجع فقط القيود اليدوية (التي ليس لها ref_authorization_id ولا ref_receipt_id)
    لاستخدامها في صفحة عرض القيود اليدوية.
    """
    entries = (
        JournalEntry.query
        .filter(JournalEntry.ref_authorization_id.is_(None))
        .filter(JournalEntry.ref_receipt_id.is_(None))
        .order_by(JournalEntry.date.desc(), JournalEntry.id.desc())
        .all()
    )
    return jsonify([e.to_dict(with_lines=True) for e in entries])


# ----- Cash Receipts APIs (سندات التحصيل النقدي) -----



@app.route("/api/receipts", methods=["GET", "POST"])
def receipts_api():
    """
    GET  → يرجع قائمة سندات التحصيل النقدي.
    POST → إنشاء سند تحصيل نقدي جديد + قيد محاسبي (من /receipt.html).
    """
    if request.method == "GET":
        receipts = CashReceipt.query.order_by(CashReceipt.date.desc(), CashReceipt.id.desc()).all()
        return jsonify([r.to_dict() for r in receipts])

    # POST – إنشاء سند تحصيل
    data = request.get_json() or {}

    driver_name = (data.get("driver_name") or "").strip()
    driver_id = data.get("driver_id")
    auth_id = data.get("authorization_id")
    desc = (data.get("description") or "").strip()
    amount_val = data.get("amount")
    date_str = (data.get("date") or "").strip()

    if amount_val in (None, "", " "):
        return jsonify({"error": "قيمة المبلغ مطلوبة"}), 400

    try:
        amount_dec = Decimal(str(amount_val))
    except (InvalidOperation, ValueError, TypeError):
        return jsonify({"error": "قيمة المبلغ غير صحيحة"}), 400

    if amount_dec <= 0:
        return jsonify({"error": "قيمة المبلغ يجب أن تكون أكبر من صفر"}), 400

    # التاريخ
    rc_date = datetime.utcnow()
    if date_str:
        try:
            rc_date = datetime.fromisoformat(date_str)
        except Exception:
            return jsonify({"error": "صيغة التاريخ غير صحيحة. استخدم ISO 8601"}), 400

    # لو عندك driver_id مش مبعوت لكن الاسم موجود، نحاول نجيبه
    driver_obj = None
    if driver_id:
        driver_obj = Driver.query.get(driver_id)
    elif driver_name:
        driver_obj = Driver.query.filter_by(name=driver_name).first()

    if driver_obj and not driver_name:
        driver_name = driver_obj.name

    # تفويض مرجعي اختياري
    auth_obj = None
    if auth_id:
        auth_obj = Authorization.query.get(auth_id)

    receipt = CashReceipt(
        date=rc_date,
        driver_id=driver_obj.id if driver_obj else None,
        driver_name=driver_name or (driver_obj.name if driver_obj else None),
        amount=amount_dec,
        description=desc or (f"سداد عن تفويض رقم {auth_obj.id}" if auth_obj else "سند تحصيل نقدي"),
        ref_authorization_id=auth_obj.id if auth_obj else None,
    )

    try:
        db.session.add(receipt)
        db.session.flush()  # عشان receipt.id

        # إنشاء قيد اليومية (من الصندوق إلى حساب السائقين)
        create_journal_for_cash_receipt(receipt)

        db.session.commit()
        return jsonify(
            {
                "message": "✅ تم إنشاء سند التحصيل النقدي وتسجيل القيد المحاسبي",
                "receipt": receipt.to_dict(),
            }
        ), 201

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": f"DB error: {str(e)}"}), 500


# ---------------- Auto create tables ----------------
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        # في حالة أي خطأ أثناء إنشاء الجداول
        print("❌ DB create_all error:", e)


# ---------------- Run (local) ----------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)



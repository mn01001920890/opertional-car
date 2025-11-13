# ======================================================
# 🚗 Flask Authorization System — Weekly Authorizations (Friday Logic)
# ======================================================

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import os
import traceback


app = Flask(__name__)

# ---------------- Favicon ----------------
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
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
    id          = db.Column(db.Integer, primary_key=True)
    issue_date  = db.Column(db.DateTime, default=datetime.utcnow)  # تاريخ إصدار التفويض
    driver_name = db.Column(db.String(100), nullable=False)
    driver_license_no = db.Column(db.String(60))  # رقم رخصة السائق (للبحث السريع)
    car_number  = db.Column(db.String(50),  nullable=False)
    car_model   = db.Column(db.String(50))
    car_type    = db.Column(db.String(50))
    start_date  = db.Column(db.DateTime)          # تاريخ بداية التفويض (فعلي)
    daily_rent  = db.Column(db.Numeric(10, 2))
    details     = db.Column(db.Text)
    status      = db.Column(db.String(50))        # مؤجرة / منتهية
    # ⚠️ مهم: نستخدم end_date كتاريخ نهاية التفويض (الجمعة) وليس تاريخ الإقفال
    end_date    = db.Column(db.DateTime, nullable=True)   # تاريخ نهاية التفويض (الجمعة)
    close_date  = db.Column(db.DateTime, nullable=True)   # تاريخ الإقفال الفعلي (زر الإنهاء)

    def to_dict(self):
        # حساب عدد الأيام والمبلغ (محسوبين على أساس issue_date → end_date)
        rental_days = None
        planned_amount = None
        if self.issue_date and self.end_date and self.daily_rent is not None:
            try:
                days = (self.end_date.date() - self.issue_date.date()).days + 1
                days = max(days, 0)
                rental_days = days
                planned_amount = float(self.daily_rent) * days
            except Exception:
                pass

        return {
            "id": self.id,
            # 4 تواريخ أساسية
            "issue_date": self.issue_date.strftime("%Y-%m-%d %H:%M:%S") if self.issue_date else "",
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date":   self.end_date.strftime("%Y-%m-%d %H:%M:%S") if self.end_date else "",
            "close_date": self.close_date.strftime("%Y-%m-%d %H:%M:%S") if self.close_date else "",
            # بيانات السائق
            "driver_name": self.driver_name,
            "driver_license_no": self.driver_license_no,
            # بيانات السيارة
            "car_number": self.car_number,
            "car_model":  self.car_model,
            "car_type":   self.car_type,
            # مالية
            "daily_rent": float(self.daily_rent or 0),
            "details": self.details,
            "status":  self.status,
            # معلومات مساعدة للحسابات
            "rental_days": rental_days,
            "planned_amount": planned_amount
        }


class Car(db.Model):
    __tablename__ = "cars"
    id         = db.Column(db.Integer, primary_key=True)
    plate      = db.Column(db.String(50), nullable=False)
    model      = db.Column(db.String(80))
    car_type   = db.Column(db.String(80))
    status     = db.Column(db.String(50), default="متاحة")  # متاحة / مؤجرة / تحت الصيانة
    daily_rent = db.Column(db.Numeric(10, 2))

    def to_dict(self):
        return {
            "id": self.id,
            "plate": self.plate,
            "model": self.model,
            "car_type": self.car_type,
            "status": self.status,
            "daily_rent": float(self.daily_rent or 0)
        }


class Driver(db.Model):
    __tablename__ = "drivers"
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    phone       = db.Column(db.String(30))
    license_no  = db.Column(db.String(60))

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "license_no": self.license_no
        }


with app.app_context():
    db.create_all()


# ---------------- Pages ----------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/issue")
def issue_page():
    return render_template("issue.html")

@app.route("/view")
def view_page():
    return render_template("view.html")

@app.route("/drivers")
def drivers_page():
    return render_template("drivers.html")

@app.route("/cars")
def cars_page():
    return render_template("cars.html")

@app.route("/rented")
def rented_cars_page():
    return render_template("rented.html")

@app.route("/cars-status")
def cars_status_page():
    return render_template("cars-status.html")


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True})

@app.route("/api/debug/dburl")
def api_debug_dburl():
    # خليك مطمن إن DATABASE_URL متضبوطة على Vercel
    return jsonify({"DATABASE_URL_present": bool(os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL"))})


# ---------------- APIs ----------------
# إصدار تفويض جديد
@app.route("/api/issue", methods=["POST"])
def add_authorization():
    try:
        data = request.get_json() or {}

        # 0) تحقق من الحقول الأساسية
        driver_name = (data.get("driver_name") or "").strip()
        car_plate   = (data.get("car_number") or "").strip()
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
            Authorization.query
            .filter_by(car_number=car_plate)
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
                return jsonify({"error": "صيغة التاريخ غير صحيحة. استخدم ISO 8601 مثل 2025-11-12T10:30"}), 400
        # لو ما فيش start_date نستخدم issue_date
        if not start_date:
            start_date = issue_date

        # 5) حساب نهاية التفويض: أول جمعة بعد issue_date (نهاية اليوم)
        planned_end = get_friday_end(issue_date)

        # 6) الموديل/النوع/الإيجار
        car_model = data.get("car_model") or car.model
        car_type  = data.get("car_type") or car.car_type

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
            car_number=car_plate,
            car_model=car_model,
            car_type=car_type,
            issue_date=issue_date,
            start_date=start_date,
            daily_rent=daily_rent,
            details=data.get("details"),
            status="مؤجرة",
            end_date=planned_end,   # تاريخ الجمعة
            close_date=None
        )

        try:
            db.session.add(new_auth)
            car.status = "مؤجرة"
            db.session.commit()
            return jsonify({"message": "✅ Authorization added successfully"}), 201
        except Exception as e:
            db.session.rollback()
            traceback.print_exc()
            return jsonify({"error": f"DB error: {str(e)}"}), 500

    except Exception as outer:
        traceback.print_exc()
        return jsonify({"error": f"Server error: {str(outer)}"}), 500


# جلب كل التفويضات
@app.route("/api/authorizations", methods=["GET"])
def get_authorizations():
    auths = Authorization.query.order_by(Authorization.id.desc()).all()
    return jsonify([a.to_dict() for a in auths])


# إنهاء تفويض (يستخدم من زر الإنهاء)
@app.route("/api/authorizations/<int:auth_id>/end", methods=["PATCH"])
def end_authorization(auth_id):
    auth = Authorization.query.get(auth_id)
    if not auth:
        return jsonify({"error": "التفويض غير موجود"}), 404
    if auth.close_date:
        return jsonify({"error": "التفويض منتهي بالفعل"}), 400

    car = Car.query.filter_by(plate=auth.car_number).first()

    try:
        # تاريخ الإقفال الفعلي
        close_dt = datetime.utcnow()
        auth.close_date = close_dt
        auth.status = "منتهية"

        # لو end_date (نهاية الجمعة) مش متخزّن لأي سبب، نحسبه الآن من issue_date
        if not auth.end_date and auth.issue_date:
            auth.end_date = get_friday_end(auth.issue_date)

        # حساب عدد الأيام والمبلغ (للتقارير / دفتر اليومية)
        rental_days = None
        total_amount = None
        if auth.issue_date and auth.end_date and auth.daily_rent is not None:
            days = (auth.end_date.date() - auth.issue_date.date()).days + 1
            days = max(days, 0)
            rental_days = days
            total_amount = float(auth.daily_rent) * days

        # 📌 إنشاء تفويض جديد تلقائيًا لنفس السيارة والسائق من السبت التالي
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
            car_number=auth.car_number,
            car_model=auth.car_model,
            car_type=auth.car_type,
            issue_date=new_issue,
            start_date=new_issue,
            daily_rent=auth.daily_rent,
            details=auth.details,
            status="مؤجرة",
            end_date=new_end,
            close_date=None
        )
        db.session.add(new_auth)

        # السيارة تظل "مؤجرة" لأن التفويض يتجدد أسبوعيًا تلقائيًا
        if car:
            car.status = "مؤجرة"

        db.session.commit()

        return jsonify({
            "message": "✅ تم إنهاء التفويض وإنشاء تفويض جديد للأسبوع التالي",
            "closed_authorization": auth.to_dict(),
            "new_authorization": new_auth.to_dict(),
            "rental_days": rental_days,
            "total_amount": total_amount
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
    data = request.get_json() or {}
    plate = (data.get("plate") or "").strip()
    if not plate:
        return jsonify({"error": "رقم اللوحة مطلوب"}), 400

    # تحويل الإيجار لرقم Decimal
    rent_in = data.get("daily_rent")
    daily_rent = None
    if rent_in not in (None, "", " "):
        try:
            daily_rent = Decimal(str(rent_in))
        except (InvalidOperation, ValueError, TypeError):
            return jsonify({"error": "قيمة الإيجار اليومي غير صحيحة"}), 400

    try:
        new_car = Car(
            plate=plate,
            model=data.get("model"),
            car_type=data.get("car_type"),
            status=(data.get("status") or "متاحة"),
            daily_rent=daily_rent
        )
        db.session.add(new_car)
        db.session.commit()
        return jsonify({"message": "✅ Car added", "car": new_car.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ----- Drivers APIs -----
@app.route("/api/drivers", methods=["GET"])
def list_drivers():
    drivers = Driver.query.order_by(Driver.id.desc()).all()
    return jsonify([d.to_dict() for d in drivers])

@app.route("/api/drivers", methods=["POST"])
def add_driver():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "اسم السائق مطلوب"}), 400
    try:
        new_driver = Driver(
            name=name,
            phone=data.get("phone"),
            license_no=data.get("license_no")
        )
        db.session.add(new_driver)
        db.session.commit()
        return jsonify({"message": "✅ Driver added", "driver": new_driver.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ---------------- Run (local) ----------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)

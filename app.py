# ======================================================
# 🚗 Flask Authorization System — with End Authorization
# ======================================================

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )

# 🔹 إعداد الاتصال بقاعدة البيانات PostgreSQL (Neon)
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ لم يتم ضبط متغير البيئة DATABASE_URL في Vercel")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------- الجداول ----------
class Authorization(db.Model):
    __tablename__ = "authorizations"
    id = db.Column(db.Integer, primary_key=True)
    issue_date = db.Column(db.DateTime, default=datetime.utcnow)
    # ملاحظة: حالياً بنربط بالأسماء/الأرقام كنصوص (بدون FK) للحفاظ على بساطة التعديلات
    driver_name = db.Column(db.String(100), nullable=False)
    car_number  = db.Column(db.String(50),  nullable=False)
    car_model   = db.Column(db.String(50))
    car_type    = db.Column(db.String(50))
    start_date  = db.Column(db.DateTime)
    daily_rent  = db.Column(db.Numeric(10, 2))
    details     = db.Column(db.Text)
    status      = db.Column(db.String(50))
    # جديد:
    end_date    = db.Column(db.DateTime, nullable=True)  # تاريخ إنهاء التفويض

    def to_dict(self):
        return {
            "id": self.id,
            "issue_date": self.issue_date.strftime("%Y-%m-%d %H:%M:%S") if self.issue_date else "",
            "driver_name": self.driver_name,
            "car_number": self.car_number,
            "car_model": self.car_model,
            "car_type": self.car_type,
            "start_date": self.start_date.strftime("%Y-%m-%d %H:%M:%S") if self.start_date else "",
            "daily_rent": float(self.daily_rent or 0),
            "details": self.details,
            "status": self.status,
            "end_date": self.end_date.strftime("%Y-%m-%d %H:%M:%S") if self.end_date else ""
        }

class Driver(db.Model):
    __tablename__ = "drivers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50))
    license_no = db.Column(db.String(80))
    notes = db.Column(db.Text)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "phone": self.phone,
                "license_no": self.license_no, "notes": self.notes}

class Car(db.Model):
    __tablename__ = "cars"
    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(80))
    car_type = db.Column(db.String(80))
    status = db.Column(db.String(50), default="متاحة")  # متاحة / مؤجرة / تحت الصيانة
    daily_rent = db.Column(db.Numeric(10,2))

    def to_dict(self):
        return {"id": self.id, "plate": self.plate, "model": self.model,
                "car_type": self.car_type, "status": self.status,
                "daily_rent": float(self.daily_rent or 0)}

with app.app_context():
    db.create_all()

# ---------- صفحات الواجهة ----------
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

# ---------- APIs ----------
# إصدار تفويض جديد
@app.route("/api/issue", methods=["POST"])
def add_authorization():
    data = request.get_json() or {}



    # 1) التحقق من السيارة
    car_plate = (data.get("car_number") or "").strip()
    car = Car.query.filter_by(plate=car_plate).first()
    if not car:
        return jsonify({"error": "السيارة غير موجودة في قاعدة البيانات"}), 400
    if car.status != "متاحة":
        return jsonify({"error": "السيارة غير متاحة حالياً"}), 400

    # 2) منع ازدواج التفويض لنفس السيارة (تفويض مفتوح بدون end_date)
    open_auth = Authorization.query.filter_by(car_number=car_plate).filter(Authorization.end_date.is_(None)).first()
    if open_auth:
        return jsonify({"error": "هناك تفويض مفتوح لهذه السيارة بالفعل"}), 400

    # 3) تجهيز الحقول
    start_date = None
    if data.get("start_date"):
        try:
            start_date = datetime.fromisoformat(data["start_date"])
        except Exception:
            start_date = None

    # لو المستخدم ما أدخلش الموديل/النوع/الإيجار، ناخدهم من السيارة أو نخليهم زي ما هم
    car_model = data.get("car_model") or car.model
    car_type  = data.get("car_type") or car.car_type
    daily_rent = data.get("daily_rent") or car.daily_rent

    new_auth = Authorization(
        driver_name=data.get("driver_name"),
        car_number=car_plate,
        car_model=car_model,
        car_type=car_type,
        start_date=start_date,
        daily_rent=daily_rent,
        details=data.get("details"),
        status=data.get("status") or "مؤجرة",
        end_date=None
    )

    try:
        db.session.add(new_auth)
        # حدّث حالة السيارة إلى "مؤجرة"
        car.status = "مؤجرة"
        db.session.commit()
        return jsonify({"message": "✅ Authorization added successfully"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# جلب كل التفويضات
@app.route("/api/authorizations", methods=["GET"])
def get_authorizations():
    auths = Authorization.query.order_by(Authorization.id.desc()).all()
    return jsonify([a.to_dict() for a in auths])

# إنهاء تفويض (يعيد السيارة متاحة + يسجل end_date)
@app.route("/api/authorizations/<int:auth_id>/end", methods=["PATCH"])
def end_authorization(auth_id):
    auth = Authorization.query.get(auth_id)
    if not auth:
        return jsonify({"error": "التفويض غير موجود"}), 404
    if auth.end_date:
        return jsonify({"error": "التفويض منتهي بالفعل"}), 400

    # رجّع السيارة
    car = Car.query.filter_by(plate=auth.car_number).first()
    try:
        auth.end_date = datetime.utcnow()
        if car:
            car.status = "متاحة"
        db.session.commit()
        return jsonify({"message": "✅ تم إنهاء التفويض"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# APIs السائقين
@app.route("/api/drivers", methods=["GET"])
def get_drivers():
    drivers = Driver.query.order_by(Driver.id.desc()).all()
    return jsonify([d.to_dict() for d in drivers])

@app.route("/api/drivers", methods=["POST"])
def add_driver():
    data = request.get_json() or {}
    try:
        new_driver = Driver(
            name=data.get("name"),
            phone=data.get("phone"),
            license_no=data.get("license_no"),
            notes=data.get("notes")
        )
        db.session.add(new_driver)
        db.session.commit()
        return jsonify({"message": "✅ Driver added", "driver": new_driver.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# APIs السيارات
@app.route("/api/cars", methods=["GET"])
def get_cars():
    cars = Car.query.order_by(Car.id.desc()).all()
    return jsonify([c.to_dict() for c in cars])

@app.route("/api/cars", methods=["POST"])
def add_car():
    data = request.get_json() or {}
    try:
        new_car = Car(
            plate=data.get("plate"),
            model=data.get("model"),
            car_type=data.get("car_type"),
            status=data.get("status") or "متاحة",
            daily_rent=data.get("daily_rent")
        )
        db.session.add(new_car)
        db.session.commit()
        return jsonify({"message": "✅ Car added", "car": new_car.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)

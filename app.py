# ======================================================
# 🚗 Flask Authorization System — Integrated with SQLAlchemy (Final Clean Version)
# ======================================================

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

# ---------------------------------------------
# 🔹 تهيئة تطبيق Flask
# ---------------------------------------------
app = Flask(__name__)

# ---------------------------------------------
# 🔹 مسار الأيقونة favicon
# ---------------------------------------------
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )

# ---------------------------------------------
# 🔹 إعداد الاتصال بقاعدة البيانات PostgreSQL (Neon)
# ---------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("❌ لم يتم ضبط متغير البيئة DATABASE_URL في Vercel")

# إصلاح عنوان الاتصال القديم إن وُجد
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ---------------------------------------------
# 🔹 تهيئة قاعدة البيانات
# ---------------------------------------------
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------------------------------------------
# 🔹 تعريف جدول التفويضات Authorizations
# ---------------------------------------------
class Authorization(db.Model):
    __tablename__ = "authorizations"

    id = db.Column(db.Integer, primary_key=True)
    issue_date = db.Column(db.DateTime, default=datetime.utcnow)
    driver_name = db.Column(db.String(100), nullable=False)
    car_number = db.Column(db.String(50), nullable=False)
    car_model = db.Column(db.String(50))
    car_type = db.Column(db.String(50))
    start_date = db.Column(db.DateTime)
    daily_rent = db.Column(db.Numeric(10, 2))
    details = db.Column(db.Text)
    status = db.Column(db.String(50))

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
            "status": self.status
        }

# ---------------------------------------------
# 🔹 إنشاء الجداول تلقائيًا عند أول تشغيل
# ---------------------------------------------
with app.app_context():
    db.create_all()
    print("✅ Database and tables created successfully.")

# ---------------------------------------------
# 🔹 المسارات الأساسية (Frontend)
# ---------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/issue")
def issue_page():
    return render_template("issue.html")

# ---------------------------------------------
# 🔹 واجهات الـ API (Backend)
# ---------------------------------------------
@app.route("/api/issue", methods=["POST"])
def add_authorization():
    data = request.get_json()
    try:
        start_date = None
        if data.get("start_date"):
            try:
                # تنسيق التاريخ من HTML (مثل 2025-11-11T14:30)
                start_date = datetime.fromisoformat(data["start_date"])
            except Exception:
                start_date = None

        new_auth = Authorization(
            driver_name=data.get("driver_name"),
            car_number=data.get("car_number"),
            car_model=data.get("car_model"),
            car_type=data.get("car_type"),
            start_date=start_date,
            daily_rent=data.get("daily_rent"),
            details=data.get("details"),
            status=data.get("status")
        )

        db.session.add(new_auth)
        db.session.commit()
        return jsonify({"message": "✅ Authorization added successfully"}), 201

    except Exception as e:
        db.session.rollback()
        print("❌ Error saving authorization:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/authorizations", methods=["GET"])
def get_authorizations():
    try:
        all_auths = Authorization.query.order_by(Authorization.id.desc()).all()
        return jsonify([a.to_dict() for a in all_auths])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ✅ API: إضافة سائق
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


# ✅ API: عرض السائقين
@app.route("/api/drivers", methods=["GET"])
def get_drivers():
    drivers = Driver.query.order_by(Driver.id.desc()).all()
    return jsonify([d.to_dict() for d in drivers])


# ✅ API: إضافة سيارة
@app.route("/api/cars", methods=["POST"])
def add_car():
    data = request.get_json() or {}
    try:
        new_car = Car(
            plate=data.get("plate"),
            model=data.get("model"),
            car_type=data.get("car_type"),
            status=data.get("status"),
            daily_rent=data.get("daily_rent")
        )
        db.session.add(new_car)
        db.session.commit()
        return jsonify({"message": "✅ Car added", "car": new_car.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ✅ API: عرض السيارات
@app.route("/api/cars", methods=["GET"])
def get_cars():
    cars = Car.query.order_by(Car.id.desc()).all()
    return jsonify([c.to_dict() for c in cars])





# ---------------------------------------------
# 🔹 جدول السائقين Drivers
# ---------------------------------------------
class Driver(db.Model):
    __tablename__ = "drivers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50))
    license_no = db.Column(db.String(80))
    notes = db.Column(db.Text)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "license_no": self.license_no,
            "notes": self.notes
        }


# ---------------------------------------------
# 🔹 جدول السيارات Cars
# ---------------------------------------------
class Car(db.Model):
    __tablename__ = "cars"

    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(80))
    car_type = db.Column(db.String(80))
    status = db.Column(db.String(50), default="متاحة")
    daily_rent = db.Column(db.Numeric(10,2))

    def to_dict(self):
        return {
            "id": self.id,
            "plate": self.plate,
            "model": self.model,
            "car_type": self.car_type,
            "status": self.status,
            "daily_rent": float(self.daily_rent or 0)
        }


# ---------------------------------------------
# 🔹 تشغيل محلي (اختياري)
# ---------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)


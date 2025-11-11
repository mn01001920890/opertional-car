from flask import send_from_directory

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )



# ======================================================
# 🚗 Flask Authorization System — Integrated with SQLAlchemy (Fixed)
# ======================================================

from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__)

# ---------------------------------------------
# 🔹 إعداد الاتصال بقاعدة البيانات PostgreSQL (Neon)
# ---------------------------------------------
DATABASE_URL = os.environ.get("POSTGRES_URL")

if not DATABASE_URL:
    raise ValueError("❌ لم يتم ضبط متغير البيئة POSTGRES_URL في Vercel")

# 🔸 إصلاح خاص لـ Vercel وNeon: تحويل URI القديمة postgresql:// → postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ---------------------------------------------
# 🔹 تهيئة قاعدة البيانات
# ---------------------------------------------
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------------------------------------------
# 🔹 تعريف جدول Authorizations
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
# 🔹 واجهات API (Backend)
# ---------------------------------------------
@app.route("/api/issue", methods=["POST"])
def add_authorization():
    data = request.get_json()
    try:
        start_date = None
        if data.get("start_date"):
            try:
                # 🧠 إصلاح تنسيق التاريخ القادم من HTML (مثل 2025-11-11T14:30)
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


# ---------------------------------------------
# 🔹 تشغيل محلي (اختياري)
# ---------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)


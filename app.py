# -*- coding: utf-8 -*-
"""
Flask backend for Car Rental / Authorizations
- Safe Decimal handling for daily_rent
- Robust issue (authorization) creation with validations
- End authorization endpoint updates car status back to "متاحة"
- Works on Vercel/Neon: reads DATABASE_URL (fallback POSTGRES_URL), fixes postgres:// → postgresql://
- **NEW**: UI routes for serving index.html وباقي الصفحات لمنع 404 على الجذر والمسارات الأمامية
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Numeric, and_
from datetime import datetime
from decimal import Decimal, InvalidOperation
import os
import traceback

app = Flask(__name__)

# ------------------------------
# DB URL (Vercel/Neon compatible)
# ------------------------------
DB_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if not DB_URL:
    raise RuntimeError("❌ لم يتم ضبط متغير البيئة DATABASE_URL أو POSTGRES_URL")

# Fix old postgres:// scheme if present
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DB_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Init DB
db = SQLAlchemy(app)

# ------------------------------
# Models
# ------------------------------
class Car(db.Model):
    __tablename__ = 'cars'
    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(64), unique=True, nullable=False)
    model = db.Column(db.String(120))
    car_type = db.Column(db.String(120))
    daily_rent = db.Column(Numeric(10, 2), default=Decimal('0.00'))
    status = db.Column(db.String(32), default='متاحة')  # متاحة / مؤجرة / تحت الصيانة

    def to_dict(self):
        return {
            "id": self.id,
            "plate": self.plate,
            "model": self.model,
            "car_type": self.car_type,
            "daily_rent": float(self.daily_rent or 0),
            "status": self.status,
        }

class Driver(db.Model):
    __tablename__ = 'drivers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(64))
    license_no = db.Column(db.String(64))
    notes = db.Column(db.Text)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "license_no": self.license_no,
            "notes": self.notes,
        }

class Authorization(db.Model):
    __tablename__ = 'authorizations'
    id = db.Column(db.Integer, primary_key=True)
    driver_name = db.Column(db.String(120), nullable=False)
    car_number = db.Column(db.String(64), nullable=False)  # refers to Car.plate
    car_model = db.Column(db.String(120))
    car_type = db.Column(db.String(120))
    start_date = db.Column(db.String(40))  # keep as string from UI (datetime-local) to avoid TZ issues
    end_date = db.Column(db.String(40), nullable=True)
    daily_rent = db.Column(Numeric(10, 2), default=Decimal('0.00'))
    details = db.Column(db.Text)
    status = db.Column(db.String(32), default='مؤجرة')  # حالة السيارة أثناء التفويض

    def to_dict(self):
        return {
            "id": self.id,
            "driver_name": self.driver_name,
            "car_number": self.car_number,
            "car_model": self.car_model,
            "car_type": self.car_type,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "daily_rent": float(self.daily_rent or 0),
            "details": self.details,
            "status": self.status,
        }

# Create tables on boot (works on Vercel serverless too)
with app.app_context():
    db.create_all()


# ------------------------------
# Helpers
# ------------------------------

def _to_decimal(value, default=Decimal('0.00')) -> Decimal:
    if value in (None, "", 0, 0.0, "0", "0.0"):
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("قيمة رقمية غير صالحة")


def _json_error(msg, code=400):
    return jsonify({"error": msg}), code


# ------------------------------
# Static / UI routes (fix 404 on "/" and pages)
# ------------------------------
ROOT_DIR = os.path.abspath(os.path.dirname(__file__))

@app.route('/')
def home():
    # Serve index.html from project root
    return send_from_directory(ROOT_DIR, 'index.html')

@app.route('/index')
@app.route('/index.html')
def index_page():
    return send_from_directory(ROOT_DIR, 'index.html')

@app.route('/cars')
@app.route('/cars.html')
def cars_page():
    return send_from_directory(ROOT_DIR, 'cars.html')

@app.route('/drivers')
@app.route('/drivers.html')
def drivers_page():
    return send_from_directory(ROOT_DIR, 'drivers.html')

@app.route('/issue')
@app.route('/issue.html')
def issue_page():
    return send_from_directory(ROOT_DIR, 'issue.html')

@app.route('/rented')
@app.route('/rented.html')
def rented_page():
    return send_from_directory(ROOT_DIR, 'rented.html')

@app.route('/view')
@app.route('/view.html')
def view_page():
    return send_from_directory(ROOT_DIR, 'view.html')

@app.route('/cars-status')
@app.route('/cars-status.html')
def cars_status_page():
    return send_from_directory(ROOT_DIR, 'cars-status.html')

# generic static handler (serve any .html file if present)
@app.route('/<path:fname>')
def static_files(fname):
    # if requesting a known api path, let other routes handle it
    if fname.startswith('api/'):
        return _json_error('Not Found', 404)
    # try to serve the requested file from project root
    fpath = os.path.join(ROOT_DIR, fname)
    if os.path.isfile(fpath):
        directory = os.path.dirname(fpath)
        filename = os.path.basename(fpath)
        return send_from_directory(directory, filename)
    return _json_error('Not Found', 404)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path), 'favicon.ico', mimetype='image/vnd.microsoft.icon')


# ------------------------------
# Cars API
# ------------------------------
@app.route('/api/cars', methods=['GET'])
def list_cars():
    cars = Car.query.order_by(Car.id.desc()).all()
    return jsonify([c.to_dict() for c in cars])


@app.route('/api/cars', methods=['POST'])
def add_car():
    data = request.get_json(force=True, silent=True) or {}
    plate = (data.get('plate') or '').strip()
    if not plate:
        return _json_error('رقم اللوحة مطلوب')

    if Car.query.filter_by(plate=plate).first():
        return _json_error('هذه السيارة مسجلة بالفعل')

    try:
        rent = _to_decimal(data.get('daily_rent', '0'))
    except ValueError:
        return _json_error('قيمة الإيجار غير صالحة')

    car = Car(
        plate=plate,
        model=data.get('model'),
        car_type=data.get('car_type'),
        daily_rent=rent,
        status=(data.get('status') or 'متاحة')
    )
    db.session.add(car)
    db.session.commit()
    return jsonify({"message": "تمت إضافة السيارة", "car": car.to_dict()}), 201


# ------------------------------
# Drivers API
# ------------------------------
@app.route('/api/drivers', methods=['GET'])
def list_drivers():
    drivers = Driver.query.order_by(Driver.id.desc()).all()
    return jsonify([d.to_dict() for d in drivers])


@app.route('/api/drivers', methods=['POST'])
def add_driver():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return _json_error('اسم السائق مطلوب')

    if Driver.query.filter_by(name=name).first():
        return _json_error('هذا السائق مسجل بالفعل')

    d = Driver(
        name=name,
        phone=data.get('phone'),
        license_no=data.get('license_no'),
        notes=data.get('notes')
    )
    db.session.add(d)
    db.session.commit()
    return jsonify({"message": "تمت إضافة السائق", "driver": d.to_dict()}), 201


# ------------------------------
# Authorizations (Issue / View / End)
# ------------------------------
@app.route('/api/authorizations', methods=['GET'])
def list_authorizations():
    """Optionally filter: ?open=1 to get only open (no end_date)."""
    only_open = request.args.get('open') in ("1", "true", "True")
    q = Authorization.query
    if only_open:
        q = q.filter(Authorization.end_date.is_(None))
    auths = q.order_by(Authorization.id.desc()).all()
    return jsonify([a.to_dict() for a in auths])


@app.route('/api/issue', methods=['POST'])
def create_issue():
    data = request.get_json(force=True, silent=True) or {}
    try:
        driver_name = (data.get('driver_name') or '').strip()
        car_plate   = (data.get('car_number') or '').strip()
        if not driver_name:
            return _json_error('اختر السائق')
        if not car_plate:
            return _json_error('اختر السيارة')

        # Car exists?
        car = Car.query.filter_by(plate=car_plate).first()
        if not car:
            return _json_error('السيارة غير موجودة لديك')

        # Car must be available
        if (car.status or '').strip() != 'متاحة':
            return _json_error('السيارة غير متاحة حالياً')

        # No open authorization for this car
        existing_open = Authorization.query.filter(and_(Authorization.car_number == car_plate, Authorization.end_date.is_(None))).first()
        if existing_open:
            return _json_error('هناك تفويض مفتوح لهذه السيارة بالفعل')

        # Resolve model/type
        car_model = data.get('car_model') or car.model
        car_type  = data.get('car_type') or car.car_type

        # Safe daily_rent
        raw_rent = data.get('daily_rent', None)
        if raw_rent in (None, ""):
            daily_rent = car.daily_rent or Decimal('0.00')
        else:
            daily_rent = _to_decimal(raw_rent)

        start_date = data.get('start_date') or datetime.utcnow().strftime('%Y-%m-%dT%H:%M')
        status = data.get('status') or 'مؤجرة'

        new_auth = Authorization(
            driver_name=driver_name,
            car_number=car_plate,
            car_model=car_model,
            car_type=car_type,
            start_date=start_date,
            daily_rent=daily_rent,
            details=data.get('details'),
            status=status,
            end_date=None
        )
        db.session.add(new_auth)

        # Update car status to rented
        car.status = 'مؤجرة'
        db.session.commit()

        return jsonify({
            "message": "تم إصدار التفويض",
            "authorization": new_auth.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        app.logger.error("Issue create failed: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": "Server error while creating authorization"}), 500


@app.route('/api/authorizations/<int:auth_id>/end', methods=['PATCH'])
def end_authorization(auth_id: int):
    data = request.get_json(force=True, silent=True) or {}
    try:
        auth = Authorization.query.get(auth_id)
        if not auth:
            return _json_error('التفويض غير موجود', 404)
        if auth.end_date:
            return _json_error('تم إنهاء هذا التفويض مسبقاً')

        # End date from payload or now
        end_date = data.get('end_date') or datetime.utcnow().strftime('%Y-%m-%dT%H:%M')
        auth.end_date = end_date

        # Set car back to available
        car = Car.query.filter_by(plate=auth.car_number).first()
        if car:
            car.status = 'متاحة'

        db.session.commit()
        return jsonify({"message": "تم إنهاء التفويض", "authorization": auth.to_dict()})

    except Exception as e:
        db.session.rollback()
        app.logger.error("End auth failed: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": "Server error while ending authorization"}), 500


# ------------------------------
# Rented / Open helpers (for UI pages)
# ------------------------------
@app.route('/api/rented', methods=['GET'])
def list_rented():
    auths = Authorization.query.filter(Authorization.end_date.is_(None)).order_by(Authorization.id.desc()).all()
    return jsonify([a.to_dict() for a in auths])


# ------------------------------
# Health
# ------------------------------
@app.route('/api/health')
def health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat()})


# ---------------
# Local run
# ---------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

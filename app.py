from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
import os
from dotenv import load_dotenv

# تحميل متغيرات البيئة
load_dotenv()

app = Flask(__name__)
CORS(app)

# الاتصال بقاعدة بيانات Neon
DATABASE_URL = os.getenv("DATABASE_URL")

def get_connection():
    return psycopg2.connect(DATABASE_URL)

# إنشاء جدول التفويضات لو مش موجود
def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS authorizations (
        id SERIAL PRIMARY KEY,
        issue_date TIMESTAMP,
        driver_name VARCHAR(100),
        car_number VARCHAR(50),
        car_model VARCHAR(50),
        car_type VARCHAR(50),
        start_date TIMESTAMP,
        daily_rent NUMERIC(10,2),
        details TEXT,
        status VARCHAR(50)
    );
    """)
    conn.commit()
    cur.close()
    conn.close()

@app.route("/")
def home():
    return "🚗 API for Authorization System is running!"

# 📝 حفظ تفويض جديد
@app.route("/api/issue", methods=["POST"])
def add_authorization():
    data = request.get_json()
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO authorizations 
            (issue_date, driver_name, car_number, car_model, car_type, start_date, daily_rent, details, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            data.get("issue_date"),
            data.get("driver_name"),
            data.get("car_number"),
            data.get("car_model"),
            data.get("car_type"),
            data.get("start_date"),
            data.get("daily_rent"),
            data.get("details"),
            data.get("status")
        ))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"message": "Authorization saved successfully ✅"}), 201
    except Exception as e:
        print("Error:", e)
        return jsonify({"error": str(e)}), 500

# 📜 جلب كل التفويضات
@app.route("/api/authorizations", methods=["GET"])
def get_authorizations():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM authorizations ORDER BY id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    data = []
    for r in rows:
        data.append({
            "id": r[0],
            "issue_date": r[1],
            "driver_name": r[2],
            "car_number": r[3],
            "car_model": r[4],
            "car_type": r[5],
            "start_date": r[6],
            "daily_rent": float(r[7]),
            "details": r[8],
            "status": r[9]
        })
    return jsonify(data)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)

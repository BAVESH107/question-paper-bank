from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import sqlite3
import os
import re
import hashlib


app = Flask(__name__)
CORS(app)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day","50 per hour"],
    storage_uri="memory://"
)

# ─── ADMIN PASSWORD ───
# Default password: admin123
# CHANGE THIS before sharing!
ADMIN_PASSWORD_HASH = hashlib.sha256("LENEVO;)60".encode()).hexdigest()

UPLOAD_FOLDER = 'uploads'
DB_FILE = 'papers.db'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─── SERVE FRONTEND ───
@app.route('/')
def home():
    return send_from_directory('../FE', 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('../FE', filename)

# ─── DATABASE SETUP ───
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            subject TEXT,
            semester INTEGER,
            department TEXT,
            year INTEGER,
            exam_type TEXT,
            uploaded_by TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# ─── UPLOAD PAPER (ADMIN ONLY) ───
@app.route('/upload', methods=['POST'])
@limiter.limit("5 per minute")
def upload_paper():
    password = request.form.get('admin_password', '')
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if password_hash != ADMIN_PASSWORD_HASH:
        return jsonify({
            "error": "unauthorized",
            "message": "Unauthorized. Admin access required."
        }), 403

    file = request.files.get('file')
    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    subject = request.form.get('subject', '').strip()
    semester = request.form.get('semester', '').strip()
    department = request.form.get('department', '').strip()
    year = request.form.get('year', '').strip()
    exam_type = request.form.get('exam_type', '').strip()
    uploaded_by = request.form.get('uploaded_by', '').strip()

    if not all([subject, semester, department, year, exam_type, uploaded_by]):
        return jsonify({
            "error": "missing_fields",
            "message": "Please fill all fields."
        }), 400

    clean_subject = re.sub(r'[^A-Za-z0-9]', '', subject)
    generated_filename = f"{clean_subject}_{semester}_{department}_{exam_type}.pdf"

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute(
        "SELECT id FROM papers WHERE LOWER(filename) = LOWER(?)",
        (generated_filename,)
    )
    existing = cursor.fetchone()

    if existing:
        conn.close()
        return jsonify({
            "error": "duplicate",
            "message": f"'{generated_filename}' already exists!"
        }), 409

    file_path = os.path.join(UPLOAD_FOLDER, generated_filename)
    file.save(file_path)

    conn.execute('''
        INSERT INTO papers (filename, subject, semester, department, year, exam_type, uploaded_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        generated_filename, subject, semester, department, year, exam_type, uploaded_by
    ))
    conn.commit()
    conn.close()

    return jsonify({
        "message": f"Uploaded as '{generated_filename}'!"
    })

# ─── GET ALL PAPERS ───
@app.route('/papers', methods=['GET'])
def get_papers():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute("SELECT * FROM papers ORDER BY timestamp DESC")
    papers = [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]
    conn.close()
    return jsonify(papers)

# ─── SEARCH PAPERS ───
@app.route('/search', methods=['GET'])
def search_papers():
    query = request.args.get('q', '').strip()
    dept = request.args.get('dept', '').strip()
    sem = request.args.get('sem', '').strip()
    year = request.args.get('year', '').strip()

    sql = "SELECT * FROM papers WHERE 1=1"
    params = []

    if query:
        sql += " AND (LOWER(subject) LIKE ? OR LOWER(filename) LIKE ?)"
        params.extend([f"%{query.lower()}%", f"%{query.lower()}%"])
    if dept:
        sql += " AND department = ?"
        params.append(dept)
    if sem:
        sql += " AND semester = ?"
        params.append(sem)
    if year:
        sql += " AND year = ?"
        params.append(year)

    sql += " ORDER BY timestamp DESC"

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute(sql, params)
    papers = [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]
    conn.close()
    return jsonify(papers)

# ─── DOWNLOAD PAPER ───
@app.route('/download/<filename>', methods=['GET'])
def download_paper(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

# ─── DELETE PAPER (ADMIN ONLY) ───
@app.route('/delete/<filename>', methods=['DELETE'])
@limiter.limit("5 per minute")
def delete_paper(filename):
    password = request.headers.get('X-Admin-Password', '')
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if password_hash != ADMIN_PASSWORD_HASH:
        return jsonify({
            "error": "unauthorized",
            "message": "Unauthorized. Admin access required."
        }), 403

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute("SELECT id FROM papers WHERE filename = ?", (filename,))
    existing = cursor.fetchone()

    if not existing:
        conn.close()
        return jsonify({"error": "not_found", "message": "Paper not found."}), 404

    conn.execute("DELETE FROM papers WHERE filename = ?", (filename,))
    conn.commit()
    conn.close()

    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    return jsonify({"message": f"'{filename}' deleted successfully!"})
with app.app_context():
 init_db()

if __name__ == '__main__':
    init_db()
    print("\n📚 Paper Bank Server running on http://localhost:5000\n")
    app.run(port=5000, debug=True)
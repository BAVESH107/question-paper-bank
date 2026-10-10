from flask import Flask, request, jsonify, send_from_directory, Response, make_response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_limiter.errors import RateLimitExceeded
from supabase import create_client, Client
import psycopg2
import psycopg2.extras
import os
import re
import hashlib
import io
import time
import random
import requests as req
import pypdf
from fpdf import FPDF
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════════
# 🔧 FLASK APP SETUP
# ═══════════════════════════════════════════════════════════════════
app = Flask(__name__)
CORS(app)
# ═══════════════════════════════════════════════════════════════════

# ─── ADMIN PASSWORD ───
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "REDBULLF1TEAM")
ADMIN_PASSWORD_HASH = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()

# ─── RATE LIMITER (Admin-aware key) ───
def get_rate_limit_key():
    """Give admins their own separate rate limit bucket."""
    admin_pass = request.headers.get('X-Admin-Password', '')
    if admin_pass:
        password_hash = hashlib.sha256(admin_pass.encode()).hexdigest()
        if password_hash == ADMIN_PASSWORD_HASH:
            return "admin"
    return get_remote_address()

limiter = Limiter(
    get_rate_limit_key,
    app=app,
    default_limits=["1000 per day", "300 per hour"],
    storage_uri="memory://"
)

@app.errorhandler(RateLimitExceeded)
def handle_rate_limit_exceeded(e):
    return jsonify({
        "error": "rate_limit_exceeded",
        "message": "Too many attempts. Please wait a minute and try again."
    }), 429

# ─── SUPABASE ───
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ─── SERVE FRONTEND ───
@app.route('/')
def home():
    return send_from_directory('../FE', 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('../FE', filename)


# ─── DATABASE SETUP ───
def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS papers (
            id SERIAL PRIMARY KEY,
            filename TEXT UNIQUE NOT NULL,
            subject TEXT,
            semester INTEGER,
            department TEXT,
            year INTEGER,
            exam_type TEXT,
            uploaded_by TEXT,
            supabase_url TEXT,
            generated_questions TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS page_views (
            id SERIAL PRIMARY KEY,
            viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT DEFAULT 'web'
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()


# ═══════════════════════════════════════════════════════════════════
# 📊 ANALYTICS ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@app.route('/api/track-view', methods=['POST'])
def track_view():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO page_views (source) VALUES (%s)", ('web',))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "tracked"}), 200
    except Exception as e:
        print(f"Track view error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics', methods=['GET'])
def get_analytics():
    password = request.headers.get('X-Admin-Password', '')
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if password_hash != ADMIN_PASSWORD_HASH:
        return jsonify({"error": "unauthorized"}), 403

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM page_views")
        total_views = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM page_views WHERE viewed_at::date = CURRENT_DATE")
        views_today = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM page_views WHERE viewed_at >= NOW() - INTERVAL '7 days'")
        views_week = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        return jsonify({
            "total_views": total_views,
            "views_today": views_today,
            "views_this_week": views_week
        })
    except Exception as e:
        print(f"Analytics error: {e}")
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════
# 📄 PAPER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

@app.route('/upload', methods=['POST'])
def upload_paper():
    password = request.form.get('admin_password', '')
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if password_hash != ADMIN_PASSWORD_HASH:
        return jsonify({"error": "unauthorized", "message": "Unauthorized."}), 403

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
        return jsonify({"error": "missing_fields", "message": "Please fill all fields."}), 400

    clean_subject = re.sub(r'[^A-Za-z0-9]', '', subject)
    generated_filename = f"{clean_subject}_{semester}_{department}_{exam_type}.pdf"

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM papers WHERE LOWER(filename) = LOWER(%s)", (generated_filename,))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "duplicate", "message": f"'{generated_filename}' already exists!"}), 409

    file_data = file.read()
    try:
        supabase.storage.from_('papers').upload(
            path=generated_filename,
            file=file_data,
            file_options={"content-type": "application/pdf"}
        )
    except Exception as e:
        cursor.close()
        conn.close()
        return jsonify({"error": "storage_error", "message": str(e)}), 500

    public_url = supabase.storage.from_('papers').get_public_url(generated_filename)

    cursor.execute('''
        INSERT INTO papers (filename, subject, semester, department, year, exam_type, uploaded_by, supabase_url)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ''', (generated_filename, subject, semester, department, year, exam_type, uploaded_by, public_url))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": f"Uploaded as '{generated_filename}'!"})


@app.route('/papers', methods=['GET'])
def get_papers():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT * FROM papers ORDER BY timestamp DESC")
    papers = [dict(row) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify(papers)


@app.route('/search', methods=['GET'])
def search_papers():
    query = request.args.get('q', '').strip()
    dept = request.args.get('dept', '').strip()
    sem = request.args.get('sem', '').strip()
    year = request.args.get('year', '').strip()

    sql = "SELECT * FROM papers WHERE 1=1"
    params = []

    if query:
        sql += " AND (LOWER(subject) LIKE %s OR LOWER(filename) LIKE %s)"
        params.extend([f"%{query.lower()}%", f"%{query.lower()}%"])
    if dept:
        sql += " AND department = %s"
        params.append(dept)
    if sem:
        sql += " AND semester = %s"
        params.append(sem)
    if year:
        sql += " AND year = %s"
        params.append(year)

    sql += " ORDER BY timestamp DESC"

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(sql, params)
    papers = [dict(row) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify(papers)


@app.route('/download/<filename>', methods=['GET'])
def download_paper(filename):
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT supabase_url FROM papers WHERE filename = %s", (filename,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if not result:
        return jsonify({"error": "not_found"}), 404

    pdf_response = req.get(result[0])
    if pdf_response.status_code != 200:
        return jsonify({"error": "fetch_failed"}), 500

    return Response(
        pdf_response.content,
        mimetype='application/pdf',
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.route('/delete/<filename>', methods=['DELETE'])
def delete_paper(filename):
    password = request.headers.get('X-Admin-Password', '')
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if password_hash != ADMIN_PASSWORD_HASH:
        return jsonify({"error": "unauthorized"}), 403

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM papers WHERE filename = %s", (filename,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "not_found"}), 404

    try:
        supabase.storage.from_('papers').remove([filename])
    except Exception as e:
        print(f"Storage delete failed: {e}")

    cursor.execute("DELETE FROM papers WHERE filename = %s", (filename,))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": f"'{filename}' deleted successfully!"})


# ═══════════════════════════════════════════════════════════════════
# 🤖 AI QUESTION GENERATOR (GEMINI VISION + CACHING)
# ═══════════════════════════════════════════════════════════════════

@app.route('/generate-questions/<filename>', methods=['POST'])
def generate_questions(filename):
    try:
        # 1. CHECK CACHE
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT supabase_url, generated_questions FROM papers WHERE filename = %s", (filename,))
        result = cursor.fetchone()

        if not result:
            cursor.close()
            conn.close()
            return jsonify({"error": "not_found"}), 404

        supabase_url, cached_questions = result

        if cached_questions:
            cursor.close()
            conn.close()
            print(f"Serving cached questions for {filename}")
            return build_pdf_response(cached_questions)

        # 2. DOWNLOAD PDF
        print(f"Generating new questions for {filename}...")
        pdf_response = req.get(supabase_url, stream=True)
        if pdf_response.status_code != 200:
            cursor.close()
            conn.close()
            return jsonify({"error": "pdf_fetch_failed"}), 500

        pdf_bytes = pdf_response.raw.read(10 * 1024 * 1024)
        del pdf_response

        # 3. TEXT EXTRACTION
        pdf_reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in pdf_reader.pages[:5]:
            extracted = page.extract_text()
            if extracted:
                text += extracted

        # 4. GROQ CLIENT
        from openai import OpenAI
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            cursor.close()
            conn.close()
            return jsonify({"error": "no_key", "message": "Server config error: GROQ_API_KEY missing."}), 500

        client = OpenAI(
            api_key=groq_key,
            base_url="https://api.groq.com/openai/v1"
        )

        ai_text = None
        last_error = None

        # Models to try in order (Groq's current vision-capable models)
        models_to_try = [
            "meta-llama/llama-4-maverick-17b-128e-instruct",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "qwen/qwen3-32b"
        ]

        # CASE A: DIGITAL PDF
        if len(text.strip()) > 50:
            print("Digital PDF detected. Using text prompt.")
            text = text[:3000]
            prompt = f"""Read the exam paper content below and generate 10 short practice questions (one line each).

Rules:
- Output ONLY 10 numbered questions (1 to 10).
- Write in PLAIN ENGLISH. Use "ohm" not Ω.
- Do NOT use LaTeX or special symbols.
- Do NOT refer to diagrams or figures.
- Each question must be self-contained.

Paper content:
{text}

Generate 10 questions:"""

            for model_name in models_to_try:
                if ai_text:
                    break
                try:
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.7,
                        max_tokens=800
                    )
                    ai_text = response.choices[0].message.content
                    print(f"Success with {model_name}")
                    break
                except Exception as e:
                    last_error = str(e)
                    print(f"{model_name} failed: {last_error[:100]}")
                    continue

        # CASE B: SCANNED PDF (VISION)
        else:
            print("Scanned PDF detected. Using vision prompt.")
            try:
                from pdf2image import convert_from_bytes
                import base64

                images = convert_from_bytes(pdf_bytes, first_page=1, last_page=2, dpi=120)
                content_parts = [{
                    "type": "text",
                    "text": "Read the exam paper images below and generate 10 short practice questions (one line each). Output ONLY 10 numbered questions. Write in PLAIN ENGLISH. Do NOT use LaTeX or special symbols. Do NOT refer to diagrams or figures. Each question must be self-contained."
                }]

                for img in images:
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG', quality=70)
                    b64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                    })

                for model_name in models_to_try:
                    if ai_text:
                        break
                    try:
                        response = client.chat.completions.create(
                            model=model_name,
                            messages=[{"role": "user", "content": content_parts}],
                            temperature=0.7,
                            max_tokens=800
                        )
                        ai_text = response.choices[0].message.content
                        print(f"Vision Success with {model_name}")
                        break
                    except Exception as e:
                        last_error = str(e)
                        print(f"Vision {model_name} failed: {last_error[:100]}")
                        continue
            except Exception as e:
                print(f"Image conversion failed: {e}")
                cursor.close()
                conn.close()
                return jsonify({"error": "ocr_failed", "message": f"Could not read PDF: {str(e)[:100]}"}), 500

        # 5. HANDLE FAILURE
        if ai_text is None:
            cursor.close()
            conn.close()
            return jsonify({
                "error": "ai_busy",
                "message": "Groq's AI is currently overloaded. Please try again in a minute.",
                "debug": last_error[:200] if last_error else "no response"
            }), 503

        # 6. CACHE RESULT
        cursor.execute(
            "UPDATE papers SET generated_questions = %s WHERE filename = %s",
            (ai_text, filename)
        )
        conn.commit()
        cursor.close()
        conn.close()
        print(f"Cached questions for {filename}")

        return build_pdf_response(ai_text)

    except Exception as e:
        print(f"AI error: {e}")
        return jsonify({"error": "ai_failed", "message": str(e)[:150]}), 500


# ─── HELPER: BUILD PDF FROM AI TEXT ───
def build_pdf_response(ai_text):
    bad_phrases = ["shown below", "shown above", "the figure", "the diagram", "in the image"]
    lines = ai_text.split('\n')
    filtered = [l for l in lines if not any(p in l.lower() for p in bad_phrases)]
    ai_text = '\n'.join(filtered)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, txt="QStack Practice Questions", ln=True, align='C')
    pdf.ln(8)
    pdf.set_font("Arial", size=12)

    for line in ai_text.split('\n'):
        line = line.replace('Ω', ' ohm ').replace('µF', ' microfarad ').replace('µ', ' micro ')
        line = line.replace('mH', ' millihenry ').replace('×', ' x ').replace('≈', ' approximately ')
        line = line.replace('\\Omega', ' ohm ').replace('\\mu', ' micro ')
        line = line.replace('\\text{', '').replace('\\text', '').replace('\\', '')
        line = line.replace('{', '').replace('}', '').replace('$', '').replace('`', '')

        clean_line = re.sub(r'[^\x00-\x7F]+', '', line)

        if clean_line.strip():
            pdf.multi_cell(0, 8, txt=clean_line, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(6)

    pdf_output = bytes(pdf.output(dest='S'))
    del pdf

    response = make_response(pdf_output)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline; filename=questions.pdf'
    return response


# ─── INITIALIZE DATABASE ───
with app.app_context():
    init_db()

if __name__ == '__main__':
    print("\nQStack Server running on http://localhost:5000\n")
    app.run(port=5000, debug=True)
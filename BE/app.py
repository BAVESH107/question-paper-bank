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
import pypdf  # Updated from PyPDF2
from fpdf import FPDF
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════════
# 🔧 FLASK APP SETUP (MUST BE FIRST BEFORE ANY @app.route)
# ═══════════════════════════════════════════════════════════════════
app = Flask(__name__)
CORS(app)
# ═══════════════════════════════════════════════════════════════════

# ─── RATE LIMITING ───
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["1000 per day", "200 per hour"],
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

# ═══════════════════════════════════════════════════════════════════
# 🔑 ADMIN PASSWORD
# ═══════════════════════════════════════════════════════════════════
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "REDBULLF1TEAM")
ADMIN_PASSWORD_HASH = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
# ═══════════════════════════════════════════════════════════════════

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
    conn.commit()
    cursor.close()
    conn.close()

# ─── UPLOAD PAPER (ADMIN ONLY) ───
@app.route('/upload', methods=['POST'])
@limiter.limit("5 per minute")
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

# ─── GET ALL PAPERS ───
@app.route('/papers', methods=['GET'])
def get_papers():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT * FROM papers ORDER BY timestamp DESC")
    papers = [dict(row) for row in cursor.fetchall()]
    cursor.close()
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

# ─── DOWNLOAD PAPER ───
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

# ─── DELETE PAPER (ADMIN ONLY) ───
@app.route('/delete/<filename>', methods=['DELETE'])
@limiter.limit("5 per minute")
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

# ─── AI QUESTION GENERATOR (GEMINI VISION + CACHING) ───
@app.route('/generate-questions/<filename>', methods=['POST'])
@limiter.limit("10 per minute")
def generate_questions(filename):
    try:
        # 1. CONNECT TO DB & CHECK CACHEe
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT supabase_url, generated_questions FROM papers WHERE filename = %s", (filename,))
        result = cursor.fetchone()

        if not result:
            cursor.close()
            conn.close()
            return jsonify({"error": "not_found"}), 404

        supabase_url, cached_questions = result

        # 2. IF CACHED, RETURN IMMEDIATELY
        if cached_questions:
            cursor.close()
            conn.close()
            print(f"Serving cached questions for {filename}")
            return build_pdf_response(cached_questions)

        # 3. DOWNLOAD PDF FROM SUPABASE
        print(f"Generating new questions for {filename}...")
        pdf_response = req.get(supabase_url, stream=True)
        if pdf_response.status_code != 200:
            cursor.close()
            conn.close()
            return jsonify({"error": "pdf_fetch_failed"}), 500

        pdf_bytes = pdf_response.raw.read(10 * 1024 * 1024)  # 10MB limit
        del pdf_response

        # 4. TRY TEXT EXTRACTION
        pdf_reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in pdf_reader.pages[:5]:
            extracted = page.extract_text()
            if extracted:
                text += extracted

        # 5. PREPARE GEMINI CLIENT & KEYS
        from google import genai
        
        GEMINI_KEYS = [
            os.getenv("GEMINI_API_KEY"),
            os.getenv("GEMINI_API_KEY_2"),
            os.getenv("GEMINI_API_KEY_3"),
        ]
        GEMINI_KEYS = [k for k in GEMINI_KEYS if k]

        if not GEMINI_KEYS:
            cursor.close()
            conn.close()
            return jsonify({"error": "no_keys", "message": "Server config error: No API keys."}), 500

        ai_text = None
        last_error = None
        models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]

        # ─── CASE A: DIGITAL PDF ───
        if len(text.strip()) > 50:
            print("Digital PDF detected. Using text extraction.")
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
                for i, key in enumerate(GEMINI_KEYS):
                    try:
                        client = genai.Client(api_key=key)
                        response = client.models.generate_content(
                            model=model_name,
                            contents=prompt
                        )
                        ai_text = response.text
                        print(f"Success with {model_name}, key #{i+1}")
                        break
                    except Exception as e:
                        last_error = str(e)
                        print(f"{model_name} | Key #{i+1} failed: {last_error[:80]}")
                        continue
                if not ai_text:
                    time.sleep(random.uniform(2, 5))

        # ─── CASE B: SCANNED PDF (GEMINI VISION) ───
        else:
            print("Scanned PDF detected. Converting to images for Gemini Vision.")
            try:
                from pdf2image import convert_from_bytes
                images = convert_from_bytes(pdf_bytes, first_page=1, last_page=3, dpi=150)
                
                prompt_parts = [
                    "Read the exam paper images below and generate 10 short practice questions (one line each).",
                    "Rules: Output ONLY 10 numbered questions (1 to 10). Write in PLAIN ENGLISH. Use 'ohm' not Ω. Do NOT use LaTeX or special symbols. Do NOT refer to diagrams or figures. Each question must be self-contained."
                ]
                
                for img in images:
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG')
                    prompt_parts.append(img_byte_arr.getvalue())

                for model_name in models_to_try:
                    if ai_text:
                        break
                    for i, key in enumerate(GEMINI_KEYS):
                        try:
                            client = genai.Client(api_key=key)
                            response = client.models.generate_content(
                                model=model_name,
                                contents=prompt_parts
                            )
                            ai_text = response.text
                            print(f"Vision Success with {model_name}, key #{i+1}")
                            break
                        except Exception as e:
                            last_error = str(e)
                            print(f"Vision {model_name} | Key #{i+1} failed: {last_error[:80]}")
                            continue
                    if not ai_text:
                        time.sleep(random.uniform(2, 5))
            except Exception as e:
                print(f"Image conversion failed: {e}")
                cursor.close()
                conn.close()
                return jsonify({"error": "ocr_failed", "message": f"Could not read PDF: {str(e)[:100]}"}), 500

        # 6. HANDLE FAILURE
        if ai_text is None:
            cursor.close()
            conn.close()
            return jsonify({
                "error": "ai_busy",
                "message": "Google's AI is currently overloaded. Please try again in 2 minutes."
            }), 429

        # 7. SAVE TO DATABASE (CACHE)
        cursor.execute(
            "UPDATE papers SET generated_questions = %s WHERE filename = %s",
            (ai_text, filename)
        )
        conn.commit()
        cursor.close()
        conn.close()
        print(f"Cached questions for {filename}")

        # 8. RETURN PDF
        return build_pdf_response(ai_text)

    except Exception as e:
        print(f"AI error: {e}")
        return jsonify({"error": "ai_failed", "message": str(e)[:150]}), 500


# ─── HELPER: BUILD PDF FROM AI TEXT ───
def build_pdf_response(ai_text):
    """Converts raw AI text into a clean, downloadable PDF."""
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
from flask import Flask, request, jsonify, send_from_directory, Response, make_response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_limiter.errors import RateLimitExceeded
from supabase import create_client, Client
from groq import Groq
import psycopg2
import psycopg2.extras
import os
import re
import hashlib
import io
import time
import requests as req
import PyPDF2
from fpdf import FPDF
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# ─── RATE LIMITING ───
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
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

# ─── GROQ AI ───
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ─── ADMIN PASSWORD ───
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
ADMIN_PASSWORD_HASH = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()

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

# ─── AI QUESTION GENERATOR (GROQ) ───
@app.route('/generate-questions/<filename>', methods=['POST'])
@limiter.limit("3 per minute")
def generate_questions(filename):
    try:
        # Get paper URL
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT supabase_url FROM papers WHERE filename = %s", (filename,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if not result:
            return jsonify({"error": "not_found"}), 404

        # Download PDF
        pdf_response = req.get(result[0])
        if pdf_response.status_code != 200:
            return jsonify({"error": "pdf_fetch_failed"}), 500

        # Extract text from first 4 pages
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_response.content))
        text = ""
        for page in pdf_reader.pages[1:5]:
            text += page.extract_text()

        del pdf_response
        del pdf_reader

        if not text.strip():
            return jsonify({"error": "no_text"}), 400

        text = text[:3000]

        prompt = f"""Read the exam paper content below and generate 10 practice questions for a student preparing for this exam.

INSTRUCTIONS:
1. First, understand what subject/topic this paper is about.
2. Generate 10 questions ONLY on that subject/topic.
3. Questions must test understanding, calculation, or application.
4. Output ONLY the 10 numbered questions (1 to 10).
5. Write in PLAIN ENGLISH.
6. Use full words instead of symbols:
   - "ohm" instead of the ohm symbol
   - "microfarad" instead of the micro symbol F
   - "millihenry" instead of mH when used after a number
   - "volt" instead of V when written after a number
   - "ampere" instead of A when written after a number
7. Do NOT use LaTeX, backslashes, dollar signs, curly braces, or backticks.
8. Do NOT ask questions that refer to "the circuit shown below", "the diagram above", "the figure", or any image. All questions must be solvable from text alone.
9. Do NOT reference the document, marks, instructions, or course outcomes.
10. Each question must be fully self-contained.

Paper content:
{text}

Generate 10 questions:"""

        # Call Groq (single attempt)
        try:
            client = Groq(api_key=GROQ_API_KEY)
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="openai/gpt-oss-120b",
                max_tokens=2000
            )
            ai_text = chat_completion.choices[0].message.content
        except Exception as e:
            return jsonify({
                "error": "ai_failed",
                "message": f"AI failed: {str(e)[:150]}"
            }), 500

        # Filter out diagram-dependent questions (backup safety)
        bad_phrases = ["shown below", "shown above", "the figure", "the diagram", "in the image", "refer to the"]
        lines = ai_text.split('\n')
        filtered = [l for l in lines if not any(p in l.lower() for p in bad_phrases)]
        ai_text = '\n'.join(filtered)

        # Create PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, txt="QStack Practice Questions", ln=True, align='C')
        pdf.ln(8)
        pdf.set_font("Arial", size=12)

        for line in ai_text.split('\n'):
            # Replace symbols with words
            line = line.replace('Ω', ' ohm ')
            line = line.replace('µF', ' microfarad ')
            line = line.replace('µ', ' micro ')
            line = line.replace('mH', ' millihenry ')
            line = line.replace('×', ' x ')
            line = line.replace('≈', ' approximately ')

            # Remove LaTeX artifacts
            line = line.replace('\\Omega', ' ohm ')
            line = line.replace('\\mu', ' micro ')
            line = line.replace('\\text{', '')
            line = line.replace('\\text', '')
            line = line.replace('\\', '')
            line = line.replace('{', '')
            line = line.replace('}', '')
            line = line.replace('$', '')
            line = line.replace('`', '')

            # Strip any remaining non-ASCII
            clean_line = re.sub(r'[^\x00-\x7F]+', '', line)

            if clean_line.strip():
                pdf.multi_cell(0, 8, txt=clean_line, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(6)

        pdf_output = bytes(pdf.output(dest='S'))

        response = make_response(pdf_output)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'inline; filename=questions.pdf'
        return response

    except Exception as e:
        print(f"AI error: {e}")
        return jsonify({"error": "ai_failed", "message": str(e)[:150]}), 500

# ─── INITIALIZE DATABASE ───
with app.app_context():
    init_db()

if __name__ == '__main__':
    print("\n📚 QStack Server running on http://localhost:5000\n")
    app.run(port=5000, debug=True)
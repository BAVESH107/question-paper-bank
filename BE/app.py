from http.server import BaseHTTPRequestHandler
from google import genai
from fpdf import FPDF
import PyPDF2
import io
import os
import re
import time
import requests as req
import urllib.parse

# ═══════════════════════════════════════════════════════════════════
# 🔑 3 GEMINI API KEYS
# ═══════════════════════════════════════════════════════════════════
GEMINI_KEYS = [
    os.environ.get("GEMINI_API_KEY_1"),
    os.environ.get("GEMINI_API_KEY_2"),
    os.environ.get("GEMINI_API_KEY_3"),
]
# ═══════════════════════════════════════════════════════════════════

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # 1. Get filename from URL
            filename = urllib.parse.unquote(self.path.split('/')[-1])

            # 2. Get paper URL from Supabase
            supabase_url = os.environ.get("SUPABASE_URL")
            supabase_key = os.environ.get("SUPABASE_KEY")

            resp = req.get(
                f"{supabase_url}/rest/v1/papers?filename=eq.{filename}&select=supabase_url",
                headers={"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
            )
            data = resp.json()

            if not data:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"error": "not_found"}')
                return

            pdf_url = data[0]["supabase_url"]

            # 3. Download PDF (stream, limited to 2MB)
            pdf_response = req.get(pdf_url, stream=True)
            pdf_bytes = pdf_response.raw.read(2 * 1024 * 1024)
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))

            text = ""
            for page in pdf_reader.pages[1:3]:
                text += page.extract_text()
            text = text[:1000]

            # 4. Build prompt
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

            # ═══════════════════════════════════════════════════════════
            # 🔑 TRY ALL 3 KEYS (2 ROUNDS)
            # ═══════════════════════════════════════════════════════════
            ai_text = None
            last_error = None

            for attempt in range(2):
                for i, key in enumerate(GEMINI_KEYS):
                    if not key:
                        continue
                    try:
                        client = genai.Client(api_key=key)
                        response = client.models.generate_content(
                            model="gemini-3.6-flash",
                            contents=prompt
                        )
                        ai_text = response.text
                        print(f"Success with key #{i + 1}")
                        break
                    except Exception as e:
                        last_error = str(e)
                        print(f"Key #{i + 1} attempt {attempt + 1} failed: {last_error[:80]}")
                        continue

                if ai_text:
                    break
                time.sleep(2)

            if ai_text is None:
                self.send_response(503)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"error": "ai_busy", "message": "AI is overloaded. Try again in a minute."}')
                return
            # ═══════════════════════════════════════════════════════════

            # 5. Build the PDF
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", 'B', 16)
            pdf.cell(0, 10, txt="QStack Practice Questions", ln=True, align='C')
            pdf.ln(8)
            pdf.set_font("Arial", size=12)

            for line in ai_text.split('\n'):
                line = line.replace('Ω', ' ohm ')
                line = line.replace('µF', ' microfarad ')
                line = line.replace('µ', ' micro ')
                line = line.replace('mH', ' millihenry ')
                line = line.replace('×', ' x ')
                line = line.replace('\\Omega', ' ohm ')
                line = line.replace('\\mu', ' micro ')
                line = line.replace('\\text{', '')
                line = line.replace('\\text', '')
                line = line.replace('\\', '')
                line = line.replace('{', '')
                line = line.replace('}', '')
                line = line.replace('$', '')
                line = line.replace('`', '')

                clean_line = re.sub(r'[^\x00-\x7F]+', '', line)

                if clean_line.strip():
                    pdf.multi_cell(0, 8, txt=clean_line, new_x="LMARGIN", new_y="NEXT")
                    pdf.ln(6)

            pdf_output = bytes(pdf.output(dest='S'))

            # 6. Return the PDF
            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Disposition', 'inline; filename=questions.pdf')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(pdf_output)

        except Exception as e:
            error_msg = str(e)[:150]
            print(f"AI error: {error_msg}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(f'{{"error": "ai_failed", "message": "{error_msg}"}}'.encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
from http.server import BaseHTTPRequestHandler
from google import genai
import PyPDF2
import io
import os
import re
import requests as req
import urllib.parse

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # 1. Get the filename from the URL
            filename = urllib.parse.unquote(self.path.split('/')[-1])
            
            # 2. Get paper URL from Supabase (via REST API)
            supabase_url = os.environ.get("SUPABASE_URL")
            supabase_key = os.environ.get("SUPABASE_KEY")
            
            resp = req.get(
                f"{supabase_url}/rest/v1/papers?filename=eq.{filename}&select=supabase_url",
                headers={"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
            )
            data = resp.json()
            
            if not data:
                self.send_response(404)
                self.end_headers()
                return
            
            pdf_url = data[0]["supabase_url"]
            
            # 3. Download and extract text (lightweight)
            pdf_response = req.get(pdf_url, stream=True)
            pdf_bytes = pdf_response.raw.read(2 * 1024 * 1024) # Limit to 2MB
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            
            text = ""
            for page in pdf_reader.pages[1:3]: # Skip cover, take 2 pages
                text += page.extract_text()
            text = text[:1500] # Keep prompt small
            
            # 4. Generate with Gemini
            client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
            prompt = f"""Read the exam paper content below and generate 10 practice questions.
            
Paper content:
{text}

Output ONLY 10 numbered questions. Plain English. No diagrams."""
            
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )
            
            # 5. Return the result
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(response.text.encode())
            
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(f'{{"error": "{str(e)[:100]}"}}'.encode())
    
    def do_OPTIONS(self):
        # This handles the browser's CORS preflight check
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
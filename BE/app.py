# ─── AI QUESTION GENERATOR (GEMINI VISION + CACHING) ───
@app.route('/generate-questions/<filename>', methods=['POST'])
@limiter.limit("5 per minute")
def generate_questions(filename):
    try:
        # 1. CONNECT TO DB & CHECK CACHE
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT supabase_url, generated_questions FROM papers WHERE filename = %s", (filename,))
        result = cursor.fetchone()

        if not result:
            cursor.close()
            conn.close()
            return jsonify({"error": "not_found"}), 404

        supabase_url, cached_questions = result

        # 2. IF CACHED, RETURN IMMEDIATELY (No Gemini call!)
        if cached_questions:
            cursor.close()
            conn.close()
            print(f"✅ Serving cached questions for {filename}")
            return build_pdf_response(cached_questions)

        # 3. DOWNLOAD PDF FROM SUPABASE
        print(f"🔄 Generating new questions for {filename}...")
        pdf_response = req.get(supabase_url, stream=True)
        if pdf_response.status_code != 200:
            cursor.close()
            conn.close()
            return jsonify({"error": "pdf_fetch_failed"}), 500

        pdf_bytes = pdf_response.raw.read(10 * 1024 * 1024)  # 10MB limit for scans
        del pdf_response

        # 4. TRY TEXT EXTRACTION FIRST (Digital PDFs)
        import pypdf
        pdf_reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in pdf_reader.pages[:5]:  # Read first 5 pages
            extracted = page.extract_text()
            if extracted:
                text += extracted
        
        # 5. DECIDE: TEXT PROMPT vs VISION PROMPT
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

        # ─── CASE A: DIGITAL PDF (Has extractable text) ───
        if len(text.strip()) > 50:
            print("📄 Digital PDF detected. Using text extraction.")
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
                        print(f"✅ Success with {model_name}, key #{i+1}")
                        break
                    except Exception as e:
                        last_error = str(e)
                        print(f"❌ {model_name} | Key #{i+1} failed: {last_error[:80]}")
                        continue
                if not ai_text:
                    import random
                    time.sleep(random.uniform(2, 5))

        # ─── CASE B: SCANNED PDF (No text) ───
        else:
            print("🖼️ Scanned PDF detected. Converting to images for Gemini Vision.")
            try:
                from pdf2image import convert_from_bytes
                # Convert first 3 pages of the PDF into images
                images = convert_from_bytes(pdf_bytes, first_page=1, last_page=3, dpi=150)
                
                # Build a multimodal prompt for Gemini
                prompt_parts = [
                    "Read the exam paper images below and generate 10 short practice questions (one line each).",
                    "Rules: Output ONLY 10 numbered questions (1 to 10). Write in PLAIN ENGLISH. Use 'ohm' not Ω. Do NOT use LaTeX or special symbols. Do NOT refer to diagrams or figures. Each question must be self-contained."
                ]
                
                # Add each image to the prompt
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
                            print(f"✅ Vision Success with {model_name}, key #{i+1}")
                            break
                        except Exception as e:
                            last_error = str(e)
                            print(f"❌ Vision {model_name} | Key #{i+1} failed: {last_error[:80]}")
                            continue
                    if not ai_text:
                        import random
                        time.sleep(random.uniform(2, 5))
            except Exception as e:
                print(f"❌ Image conversion failed: {e}")
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
        print(f"💾 Cached questions for {filename}")

        # 8. RETURN PDF
        return build_pdf_response(ai_text)

    except Exception as e:
        print(f"🔥 AI error: {e}")
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
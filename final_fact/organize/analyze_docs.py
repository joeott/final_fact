import os
import csv
import time
import json
import logging
from google import genai
from google.genai import types
from tqdm import tqdm
import requests
import base64
import google.auth
from google.auth.transport.requests import Request

# Configuration
SOURCE_DIR = os.path.dirname(os.path.abspath(__file__)) # ai_docs/organize
ROOT_DIR = os.path.dirname(os.path.dirname(SOURCE_DIR)) # Kunda v. Smith root
ORGANIZED_DIR = os.path.join(ROOT_DIR, "organized")
OCR_DIR = os.path.join(ORGANIZED_DIR, "ocr")
ANALYSIS_DIR = os.path.join(ORGANIZED_DIR, "analysis")
ANALYSIS_FILE = os.path.join(ANALYSIS_DIR, "analysis.csv")
FILE_INVENTORY = os.path.join(ORGANIZED_DIR, "file_inventory.csv")
PETITION_FILE = os.path.join(ROOT_DIR, "Trial/1. Plaintiff Evidence/Petition.pdf")

# Project Config
PROJECT_ID = "document-processor-v3"
LOCATION = "us-central1" 

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

import docx

def extract_text_from_docx(filepath):
    try:
        doc = docx.Document(filepath)
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)
        return '\n'.join(full_text)
    except Exception as e:
        logging.error(f"Error reading .docx {filepath}: {e}")
        return None

def extract_text_from_doc_fallback(filepath):
    # Fallback for binary .doc files using strings
    try:
        with open(filepath, 'rb') as f:
            content = f.read()
            # Basic strings extraction: printable chars >= 4
            result = ""
            current_string = ""
            for byte in content:
                char = chr(byte)
                if char.isprintable():
                    current_string += char
                else:
                    if len(current_string) >= 4:
                        result += current_string + "\n"
                    current_string = ""
            return result
    except Exception as e:
        logging.error(f"Error reading .doc {filepath}: {e}")
        return None


# Setup Client
# Using the Unified Google GenAI SDK
try:
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
except Exception as e:
    logging.error(f"Failed to initialize Vertex AI client: {e}")
    exit(1)

def get_token():
    """Retrieves Google Cloud auth token."""
    creds, project = google.auth.default()
    creds.refresh(Request())
    return creds.token

def load_inventory_mapping():
    """Loads file_inventory.csv to map New Filename -> Original Path."""
    mapping = {} # Filename -> Original Path
    if os.path.exists(FILE_INVENTORY):
        with open(FILE_INVENTORY, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                mapping[row['New Filename']] = row['Original Path']
    else:
        logging.warning("file_inventory.csv not found. Original paths will be missing.")
    return mapping

# Retry configuration
MAX_RETRIES = 5
INITIAL_BACKOFF = 2

def retry_request(func):
    """Decorator to retry functions on failure (429/5xx)."""
    def wrapper(*args, **kwargs):
        backoff = INITIAL_BACKOFF
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Check for rate limit or server errors
                is_retryable = False
                error_str = str(e).lower()
                if "429" in error_str or "quota" in error_str:
                    is_retryable = True
                elif "500" in error_str or "503" in error_str or "504" in error_str:
                    is_retryable = True
                
                if is_retryable and attempt < MAX_RETRIES - 1:
                    logging.warning(f"Request failed with {e}. Retrying in {backoff}s...")
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    logging.error(f"Request failed permanently after {attempt+1} attempts: {e}")
                    return None
    return wrapper

@retry_request
def perform_ocr_vertex(filepath, filename):
    """
    Performs OCR using Mistral OCR via Vertex AI (Raw HTTP Predict).
    Save output to .md file in OCR_DIR.
    """
    ocr_filename = os.path.splitext(filename)[0] + ".md"
    ocr_path = os.path.join(OCR_DIR, ocr_filename)

    # Check cache
    if os.path.exists(ocr_path):
        logging.info(f"Loading cached OCR for {filename}")
        with open(ocr_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    logging.info(f"OCR Processing {filename} with mistral-ocr-2505...")
    
    # Read file bytes & base64 encode
    with open(filepath, "rb") as f:
        file_content = f.read()
    
    encoded_content = base64.b64encode(file_content).decode('utf-8')

    # Determine MIME type
    mime_type = "application/pdf"
    ext = os.path.splitext(filename)[1].lower()
    if ext in ['.jpg', '.jpeg']:
        mime_type = "image/jpeg"
    elif ext == '.png':
        mime_type = "image/png"
        
    logging.info(f"Uploading {filename} as {mime_type}")

    # Construct Endpoint & Payload for rawPredict
    model_id = "mistral-ocr-2505"
    endpoint = f"https://{LOCATION}-aiplatform.googleapis.com/v1beta1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/mistralai/models/{model_id}:rawPredict"
    
    payload = {
        "model": model_id,
        "document": {
            "type": "document_url",
            "document_url": f"data:{mime_type};base64,{encoded_content}"
        },
        "include_image_base64": False
    }

    # Send Request
    token = get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = requests.post(endpoint, headers=headers, json=payload)
    
    if response.status_code == 429:
        raise Exception(f"429 Quota Exceeded for OCR: {response.text}")
    
    if response.status_code != 200:
        logging.error(f"OCR Request failed: {response.status_code} - {response.text[:200]}")
        return None
        
    result_json = response.json()
    
    # Combine pages
    full_markdown = ""
    if "pages" in result_json:
        for page in result_json["pages"]:
            full_markdown += page.get("markdown", "") + "\n\n"
    
    if not full_markdown:
        logging.warning(f"No OCR text content found in response for {filename}")
        return None

    # Save to cache
    with open(ocr_path, 'w', encoding='utf-8') as f:
        f.write(full_markdown)
        
    return full_markdown

@retry_request
def analyze_with_gemini(content_input, filename, petition_text, mime_type=None):
    """
    Analyzes content using Gemini 3.0 Flash.
    content_input: Can be a string (text) or bytes (image/media).
    mime_type: Required if content_input is bytes.
    """
    if not content_input:
        return None

    # Construct Prompt Part
    prompt_text = f"""
    You are a legal assistant. Analyze this digital file in the context of the allegations in the following Petition.

    PETITION CONTENT (Context):
    {petition_text[:30000]}
    
    INSTRUCTIONS:
    1. Provide a concise 1-sentence summary of the file.
    2. Analyze its relevance to the allegations in the Petition (Relevant, Not Relevant, Potentially Relevant) and explain why in 1-2 sentences.

    OUTPUT FORMAT (JSON):
    {{
        "summary": "...",
        "relevance_status": "Relevant" | "Not Relevant" | "Potentially Relevant",
        "relevance_explanation": "..."
    }}
    """

    generation_contents = [prompt_text]

    if getattr(content_input, 'encode', None): # It's a string (Text/OCR output)
        generation_contents.append(f"\nDOCUMENT CONTENT (OCR Output):\n{content_input[:100000]}")
    else: # It's bytes (Image/Video)
        if not mime_type:
            logging.error(f"Missing mime_type for binary content in {filename}")
            return None
        generation_contents.append(types.Part.from_bytes(data=content_input, mime_type=mime_type))

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=generation_contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json" 
            )
        )
        result = json.loads(response.text)
        if isinstance(result, list):
            if len(result) > 0 and isinstance(result[0], dict):
                 return result[0]
            else:
                 logging.warning(f"Gemini returned unexpected list format for {filename}: {result}")
                 return None
        return result
    except Exception as e:
         # Re-raise to trigger retry if it's a quota issue
        if "429" in str(e) or "quota" in str(e).lower():
            raise e
        logging.error(f"Error analyzing {filename} with Gemini: {e}")
        return None

def main():
    if not os.path.exists(ANALYSIS_DIR):
        os.makedirs(ANALYSIS_DIR)
    if not os.path.exists(OCR_DIR):
        os.makedirs(OCR_DIR)

    # 1. OCR Petition
    logging.info("Processing Petition...")
    if not os.path.exists(PETITION_FILE):
        logging.error(f"Petition file not found at {PETITION_FILE}")
        return
        
    petition_text = perform_ocr_vertex(PETITION_FILE, "Petition.pdf")
    if not petition_text:
        logging.error("Failed to extract petition text via OCR. Aborting.")
        return

    # 2. Load Mapping
    file_mapping = load_inventory_mapping()

    # 3. Check processed files
    processed_files = set()
    if os.path.exists(ANALYSIS_FILE):
        with open(ANALYSIS_FILE, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if row:
                    try:
                        processed_files.add(row[1])
                    except IndexError:
                        pass

    # 4. Iterate
    files_to_process = sorted([f for f in os.listdir(ORGANIZED_DIR) if f.startswith("DOC_")])
    
    file_exists = os.path.exists(ANALYSIS_FILE)
    mode = 'a' if file_exists else 'w'
    
    with open(ANALYSIS_FILE, mode, newline='', encoding='utf-8') as csvfile:
        fieldnames = ['Original File Path', 'Organized Doc Number', 'File Type', 'File Description', 'Relevance Analysis']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        if not file_exists:
            writer.writeheader()

        for filename in tqdm(files_to_process, desc="Docs"):
            if filename in processed_files:
                continue
                
            filepath = os.path.join(ORGANIZED_DIR, filename)
            if os.path.isdir(filepath):
                continue
            
            # Temporary block for known problematic file causing hang
            if "DOC_0419" in filename:
                 logging.warning(f"Skipping known problematic file: {filename}")
                 continue
            
            ext = os.path.splitext(filename)[1].lower()
            
            # Supported types: Documents only (PDF, Word, Text, RTF)
            # Excluding images/videos as per user request
            supported_docs = ['.pdf', '.doc', '.docx', '.txt', '.rtf']
            is_document = ext in supported_docs
            
            if not is_document:
                 # Log skipping only once per run or debug
                 # logging.info(f"Skipping {filename} (unsupported extension)")
                 continue

            result = None
            


            # Path A: Document processing
            if is_document:
                text_content = None
                
                if ext == '.pdf':
                    text_content = perform_ocr_vertex(filepath, filename)
                    # Fallback for PDF if OCR fails
                    if not text_content:
                         # Try direct Gemini for PDF? (Implemented previously in fallback block, but integrating here)
                         pass 
                
                elif ext == '.docx':
                    text_content = extract_text_from_docx(filepath)
                
                elif ext == '.doc':
                    text_content = extract_text_from_doc_fallback(filepath)
                
                elif ext in ['.txt', '.rtf']:
                    try:
                        with open(filepath, 'r', errors='ignore') as f:
                            text_content = f.read()
                    except Exception as e:
                        logging.error(f"Error reading text file {filename}: {e}")

                # Analyze if we got text
                if text_content:
                    result = analyze_with_gemini(text_content, filename, petition_text)
                elif ext == '.pdf': 
                    # PDF Fallback logic (Direct Gemini)
                    file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
                    logging.info(f"OCR failed/skipped. Attempting direct Gemini analysis for {filename} ({file_size_mb:.2f} MB)...")
                    with open(filepath, "rb") as f:
                        file_bytes = f.read()
                    result = analyze_with_gemini(file_bytes, filename, petition_text, mime_type="application/pdf")

            # Save Result
            if result:
                original_path = file_mapping.get(filename, "Unknown")
                file_type = ext
                
                relevance_analysis = f"{result.get('relevance_status', 'Unknown')}: {result.get('relevance_explanation', '')}"
                
                row = {
                    'Original File Path': original_path,
                    'Organized Doc Number': filename,
                    'File Type': file_type,
                    'File Description': result.get('summary', ''),
                    'Relevance Analysis': relevance_analysis
                }
                
                writer.writerow(row)
                csvfile.flush()
            
            # Rate limiting sleep
            time.sleep(2.0)

    logging.info("Analysis complete.")

if __name__ == "__main__":
    main()

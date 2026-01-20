import os
import io
import math
import logging
import base64
import requests
import google.auth
from google.auth.transport.requests import Request
from pypdf import PdfReader, PdfWriter
from tqdm import tqdm
import time

# Config
SOURCE_DIR = "organized"
OCR_DIR = os.path.join(SOURCE_DIR, "ocr")
PROJECT_ID = "document-processor-v3"
LOCATION = "us-central1"
CHUNK_SIZE = 25  # Pages per chunk (Safe under 30)

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_token():
    creds, project = google.auth.default()
    creds.refresh(Request())
    return creds.token

def perform_ocr_on_bytes(file_bytes, filename_hint):
    """Sends bytes to Mistral OCR."""
    encoded_content = base64.b64encode(file_bytes).decode('utf-8')
    mime_type = "application/pdf" # Always PDF for chunks
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

    token = get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Retry loop
    for attempt in range(3):
        try:
            response = requests.post(endpoint, headers=headers, json=payload)
            if response.status_code == 200:
                result_json = response.json()
                full_markdown = ""
                if "pages" in result_json:
                    for page in result_json["pages"]:
                        full_markdown += page.get("markdown", "") + "\n\n"
                return full_markdown
            elif response.status_code == 429:
                logging.warning(f"429 Quota on chunk {filename_hint}, retrying...")
                time.sleep(5 * (attempt + 1))
            else:
                logging.error(f"Error {response.status_code} on chunk {filename_hint}: {response.text[:200]}")
                break
        except Exception as e:
            logging.error(f"Exception on chunk {filename_hint}: {e}")
            time.sleep(2)
            
    return None

def process_large_pdf(filepath, filename):
    ocr_filename = os.path.splitext(filename)[0] + ".md"
    ocr_path = os.path.join(OCR_DIR, ocr_filename)
    
    # Check cache first
    if os.path.exists(ocr_path):
        logging.info(f"Skipping {filename} (Already OCR'd)")
        return

    try:
        reader = PdfReader(filepath)
        total_pages = len(reader.pages)
        
        if total_pages <= 30:
            return  # Skip small files, handled by main script
            
        logging.info(f"Processing Large File: {filename} ({total_pages} pages)")
        
        full_doc_markdown = f"# OCR Output for {filename}\n\n"
        
        num_chunks = math.ceil(total_pages / CHUNK_SIZE)
        
        for i in range(num_chunks):
            start_page = i * CHUNK_SIZE
            end_page = min((i + 1) * CHUNK_SIZE, total_pages)
            
            chunk_writer = PdfWriter()
            for page_num in range(start_page, end_page):
                chunk_writer.add_page(reader.pages[page_num])
                
            chunk_bytes_io = io.BytesIO()
            chunk_writer.write(chunk_bytes_io)
            chunk_bytes = chunk_bytes_io.getvalue()
            
            logging.info(f"  - Chunk {i+1}/{num_chunks} (Pages {start_page+1}-{end_page})...")
            
            chunk_text = perform_ocr_on_bytes(chunk_bytes, f"{filename}_chunk_{i}")
            
            if chunk_text:
                full_doc_markdown += chunk_text + "\n\n---\n\n"
            else:
                logging.error(f"Failed to OCR chunk {i+1} for {filename}")
                full_doc_markdown += f"\n[OCR Failed for Pages {start_page+1}-{end_page}]\n\n"
            
            time.sleep(1) # rate limit padding

        # Save merged markdown
        with open(ocr_path, "w", encoding='utf-8') as f:
            f.write(full_doc_markdown)
            
        logging.info(f"Saved merged OCR to {ocr_path}")

    except Exception as e:
        logging.error(f"Failed to process {filename}: {e}")

def main():
    if not os.path.exists(OCR_DIR):
        os.makedirs(OCR_DIR)

    files = sorted([f for f in os.listdir(SOURCE_DIR) if f.lower().endswith(".pdf")])
    
    # Filter for large files only
    large_files = []
    for f in files:
        if "DOC_" not in f: continue
        fp = os.path.join(SOURCE_DIR, f)
        try:
            reader = PdfReader(fp)
            if len(reader.pages) > 30:
                large_files.append(f)
        except:
            pass

    print(f"Found {len(large_files)} large PDFs (>30 pages) to process.")
    
    for filename in tqdm(large_files):
        filepath = os.path.join(SOURCE_DIR, filename)
        process_large_pdf(filepath, filename)

if __name__ == "__main__":
    main()

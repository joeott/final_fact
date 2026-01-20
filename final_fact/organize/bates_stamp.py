import os
import io
import re
from tqdm import tqdm
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from pypdf import PdfReader, PdfWriter

# Config
SOURCE_DIR = "organized"
MARKED_DIR = os.path.join(SOURCE_DIR, "marked")
FONT_SIZE = 15
X_POSITION = 30  # Bottom Left margin
Y_POSITION = 30  # Bottom margin

def create_stamp_pdf(text, width, height):
    """Creates a temporary PDF with the bates stamp."""
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(width, height))
    c.setFont("Helvetica-Bold", FONT_SIZE) # All caps usually looks better bold, user asked for size 15
    # User asked for ALL CAPS. The DOC_XXXX is typically caps, but we force it.
    c.drawString(X_POSITION, Y_POSITION, text.upper())
    c.save()
    packet.seek(0)
    return packet

def stamp_pdf(filepath, output_path, bates_text):
    """Applies the bates stamp to a single PDF."""
    try:
        reader = PdfReader(filepath)
        writer = PdfWriter()

        for page_num, page in enumerate(reader.pages, start=1):
            # Get page dimensions to ensure stamp is relative to page size
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            
            # Format: DOC_XXXX-001
            page_bates = f"{bates_text}-{page_num:03d}"
            
            # Create stamp for this page size
            stamp_io = create_stamp_pdf(page_bates, width, height)
            stamp_pdf_reader = PdfReader(stamp_io)
            stamp_page = stamp_pdf_reader.pages[0]

            # Merge stamp (overlay)
            page.merge_page(stamp_page)
            writer.add_page(page)

        with open(output_path, "wb") as f:
            writer.write(f)
            
        return True
    except Exception as e:
        print(f"Error stamping {filepath}: {e}")
        return False

def main():
    if not os.path.exists(MARKED_DIR):
        os.makedirs(MARKED_DIR)

    files = sorted([f for f in os.listdir(SOURCE_DIR) if f.startswith("DOC_") and f.lower().endswith(".pdf")])
    
    print(f"Found {len(files)} PDFs to stamp.")
    
    for filename in tqdm(files, desc="Stamping"):
        input_path = os.path.join(SOURCE_DIR, filename)
        output_path = os.path.join(MARKED_DIR, filename)
        
        # Skip if already stamped
        if os.path.exists(output_path):
            continue
            
        # Extract Prefix (DOC_XXXX)
        # Assuming filename format is DOC_XXXX_... or DOC_XXXX_...
        # We can just take the first part split by underscore if it matches DOC
        # Actually user said "doc_ prefix for each file name".
        # Let's extract DOC_XXXX using regex to be safe.
        match = re.match(r"(DOC_\d+)", filename)
        if match:
            bates_text = match.group(1)
        else:
            # Fallback if specific pattern not found, roughly take first 8 chars? 
            # Or just DOC_....
            # Let's assume the user wants the DOC_XXXX part.
            # If filename is DOC_0001_some_file.pdf, stamp is DOC_0001.
            bates_text = filename.split("_")[0] + "_" + filename.split("_")[1]
        
        # Verify it looks like a bates number
        if not bates_text.startswith("DOC_"):
             print(f"Warning: Could not extract bates number from {filename}. Using filename.")
             bates_text = filename

        stamped = stamp_pdf(input_path, output_path, bates_text)

    print("Bates stamping complete.")

if __name__ == "__main__":
    main()

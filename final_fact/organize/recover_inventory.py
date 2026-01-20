import os
import csv
import hashlib
from tqdm import tqdm

# Configuration
SOURCE_DIR = os.path.dirname(os.path.abspath(__file__)) # ai_docs/organize
ROOT_DIR = os.path.dirname(os.path.dirname(SOURCE_DIR)) # Kunda v. Smith root
ORGANIZED_DIR = os.path.join(ROOT_DIR, "organized")
MANIFEST_FILE = os.path.join(ORGANIZED_DIR, "manifest.text")
INVENTORY_FILE = os.path.join(ORGANIZED_DIR, "file_inventory.csv")

def get_file_hash(filepath):
    """Calculates SHA256 hash of a file."""
    hasher = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        print(f"Error hashing {filepath}: {e}")
        return None

def main():
    print(" recovering file inventory mapping...")
    
    # 1. Load Source Files from Manifest
    print("Loading manifest...")
    source_files = []
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, 'r') as f:
            for line in f:
                path = line.strip()
                if path:
                    # Resolve relative path if needed, usually manifest entries are relative to project root?
                    # manifest.text lines: "Kunda - Search Cert..."
                    # Check if relative or absolute?
                    # organize_files.py line 94: rel_path = os.path.relpath(filepath, SOURCE_DIR)
                    # SOURCE_DIR there was os.getcwd().
                    # Let's assume paths are relative to ROOT_DIR.
                    full_path = os.path.join(ROOT_DIR, path)
                    if not os.path.exists(full_path):
                        # Try ignoring first part?
                        pass
                    source_files.append(full_path)
    else:
        print("Manifest file not found!")
        return

    print(f"Loaded {len(source_files)} source paths from manifest.")

    # 2. Hash Source Files
    # Map Hash -> Original Path (Keep first occurrence or list?)
    source_hashes = {} 
    for path in tqdm(source_files, desc="Hashing Source"):
        if os.path.exists(path) and os.path.isfile(path):
            h = get_file_hash(path)
            if h:
                source_hashes[h] = path # If duplicates, one is fine for mapping purpose

    # 3. Hash Organized Files
    organized_files = [f for f in os.listdir(ORGANIZED_DIR) if f.startswith("DOC_")]
    
    inventory_rows = []
    
    for filename in tqdm(organized_files, desc="Hashing Organized"):
        filepath = os.path.join(ORGANIZED_DIR, filename)
        if os.path.isfile(filepath):
            h = get_file_hash(filepath)
            if h:
                original_path = source_hashes.get(h, "Unknown (Hash not found in source)")
                # If unknown, maybe try to match basename?
                if "Unknown" in original_path:
                    # Fallback: check basenames
                    # This is fuzzy but better than nothing
                    pass
                
                # Make original path relative for readability
                if "Unknown" not in original_path:
                    try:
                        rel_original = os.path.relpath(original_path, ROOT_DIR)
                    except:
                        rel_original = original_path
                else:
                    rel_original = original_path

                inventory_rows.append({
                    "New Filename": filename,
                    "Original Path": rel_original,
                    "Summary": "" # Placeholder
                })

    # 4. Write Inventory
    print(f"Writing {len(inventory_rows)} rows to {INVENTORY_FILE}")
    with open(INVENTORY_FILE, 'w', newline='', encoding='utf-8') as f:
        # Match fields expected by analyze_docs.py
        writer = csv.DictWriter(f, fieldnames=["New Filename", "Original Path", "Summary"])
        writer.writeheader()
        writer.writerows(inventory_rows)

    print("Success.")

if __name__ == "__main__":
    main()

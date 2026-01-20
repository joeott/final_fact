import os
import hashlib
import shutil
import csv
import time
import google.generativeai as genai
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
SOURCE_DIR = os.getcwd() # Running from the root of the project
TARGET_DIR = os.path.abspath(os.path.join(SOURCE_DIR, "organized"))
MANIFEST_FILE = os.path.join(TARGET_DIR, "manifest.text")
INVENTORY_FILE = os.path.join(TARGET_DIR, "file_inventory.csv")
API_KEY = os.environ.get("GEMINI_API_KEY")

# Concurrency settings
HASHING_WORKERS = 16
COPYING_WORKERS = 32

# Setup Gemini
# Summarization skipped as per user request (handled by another agent)

def get_file_hash(filepath):
    """Calculates SHA256 hash of a file."""
    hasher = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            while chunk := f.read(65536): # Larger chunk size for speed
                hasher.update(chunk)
        return filepath, hasher.hexdigest()
    except Exception as e:
        print(f"Error hashing {filepath}: {e}")
        return filepath, None

def process_file_copy(args):
    """Worker to copy a file."""
    original_path, new_filepath, new_filename = args
    if os.path.exists(new_filepath):
        return True # Skip if already exists
        
    try:
        shutil.copy2(original_path, new_filepath)
        return True
    except Exception as e:
        print(f"Error copying {original_path}: {e}")
        return False

def main():
    if not os.path.exists(TARGET_DIR):
        os.makedirs(TARGET_DIR)

    print(f"Scanning directory: {SOURCE_DIR}")
    
    all_files = []
    # Walk the directory
    for root, dirs, files in os.walk(SOURCE_DIR):
        # Exclude hidden directories, .venv, and the target 'organized' directory
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'organized' and d != 'ai_docs']
        
        for file in files:
            if file.startswith('.'):
                continue
            filepath = os.path.join(root, file)
            all_files.append(filepath)

    print(f"Found {len(all_files)} files.")
    
    # Create Manifest
    print(f"Writing manifest to {MANIFEST_FILE}")
    with open(MANIFEST_FILE, 'w') as f:
        for filepath in all_files:
            rel_path = os.path.relpath(filepath, SOURCE_DIR)
            f.write(f"{rel_path}\n")

    # Deduplication - Concurrent Hashing
    print(f"Calculating hashes with {HASHING_WORKERS} workers...")
    unique_files = {} # hash -> (filepath, original_name)
    file_count = len(all_files)
    
    with ThreadPoolExecutor(max_workers=HASHING_WORKERS) as executor:
        futures = [executor.submit(get_file_hash, fp) for fp in all_files]
        
        for future in tqdm(as_completed(futures), total=file_count, desc="Hashing"):
            filepath, file_hash = future.result()
            if file_hash:
                if file_hash not in unique_files:
                    unique_files[file_hash] = filepath

    print(f"Found {len(unique_files)} unique files. {len(all_files) - len(unique_files)} duplicates.")

    # Prepare for Processing
    tasks = []
    count = 1
    sorted_hashes = sorted(unique_files.keys()) 
    
    for file_hash in sorted_hashes:
        original_path = unique_files[file_hash]
        original_dirname, original_basename = os.path.split(original_path)
        
        safe_basename = "".join([c for c in original_basename if c.isalpha() or c.isdigit() or c in (' ', '.', '-', '_')]).strip()
        new_filename = f"DOC_{count:04d}_{safe_basename}"
        new_filepath = os.path.join(TARGET_DIR, new_filename)
        
        tasks.append({
            "original_path": original_path,
            "new_filepath": new_filepath,
            "new_filename": new_filename,
            "safe_basename": safe_basename
        })
        count += 1

    # Concurrent Copying
    print(f"Copying files with {COPYING_WORKERS} workers...")
    with ThreadPoolExecutor(max_workers=COPYING_WORKERS) as executor:
        copy_futures = [executor.submit(process_file_copy, (t['original_path'], t['new_filepath'], t['new_filename'])) for t in tasks]
        for _ in tqdm(as_completed(copy_futures), total=len(tasks), desc="Copying"):
            pass
            
    # Summarization skipped. Generating Inventory.
    print(f"Writing inventory to {INVENTORY_FILE}")
    with open(INVENTORY_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["New Filename", "Original Path", "Summary"])
        writer.writeheader()
        for t in tasks:
             writer.writerow({
                "New Filename": t['new_filename'],
                "Original Path": os.path.relpath(t['original_path'], SOURCE_DIR),
                "Summary": "Pending (External Agent)"
            })

    print("Done!")

if __name__ == "__main__":
    main()

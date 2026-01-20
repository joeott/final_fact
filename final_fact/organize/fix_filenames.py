import os
import csv
import shutil
from tqdm import tqdm

ORGANIZED_DIR = "organized"
INVENTORY_FILE = "organized/file_inventory.csv"
ANALYSIS_FILE = "organized/analysis/analysis.csv"

def load_current_inventory():
    """Loads current inventory to preserve original paths."""
    inventory = {}
    if os.path.exists(INVENTORY_FILE):
        with open(INVENTORY_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Map current filename to original path
                inventory[row['New Filename']] = row.get('Original Path', 'Unknown')
    return inventory

def main():
    # 1. Load existing inventory to keep original paths
    original_path_map = load_current_inventory()
    
    # 2. List all current files in organized/ (excluding dirs)
    # We filter for files that look like they belong to the dataset (ignore .DS_Store, etc)
    all_files = [f for f in os.listdir(ORGANIZED_DIR) 
                 if os.path.isfile(os.path.join(ORGANIZED_DIR, f)) 
                 and not f.startswith('.')]
    
    # 3. Sort them to ensure deterministic order (e.g. by old name)
    all_files.sort()
    
    print(f"Found {len(all_files)} files to renumber.")
    
    # 4. Renumber
    new_inventory = []
    renaming_map = {} # Old Name -> New Name
    
    # Prepare CSV update for analysis
    analysis_update_map = {} # Old Doc Num -> New Doc Num

    for index, filename in enumerate(tqdm(all_files, desc="Renaming")):
        # Extract extension and original basename part (suffix)
        # Format: DOC_XXXX_OriginalName.ext
        # We want to keep OriginalName.ext if possible, or just .ext if it's messy
        parts = filename.split('_', 2)
        
        if len(parts) >= 3 and parts[0] == "DOC" and parts[1].isdigit():
             # It's already in DOC_XXXX format, keep the suffix
             suffix = parts[2]
        else:
             # It's a raw file or malformed, just use the filename
             suffix = filename
             
        # Generate New Name
        new_prefix = f"DOC_{index+1:04d}"
        new_filename = f"{new_prefix}_{suffix}"
        
        # Record Mapping
        original_path = original_path_map.get(filename, "Unknown")
        renaming_map[filename] = new_filename
        
        new_inventory.append({
            'New Filename': new_filename,
            'Original Path': original_path,
            'Summary': 'Pending' # Placeholder or preserve? 
        })
        
        # Map for analysis.csv (Key is the filename 'DOC_XXXX_...')
        analysis_update_map[filename] = new_filename

    # 5. Execute Renames
    # We must be careful not to overwrite files if potential collisions exist
    # So we move to a temp dir first? Or just rename since we are sorting?
    # Renaming in place is risky if DOC_0001 becomes DOC_0002 but DOC_0002 exists.
    # Safe bet: Move all to a temp subdirectory, then move back with new names.
    
    temp_dir = os.path.join(ORGANIZED_DIR, "temp_renaming")
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        
    print("Moving to temp dir...")
    for old_name in all_files:
        src = os.path.join(ORGANIZED_DIR, old_name)
        dst = os.path.join(temp_dir, old_name)
        shutil.move(src, dst)
        
    print("Renaming and moving back...")
    for old_name, new_name in renaming_map.items():
        src = os.path.join(temp_dir, old_name)
        dst = os.path.join(ORGANIZED_DIR, new_name)
        shutil.move(src, dst)
        
    os.rmdir(temp_dir)
    
    # 6. Update file_inventory.csv
    print("Updating inventory...")
    with open(INVENTORY_FILE, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['New Filename', 'Original Path', 'Summary']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(new_inventory)
        
    # 7. Update analysis.csv
    print("Updating analysis.csv...")
    if os.path.exists(ANALYSIS_FILE):
        updated_rows = []
        with open(ANALYSIS_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                old_doc_num = row.get('Organized Doc Number')
                if old_doc_num in analysis_update_map:
                    row['Organized Doc Number'] = analysis_update_map[old_doc_num]
                    updated_rows.append(row)
                else:
                    # If we can't map it, maybe keep it but warn?
                    # Or it refers to a file that was deleted/ignored?
                    pass
        
        if updated_rows:
            with open(ANALYSIS_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(updated_rows)

    print("Renumbering complete.")

if __name__ == "__main__":
    main()

import sys
import os
import re
import json
import fitz

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def extract_pdf_data(pdf_path, size_str, db_prefix):
    doc = fitz.open(pdf_path)
    page = doc[0]
    words = page.get_text("words")
    
    page_width = page.rect.width
    mid_x = page_width / 2.0
    
    max_x = max(w[2] for w in words)
    is_double_column = (max_x > 500)
    
    if not is_double_column:
        return process_half(words, db_prefix, size_str)
    else:
        left_words = [w for w in words if w[2] <= 420.0]
        right_words = [w for w in words if w[0] > 420.0]
        
        left_entries = process_half(left_words, db_prefix, size_str)
        right_entries = process_half(right_words, db_prefix, size_str)
        
        merged = {}
        merged.update(left_entries)
        merged.update(right_entries)
        return merged

def process_half(half_words, db_prefix, size_str):
    id_pattern = re.compile(rf"^{db_prefix}-\d+$")
    
    id_words = []
    for w in half_words:
        word_text = w[4].strip()
        if id_pattern.match(word_text):
            id_words.append(w)
            
    id_words = sorted(id_words, key=lambda w: w[1])
    
    entries = {}
    if not id_words:
        return entries
        
    for i, id_w in enumerate(id_words):
        col_id = id_w[4].strip()
        y_start = id_w[1] - 15  # Account for baseline shift
        
        if i < len(id_words) - 1:
            y_end = id_words[i+1][1] - 15
        else:
            y_end = y_start + 80
            
        row_words = [w for w in half_words if y_start <= w[1] < y_end]
        
        # Parse callout
        callout_words = []
        callout_found = False
        
        for w in sorted(row_words, key=lambda x: (x[1], x[0])):
            word_text = w[4]
            if "Main" in word_text or callout_found:
                callout_found = True
                callout_words.append(w)
                
        callout = "Unknown"
        if callout_words:
            callout_lines = {}
            for cw in callout_words:
                cx0, cy0, cx1, cy1, ctext, block_no, line_no, word_no = cw
                found = False
                for cy in callout_lines:
                    if abs(cy - cy0) < 3:
                        callout_lines[cy].append(cw)
                        found = True
                        break
                if not found:
                    callout_lines[cy0] = [cw]
            first_cy = min(callout_lines.keys())
            sorted_line_words = sorted(callout_lines[first_cy], key=lambda x: x[0])
            callout = " ".join([w[4] for w in sorted_line_words])
            callout = re.sub(r'\s+', ' ', callout).strip()
            
        # Extract numbers
        non_meta_words = []
        for w in row_words:
            if w in callout_words:
                continue
            if col_id in w[4]:
                continue
            if w[4] in ("Size", "Cross", "section", "Percentage", "Area", "of", "steel", "sqm", "sq.mm", "x"):
                continue
            non_meta_words.append(w)
            
        numbers = []
        for w in sorted(non_meta_words, key=lambda x: x[0]):
            text_clean = w[4].replace("sqm", "").replace("sq.mm", "").strip()
            text_clean = re.sub(r'[^\d\.]', '', text_clean)
            if not text_clean:
                continue
            try:
                val = float(text_clean)
                numbers.append((val, w[0]))
            except ValueError:
                pass
                
        dims = [float(d) for d in re.findall(r'\d+', size_str)]
        
        filtered_numbers = []
        for num, x_coord in numbers:
            is_dim = False
            for d in dims:
                if abs(num - d) < 1.0:
                    is_dim = True
                    break
            if not is_dim:
                filtered_numbers.append((num, x_coord))
                
        pct = None
        area = None
        
        for num, x_coord in filtered_numbers:
            if num > 10.0:
                area = num
            else:
                pct = num
                
        w_dim, d_dim = dims[0], dims[1]
        
        if pct is None and area is not None:
            pct = (area / (w_dim * d_dim)) * 100.0
        elif area is None and pct is not None:
            area = (pct * w_dim * d_dim) / 100.0
            
        entries[col_id] = {
            "id": col_id,
            "size": size_str,
            "pct": round(pct, 3) if pct is not None else None,
            "area": round(area, 2) if area is not None else None,
            "callout": callout
        }
        
    return entries

def run_update():
    print("Parsing all 5 ground-truth PDFs...")
    pdfs_to_parse = [
        (r"c:\Column Rebar Generator\C-400X400.pdf", "400 x 400", "C-4x4"),
        (r"c:\Column Rebar Generator\C-400X500.pdf", "400 x 500", "C-4x5"),
        (r"c:\Column Rebar Generator\C-400X600.pdf", "400 x 600", "C-4x6"),
        (r"c:\Column Rebar Generator\C-400X700.pdf", "400 x 700", "C-4x7"),
        (r"c:\Column Rebar Generator\C-400X800.pdf", "400 x 800", "C-4x8")
    ]
    
    pdf_db = {}
    for pdf, size, prefix in pdfs_to_parse:
        if not os.path.exists(pdf):
            print(f"Error: PDF not found: {pdf}")
            return False
        results = extract_pdf_data(pdf, size, prefix)
        # Filter out the excluded CAD names
        excluded_ids = {"C-4x5-6", "C-4x5-10", "C-4x5-11", "C-4x5-13"}
        results = {k: v for k, v in results.items() if k not in excluded_ids}
        pdf_db.update(results)
        print(f"  Extracted {len(results)} items from {os.path.basename(pdf)}")
        
    if len(pdf_db) != 75:
        print(f"Error: Extracted {len(pdf_db)} items instead of expected 75!")
        return False
        
    # Check for missing values
    missing_pcts = [k for k, v in pdf_db.items() if v["pct"] is None]
    if missing_pcts:
        print(f"Error: Missing percentages for: {missing_pcts}")
        return False
        
    # Construct database records in exact original clean JSON format
    new_db_records = []
    for col_id in sorted(pdf_db.keys(), key=natural_sort_key):
        item = pdf_db[col_id]
        new_db_records.append({
            "id": item["id"],
            "size": item["size"],
            "pct": item["pct"],
            "area": item["area"],
            "pct_raw": f"{item['pct']:.2f}%",
            "area_raw": f"{item['area']:.2f} sqm",
            "rebar": item["callout"]
        })
        
    # Back up original database
    orig_path = r"c:\Column Rebar Generator\clean_column_schedule_db.json"
    backup_path = r"c:\Column Rebar Generator\clean_column_schedule_db_backup.json"
    if os.path.exists(orig_path):
        import shutil
        shutil.copy2(orig_path, backup_path)
        print(f"Original database backed up to {backup_path}")
        
    # Write to clean_column_schedule_db.json
    with open(orig_path, "w", encoding="utf-8") as f:
        json.dump(new_db_records, f, indent=4)
    print(f"Successfully updated ground-truth database: '{orig_path}'")
    return True

if __name__ == "__main__":
    success = run_update()
    if not success:
        sys.exit(1)

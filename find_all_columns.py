import ezdxf
import os
import re

dxf_path = r"C:\Column Rebar Generator\Column reinforcement.dxf"
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

columns = []
for ent in msp:
    if ent.dxftype() in ('TEXT', 'MTEXT'):
        text = ent.dxf.text if ent.dxftype() == 'TEXT' else ent.text
        text = text.strip()
        
        # We look for strings matching C-<size>-<id> like C-4x4-1 or C-400X400-1 or C-4x5-12
        # Let's use a regex to match C- followed by numbers/chars, then x or X, then numbers/chars, then hyphen and number
        if re.match(r"^C-\d+[xX]\d+-\d+$", text):
            pt = ent.dxf.insert
            columns.append({
                "name": text,
                "x": pt.x,
                "y": pt.y
            })

print(f"Found {len(columns)} column labels.")

# Sort by name (using natural sorting)
def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s["name"])]

columns = sorted(columns, key=natural_sort_key)

print("\nList of all column labels found:")
for idx, col in enumerate(columns):
    # Cross section center is roughly col["x"] + 4130
    cross_x = col["x"] + 4130
    cross_y = col["y"]
    print(f"[{idx+1}] Label: {col['name']:<12} | Label Pos: ({col['x']:.2f}, {col['y']:.2f}) | Calc Cross Section Center: ({cross_x:.2f}, {cross_y:.2f})")

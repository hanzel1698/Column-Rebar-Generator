import ezdxf
import os

dxf_path = r"C:\Column Rebar Generator\Column reinforcement.dxf"
if not os.path.exists(dxf_path):
    print(f"DXF file not found at: {dxf_path}")
    exit(1)

print("Loading DXF...")
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

print("Document loaded successfully.")
print(f"Entity count in ModelSpace: {len(msp)}")

# Count different types of entities
types = {}
for ent in msp:
    obj_type = ent.dxftype()
    types[obj_type] = types.get(obj_type, 0) + 1

print("\nEntity types in ModelSpace:")
for k, v in types.items():
    print(f" - {k}: {v}")

# Find all TEXT/MTEXT entities and print some to understand where they are and their structure
text_ents = []
for ent in msp:
    if ent.dxftype() in ('TEXT', 'MTEXT'):
        text_ents.append(ent)

print(f"\nTotal TEXT/MTEXT entities: {len(text_ents)}")
print("\nFirst 30 text entities:")
for idx, ent in enumerate(text_ents[:30]):
    text = ent.dxf.text if ent.dxftype() == 'TEXT' else ent.text
    # Insert point
    pt = ent.dxf.insert
    print(f"[{idx+1}] Type: {ent.dxftype()} | Val: '{text}' | Pos: ({pt.x:.2f}, {pt.y:.2f})")

# Let's see if we have text matching column names like "C-4x4-1" or "SL No." or similar
print("\nText matching column names (C-*):")
count = 0
for ent in text_ents:
    text = ent.dxf.text if ent.dxftype() == 'TEXT' else ent.text
    if text.strip().startswith("C-") or "C-" in text:
        pt = ent.dxf.insert
        print(f" - '{text}' at ({pt.x:.2f}, {pt.y:.2f})")
        count += 1
        if count >= 30:
            break

import win32com.client
import time

print("Connecting to AutoCAD...")
acad = win32com.client.GetActiveObject("AutoCAD.Application")
doc = acad.ActiveDocument
print(f"Connected. Active Document: {doc.Name}")

model_space = doc.ModelSpace
print(f"Total entities in ModelSpace: {model_space.Count}")

text_entities = []
for i in range(model_space.Count):
    try:
        ent = model_space.Item(i)
        obj_name = ent.ObjectName
        if obj_name in ("AcDbText", "AcDbMText"):
            # It's a text object
            val = ent.TextString
            # Get insertion point
            pt = ent.InsertionPoint
            text_entities.append((obj_name, val, pt[0], pt[1]))
    except Exception as e:
        pass

print(f"Found {len(text_entities)} text/mtext entities.")
print("\nFirst 100 text entities:")
for idx, (obj_type, val, x, y) in enumerate(text_entities[:100]):
    print(f"[{idx+1}] Type: {obj_type} | Val: '{val}' | Pos: ({x:.2f}, {y:.2f})")

# Let's count how many match our expected pattern (e.g. C-4x4-1 or Main-8 #16)
c_pattern = []
main_pattern = []
for obj_type, val, x, y in text_entities:
    val_clean = val.strip()
    if val_clean.startswith("C-") or "C-" in val_clean:
        c_pattern.append((val_clean, x, y))
    if "Main-" in val_clean or "#" in val_clean:
        main_pattern.append((val_clean, x, y))

print(f"\nPotential Column IDs found (C-*): {len(c_pattern)}")
for val, x, y in c_pattern[:30]:
    print(f" - '{val}' at ({x:.2f}, {y:.2f})")

print(f"\nPotential Rebar Labels found (Main-*): {len(main_pattern)}")
for val, x, y in main_pattern[:30]:
    print(f" - '{val}' at ({x:.2f}, {y:.2f})")

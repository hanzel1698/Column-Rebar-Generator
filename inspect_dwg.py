import win32com.client
import os

try:
    acad = win32com.client.GetActiveObject("AutoCAD.Application")
    print("Connected to AutoCAD.")
except Exception as e:
    print(f"Failed to connect to AutoCAD: {e}")
    exit(1)

dwg_path = r"C:\Column Rebar Generator\Column reinforcement.dwg"
if not os.path.exists(dwg_path):
    print(f"DWG file not found at {dwg_path}")
    exit(1)

# Check if already open
doc = None
try:
    doc_count = acad.Documents.Count
    for i in range(doc_count):
        d = acad.Documents.Item(i)
        try:
            if d.FullName.lower() == dwg_path.lower() or d.Name.lower() == "column reinforcement.dwg":
                doc = d
                print(f"Drawing is already open: {d.Name}")
                break
        except Exception:
            pass
except Exception as e:
    print(f"Error checking open documents: {e}")

if not doc:
    print("Opening drawing...")
    try:
        doc = acad.Documents.Open(dwg_path)
        print("Drawing opened successfully.")
    except Exception as e:
        print(f"Failed to open drawing: {e}")
        exit(1)

# Set as active document
try:
    acad.ActiveDocument = doc
except Exception as e:
    print(f"Failed to set active document: {e}")

print(f"Document Name: {doc.Name}")

# Check layout names
try:
    print("\nLayouts:")
    for i in range(doc.Layouts.Count):
        layout = doc.Layouts.Item(i)
        print(f" - {layout.Name}")
except Exception as e:
    print(f"Error reading layouts: {e}")

# Count entities in ModelSpace
model_space = doc.ModelSpace
print(f"\nModelSpace entity count: {model_space.Count}")

# Let's count entity types in ModelSpace
types = {}
for i in range(min(1000, model_space.Count)): # look at first 1000
    try:
        ent = model_space.Item(i)
        obj_name = ent.ObjectName
        types[obj_name] = types.get(obj_name, 0) + 1
    except Exception as e:
        pass

print("\nModelSpace entity types (first 1000):")
for k, v in types.items():
    print(f" - {k}: {v}")

# Let's also look at blocks
print(f"\nBlocks count: {doc.Blocks.Count}")
for i in range(min(50, doc.Blocks.Count)):
    try:
        b = doc.Blocks.Item(i)
        print(f" - Block {i}: {b.Name}")
    except Exception:
        pass

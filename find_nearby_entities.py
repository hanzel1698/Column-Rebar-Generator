import ezdxf
import os

dxf_path = r"C:\Column Rebar Generator\Column reinforcement.dxf"
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

# Target text
target_text = "C-4x5-1"
target_x = 4298651.49
target_y = 2061876.11

# Find entities within a bounding box
# Let's search from target_x to target_x + 8000 (going right) and target_y - 3000 to target_y + 3000
x_min = target_x - 1000
x_max = target_x + 9000
y_min = target_y - 4000
y_max = target_y + 2000

print(f"Searching for entities in box: X [{x_min:.2f}, {x_max:.2f}], Y [{y_min:.2f}, {y_max:.2f}]")

nearby_entities = []
for ent in msp:
    # Estimate center coordinate based on entity type
    etype = ent.dxftype()
    cx, cy = None, None
    if etype == 'CIRCLE':
        cx, cy = ent.dxf.center.x, ent.dxf.center.y
    elif etype == 'LINE':
        cx = (ent.dxf.start.x + ent.dxf.end.x) / 2
        cy = (ent.dxf.start.y + ent.dxf.end.y) / 2
    elif etype in ('TEXT', 'MTEXT'):
        cx, cy = ent.dxf.insert.x, ent.dxf.insert.y
    elif etype == 'LWPOLYLINE':
        # Average of vertices
        verts = ent.get_points()
        if verts:
            cx = sum(v[0] for v in verts) / len(verts)
            cy = sum(v[1] for v in verts) / len(verts)
    elif etype == 'ARC':
        cx, cy = ent.dxf.center.x, ent.dxf.center.y
    elif etype == 'HATCH':
        # Use first path or a fallback
        cx, cy = target_x + 4000, target_y # default estimate
        
    if cx is not None and cy is not None:
        if x_min <= cx <= x_max and y_min <= cy <= y_max:
            nearby_entities.append((ent, cx, cy))

print(f"Found {len(nearby_entities)} entities in the bounding box.")

# Group by type and print positions
print("\nEntity List:")
for idx, (ent, cx, cy) in enumerate(nearby_entities):
    etype = ent.dxftype()
    layer = ent.dxf.layer
    info = ""
    if etype in ('TEXT', 'MTEXT'):
        text_val = ent.dxf.text if etype == 'TEXT' else ent.text
        info = f"Val: '{text_val}'"
    elif etype == 'CIRCLE':
        info = f"Radius: {ent.dxf.radius:.2f}"
    elif etype == 'LINE':
        info = f"Start: ({ent.dxf.start.x:.2f}, {ent.dxf.start.y:.2f}) End: ({ent.dxf.end.x:.2f}, {ent.dxf.end.y:.2f})"
    elif etype == 'LWPOLYLINE':
        info = f"Vertices count: {len(ent.get_points())}"
        
    print(f"[{idx+1}] Type: {etype} | Layer: {layer} | Pos: ({cx:.2f}, {cy:.2f}) | {info}")

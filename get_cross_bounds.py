import ezdxf
import os

dxf_path = r"C:\Column Rebar Generator\Column reinforcement.dxf"
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

# Target cross section center for C-4x5-1
cross_x = 4298651.49 + 4130
cross_y = 2061876.11

# Let's search in a small radius around this center (e.g., 2500 units)
search_radius = 2500

xs = []
ys = []

for ent in msp:
    etype = ent.dxftype()
    if etype in ('TEXT', 'MTEXT') and ("C-4" in ent.dxf.text if etype == 'TEXT' else "C-4" in ent.text):
        continue # skip the column name label itself
        
    cx, cy = None, None
    if etype == 'CIRCLE':
        cx, cy = ent.dxf.center.x, ent.dxf.center.y
        r = ent.dxf.radius
        # Include circle extents
        if abs(cx - cross_x) < search_radius and abs(cy - cross_y) < search_radius:
            xs.extend([cx - r, cx + r])
            ys.extend([cy - r, cy + r])
    elif etype == 'LINE':
        sx, sy = ent.dxf.start.x, ent.dxf.start.y
        ex, ey = ent.dxf.end.x, ent.dxf.end.y
        cx = (sx + ex) / 2
        cy = (sy + ey) / 2
        if abs(cx - cross_x) < search_radius and abs(cy - cross_y) < search_radius:
            xs.extend([sx, ex])
            ys.extend([sy, ey])
    elif etype == 'LWPOLYLINE':
        verts = ent.get_points()
        if verts:
            cx = sum(v[0] for v in verts) / len(verts)
            cy = sum(v[1] for v in verts) / len(verts)
            if abs(cx - cross_x) < search_radius and abs(cy - cross_y) < search_radius:
                xs.extend(v[0] for v in verts)
                ys.extend(v[1] for v in verts)
    elif etype == 'ARC':
        cx, cy = ent.dxf.center.x, ent.dxf.center.y
        r = ent.dxf.radius
        if abs(cx - cross_x) < search_radius and abs(cy - cross_y) < search_radius:
            xs.extend([cx - r, cx + r])
            ys.extend([cy - r, cy + r])
    elif etype == 'MTEXT':
        cx, cy = ent.dxf.insert.x, ent.dxf.insert.y
        if abs(cx - cross_x) < search_radius and abs(cy - cross_y) < search_radius:
            xs.append(cx)
            ys.append(cy)

if xs and ys:
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width = max_x - min_x
    height = max_y - min_y
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    print(f"For C-4x5-1 cross section:")
    print(f" - X range: [{min_x:.2f}, {max_x:.2f}] (width: {width:.2f})")
    print(f" - Y range: [{min_y:.2f}, {max_y:.2f}] (height: {height:.2f})")
    print(f" - Calculated Center: ({center_x:.2f}, {center_y:.2f})")
    print(f" - Offset from Label: dx = {center_x - 4298651.49:.2f}, dy = {center_y - 2061876.11:.2f}")
else:
    print("No entities found around the cross section center.")

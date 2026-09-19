import ezdxf
import os
import re

dxf_path = r"C:\Column Rebar Generator\Column reinforcement.dxf"
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

# Find some test labels
test_names = ["C-4x4-1", "C-4x5-2", "C-4x5-12", "C-4x6-1", "C-4x7-1", "C-4x8-1", "C-4x8-16"]
labels = {}

for ent in msp:
    if ent.dxftype() in ('TEXT', 'MTEXT'):
        text = ent.dxf.text if ent.dxftype() == 'TEXT' else ent.text
        text = text.strip()
        if text in test_names:
            pt = ent.dxf.insert
            labels[text] = (pt.x, pt.y)

search_radius = 2500

for name in test_names:
    if name not in labels:
        print(f"Label {name} not found.")
        continue
        
    lx, ly = labels[name]
    # Expected center
    cross_x = lx + 4470.03
    cross_y = ly + 192.32
    
    xs = []
    ys = []
    
    for ent in msp:
        etype = ent.dxftype()
        if etype in ('TEXT', 'MTEXT') and (name in (ent.dxf.text if etype == 'TEXT' else ent.text)):
            continue
            
        cx, cy = None, None
        if etype == 'CIRCLE':
            cx, cy = ent.dxf.center.x, ent.dxf.center.y
            r = ent.dxf.radius
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
        w = max_x - min_x
        h = max_y - min_y
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2
        dx = cx - lx
        dy = cy - ly
        print(f"Label: {name:<10} | Pos: ({lx:.2f}, {ly:.2f}) | Bounds: W={w:.2f}, H={h:.2f} | Offset: dx={dx:.2f}, dy={dy:.2f}")
    else:
        print(f"Label: {name:<10} | No entities found.")

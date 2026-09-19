import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import matplotlib.pyplot as plt
import os

dxf_path = r"C:\Column Rebar Generator\Column reinforcement.dxf"
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

# Target label for testing: C-4x5-1
label_name = "C-4x5-1"
lx, ly = 4298651.49, 2061876.11 # coordinates of C-4x5-1 text insert

# Bounding box search area (centered around cross section region)
# We know the cross section is to the right
cross_x = lx + 4400
cross_y = ly

search_radius = 2500
xs = []
ys = []

# Gather entities within the radius to compute the bounding box
for ent in msp:
    etype = ent.dxftype()
    # Skip the column label itself
    if etype in ('TEXT', 'MTEXT') and (label_name in (ent.dxf.text if etype == 'TEXT' else ent.text)):
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

if not xs or not ys:
    print("Error: No cross section entities found.")
    exit(1)

min_x, max_x = min(xs), max(xs)
min_y, max_y = min(ys), max(ys)
width = max_x - min_x
height = max_y - min_y

print(f"Computed Bounds: X [{min_x:.2f}, {max_x:.2f}], Y [{min_y:.2f}, {max_y:.2f}] (W={width:.2f}, H={height:.2f})")

# Let's set up the rendering context and Matplotlib figure
fig, ax = plt.subplots(figsize=(6, 8), dpi=150)
ax.set_aspect('equal')
ax.set_axis_off()

# Set white background
fig.patch.set_facecolor('white')
ax.set_facecolor('white')

# Set rendering context
ctx = RenderContext(doc)
# Force black-and-white (black lines on white background)
# Matplotlib backend automatically handles color overrides if we customize
# Or we can let it render with default colors and see.
ctx.set_current_layout(msp)

out = MatplotlibBackend(ax)
Frontend(ctx, out).draw_layout(msp, finalize=False)

# Crop to the computed bounds (with a small padding, e.g. 5% of size)
padding_x = width * 0.1
padding_y = height * 0.1
ax.set_xlim(min_x - padding_x, max_x + padding_x)
ax.set_ylim(min_y - padding_y, max_y + padding_y)

# Save figure
output_path = os.path.abspath(r"C:\Column Rebar Generator\C-4x5-1.png")
plt.savefig(output_path, bbox_inches='tight', pad_inches=0.1, facecolor='white')
plt.close(fig)

print(f"Saved rendered image to: {output_path}")

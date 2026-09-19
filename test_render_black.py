import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.config import Configuration, ColorPolicy, TextPolicy
import matplotlib.pyplot as plt
import os

dxf_path = r"C:\Column Rebar Generator\Column reinforcement.dxf"
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

# Target label for testing: C-4x5-1
label_name = "C-4x5-1"
lx, ly = 4298651.49, 2061876.11

cross_x = lx + 4400
cross_y = ly

search_radius = 2500
xs = []
ys = []

for ent in msp:
    etype = ent.dxftype()
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

min_x, max_x = min(xs), max(xs)
min_y, max_y = min(ys), max(ys)
width = max_x - min_x
height = max_y - min_y

print(f"Computed Bounds: X [{min_x:.2f}, {max_x:.2f}], Y [{min_y:.2f}, {max_y:.2f}] (W={width:.2f}, H={height:.2f})")

fig, ax = plt.subplots(figsize=(6, 8), dpi=150)
ax.set_aspect('equal')
ax.set_axis_off()

fig.patch.set_facecolor('white')
ax.set_facecolor('white')

ctx = RenderContext(doc)
ctx.set_current_layout(msp)

# Set up custom configuration for monochrome/black line rendering
config = Configuration(
    color_policy=ColorPolicy.BLACK,    # Force all lines to black
    text_policy=TextPolicy.FILLING,     # Fill text paths
    show_defpoints=False
)

out = MatplotlibBackend(ax)
# Pass configuration to Frontend
Frontend(ctx, out, config=config).draw_layout(msp, finalize=False)

# Crop
padding_x = width * 0.1
padding_y = height * 0.1
ax.set_xlim(min_x - padding_x, max_x + padding_x)
ax.set_ylim(min_y - padding_y, max_y + padding_y)

output_path = os.path.abspath(r"C:\Column Rebar Generator\C-4x5-1_black.png")
plt.savefig(output_path, bbox_inches='tight', pad_inches=0.1, facecolor='white')
plt.close(fig)

print(f"Saved rendered image to: {output_path}")

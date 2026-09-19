import ezdxf
from ezdxf import bbox
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.config import Configuration, ColorPolicy, TextPolicy
import matplotlib.pyplot as plt
import os

dxf_path = r"C:\Column Rebar Generator\Column reinforcement.dxf"
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

# Delete very long lines (table borders/grid lines) from the modelspace
deleted_count = 0
for ent in list(msp):
    if ent.dxftype() == 'LINE':
        start = ent.dxf.start
        end = ent.dxf.end
        length = ((start.x - end.x)**2 + (start.y - end.y)**2)**0.5
        if length > 2200: # Heuristic length for table lines
            msp.delete_entity(ent)
            deleted_count += 1

print(f"Deleted {deleted_count} table grid lines.")

# Target label: C-4x5-1
label_name = "C-4x5-1"
lx, ly = 4298651.49, 2061876.11

cross_x = lx + 4400
cross_y = ly

search_radius = 2500
x_min_search = cross_x - 2250
x_max_search = cross_x + 2250
y_min_search = cross_y - 2500
y_max_search = cross_y + 2500

collected_entities = []

for ent in msp:
    # Skip the column label itself
    if ent.dxftype() in ('TEXT', 'MTEXT') and (label_name in (ent.dxf.text if ent.dxftype() == 'TEXT' else ent.text)):
        continue
        
    try:
        box = bbox.extents([ent])
        if box.extmin is None or box.extmax is None:
            continue
            
        cx = (box.extmin.x + box.extmax.x) / 2
        cy = (box.extmin.y + box.extmax.y) / 2
        
        # Check if the entity is in our search region
        if x_min_search <= cx <= x_max_search and y_min_search <= cy <= y_max_search:
            collected_entities.append(ent)
    except Exception:
        pass

print(f"Collected {len(collected_entities)} entities for cross section.")

# Compute the unified bounding box of all collected entities
overall_box = bbox.extents(collected_entities)
min_x = overall_box.extmin.x
max_x = overall_box.extmax.x
min_y = overall_box.extmin.y
max_y = overall_box.extmax.y

width = max_x - min_x
height = max_y - min_y

print(f"Unified Bounds: X [{min_x:.2f}, {max_x:.2f}], Y [{min_y:.2f}, {max_y:.2f}] (W={width:.2f}, H={height:.2f})")

# Render
fig, ax = plt.subplots(figsize=(6, 8), dpi=150)
ax.set_aspect('equal')
ax.set_axis_off()

fig.patch.set_facecolor('white')
ax.set_facecolor('white')

ctx = RenderContext(doc)
ctx.set_current_layout(msp)

config = Configuration(
    color_policy=ColorPolicy.BLACK,
    text_policy=TextPolicy.FILLING,
    show_defpoints=False
)

out = MatplotlibBackend(ax)
Frontend(ctx, out, config=config).draw_layout(msp, finalize=False)

# Add padding
padding_x = width * 0.1
padding_y = height * 0.1
ax.set_xlim(min_x - padding_x, max_x + padding_x)
ax.set_ylim(min_y - padding_y, max_y + padding_y)

output_path = os.path.abspath(r"C:\Column Rebar Generator\C-4x5-1_no_grid.png")
plt.savefig(output_path, bbox_inches='tight', pad_inches=0.1, facecolor='white')
plt.close(fig)

print(f"Saved clean rendered image to: {output_path}")

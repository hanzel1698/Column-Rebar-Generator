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
    if ent.dxftype() in ('TEXT', 'MTEXT') and (label_name in (ent.dxf.text if ent.dxftype() == 'TEXT' else ent.text)):
        continue
        
    try:
        box = bbox.extents([ent])
        if box.extmin is None or box.extmax is None:
            continue
            
        cx = (box.extmin.x + box.extmax.x) / 2
        cy = (box.extmin.y + box.extmax.y) / 2
        
        # Check if center is in search window
        if x_min_search <= cx <= x_max_search and y_min_search <= cy <= y_max_search:
            # Skip very long table grid lines
            if ent.dxftype() == 'LINE':
                length = ((ent.dxf.start.x - ent.dxf.end.x)**2 + (ent.dxf.start.y - ent.dxf.end.y)**2)**0.5
                if length > 2500:
                    continue
            collected_entities.append(ent)
    except Exception:
        pass

print(f"Collected {len(collected_entities)} entities.")

# Create a new document in memory
new_doc = ezdxf.new()
new_msp = new_doc.modelspace()

# Copy text styles if any are used, or let ezdxf default
# We can also add font style mapping if needed. For Times New Roman, it's standard.
for ent in collected_entities:
    try:
        new_msp.add_foreign_entity(ent)
    except Exception as e:
        print(f"Failed to copy entity {ent.dxftype()}: {e}")

# Compute unified bounding box
overall_box = bbox.extents(new_msp)
min_x = overall_box.extmin.x
max_x = overall_box.extmax.x
min_y = overall_box.extmin.y
max_y = overall_box.extmax.y

width = max_x - min_x
height = max_y - min_y

print(f"New Doc Bounds: X [{min_x:.2f}, {max_x:.2f}], Y [{min_y:.2f}, {max_y:.2f}] (W={width:.2f}, H={height:.2f})")

# Render only the new document
fig, ax = plt.subplots(figsize=(6, 8), dpi=150)
ax.set_aspect('equal')
ax.set_axis_off()
fig.patch.set_facecolor('white')
ax.set_facecolor('white')

ctx = RenderContext(new_doc)
ctx.set_current_layout(new_msp)

config = Configuration(
    color_policy=ColorPolicy.BLACK,
    text_policy=TextPolicy.FILLING,
    show_defpoints=False
)

out = MatplotlibBackend(ax)
Frontend(ctx, out, config=config).draw_layout(new_msp, finalize=False)

# Add padding
padding_x = width * 0.08
padding_y = height * 0.08
ax.set_xlim(min_x - padding_x, max_x + padding_x)
ax.set_ylim(min_y - padding_y, max_y + padding_y)

output_path = os.path.abspath(r"C:\Column Rebar Generator\C-4x5-1_clean.png")
plt.savefig(output_path, bbox_inches='tight', pad_inches=0.05, facecolor='white')
plt.close(fig)

print(f"Saved clean rendered image to: {output_path}")

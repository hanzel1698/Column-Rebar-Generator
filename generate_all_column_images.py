import ezdxf
from ezdxf import bbox
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.config import Configuration, ColorPolicy, TextPolicy
import matplotlib.pyplot as plt
import os
import re
import time

def main():
    start_time = time.time()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    dxf_path = os.path.join(base_dir, "Column reinforcement.dxf")
    output_dir = os.path.join(base_dir, "Column_Sections")
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")
        
    if not os.path.exists(dxf_path):
        print(f"Error: DXF file not found at {dxf_path}")
        return
        
    print("Loading DXF file...")
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    print("DXF loaded successfully.")
    
    # 1. Identify all column labels
    print("Scanning for column labels...")
    labels = []
    for ent in msp:
        if ent.dxftype() in ('TEXT', 'MTEXT'):
            text = ent.dxf.text if ent.dxftype() == 'TEXT' else ent.text
            text = text.strip()
            # Match pattern like C-4x4-1, C-4x5-12, etc.
            if re.match(r"^C-\d+[xX]\d+-\d+$", text):
                pt = ent.dxf.insert
                labels.append({
                    "name": text,
                    "x": pt.x,
                    "y": pt.y
                })
                
    # Sort labels naturally
    def natural_sort_key(item):
        return [int(s) if s.isdigit() else s.lower() for s in re.split(r'(\d+)', item["name"])]
        
    labels = sorted(labels, key=natural_sort_key)
    print(f"Found {len(labels)} column labels to process.")
    
    # Setup rendering context
    ctx = RenderContext(doc)
    ctx.set_current_layout(msp)
    
    config = Configuration(
        color_policy=ColorPolicy.BLACK,   # Black lines
        text_policy=TextPolicy.FILLING,    # Filled text
        show_defpoints=False
    )
    
    # 2. Process each column
    success_count = 0
    search_radius = 2500
    
    for idx, label in enumerate(labels):
        col_name = label["name"]
        lx, ly = label["x"], label["y"]
        
        # Center of cross-section search area
        cross_x = lx + 4400
        cross_y = ly
        
        x_min_search = cross_x - 2250
        x_max_search = cross_x + 2250
        y_min_search = cross_y - 2500
        y_max_search = cross_y + 2500
        
        # Collect nearby entities
        collected = []
        for ent in msp:
            # Skip the label itself
            if ent.dxftype() in ('TEXT', 'MTEXT') and (col_name in (ent.dxf.text if ent.dxftype() == 'TEXT' else ent.text)):
                continue
                
            try:
                box = bbox.extents([ent])
                if box.extmin is None or box.extmax is None:
                    continue
                    
                cx = (box.extmin.x + box.extmax.x) / 2
                cy = (box.extmin.y + box.extmax.y) / 2
                
                if x_min_search <= cx <= x_max_search and y_min_search <= cy <= y_max_search:
                    # Filter out long table grid lines
                    if ent.dxftype() == 'LINE':
                        length = ((ent.dxf.start.x - ent.dxf.end.x)**2 + (ent.dxf.start.y - ent.dxf.end.y)**2)**0.5
                        if length > 2200:
                            continue
                    collected.append(ent)
            except Exception:
                pass
                
        if not collected:
            print(f"[{idx+1}/{len(labels)}] Column {col_name}: No cross section entities found. Skipping.")
            continue
            
        try:
            # Compute unified bounding box
            overall_box = bbox.extents(collected)
            min_x = overall_box.extmin.x
            max_x = overall_box.extmax.x
            min_y = overall_box.extmin.y
            max_y = overall_box.extmax.y
            
            w = max_x - min_x
            h = max_y - min_y
            
            # Setup matplotlib figure
            fig, ax = plt.subplots(figsize=(6, 8), dpi=120)
            ax.set_aspect('equal')
            ax.set_axis_off()
            fig.patch.set_facecolor('white')
            ax.set_facecolor('white')
            
            # Render selected entities
            out = MatplotlibBackend(ax)
            Frontend(ctx, out, config=config).draw_entities(collected)
            
            # Crop with 10% padding
            padding_x = w * 0.1
            padding_y = h * 0.1
            ax.set_xlim(min_x - padding_x, max_x + padding_x)
            ax.set_ylim(min_y - padding_y, max_y + padding_y)
            
            # Save file
            out_filename = f"{col_name}.png"
            out_filepath = os.path.join(output_dir, out_filename)
            plt.savefig(out_filepath, bbox_inches='tight', pad_inches=0.1, facecolor='white')
            plt.close(fig)
            
            success_count += 1
            print(f"[{idx+1}/{len(labels)}] Saved {out_filename}")
        except Exception as e:
            print(f"[{idx+1}/{len(labels)}] Column {col_name}: Failed to render - {e}")
            if 'fig' in locals():
                plt.close(fig)
                
    elapsed = time.time() - start_time
    print(f"\nFinished! Rendered {success_count}/{len(labels)} column images in {elapsed:.1f} seconds.")
    print(f"Output directory: {output_dir}")

if __name__ == '__main__':
    main()

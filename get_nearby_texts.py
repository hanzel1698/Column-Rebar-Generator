import ezdxf
import os

dxf_path = r"C:\Column Rebar Generator\Column reinforcement.dxf"
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

# Target center for C-4x5-1 cross section
cross_x = 4298651.49 + 4130
cross_y = 2061876.11

print(f"Searching for text entities around X = {cross_x:.2f}, Y = {cross_y:.2f} within radius 3000...")

for ent in msp:
    etype = ent.dxftype()
    if etype in ('TEXT', 'MTEXT'):
        text = ent.dxf.text if etype == 'TEXT' else ent.text
        pt = ent.dxf.insert
        dist = ((pt.x - cross_x)**2 + (pt.y - cross_y)**2)**0.5
        if dist < 3000:
            print(f"Type: {etype} | Text: '{text}' | Pos: ({pt.x:.2f}, {pt.y:.2f}) | Dist: {dist:.2f}")
            
# Let's also check all layers in the document to see if some are frozen or off
print("\nLayers in the document:")
for layer in doc.layers:
    print(f" - Layer: {layer.dxf.name} | IsOff: {layer.is_off()} | IsFrozen: {layer.is_frozen()}")

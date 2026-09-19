import sys
import os

def test_with_flags(flags_val, name):
    print(f"\n--- Testing with coinit_flags = {flags_val} ({name}) ---")
    # Clean up sys.modules to force reloading of win32com and comtypes
    for mod in list(sys.modules.keys()):
        if "win32com" in mod or "comtypes" in mod:
            del sys.modules[mod]
            
    sys.coinit_flags = flags_val
    
    try:
        import win32com.client
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
        print("win32com GetActiveObject success!")
        print("Active doc:", acad.ActiveDocument.Name)
        return True
    except Exception as e:
        print("win32com failed:", e)
        
    try:
        import comtypes.client
        acad = comtypes.client.GetActiveObject("AutoCAD.Application")
        print("comtypes GetActiveObject success!")
        print("Active doc:", acad.ActiveDocument.Name)
        return True
    except Exception as e:
        print("comtypes failed:", e)
        
    return False

test_with_flags(2, "MTA")
test_with_flags(0, "STA")

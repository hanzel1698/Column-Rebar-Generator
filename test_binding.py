import win32com.client
import sys

print("Checking win32com.client.gencache...")
try:
    acad = win32com.client.gencache.EnsureDispatch("AutoCAD.Application")
    print("EnsureDispatch success. Documents count:", acad.Documents.Count)
except Exception as e:
    print("EnsureDispatch failed:", e)

print("\nChecking comtypes.client...")
try:
    import comtypes.client
    acad_ct = comtypes.client.GetActiveObject("AutoCAD.Application")
    print("comtypes success. Documents count:", acad_ct.Documents.Count)
except Exception as e:
    print("comtypes failed:", e)

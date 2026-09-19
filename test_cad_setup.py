import sys

try:
    import ezdxf
    print("ezdxf: OK")
except ImportError:
    print("ezdxf: NOT INSTALLED")

try:
    import matplotlib
    print("matplotlib: OK")
except ImportError:
    print("matplotlib: NOT INSTALLED")

try:
    import PIL
    print("pillow: OK")
except ImportError:
    print("pillow: NOT INSTALLED")

try:
    import win32com.client
    print("win32com.client: OK")
    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
        print("AutoCAD: RUNNING")
    except Exception as e:
        print(f"AutoCAD GetActiveObject failed: {e}")
        try:
            acad = win32com.client.Dispatch("AutoCAD.Application")
            print("AutoCAD Dispatch: SUCCESS")
        except Exception as e2:
            print(f"AutoCAD Dispatch failed: {e2}")
except ImportError:
    print("win32com: NOT INSTALLED")

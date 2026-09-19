import os
import subprocess
import time
import win32com.client

print("Step 1: Killing running acad.exe instances...")
subprocess.run("taskkill /f /im acad.exe", shell=True)

# Wait a moment for process to terminate
time.sleep(2)

print("Step 2: Checking and deleting CAD lock files...")
lock1 = r"C:\Column Rebar Generator\Column reinforcement.dwl"
lock2 = r"C:\Column Rebar Generator\Column reinforcement.dwl2"

for lock_file in [lock1, lock2]:
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
            print(f"Removed lock file: {lock_file}")
        except Exception as e:
            print(f"Could not remove lock file {lock_file}: {e}")

print("Step 3: Launching a new instance of AutoCAD via COM...")
try:
    # Set COM MTA model
    import sys
    sys.coinit_flags = 2 # MTA
    
    acad = win32com.client.Dispatch("AutoCAD.Application")
    # Wait for AutoCAD to load
    print("Waiting for AutoCAD to initialize...")
    time.sleep(10)
    
    # Make visible
    acad.Visible = True
    print("AutoCAD Name:", acad.Name)
    print("AutoCAD Version:", acad.Version)
    
    dwg_path = r"C:\Column Rebar Generator\Column reinforcement.dwg"
    print(f"Opening drawing: {dwg_path}")
    doc = acad.Documents.Open(dwg_path)
    print("Opened successfully!")
    print("Active Document:", acad.ActiveDocument.Name)
    
    # Try reading layouts
    print("Layouts in drawing:")
    for i in range(doc.Layouts.Count):
        print(f" - {doc.Layouts.Item(i).Name}")
        
    print("COM Communication verified successfully!")
except Exception as e:
    print(f"Failed to launch or communicate with AutoCAD: {e}")

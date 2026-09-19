import win32com.client
import time
import os

print("Connecting to AutoCAD...")
acad = win32com.client.GetActiveObject("AutoCAD.Application")
print("Connected.")

dwg_path = r"C:\Column Rebar Generator\Column reinforcement.dwg"
doc = None

# Check if drawing already open
try:
    for i in range(acad.Documents.Count):
        d = acad.Documents.Item(i)
        if d.FullName.lower() == dwg_path.lower() or d.Name.lower() == "column reinforcement.dwg":
            doc = d
            print("Drawing is already open.")
            break
except Exception as e:
    print("Could not iterate documents directly, trying open...")

if not doc:
    print("Opening drawing...")
    try:
        doc = acad.Documents.Open(dwg_path)
        print("Open command sent. Waiting 5 seconds for drawing to load...")
        time.sleep(5)
    except Exception as e:
        print(f"Failed to open: {e}")
        exit(1)

# Retry loop for accessing doc properties
print("Attempting to access document properties...")
success = False
for attempt in range(10):
    try:
        print(f"Attempt {attempt+1}...")
        doc_name = doc.Name
        layouts_count = doc.Layouts.Count
        print(f"Success! Document Name: {doc_name}")
        print(f"Layouts Count: {layouts_count}")
        success = True
        break
    except Exception as e:
        print(f"Rejected: {e}")
        time.sleep(1.0)

if success:
    try:
        print("\nListing layouts:")
        for i in range(doc.Layouts.Count):
            print(f" - Layout {i}: {doc.Layouts.Item(i).Name}")
    except Exception as e:
        print("Failed to list layouts:", e)
else:
    print("Failed to access document properties after multiple attempts.")

import win32com.client
import sys
import time

try:
    acad = win32com.client.GetActiveObject("AutoCAD.Application")
    print("AutoCAD Application Object Retrieved.")
    print("Name:", acad.Name)
    print("Version:", acad.Version)
    print("Visible:", acad.Visible)
    print("Caption:", acad.Caption)
except Exception as e:
    print("Failed to get basic properties:", e)

try:
    # Try accessing Documents
    print("Attempting to get Documents collection...")
    docs = acad.Documents
    print("Documents collection retrieved.")
    print("Documents Count:", docs.Count)
except Exception as e:
    print("Failed to get documents:", e)

import win32com.client
import time

print("Connecting to AutoCAD...")
acad = win32com.client.GetActiveObject("AutoCAD.Application")
print("Connected.")

# Let's retry getting acad.Documents
docs = None
for i in range(20):
    try:
        print(f"Attempt {i+1} to get Documents...")
        docs = acad.Documents
        print("Success! Documents Count:", docs.Count)
        break
    except Exception as e:
        print("Rejected, sleeping...")
        time.sleep(0.5)

if docs:
    for i in range(docs.Count):
        try:
            print(f"Document {i}: {docs.Item(i).Name}")
        except Exception as e:
            print("Failed to get document name:", e)
else:
    print("Could not retrieve Documents collection.")

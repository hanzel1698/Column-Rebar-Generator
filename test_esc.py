import win32gui
import win32api
import win32con
import win32com.client
import time

def find_acad_hwnd():
    hwnd_list = []
    def callback(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            classname = win32gui.GetClassName(hwnd)
            if "autocad" in title.lower() or "acad" in classname.lower():
                hwnd_list.append(hwnd)
        return True
    win32gui.EnumWindows(callback, None)
    return hwnd_list[0] if hwnd_list else None

acad_hwnd = find_acad_hwnd()
if not acad_hwnd:
    print("AutoCAD window not found.")
    exit(1)

print(f"Found AutoCAD HWND: {acad_hwnd}")

# Send Escape key (VK_ESCAPE = 0x1B) three times to clear any pending commands
print("Sending ESC keys to AutoCAD...")
for _ in range(3):
    # PostMessage or SendMessage
    # WM_KEYDOWN, WM_KEYUP
    win32api.PostMessage(acad_hwnd, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
    time.sleep(0.1)
    win32api.PostMessage(acad_hwnd, win32con.WM_KEYUP, win32con.VK_ESCAPE, 0xC0000001)
    time.sleep(0.2)

print("Attempting to connect via COM after ESC keys...")
try:
    acad = win32com.client.GetActiveObject("AutoCAD.Application")
    docs = acad.Documents
    print("Success! Documents Count:", docs.Count)
    print("Active Document:", acad.ActiveDocument.Name)
except Exception as e:
    print("COM Call failed:", e)

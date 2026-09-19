import win32gui
import win32process

def get_window_info():
    def callback(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            classname = win32gui.GetClassName(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            
            # Print if title or classname relates to AutoCAD
            title_lower = title.lower()
            class_lower = classname.lower()
            if "acad" in title_lower or "autocad" in title_lower or "acad" in class_lower or "autocad" in class_lower:
                print(f"HWND: {hwnd} | PID: {pid} | Class: {classname} | Title: '{title}'")
                
                # Check for child windows (like dialogs)
                def child_callback(child_hwnd, child_extra):
                    child_title = win32gui.GetWindowText(child_hwnd)
                    child_class = win32gui.GetClassName(child_hwnd)
                    if win32gui.IsWindowVisible(child_hwnd) and (child_title or child_class):
                        print(f"   --> Child HWND: {child_hwnd} | Class: {child_class} | Title: '{child_title}'")
                    return True
                
                try:
                    win32gui.EnumChildWindows(hwnd, child_callback, None)
                except Exception as e:
                    pass
        return True

    print("Scanning visible windows for AutoCAD...")
    win32gui.EnumWindows(callback, None)

get_window_info()

import sys
import os
import traceback
import re

def run_diagnostics():
    report = []
    report.append("====================================================")
    report.append("         ETABS CONNECTION DIAGNOSTIC REPORT         ")
    report.append("====================================================\n")
    
    # 1. System Information
    report.append("--- SYSTEM INFO ---")
    report.append(f"Python Version: {sys.version}")
    report.append(f"Executable: {sys.executable}")
    report.append(f"Working Directory: {os.getcwd()}")
    try:
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        report.append(f"Running as Administrator: {is_admin}")
    except Exception as e:
        report.append(f"Failed to check Admin status: {e}")
    report.append("")

    # 2. Check for running ETABS processes
    report.append("--- PROCESS CHECK ---")
    etabs_running = False
    try:
        import subprocess
        # Get list of running processes with "etabs" in the name
        cmd = 'tasklist /FI "IMAGENAME eq ETABS.exe" /FO CSV /NH'
        output = subprocess.check_output(cmd, shell=True, text=True)
        if "ETABS.exe" in output:
            report.append("Found ETABS.exe running in processes:")
            report.append(output.strip())
            etabs_running = True
        else:
            report.append("WARNING: ETABS.exe was NOT found in the running processes list.")
            report.append("Make sure ETABS is open before running the connection.")
    except Exception as e:
        report.append(f"Failed to query tasklist: {e}")
    report.append("")

    # 3. pywin32 / pythoncom check
    report.append("--- PYWIN32 & ROT SCAN ---")
    try:
        import pythoncom
        import win32com.client
        report.append("pythoncom and win32com imported successfully.")
        
        # Scan Running Object Table (ROT)
        try:
            rot = pythoncom.GetRunningObjectTable()
            bind_ctx = pythoncom.CreateBindCtx(0)
            enum_monikers = rot.EnumRunning()
            
            rot_instances = []
            for moniker in enum_monikers:
                try:
                    name = moniker.GetDisplayName(bind_ctx, None)
                    if "etabs" in name.lower() or "csi" in name.lower():
                        rot_instances.append(name)
                except Exception:
                    continue
            
            if rot_instances:
                report.append("Found ETABS/CSI related objects in Running Object Table (ROT):")
                for inst in rot_instances:
                    report.append(f"  - {inst}")
            else:
                report.append("No ETABS/CSI objects found in ROT.")
                report.append("This is common if ETABS and this script have different privilege/integrity levels (e.g. one is Admin, one is normal user).")
        except Exception as e:
            report.append(f"Error scanning ROT: {e}\n{traceback.format_exc()}")
            
    except ImportError as e:
        report.append(f"ERROR: pywin32/pythoncom not installed or failed to import: {e}")
    report.append("")

    # 4. comtypes check
    report.append("--- COMTYPES CHECK ---")
    try:
        import comtypes
        import comtypes.client
        report.append(f"comtypes version {comtypes.__version__} imported successfully.")
        
        # Check comtypes cache path
        try:
            from comtypes.client import _code_cache
            report.append(f"comtypes cache folder: {_code_cache.directory}")
        except Exception as e:
            report.append(f"Could not determine comtypes cache folder: {e}")
            
    except ImportError as e:
        report.append(f"ERROR: comtypes not installed or failed to import: {e}")
    report.append("")

    # 5. Connection Method A: CSI.ETABS.API.ETABSObject (Direct GetActiveObject)
    report.append("--- METHOD A: GetActiveObject (CSI.ETABS.API.ETABSObject) ---")
    try:
        import comtypes.client
        report.append("Attempting comtypes.client.GetActiveObject('CSI.ETABS.API.ETABSObject')...")
        etabs_object = comtypes.client.GetActiveObject("CSI.ETABS.API.ETABSObject")
        report.append("SUCCESS: Connected to ETABSObject!")
        try:
            sap_model = etabs_object.SapModel
            filename = sap_model.GetModelFilename(False)
            report.append(f"SUCCESS: Retrieved SapModel. Active file: {filename}")
        except Exception as e:
            report.append(f"ERROR retrieving SapModel: {e}\n{traceback.format_exc()}")
    except Exception as e:
        report.append(f"FAILED Method A: {e}")
        report.append(traceback.format_exc())
    report.append("")

    # 6. Connection Method B: win32com GetActiveObject
    report.append("--- METHOD B: win32com GetActiveObject ---")
    try:
        import win32com.client
        report.append("Attempting win32com.client.GetActiveObject('CSI.ETABS.API.ETABSObject')...")
        etabs_object = win32com.client.GetActiveObject("CSI.ETABS.API.ETABSObject")
        report.append("SUCCESS: Connected via win32com GetActiveObject!")
        try:
            sap_model = etabs_object.SapModel
            filename = sap_model.GetModelFilename(False)
            report.append(f"SUCCESS: Retrieved SapModel. Active file: {filename}")
        except Exception as e:
            report.append(f"ERROR retrieving SapModel: {e}\n{traceback.format_exc()}")
    except Exception as e:
        report.append(f"FAILED Method B: {e}")
        report.append(traceback.format_exc())
    report.append("")

    # 7. Connection Method C: ETABSv1.Helper (CSI API standard method)
    report.append("--- METHOD C: ETABSv1.Helper Helper Class ---")
    try:
        import comtypes.client
        report.append("Attempting to create ETABSv1.Helper...")
        helper = comtypes.client.CreateObject('ETABSv1.Helper')
        report.append("SUCCESS: Created ETABSv1.Helper object.")
        try:
            helper = helper.QueryInterface(comtypes.gen.ETABSv1.cHelper)
            report.append("SUCCESS: Queried cHelper interface.")
        except Exception as e:
            report.append(f"cHelper QueryInterface failed: {e}. Attempting dynamically...")
            
        try:
            # Try to get active object through helper
            report.append("Attempting helper.GetObject('CSI.ETABS.API.ETABSObject')...")
            etabs_object = helper.GetObject("CSI.ETABS.API.ETABSObject")
            if etabs_object:
                report.append("SUCCESS: helper.GetObject returned an object.")
                sap_model = etabs_object.SapModel
                filename = sap_model.GetModelFilename(False)
                report.append(f"SUCCESS: Retrieved SapModel. Active file: {filename}")
            else:
                report.append("FAILED: helper.GetObject returned None.")
        except Exception as e:
            report.append(f"FAILED helper.GetObject: {e}\n{traceback.format_exc()}")
    except Exception as e:
        report.append(f"FAILED Method C: {e}")
        report.append(traceback.format_exc())
    report.append("")

    # 8. Registry Check for CSI/ETABS COM keys
    report.append("--- REGISTRY COM REGISTRATION CHECK ---")
    try:
        import winreg
        keys_to_check = [
            r"CLSID\{F19760EE-5CE7-4180-8772-74E9A4B866EE}", # ETABSv1.Helper
            r"CSI.ETABS.API.ETABSObject",
            r"ETABSv1.Helper"
        ]
        
        for key_path in keys_to_check:
            try:
                key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key_path)
                report.append(f"Registry Key FOUND: HKEY_CLASSES_ROOT\\{key_path}")
                winreg.CloseKey(key)
            except WindowsError:
                report.append(f"WARNING: Registry Key NOT FOUND: HKEY_CLASSES_ROOT\\{key_path}")
    except Exception as e:
        report.append(f"Failed to check registry: {e}")
    report.append("")

    # 9. Troubleshooting Tips based on findings
    report.append("--- DIAGNOSTIC CONCLUSIONS ---")
    full_report_lower = "\n".join(report).lower()
    if not etabs_running:
        report.append("-> CONCLUSION: ETABS.exe is not running. Please open ETABS and open your model before launching this.")
    elif "found" not in full_report_lower:
        report.append("-> CONCLUSION: The ETABS COM API registrations are missing from the Windows registry.")
        report.append("   Please run 'RegisterETABS.exe' inside your ETABS installation directory as Administrator.")
    elif "success: connected" not in full_report_lower:
        report.append("-> CONCLUSION: ETABS is running, but Windows COM cannot bind to it.")
        report.append("   This is almost always a Privilege Mismatch (UAC).")
        report.append("   Make sure BOTH the command prompt/Detailer and ETABS are run as normal user OR both run as Administrator.")
    else:
        report.append("-> CONCLUSION: Diagnostics completed. At least one connection method succeeded.")

    report.append("\n====================================================")
    
    # Save report to file
    report_content = "\n".join(report)
    filename = "etabs_diagnostic_report.txt"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(report_content)
        print(f"Diagnostics complete! Report saved to '{os.path.abspath(filename)}'")
    except Exception as e:
        print(f"Failed to save diagnostic report to file: {e}")
        
    return report_content

if __name__ == "__main__":
    print("Running ETABS connection diagnostics...")
    content = run_diagnostics()
    print("\n--- REPORT PREVIEW ---")
    print("\n".join(content.split("\n")[:30]))
    print("... (see full report in etabs_diagnostic_report.txt) ...")

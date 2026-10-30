import os
import sys

# Ensure comtypes uses a writable directory for dynamically generated COM modules when packaged as an EXE
if getattr(sys, 'frozen', False):
    import tempfile
    try:
        import comtypes.client
        # Set a writable directory for comtypes dynamically generated wrappers
        comtypes.client.gen_dir = os.path.join(tempfile.gettempdir(), "comtypes_gen")
        if not os.path.exists(comtypes.client.gen_dir):
            os.makedirs(comtypes.client.gen_dir)
        # Add the gen_dir to sys.path so comtypes can load the generated modules
        if comtypes.client.gen_dir not in sys.path:
            sys.path.append(comtypes.client.gen_dir)
    except Exception as e:
        print(f"Failed to set writable comtypes cache directory: {e}")

import comtypes.client
import pandas as pd
import numpy as np
import io
import re

def connect_to_etabs(gui_callback=None):
    """
    Connect to the active instance of ETABS and return SapModel.
    Scans the ROT using pywin32 to find running instances.
    If multiple instances are found, lets the user select (or GUI callback).
    """
    print("Connecting to ETABS...")
    
    # Pre-initialize ETABS type library so comtypes knows how to cast generic wrapped COM objects.
    # GetBestInterface auto-generates bindings from whichever type library the currently
    # installed/running ETABS actually registers (e.g. ETABSv1.tlb on ETABS 20 vs. CSiAPIv1.tlb
    # on ETABS 22+) instead of a hardcoded cached interface that can silently mismatch a newer
    # or older ETABS install and corrupt memory on calls (observed as COM access violations).
    try:
        helper = comtypes.client.CreateObject('ETABSv1.Helper')
        helper = comtypes.client.GetBestInterface(helper)
        print("Successfully pre-initialized ETABS type library in comtypes.")
    except Exception as e:
        print(f"Pre-initialization of ETABS type library bypassed: {e}")
        
    # Try pywin32 ROT-based multi-instance selection first
    try:
        import pythoncom
        import ctypes
        
        rot = pythoncom.GetRunningObjectTable()
        bind_ctx = pythoncom.CreateBindCtx(0)
        enum_monikers = rot.EnumRunning()
        
        instances = []
        for moniker in enum_monikers:
            try:
                name = moniker.GetDisplayName(bind_ctx, None)
                if "csi.etabs.api.etabsobject" in name.lower():
                    pid = name.split(":")[-1]
                    punk_pywin = rot.GetObject(moniker)
                    
                    rep = repr(punk_pywin)
                    match = re.search(r"with obj at (0x[0-9a-fA-F]+)", rep)
                    if not match:
                        continue
                        
                    addr_val = int(match.group(1), 16)
                    
                    # Bind using comtypes
                    from comtypes import IUnknown, POINTER
                    punk = ctypes.cast(addr_val, POINTER(IUnknown))
                    punk.AddRef()
                    
                    etabs_object = comtypes.client.wrap(punk)
                    # Crucial cast step: resolve to the fully-typed interface matching the
                    # actual installed ETABS version (see GetBestInterface note above) so
                    # attributes (like SapModel) are exposed.
                    try:
                        etabs_object = comtypes.client.GetBestInterface(etabs_object)
                    except Exception as qi_err:
                        print(f"Failed to cast ETABS object to typed interface in ROT scan: {qi_err}")
                    sap_model = etabs_object.SapModel
                    
                    try:
                        filename = sap_model.GetModelFilename(False)
                        filepath = sap_model.GetModelFilename(True)
                    except Exception:
                        filename = None
                        filepath = None
                    # Unsaved models return None for their filename
                    filename = filename or "Untitled / No Model Loaded"
                    filepath = filepath or ""
                        
                    instances.append({
                        'pid': pid,
                        'filename': filename,
                        'filepath': filepath,
                        'sap_model': sap_model,
                        'display_name': f"PID {pid} - {filename}"
                    })
            except Exception:
                continue
                
        if instances:
            if len(instances) == 1:
                inst = instances[0]
                print(f"Connected to running ETABS instance (PID: {inst['pid']}, Model: {inst['filename']})")
                return inst['sap_model'], inst['filename'], inst['filepath']
            else:
                if gui_callback:
                    # Let the GUI handle selection
                    return instances
                    
                print(f"\nDetected {len(instances)} running ETABS instances:")
                for idx, inst in enumerate(instances):
                    print(f"[{idx + 1}] PID: {inst['pid']} | Model: {inst['filename']}")
                print("-" * 50)
                
                choice = 1
                try:
                    choice_str = input(f"Select ETABS instance (1-{len(instances)}) [default 1]: ").strip()
                    if choice_str:
                        choice = int(choice_str)
                except Exception:
                    pass
                
                inst = instances[min(max(0, choice - 1), len(instances) - 1)]
                print(f"Connected to selected instance (PID: {inst['pid']}, Model: {inst['filename']})")
                return inst['sap_model'], inst['filename'], inst['filepath']
    except Exception as e:
        print(f"ROT-based connection scan bypassed or pywin32 not available: {e}")
        
    # Standard single-instance fallback
    try:
        helper = comtypes.client.CreateObject('ETABSv1.Helper')
        helper = comtypes.client.GetBestInterface(helper)

        etabs_object = None
        # Method 1: CSI Helper standard GetObject method (proven to succeed on this machine where GetActiveObject fails)
        try:
            etabs_object = helper.GetObject("CSI.ETABS.API.ETABSObject")
            if etabs_object:
                print("Retrieved active ETABS object via helper.GetObject.")
        except Exception as helper_err:
            print(f"helper.GetObject failed: {helper_err}")
            
        # Method 2: Fallback to comtypes GetActiveObject
        if not etabs_object:
            print("Attempting standard GetActiveObject fallback...")
            etabs_object = comtypes.client.GetActiveObject("CSI.ETABS.API.ETABSObject")
            
        # Crucial cast step: resolve to the fully-typed interface matching the actual
        # installed ETABS version (see GetBestInterface note above) so attributes
        # (like SapModel) are exposed.
        try:
            etabs_object = comtypes.client.GetBestInterface(etabs_object)
        except Exception as qi_err:
            print(f"Failed to cast ETABS object to typed interface: {qi_err}")
            
        sap_model = etabs_object.SapModel
        try:
            filename = sap_model.GetModelFilename(False)
            filepath = sap_model.GetModelFilename(True)
        except Exception:
            filename = None
            filepath = None
        # Unsaved models return None for their filename
        filename = filename or "Active ETABS Model"
        filepath = filepath or ""
        print("Connected to active ETABS object successfully.")
        return sap_model, filename, filepath
    except Exception as e:
        print(f"Error connecting to active ETABS: {e}")
        return None, None, None

def read_etabs_table(sap_model, table_key):
    """Helper to query a specific ETABS database table into a pandas DataFrame."""
    try:
        ret = sap_model.DatabaseTables.GetTableForDisplayCSVString(TableKey=table_key, GroupName="")
        if isinstance(ret, str):
            if "Story" in ret or "Label" in ret or "," in ret:
                return pd.read_csv(io.StringIO(ret))
        if isinstance(ret, (tuple, list)):
            for val in ret:
                if isinstance(val, str) and ("," in val or "\n" in val or "Frame" in val or "Story" in val or "Label" in val):
                    return pd.read_csv(io.StringIO(val))
    except Exception as e:
        print(f"Table '{table_key}' not readable: {e}")
    return None

def get_grid_lines(sap_model):
    """Extract coordinate grid lines from ETABS including Cartesian and General grids using database tables."""
    table_key = "Grid Definitions - Grid Lines"
    df_results = read_etabs_table(sap_model, table_key)
    if df_results is None:
        return None, None
        
    try:
        df_results.columns = [c.strip() for c in df_results.columns]
        x_grids = []
        y_grids = []
        
        for _, row in df_results.iterrows():
            g_type = str(row['Grid Line Type']).strip()
            g_id = str(row['ID']).strip()
            
            # Cartesian grid lines use Ordinate
            if 'Cartesian' in g_type and ('X' in g_type or 'Y' in g_type):
                try:
                    ord_val = float(row['Ordinate'])
                except ValueError:
                    continue
                
                grid_dict = {
                    'id': g_id,
                    'type': 'X_Cartesian' if 'X' in g_type else 'Y_Cartesian',
                    'ordinate': ord_val
                }
                
                if 'X' in g_type:
                    x_grids.append(grid_dict)
                else:
                    y_grids.append(grid_dict)
            
            # General Cartesian grids
            elif 'General' in g_type:
                try:
                    x1 = float(row['X1'])
                    y1 = float(row['Y1'])
                    x2 = float(row['X2'])
                    y2 = float(row['Y2'])
                except (ValueError, TypeError):
                    continue
                
                grid_dict = {
                    'id': g_id,
                    'type': 'General',
                    'x1': x1,
                    'y1': y1,
                    'x2': x2,
                    'y2': y2
                }
                
                dx = x2 - x1
                dy = y2 - y1
                
                # Classify by orientation
                if abs(dy) >= abs(dx):
                    x_grids.append(grid_dict) # Vertical-ish acts as an X-grid
                else:
                    y_grids.append(grid_dict) # Horizontal-ish acts as a Y-grid
                    
        # Helper to sort grid objects
        def sort_key(grid):
            if grid['type'] in ('X_Cartesian', 'Y_Cartesian'):
                return grid['ordinate']
            elif grid['type'] == 'General':
                # Return the average coordinate along its axis
                dx = grid['x2'] - grid['x1']
                dy = grid['y2'] - grid['y1']
                if abs(dy) >= abs(dx):
                    return (grid['x1'] + grid['x2']) / 2.0
                else:
                    return (grid['y1'] + grid['y2']) / 2.0
            return 0.0

        # Remove duplicates by ID and sort
        x_seen = {}
        for g in x_grids:
            x_seen[g['id']] = g
        x_grids = sorted(list(x_seen.values()), key=sort_key)

        y_seen = {}
        for g in y_grids:
            y_seen[g['id']] = g
        y_grids = sorted(list(y_seen.values()), key=sort_key)
        
        return x_grids, y_grids
    except Exception:
        return None, None

def distance_to_grid_line(cx, cy, grid, is_x=True):
    """Helper to calculate distance from coordinates (cx, cy) to a grid line."""
    if isinstance(grid, tuple):
        # Backward compatibility for tuple-based virtual grids
        ord_val = grid[1]
        return abs((cx if is_x else cy) - ord_val)
        
    g_type = grid.get('type')
    if g_type == 'X_Cartesian':
        return abs(cx - grid['ordinate'])
    elif g_type == 'Y_Cartesian':
        return abs(cy - grid['ordinate'])
    elif g_type == 'General':
        x1, y1 = grid['x1'], grid['y1']
        x2, y2 = grid['x2'], grid['y2']
        
        dx = x2 - x1
        dy = y2 - y1
        
        # Degenerate case (point instead of line)
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return ((cx - x1)**2 + (cy - y1)**2)**0.5
            
        # Perpendicular distance to the infinite line
        num = abs(dy * cx - dx * cy + x2 * y1 - y2 * x1)
        den = (dy**2 + dx**2)**0.5
        return num / den
    return float('inf')


def generate_virtual_grids(column_coords, tolerance=0.5):
    """Generate virtual grids if structural grids are unavailable."""
    if not column_coords:
        return [("X1", 0.0)], [("Y1", 0.0)]
        
    x_coords = sorted(list(set([c[0] for c in column_coords])))
    y_coords = sorted(list(set([c[1] for c in column_coords])))
    
    grouped_x = []
    current = []
    for x in x_coords:
        if not current:
            current.append(x)
        elif abs(x - current[-1]) < tolerance:
            current.append(x)
        else:
            grouped_x.append(np.mean(current))
            current = [x]
    if current:
        grouped_x.append(np.mean(current))
        
    grouped_y = []
    current = []
    for y in y_coords:
        if not current:
            current.append(y)
        elif abs(y - current[-1]) < tolerance:
            current.append(y)
        else:
            grouped_y.append(np.mean(current))
            current = [y]
    if current:
        grouped_y.append(np.mean(current))
        
    import string
    x_grids = []
    for i, x in enumerate(grouped_x):
        label = ""
        n = i
        while n >= 0:
            label = string.ascii_uppercase[n % 26] + label
            n = n // 26 - 1
        x_grids.append((label, x))
        
    y_grids = []
    for i, y in enumerate(grouped_y):
        y_grids.append((str(i+1), y))
        
    return x_grids, y_grids

def get_section_dimensions(sap_model, prop_name, status_callback=None, warned_sections=None):
    """Retrieve the physical width and depth of a section in meters."""
    def emit(msg):
        if status_callback:
            status_callback(msg)
        else:
            print(msg)

    fail_reasons = []

    try:
        ret = sap_model.PropFrame.GetRectangle(prop_name)
        if ret[-1] == 0:
            return "Rectangular", ret[3], ret[2]
        fail_reasons.append(f"GetRectangle ret_code={ret[-1]}")
    except Exception as e:
        fail_reasons.append(f"GetRectangle raised: {e}")

    try:
        ret = sap_model.PropFrame.GetCircle(prop_name)
        if ret[-1] == 0:
            return "Circular", ret[2], ret[2]
        fail_reasons.append(f"GetCircle ret_code={ret[-1]}")
    except Exception as e:
        fail_reasons.append(f"GetCircle raised: {e}")

    # Covers sections defined by overall dimensions (e.g. "General" property type)
    # rather than a literal rectangular/circular shape.
    try:
        ret = sap_model.PropFrame.GetGeneral(prop_name)
        if ret[-1] == 0 and ret[2] > 0 and ret[3] > 0:
            return "Rectangular", ret[3], ret[2]
        fail_reasons.append(f"GetGeneral ret_code={ret[-1] if ret else 'N/A'}")
    except Exception as e:
        fail_reasons.append(f"GetGeneral raised: {e}")

    already_warned = warned_sections is not None and prop_name in warned_sections
    if warned_sections is not None:
        warned_sections.add(prop_name)

    # Last resort for shapes with no direct dimension API (e.g. Section Designer,
    # auto-select list members not yet resolved): derive an equivalent square from
    # the actual cross-sectional area instead of guessing a fixed size.
    try:
        ret = sap_model.PropFrame.GetSectProps(prop_name)
        if ret[-1] == 0 and ret[0] > 0:
            side = ret[0] ** 0.5
            if not already_warned:
                emit(f"Warning: Could not determine exact shape for section '{prop_name}' "
                     f"({'; '.join(fail_reasons)}); approximated as "
                     f"{side * 1000.0:.0f}x{side * 1000.0:.0f}mm from cross-sectional area. "
                     f"Verify this column's size manually.")
            return "Rectangular", side, side
        fail_reasons.append(f"GetSectProps ret_code={ret[-1] if ret else 'N/A'}")
    except Exception as e:
        fail_reasons.append(f"GetSectProps raised: {e}")

    if not already_warned:
        emit(f"Warning: Could not determine dimensions for section '{prop_name}' "
             f"({'; '.join(fail_reasons)}); defaulting to 400x400mm. Verify this column's size manually.")
    return "Rectangular", 0.4, 0.4

def extract_rebar_design_results(sap_model):
    """Extract required longitudinal rebar percentage for each column frame."""
    table_keys = []
    try:
        ret = sap_model.DatabaseTables.GetAvailableTables()
        num_tables, keys, names, import_types, ret_code = ret
        if ret_code == 0:
            table_keys = list(keys)
    except Exception:
        pass
        
    design_table_key = None
    for key in table_keys:
        k_lower = key.lower()
        if "concrete column" in k_lower and "pmm" in k_lower and "envelope" in k_lower:
            design_table_key = key
            break
            
    common_keys = [
        "Concrete Column PMM Envelope - IS 456-2000",
        "Concrete Column PMM Envelope - ACI 318-19",
        "Concrete Column PMM Envelope - ACI 318-14",
        "Concrete Column PMM Envelope - Eurocode 2-2004",
        "Concrete Column PMM Envelope"
    ]
    
    df_results = None
    if design_table_key:
        df_results = read_etabs_table(sap_model, design_table_key)
    else:
        for key in common_keys:
            df_results = read_etabs_table(sap_model, key)
            if df_results is not None:
                break
                
    rebar_data = {}
    if df_results is not None:
        df_results.columns = [c.strip() for c in df_results.columns]
        
        frame_col = None
        for target in ['uniquename', 'unique name', 'frame', 'element']:
            for c in df_results.columns:
                if c.lower() == target:
                    frame_col = c
                    break
            if frame_col:
                break
        if not frame_col:
            for c in df_results.columns:
                if c.lower() == 'label':
                    frame_col = c
                    break
                    
        rebar_col = None
        for c in df_results.columns:
            c_low = c.lower()
            if 'rebar %' in c_low or 'rebar percent' in c_low or 'pmm ratio or rebar' in c_low or 'ratio' in c_low:
                rebar_col = c
                break
                
        if frame_col and rebar_col:
            for _, row in df_results.iterrows():
                frame_name = str(row[frame_col]).strip()
                rebar_str = str(row[rebar_col]).strip()
                rebar_val = 0.0
                try:
                    val_str = rebar_str.replace('%', '').strip()
                    rebar_val = float(val_str)
                    if 'ratio' in rebar_col.lower() and 'rebar %' not in rebar_col.lower() and rebar_val < 0.1 and rebar_val > 0.0:
                        rebar_val *= 100.0
                except ValueError:
                    pass
                rebar_data[frame_name] = max(rebar_val, rebar_data.get(frame_name, 0.0))
                
    return rebar_data

def extract_column_data(sap_model, status_callback=None):
    """
    Connects to ETABS database and geometry APIs, aggregates grid systems,
    and extracts all concrete columns with their coordinates, story, size, and design steel ratio.
    """
    if status_callback:
        status_callback("Extracting connectivity tables from ETABS...")
        
    original_units = 6
    try:
        ret = sap_model.GetPresentUnits()
        if isinstance(ret, (list, tuple)):
            original_units = ret[0]
        else:
            original_units = ret
    except Exception:
        pass
        
    try:
        # Set to kN_m_C
        sap_model.SetPresentUnits(6)
        
        df_connectivity = read_etabs_table(sap_model, "Column Object Connectivity")
        df_column_bays = read_etabs_table(sap_model, "Column Bays")
        df_point_bays = read_etabs_table(sap_model, "Point Bays")
        
        if df_connectivity is None:
            print("Failed to read critical Column Object Connectivity table from ETABS database.")
            sap_model.SetPresentUnits(original_units)
            return None
            
        df_connectivity.columns = [c.strip() for c in df_connectivity.columns]
        warned_sections = set()

        if status_callback:
            status_callback("Extracting grid layout and design rebar ratio...")
            
        # Parse grid systems
        x_grids, y_grids = get_grid_lines(sap_model)
        
        # Build coordinates maps (optional, with robust OAPI fallback)
        col_bay_to_pt_bay = {}
        pt_bay_to_coord = {}
        
        if df_column_bays is not None:
            df_column_bays.columns = [c.strip() for c in df_column_bays.columns]
            col_bay_to_pt_bay = {str(row['Label']).strip(): str(row['PointBayI']).strip() for _, row in df_column_bays.iterrows()}
            
        if df_point_bays is not None:
            df_point_bays.columns = [c.strip() for c in df_point_bays.columns]
            pt_bay_to_coord = {str(row['Label']).strip(): (float(row['X']), float(row['Y'])) for _, row in df_point_bays.iterrows()}
        
        # If structural grids are not found, use virtual grids clustered from coordinates
        if not x_grids or not y_grids:
            coords_list = list(pt_bay_to_coord.values())
            x_grids, y_grids = generate_virtual_grids(coords_list)
            
        # Get rebar results
        rebar_data = extract_rebar_design_results(sap_model)
        
        resolved_cols = []
        total_rows = len(df_connectivity)
        
        if status_callback:
            status_callback(f"Resolving properties for {total_rows} column elements...")
            
        for idx, row in df_connectivity.iterrows():
            if idx % 50 == 0 and status_callback:
                status_callback(f"Resolving column elements {idx}/{total_rows}...")
                
            uniq_name = str(row['Unique Name']).strip()
            story = str(row['Story']).strip()
            col_bay = str(row['ColumnBay']).strip()
            
            cx, cy = None, None
            pt_bay = col_bay_to_pt_bay.get(col_bay, None)
            if pt_bay:
                coord = pt_bay_to_coord.get(pt_bay, None)
                if coord:
                    cx, cy = coord
                    
            # Fallback to direct OAPI if coordinates couldn't be resolved from database tables
            if cx is None or cy is None:
                try:
                    # Get point I (bottom joint) of the column frame
                    ret_points = sap_model.FrameObj.GetPoints(uniq_name)
                    if ret_points[-1] == 0:
                        pt_i = ret_points[0]
                        ret_coord = sap_model.PointObj.GetCoordCartesian(pt_i)
                        if ret_coord[-1] == 0:
                            cx, cy = ret_coord[0], ret_coord[1]
                except Exception as e:
                    print(f"Failed direct OAPI coordinate recovery for frame '{uniq_name}': {e}")
                    
            if cx is None or cy is None:
                # Only skip if both database lookup and OAPI direct recovery fail
                continue
            
            # Map grid label
            best_x_id = "Off-Grid"
            min_dist_x = float('inf')
            for grid in x_grids:
                dist = distance_to_grid_line(cx, cy, grid, is_x=True)
                if dist < min_dist_x and dist < 0.5:
                    min_dist_x = dist
                    best_x_id = grid[0] if isinstance(grid, tuple) else grid['id']
                    
            best_y_id = "Off-Grid"
            min_dist_y = float('inf')
            for grid in y_grids:
                dist = distance_to_grid_line(cx, cy, grid, is_x=False)
                if dist < min_dist_y and dist < 0.5:
                    min_dist_y = dist
                    best_y_id = grid[0] if isinstance(grid, tuple) else grid['id']
                    
            grid_label = f"{best_y_id}-{best_x_id}"
            
            try:
                ret_sect = sap_model.FrameObj.GetSection(uniq_name)
                section_name = ret_sect[0]
            except Exception as e:
                section_name = "Default"
                if status_callback:
                    status_callback(f"Warning: Could not read section assignment for frame '{uniq_name}' "
                                     f"(FrameObj.GetSection raised: {e}); using 'Default'.")

            shape, w, d = get_section_dimensions(sap_model, section_name,
                                                  status_callback=status_callback,
                                                  warned_sections=warned_sections)
            
            angle = 0.0
            try:
                ret_axes = sap_model.FrameObj.GetLocalAxes(uniq_name)
                if ret_axes[-1] == 0:
                    angle = ret_axes[0]
            except Exception:
                pass
                
            rebar_pct = rebar_data.get(uniq_name, 0.0)
            
            resolved_cols.append({
                'frame_name': uniq_name,
                'col_label': col_bay,
                'story_name': story,
                'x': cx,
                'y': cy,
                'grid_label': grid_label,
                'prop_name': section_name,
                'shape': shape,
                'width': w * 1000.0,  # Convert to mm
                'depth': d * 1000.0,  # Convert to mm
                'angle': angle,
                'rebar_pct': rebar_pct
            })
            
        # Revert units
        sap_model.SetPresentUnits(original_units)
        return {
            'columns': resolved_cols,
            'x_grids': x_grids,
            'y_grids': y_grids
        }
    except Exception as e:
        print(f"Error in column extraction: {e}")
        try:
            sap_model.SetPresentUnits(original_units)
        except Exception:
            pass
        return None

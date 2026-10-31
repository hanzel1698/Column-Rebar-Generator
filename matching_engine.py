import json
import os
import re
import pandas as pd

class MatchingEngine:
    def __init__(self, db_path=None):
        """Loads and pre-processes the AutoCAD Column Schedule Database."""
        self.db_path = db_path
        self.schedule_db = []
        self.load_database()

    def load_database(self):
        """Loads the Excel (or JSON) database and normalizes values for matching."""
        import sys
        
        # 1. Gather all potential database paths to try
        paths_to_try = []
        
        # If an explicit path was passed, try that first
        if self.db_path:
            paths_to_try.append(self.db_path)
            
        # Determine directory of the running executable or script
        if getattr(sys, 'frozen', False):
            run_dir = os.path.dirname(sys.executable)
            # Bundled resources in PyInstaller
            if hasattr(sys, '_MEIPASS'):
                paths_to_try.append(os.path.join(sys._MEIPASS, "clean_column_schedule_db.json"))
        else:
            run_dir = os.path.dirname(os.path.abspath(__file__))
            
        # Check for Excel next to executable/script
        paths_to_try.append(os.path.join(run_dir, "Suggested_CAD_Rebar_Percentages.xlsx"))
        paths_to_try.append(os.path.join(run_dir, "clean_column_schedule_db.json"))
        
        # Check current working directory
        paths_to_try.append(os.path.join(os.getcwd(), "Suggested_CAD_Rebar_Percentages.xlsx"))
        paths_to_try.append(os.path.join(os.getcwd(), "clean_column_schedule_db.json"))
        
        # Hardcoded fallback paths
        paths_to_try.append(r"c:\Column Rebar Generator\Suggested_CAD_Rebar_Percentages.xlsx")
        paths_to_try.append(r"c:\Column Rebar Generator\clean_column_schedule_db.json")
        
        # Deduplicate paths while preserving order
        unique_paths = []
        for p in paths_to_try:
            p_abs = os.path.abspath(p) if p else None
            if p_abs and p_abs not in unique_paths:
                unique_paths.append(p_abs)
                
        # 2. Try loading the first existing path
        loaded = False
        
        for path in unique_paths:
            if os.path.exists(path):
                try:
                    self.schedule_db = []
                    # Check if it's an Excel spreadsheet
                    if path.lower().endswith(('.xlsx', '.xls')):
                        df = pd.read_excel(path, sheet_name="Suggested CAD to Rebar %")
                        df.columns = [c.strip() for c in df.columns]
                        
                        for _, row in df.iterrows():
                            col_id = str(row["Suggested CAD"]).strip()
                            size_str = str(row["Section Size (mm)"]).strip()
                            pct_val = row["Provided rebar %"]
                            area_val = row["Rebar Area (sq.mm)"]
                            rebar_val = row.get("Rebar Callout", "Unknown")
                            
                            # Parse width and depth
                            w, d = 400, 400
                            m = re.match(r"^(\d+)\s*x\s*(\d+)$", size_str.lower().strip())
                            if m:
                                w, d = int(m.group(1)), int(m.group(2))
                            else:
                                m_id = re.match(r"^C-(\d+)x(\d+)-\d+$", col_id)
                                if m_id:
                                    w, d = int(m_id.group(1)) * 100, int(m_id.group(2)) * 100
                                    
                            # Robust scale parsing for provided percentage
                            if pct_val is not None:
                                try:
                                    pct_val = float(pct_val)
                                    # Convert back to standard 0-100 percentage scale for matching
                                    if pct_val <= 1.0:
                                        pct_val *= 100.0
                                except ValueError:
                                    pct_val = None
                                    
                            # Parse area as float
                            if area_val is not None:
                                try:
                                    area_val = float(area_val)
                                except ValueError:
                                    area_val = None
                                    
                            self.schedule_db.append({
                                "id": col_id,
                                "size_raw": size_str,
                                "w": w,
                                "d": d,
                                "pct": pct_val,
                                "area": area_val,
                                "pct_raw": f"{pct_val:.2f}%" if pct_val is not None else "Unknown",
                                "area_raw": f"{area_val:.2f} sqm" if area_val is not None else "Unknown",
                                "rebar": rebar_val
                            })
                        print(f"MatchingEngine successfully initialized with {len(self.schedule_db)} options loaded from Excel database: '{path}'")
                        
                    else:
                        # Fallback to loading original JSON format
                        with open(path, "r", encoding="utf-8") as f:
                            raw_data = json.load(f)
                            
                        for item in raw_data:
                            size_str = item.get("size", "")
                            w, d = 400, 400
                            m = re.match(r"^(\d+)\s*x\s*(\d+)$", size_str.lower().strip())
                            if m:
                                w, d = int(m.group(1)), int(m.group(2))
                            else:
                                m_id = re.match(r"^C-(\d+)x(\d+)-\d+$", item.get("id", ""))
                                if m_id:
                                    w, d = int(m_id.group(1)) * 100, int(m_id.group(2)) * 100
                            
                            pct = item.get("pct")
                            area = item.get("area")
                            
                            self.schedule_db.append({
                                "id": item.get("id"),
                                "size_raw": size_str,
                                "w": w,
                                "d": d,
                                "pct": pct,
                                "area": area,
                                "pct_raw": item.get("pct_raw"),
                                "area_raw": item.get("area_raw"),
                                "rebar": item.get("rebar", "Unknown")
                            })
                        print(f"MatchingEngine successfully initialized with {len(self.schedule_db)} options loaded from JSON database: '{path}'")
                    
                    self.db_path = path
                    loaded = True
                    break
                except Exception as e:
                    print(f"Failed to load database from '{path}': {e}")
                    
        if not loaded:
            print(f"Error: Could not load column schedule database from any of the tried paths: {unique_paths}")


    def find_matching_column(self, etabs_w, etabs_d, required_pct, buffer_pct=0.0):
        """
        Suggests the optimal, most economical column schedule item from CAD.
        Tolerates column orientation (e.g. width/depth rotation).
        """
        target_w = round(etabs_w)
        target_d = round(etabs_d)
        target_pct = required_pct + buffer_pct
        
        # 1. Filter schedule by dimensions (supporting orientation rotation)
        size_matches = []
        for item in self.schedule_db:
            # Check normal orientation
            normal_match = (abs(item["w"] - target_w) < 10 and abs(item["d"] - target_d) < 10)
            # Check rotated orientation
            rotated_match = (abs(item["w"] - target_d) < 10 and abs(item["d"] - target_w) < 10)
            
            if normal_match or rotated_match:
                size_matches.append(item)
                
        if not size_matches:
            return {
                "status": "SIZE NOT FOUND",
                "suggested_id": "N/A",
                "cad_pct": 0.0,
                "cad_area": 0.0,
                "efficiency": 0.0,
                "reason": f"No column with size {target_w}x{target_d} found in CAD schedule."
            }
            
        # 2. Filter conforming columns (provided steel > target steel)
        conforming_matches = []
        for item in size_matches:
            if item["pct"] is not None:
                if item["pct"] > target_pct:
                    conforming_matches.append(item)
            elif item["area"] is not None:
                # If pct is missing but area is present, compute required area
                # Target Area = target_pct * concrete_area / 100
                concrete_area = target_w * target_d
                req_area = (target_pct * concrete_area) / 100.0
                if item["area"] > req_area:
                    # Set a temporary pct if missing
                    item_copy = item.copy()
                    item_copy["pct"] = (item["area"] / concrete_area) * 100.0
                    conforming_matches.append(item_copy)
                    
        if not conforming_matches:
            # The size exists, but no reinforcement option in the drawing is high enough!
            # Let's find the max reinforcement available for this size class to report it
            max_avail = max([item["pct"] for item in size_matches if item["pct"] is not None] + [0.0])
            return {
                "status": "REINFORCEMENT EXCEEDED",
                "suggested_id": "CUSTOM / EXCEEDED",
                "cad_pct": max_avail,
                "cad_area": 0.0,
                "efficiency": (max_avail / required_pct * 100.0) if required_pct > 0 else 0.0,
                "reason": f"Required steel ({target_pct:.2f}%) exceeds maximum available ({max_avail:.2f}%) in CAD schedule."
            }
            
        # 3. Select the minimum conforming reinforcement (most economical suggestion)
        # Sort by steel percentage ascending
        conforming_matches = sorted(conforming_matches, key=lambda x: x["pct"])
        optimal_match = conforming_matches[0]
        
        # Calculate Efficiency Index
        # Efficiency = required_pct / provided_pct * 100%
        provided_pct = optimal_match["pct"]
        efficiency = 100.0
        if provided_pct > 0.0:
            efficiency = min(100.0, (required_pct / provided_pct) * 100.0)
            
        # Decode the rebar callout based on standard mathematical mapping for report presentation
        rebar_callout = self.decode_rebar_callout(optimal_match["id"], optimal_match["area"])
        
        return {
            "status": "SUCCESS",
            "suggested_id": optimal_match["id"],
            "cad_pct": provided_pct,
            "cad_area": optimal_match["area"] if optimal_match["area"] else (provided_pct * target_w * target_d / 100.0),
            "efficiency": efficiency,
            "rebar_callout": rebar_callout,
            "reason": "Optimal matching column identified."
        }

    def decode_rebar_callout(self, col_id, area_val):
        """Returns the exact rebar callout from the database for the given column ID, falling back to decoding if needed."""
        # Query database first for literal callout text
        for item in self.schedule_db:
            if item["id"] == col_id:
                if item.get("rebar") and item["rebar"] != "Unknown":
                    return item["rebar"]

        if not area_val or area_val == "Unknown":
            return "Refer to CAD details"
            
        try:
            area = float(area_val)
        except Exception:
            return "Refer to CAD details"
            
        # Standard rebar database mapped to exact circular areas (using pi=3.14 to align with CAD calculations)
        # Mapping: (Rebar Description, Area)
        # Sorted ascending to find best match
        rebar_combinations = [
            ("8 #16", 1607.68),
            ("4 #20 + 4 #16", 2059.84),
            ("12 #16", 2411.52),
            ("8 #20", 2512.00),
            ("4 #20 + 8 #16", 2863.68),
            ("16 #16", 3215.36),
            ("4 #25 + 8 #16", 3570.18),
            ("4 #20 + 12 #16", 3667.52),
            ("12 #20", 3768.00),
            ("10 #25", 4906.25),
            ("8 #25 + 4 #20", 5181.00),  # Matches C-4x5-12
            ("12 #25", 5887.50),         # Matches C-4x7-17 area 5887.5
            ("14 #25", 6868.75),         # Matches C-4x8-2 area 6868.75
            ("8 #25 + 8 #20", 6437.00),  # Matches C-4x8-9 area 6437.00
            ("16 #25", 7850.00),         # Matches C-4x7-5 area 7850.00
            ("14 #25 + 2 #20", 7496.75),
            ("16 #25 + 2 #20", 8479.25),
            ("18 #25", 8831.25),         # Matches C-4x8-15 area 8831.25
            ("20 #25", 9812.50)          # Matches C-4x8-16 area 9812.50
        ]
        
        # Find closest matching rebar combination within 5% tolerance
        for desc, comb_area in rebar_combinations:
            if abs(area - comb_area) < (0.02 * comb_area):
                return desc
                
        # Heuristic search fallback
        return f"{area:.0f} sq.mm (Callout: Refer to Schedule)"

    def natural_sort_key(self, s):
        """Helper to sort strings containing numbers naturally (e.g. Story2 before Story10)."""
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

    def match_all_columns(self, etabs_data, buffer_pct=0.0):
        """
        Groups ETABS columns by spatial vertical line (grid_label, coordinate x, y),
        finds the maximum required rebar percentage within each stack,
        and matches the optimal CAD column option using the largest section size.
        """
        if not etabs_data or 'columns' not in etabs_data:
            return []
            
        # Group by (grid_label, rounded_x, rounded_y)
        groups = {}
        for col in etabs_data['columns']:
            grid_label = col.get('grid_label', '').strip()
            if not grid_label or grid_label.lower() == 'none' or grid_label == 'Off-Grid-Off-Grid':
                grid_label = f"Col_{col['x']:.2f}_{col['y']:.2f}"
                
            x_val = round(col['x'], 3)
            y_val = round(col['y'], 3)
            
            key = (grid_label, x_val, y_val)
            if key not in groups:
                groups[key] = {
                    'grid_label': grid_label,
                    'x': col['x'],
                    'y': col['y'],
                    'all_cols': []
                }
            
            groups[key]['all_cols'].append(col)
            
        # Now process each group and find matches based on the max rebar % and largest size
        matched_results = []
        for key, group in groups.items():
            # 1. Find the column frame with the max rebar pct
            max_rebar_col = max(group['all_cols'], key=lambda c: c['rebar_pct'])
            max_rebar_pct = max_rebar_col['rebar_pct']
            
            # 2. Find the largest section size at this grid point to match
            def get_area(c):
                w = c['width']
                d = c['depth']
                if c['shape'] == "Circular":
                    return 3.14159265 * (w / 2.0)**2
                return w * d
                
            largest_col = max(group['all_cols'], key=get_area)
            
            # Match optimal CAD column using the largest section size and max rebar %
            match = self.find_matching_column(
                etabs_w=largest_col['width'],
                etabs_d=largest_col['depth'],
                required_pct=max_rebar_pct,
                buffer_pct=buffer_pct
            )
            
            # Format the story list into a clean range string
            stories_in_group = [c['story_name'] for c in group['all_cols']]
            story_list = sorted(list(set(stories_in_group)), key=self.natural_sort_key)
            if len(story_list) == 1:
                story_range = story_list[0]
            elif len(story_list) > 1:
                story_range = f"{story_list[0]} to {story_list[-1]}"
            else:
                story_range = "Unknown"
                
            # Gather all unique column labels present in the stack
            col_labels = sorted(list(set([c.get('col_label', '') for c in group['all_cols'] if c.get('col_label')])))
            col_labels = [l for l in col_labels if l and l.lower() != 'none']
            
            if col_labels:
                col_label_str = "/".join(col_labels)
            else:
                col_label_str = group['grid_label']
                
            # Create the reconciled result dictionary
            res = {
                'frame_name': col_label_str, # Used in reports and UI for column labels
                'col_label': col_label_str,
                'story_name': story_range,
                'x': group['x'],
                'y': group['y'],
                'grid_label': group['grid_label'],
                'prop_name': largest_col['prop_name'],
                'shape': largest_col['shape'],
                'width': largest_col['width'],
                'depth': largest_col['depth'],
                'angle': largest_col['angle'],
                'rebar_pct': max_rebar_pct,
                'suggested_id': match['suggested_id'],
                'cad_pct': match['cad_pct'],
                'cad_area': match['cad_area'],
                'efficiency': match['efficiency'],
                'status': match['status'],
                'rebar_callout': match.get('rebar_callout', "N/A"),
                'reason': match['reason'],
                'all_stories': list(set(stories_in_group)),
                'all_frames': [c['frame_name'] for c in group['all_cols']]
            }
            
            matched_results.append(res)
            
        # Sort spatially: from top to bottom (y descending), then left to right (x ascending)
        matched_results = sorted(matched_results, key=lambda c: (-round(c['y'], 3), round(c['x'], 3)))
        return matched_results

    def auto_group_columns(self, columns, tolerance=0.30):
        """
        Groups matching columns based on physical section size and provided rebar % proximity.
        Each column in the group is detailed using the worst-case (highest pct) option.
        Assigns sequential notations (C1, C2, C3...) across all sizes.
        """
        # Distinguish SUCCESS (conforming) and non-conforming
        conforming_cols = [c for c in columns if c['status'] == 'SUCCESS']
        non_conforming_cols = [c for c in columns if c['status'] != 'SUCCESS']
        
        # Ensure backup fields exist so we can always revert to original matches
        for c in columns:
            c['original_suggested_id'] = c.get('original_suggested_id', c['suggested_id'])
            c['original_cad_pct'] = c.get('original_cad_pct', c['cad_pct'])
            c['original_rebar_callout'] = c.get('original_rebar_callout', c.get('rebar_callout', 'N/A'))
            
        # Group by physical size (width, depth)
        size_groups = {}
        for c in conforming_cols:
            size_key = (round(c['width']), round(c['depth']))
            if size_key not in size_groups:
                size_groups[size_key] = []
            size_groups[size_key].append(c)
            
        notation_counter = 1
        grouped_results = []
        
        # Process sizes in ascending order of cross-sectional area
        for size_key in sorted(size_groups.keys(), key=lambda k: k[0] * k[1]):
            cols_in_size = size_groups[size_key]
            
            # Sort by original matched CAD provided rebar %
            cols_in_size = sorted(cols_in_size, key=lambda c: c['original_cad_pct'])
            
            # Sub-group based on tolerance
            sub_groups = []
            current_sub_group = []
            
            for c in cols_in_size:
                if not current_sub_group:
                    current_sub_group.append(c)
                else:
                    diff = abs(c['original_cad_pct'] - current_sub_group[-1]['original_cad_pct'])
                    if diff <= tolerance:
                        current_sub_group.append(c)
                    else:
                        sub_groups.append(current_sub_group)
                        current_sub_group = [c]
            if current_sub_group:
                sub_groups.append(current_sub_group)
                
            # Process each sub-group
            for sub in sub_groups:
                notation_label = f"C{notation_counter}"
                notation_counter += 1
                
                # Find worst-case within the sub-group
                worst_case = max(sub, key=lambda c: c['original_cad_pct'])
                worst_cad_id = worst_case['original_suggested_id']
                worst_cad_pct = worst_case['original_cad_pct']
                worst_cad_callout = worst_case['original_rebar_callout']
                
                # Update all columns in sub-group to use the worst-case design
                for c in sub:
                    c['group_notation'] = notation_label
                    c['suggested_id'] = worst_cad_id
                    c['cad_pct'] = worst_cad_pct
                    c['rebar_callout'] = worst_cad_callout
                    if worst_cad_pct > 0.0:
                        c['efficiency'] = min(100.0, (c['rebar_pct'] / worst_cad_pct) * 100.0)
                    else:
                        c['efficiency'] = 100.0
                        
                grouped_results.extend(sub)
                
        # Non-conforming columns do not get automatically grouped
        for c in non_conforming_cols:
            c['group_notation'] = "Exceeded" if c['status'] == 'REINFORCEMENT EXCEEDED' else "N/A"
            c['original_suggested_id'] = c.get('original_suggested_id', c['suggested_id'])
            c['original_cad_pct'] = c.get('original_cad_pct', c['cad_pct'])
            c['original_rebar_callout'] = c.get('original_rebar_callout', c.get('rebar_callout', 'N/A'))
            grouped_results.append(c)
            
        # Re-sort spatially (y descending, x ascending)
        grouped_results = sorted(grouped_results, key=lambda c: (-round(c['y'], 3), round(c['x'], 3)))
        return grouped_results

    def recalculate_groups(self, columns):
        """
        Recalculates group suggestions and column efficiencies based on the current 'group_notation' assignments.
        Validates that no two different section sizes are grouped under the same notation.
        """
        # Group columns by current group_notation (ignoring non-group notations)
        groups = {}
        for c in columns:
            notation = c.get('group_notation', '').strip()
            if not notation or notation in ('N/A', 'Exceeded', 'Default', '-'):
                continue
            if notation not in groups:
                groups[notation] = []
            groups[notation].append(c)
            
        errors = []
        for notation, cols in groups.items():
            # Check physical sizes consistency
            sizes = set((round(c['width']), round(c['depth'])) for c in cols)
            if len(sizes) > 1:
                errors.append(f"Notation '{notation}' contains multiple section sizes: {list(sizes)}. Columns with different section sizes cannot be grouped under the same notation.")
                continue
                
            # Find the worst-case among them based on their original matched CAD column details
            worst_case = max(cols, key=lambda c: c['original_cad_pct'])
            worst_cad_id = worst_case['original_suggested_id']
            worst_cad_pct = worst_case['original_cad_pct']
            worst_cad_callout = worst_case['original_rebar_callout']
            
            # Apply to all columns in the group
            for c in cols:
                c['suggested_id'] = worst_cad_id
                c['cad_pct'] = worst_cad_pct
                c['rebar_callout'] = worst_cad_callout
                if worst_cad_pct > 0.0:
                    c['efficiency'] = min(100.0, (c['rebar_pct'] / worst_cad_pct) * 100.0)
                else:
                    c['efficiency'] = 100.0
                    
        return errors


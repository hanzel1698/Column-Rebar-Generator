# Gemini Development Rules for ETABS-to-CAD Column Detailer

This file defines the core architectural guidelines and execution rules for developers (including AI coding assistants) working on the Column Rebar Detailer.

## 1. Executable Compilation Rule (PyInstaller)
- **Do Not Auto-Build the Standalone EXE**: Do not automatically trigger PyInstaller compiler commands (e.g., `pyinstaller` or `pyinstaller.exe` calls) after code updates.
- **Explicit Permission Required**: Always request explicit user permission before initiating any executable packaging or rebuild.

## 2. Spatial Grouping Architecture
- **Coordinate-based Grouping**: Group column frame design results spatially using plan coordinate intersection keys: `(grid_label, round(x, 3), round(y, 3))` instead of string labels alone. This ensures varying floor-by-floor column labels in the vertical stack are correctly consolidated.
- **Worst-case Reinforcement & Largest Size**: Aggregations for vertical lines must always identify the envelope maximum required rebar percentage and the largest physical size along the stack to match against AutoCAD schedules.

## 3. PDF Saving Paths
- **Active Directory Matching**: The default directory for saving and exporting report PDFs must always match the directory path of the currently loaded/active `.EDB` model.

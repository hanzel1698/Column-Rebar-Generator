import os
import sys
import io
import re
import math
from datetime import datetime
from reportlab.lib.pagesizes import letter, A4, A3, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, Image as RLImage
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect, Circle, String, Line, Group
from PIL import Image as PILImage

def get_pdf_notation_color(notation, matched_columns):
    """Returns a distinct hex color for each naturally sorted notation group, matching plan design colors."""
    NOTATION_COLORS = [
        "#3B82F6",  # Cobalt Blue
        "#10B981",  # Emerald Green
        "#8B5CF6",  # Violet Purple
        "#EC4899",  # Pink
        "#F59E0B",  # Amber Orange
        "#06B6D4",  # Cyan
        "#14B8A6",  # Teal
        "#A855F7",  # Purple
        "#F43F5E",  # Rose Red
        "#6366F1",  # Indigo
        "#E11D48",  # Crimson
        "#059669",  # Dark Emerald
    ]
    if not notation or notation in ('N/A', 'Default', '-'):
        return "#64748B"  # Slate Gray
    if notation == "Exceeded":
        return "#EF4444"  # Warning Red
        
    unique_notations = sorted(
        list(set(c.get('group_notation', '').strip() for c in matched_columns if c.get('group_notation', '').strip())),
        key=lambda n: [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', n)]
    )
    if notation in unique_notations:
        idx = unique_notations.index(notation) % len(NOTATION_COLORS)
        return NOTATION_COLORS[idx]
    return "#64748B"

class NumberedCanvas(canvas.Canvas):
    """Custom canvas for premium multi-page header/footer detailing on A3 Landscape."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        # Skip decoration on cover page (Page 1)
        if self._pageNumber == 1:
            return

        self.saveState()
        page_width, page_height = self._pagesize if hasattr(self, '_pagesize') else (1190.55, 841.89)
        margin = 54
        right_boundary = page_width - margin

        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#1E293B")) # Dark Slate

        # Header
        self.drawString(margin, page_height - 36, "ETABS-TO-CAD COLUMN REBAR RECONCILIATION AUDIT")
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawRightString(right_boundary, page_height - 36, f"Date: {datetime.now().strftime('%Y-%m-%d')}")
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(margin, page_height - 44, right_boundary, page_height - 44)

        # Footer
        self.line(margin, 45, right_boundary, 45)
        self.setFont("Helvetica", 7.5)
        self.drawString(margin, 30, "Confidential Structural Integrity Audit Report")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(right_boundary, 30, page_text)
        self.restoreState()

def get_column_image(suggested_id, max_w=180.0, max_h=120.0):
    """Searches for the column image in 'Column xn' case-insensitively and returns a scaled RLImage flowable or None."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        image_dir = os.path.join(sys._MEIPASS, "Column xn")
    else:
        image_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Column xn")
        
    if not os.path.exists(image_dir):
        return None
        
    # Standardize name search, e.g. 'c-4x5-1' -> 'c-4x5-1'
    target_name = str(suggested_id).strip().lower().replace(' ', '')
    
    img_path = None
    for f in os.listdir(image_dir):
        f_clean = f.strip().lower().replace(' ', '').replace('.jpg', '').replace('.jpeg', '')
        if f_clean == target_name:
            img_path = os.path.join(image_dir, f)
            break
            
    if not img_path or not os.path.exists(img_path):
        return None
        
    try:
        with PILImage.open(img_path) as pil_img:
            img_w, img_h = pil_img.size
        # Proportional scale
        scale = min(max_h / img_h, max_w / img_w)
        draw_w = img_w * scale
        draw_h = img_h * scale
        return RLImage(img_path, width=draw_w, height=draw_h)
    except Exception as e:
        print(f"Error loading image '{img_path}': {e}")
        return None

def generate_pdf_report(matched_columns, etabs_name, buffer_pct, file_path, raw_etabs_data=None):
    """Generates a highly polished structural audit report in PDF format (A3 Landscape) including structural plan and groups summary."""
    print(f"Compiling professional PDF report: '{file_path}'...")
    
    # 1. Compute summary stats
    total_cols = len(matched_columns)
    conforming = sum(1 for c in matched_columns if c['status'] == 'SUCCESS')
    exceeded = sum(1 for c in matched_columns if c['status'] == 'REINFORCEMENT EXCEEDED')
    not_found = sum(1 for c in matched_columns if c['status'] == 'SIZE NOT FOUND')
    
    valid_effs = [c['efficiency'] for c in matched_columns if c['status'] == 'SUCCESS']
    avg_efficiency = (sum(valid_effs) / len(valid_effs)) if valid_effs else 0.0

    # 2. Setup document (A3 Landscape)
    doc = SimpleDocTemplate(
        file_path,
        pagesize=landscape(A3),
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )
    
    styles = getSampleStyleSheet()
    
    # Define Custom Typography Styles
    title_style = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=32,
        leading=38,
        textColor=colors.HexColor('#1E293B'),
        spaceAfter=20
    )
    
    subtitle_style = ParagraphStyle(
        'CoverSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=16,
        leading=20,
        textColor=colors.HexColor('#475569'),
        spaceAfter=40
    )
    
    h1_style = ParagraphStyle(
        'Heading1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0F172A'),
        spaceBefore=15,
        spaceAfter=10,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#334155')
    )
    
    cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#1E293B')
    )
    
    cell_bold_style = ParagraphStyle(
        'TableCellBold',
        parent=cell_style,
        fontName='Helvetica-Bold'
    )
    
    story_parts = []

    # ==================== COVER PAGE ====================
    story_parts.append(Spacer(1, 100))
    # Elegant top border line
    d_line = Table([[""]], colWidths=[1082], rowHeights=[6])
    d_line.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#3B82F6')), # Cobalt Blue Accent
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    story_parts.append(d_line)
    story_parts.append(Spacer(1, 25))
    
    story_parts.append(Paragraph("ETABS-to-CAD Column Rebar<br/>Reconciliation & Detailer Suggester", title_style))
    story_parts.append(Paragraph("Structural Auditing and Optimization Schedule Report", subtitle_style))
    
    # Metadata block
    meta_data = [
        [Paragraph("<b>Target ETABS Model:</b>", body_style), Paragraph(os.path.basename(etabs_name), body_style)],
        [Paragraph("<b>AutoCAD Drawing Database:</b>", body_style), Paragraph("Column reinforcement.dwg (Deduplicated Schedule)", body_style)],
        [Paragraph("<b>Rebar Safety Buffer:</b>", body_style), Paragraph(f"{buffer_pct:.2f}%", body_style)],
        [Paragraph("<b>Total Concrete Columns Audited:</b>", body_style), Paragraph(str(total_cols), body_style)],
        [Paragraph("<b>Conforming Matches suggested:</b>", body_style), Paragraph(f"{conforming} / {total_cols} columns ({conforming/total_cols*100:.1f}%)", body_style)],
        [Paragraph("<b>Non-conforming (Exceeded) warnings:</b>", body_style), Paragraph(f"<font color='#EF4444'><b>{exceeded} warnings</b></font>" if exceeded else "0", body_style)],
        [Paragraph("<b>Section Size Mismatch warnings:</b>", body_style), Paragraph(f"<font color='#F59E0B'><b>{not_found} warnings</b></font>" if not_found else "0", body_style)],
        [Paragraph("<b>Average Suggestion Efficiency Index:</b>", body_style), Paragraph(f"<b>{avg_efficiency:.2f}%</b> (Economical Optimization)", body_style)],
        [Paragraph("<b>Date of Report Generation:</b>", body_style), Paragraph(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), body_style)],
    ]
    
    meta_table = Table(meta_data, colWidths=[300, 782])
    meta_table.setStyle(TableStyle([
        ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story_parts.append(meta_table)
    story_parts.append(PageBreak())

    # ==================== PAGE 2: STRUCTURAL PLAN & GROUPS SUMMARY ====================
    story_parts.append(Paragraph("Interactive Structural Plan Layout & Groups Summary", h1_style))
    story_parts.append(Spacer(1, 10))
    
    # Setup vector drawing container dimensions
    drawing_width = 720
    drawing_height = 600
    drawing = Drawing(drawing_width, drawing_height)
    
    # Add a subtle light slate background to plan drawing box
    drawing.add(Rect(0, 0, drawing_width, drawing_height, fillColor=colors.HexColor("#F8FAFC"), strokeColor=colors.HexColor("#CBD5E1"), strokeWidth=1))
    
    cols_x = [c['x'] for c in matched_columns]
    cols_y = [c['y'] for c in matched_columns]
    if cols_x:
        x_min, x_max = min(cols_x), max(cols_x)
        y_min, y_max = min(cols_y), max(cols_y)
    else:
        x_min, x_max, y_min, y_max = 0.0, 10.0, 0.0, 10.0
        
    pad = 3.0
    x_range = (x_max - x_min) + 2 * pad
    y_range = (y_max - y_min) + 2 * pad
    if x_range <= 0: x_range = 1.0
    if y_range <= 0: y_range = 1.0
    
    scale_x = (drawing_width - 60) / x_range
    scale_y = (drawing_height - 60) / y_range
    scale = min(scale_x, scale_y)
    
    offset_x = 30 + (drawing_width - 60 - (x_max - x_min + 2 * pad) * scale) / 2.0
    offset_y = 30 + (drawing_height - 60 - (y_max - y_min + 2 * pad) * scale) / 2.0
    
    def to_pdf_coords(cx, cy):
        px = offset_x + (cx - (x_min - pad)) * scale
        py = offset_y + (cy - (y_min - pad)) * scale
        return px, py
        
    # Draw Dynamic Gridlines
    if raw_etabs_data:
        x_grids = raw_etabs_data.get('x_grids', [])
        y_grids = raw_etabs_data.get('y_grids', [])
        
        # Draw X Gridlines (Vertical)
        for g in x_grids:
            val = None
            label = ""
            if isinstance(g, tuple):
                label, val = g
            elif isinstance(g, dict) and g.get('type') == 'X_Cartesian':
                label, val = g.get('id', ''), g.get('ordinate')
                
            if val is not None:
                x1, y1 = to_pdf_coords(val, y_min - pad + 0.5)
                x2, y2 = to_pdf_coords(val, y_max + pad - 0.5)
                drawing.add(Line(x1, y1, x2, y2, strokeColor=colors.HexColor("#94A3B8"), strokeWidth=0.5, strokeDashArray=[2, 4]))
                
                # Bubbles
                for bx, by in [(x1, y1 - 10), (x2, y2 + 10)]:
                    drawing.add(Circle(bx, by, 7, fillColor=colors.HexColor("#FFFFFF"), strokeColor=colors.HexColor("#94A3B8"), strokeWidth=0.5))
                    drawing.add(String(bx, by - 2.5, label, textAnchor="middle", fontSize=6, fontName="Helvetica", fillColor=colors.HexColor("#475569")))
                    
        # Draw Y Gridlines (Horizontal)
        for g in y_grids:
            val = None
            label = ""
            if isinstance(g, tuple):
                label, val = g
            elif isinstance(g, dict) and g.get('type') == 'Y_Cartesian':
                label, val = g.get('id', ''), g.get('ordinate')
                
            if val is not None:
                x1, y1 = to_pdf_coords(x_min - pad + 0.5, val)
                x2, y2 = to_pdf_coords(x_max + pad - 0.5, val)
                drawing.add(Line(x1, y1, x2, y2, strokeColor=colors.HexColor("#94A3B8"), strokeWidth=0.5, strokeDashArray=[2, 4]))
                
                # Bubbles
                for bx, by in [(x1 - 10, y1), (x2 + 10, y2)]:
                    drawing.add(Circle(bx, by, 7, fillColor=colors.HexColor("#FFFFFF"), strokeColor=colors.HexColor("#94A3B8"), strokeWidth=0.5))
                    drawing.add(String(bx, by - 2.5, label, textAnchor="middle", fontSize=6, fontName="Helvetica", fillColor=colors.HexColor("#475569")))
                    
    # Draw Columns Geometries and Dynamic Centered Notations
    for c in matched_columns:
        cx, cy = c['x'], c['y']
        w, d = c['width'], c['depth']
        shape = c['shape']
        angle = c['angle']
        notation = c.get('group_notation', 'N/A')
        
        # Dynamic Group Color Matching
        color_hex = get_pdf_notation_color(notation, matched_columns)
        color = colors.HexColor(color_hex)
        
        # Translate to RGB with 25% alpha
        h_c = color_hex.lstrip('#')
        rgb = tuple(int(h_c[i:i+2], 16)/255.0 for i in (0, 2, 4))
        fill_color = colors.Color(rgb[0], rgb[1], rgb[2], alpha=0.25)
        
        px, py = to_pdf_coords(cx, cy)
        pw = (w / 1000.0) * scale
        pd = (d / 1000.0) * scale
        
        if shape == "Circular":
            r = pw / 2.0
            drawing.add(Circle(px, py, r, fillColor=fill_color, strokeColor=color, strokeWidth=1.0))
        else:
            # Draw rectangular columns under rotation using Group
            g = Group()
            g.translate(px, py)
            g.rotate(angle + 90)  # Corrected orientation phase shift
            g.add(Rect(-pw/2.0, -pd/2.0, pw, pd, fillColor=fill_color, strokeColor=color, strokeWidth=1.0))
            drawing.add(g)
            
        # Dynamic Anti-Overlap Label offset margins
        if shape == "Circular":
            y_extent = (w / 1000.0) / 2.0
        else:
            alpha = math.radians(angle + 90)
            hw = (w / 1000.0) / 2.0
            hd = (d / 1000.0) / 2.0
            y_extent = abs(hw * math.sin(alpha)) + abs(hd * math.cos(alpha))
            
        cy_text = cy - y_extent - 0.55  # 55cm Margin
        px_text, py_text = to_pdf_coords(cx, cy_text)
        
        if shape == "Circular":
            dim_text = f"D{w/10.0:.0f}"
        else:
            dim_text = f"{w/10.0:.0f}X{d/10.0:.0f}"
            
        # Add top line (Notation) and bottom line (Dimensions)
        drawing.add(String(px, py_text, notation, textAnchor="middle", fontSize=9.0, fontName="Helvetica-Bold", fillColor=color))
        drawing.add(String(px, py_text - 10, dim_text, textAnchor="middle", fontSize=8.0, fontName="Helvetica", fillColor=color))
        
    # Build Active Schedule Groups Summary table (Right Side)
    groups = {}
    for c in matched_columns:
        notation = c.get('group_notation', '').strip()
        if not notation or notation in ('N/A', 'Exceeded', 'Default', '-'):
            continue
        if notation not in groups:
            groups[notation] = []
        groups[notation].append(c)
        
    summary_rows = [[
        Paragraph("<b>Group</b>", cell_bold_style),
        Paragraph("<b>CAD Name</b>", cell_bold_style),
        Paragraph("<b>Size</b>", cell_bold_style),
        Paragraph("<b>Rebar Details</b>", cell_bold_style),
        Paragraph("<b>Qty</b>", cell_bold_style),
    ]]
    
    sorted_notations = sorted(groups.keys(), key=lambda n: [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', n)])
    
    for notation in sorted_notations:
        cols = groups[notation]
        cad_name = cols[0].get('suggested_id', 'N/A')
        size_str = f"{cols[0]['width']:.0f}x{cols[0]['depth']:.0f}"
        callout = cols[0]['rebar_callout']
        qty = len(cols)
        
        color_hex = get_pdf_notation_color(notation, matched_columns)
        color = colors.HexColor(color_hex)
        
        row_style = ParagraphStyle(
            'PDFRowNotStyle', parent=cell_style, fontName='Helvetica-Bold', textColor=color
        )
        
        summary_rows.append([
            Paragraph(notation, row_style),
            Paragraph(cad_name, row_style),
            Paragraph(size_str, row_style),
            Paragraph(callout, row_style),
            Paragraph(str(qty), cell_style),
        ])
        
    # Width of summary: 362pt (exactly fits the right column of parent layout)
    summary_table = Table(summary_rows, colWidths=[45, 85, 55, 147, 30])
    t_sum_styles = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
    ]
    for i in range(1, len(summary_rows)):
        if i % 2 == 0:
            t_sum_styles.append(('BACKGROUND', (0,i), (-1,i), colors.HexColor('#F8FAFC')))
    summary_table.setStyle(TableStyle(t_sum_styles))
    
    # Parent layout table side-by-side: Drawing on Left (720pt) and Table on Right (342pt) + gap
    plan_summary_layout = Table([[drawing, summary_table]], colWidths=[720, 362])
    plan_summary_layout.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    story_parts.append(plan_summary_layout)
    story_parts.append(PageBreak())

    # ==================== PAGE 3: COLUMN SCHEDULE ====================
    story_parts.append(Paragraph("Standard Column Rebar Schedule (AutoCAD Library)", h1_style))
    story_parts.append(Spacer(1, 10))
    
    # 1. Identify conforming columns
    conforming_groups = {}
    for c in matched_columns:
        notation = c.get('group_notation', '').strip()
        # Conforming notations are C1, C2, C3, etc.
        if notation and notation.startswith('C') and notation[1:].isdigit():
            if notation not in conforming_groups:
                conforming_groups[notation] = c
                
    # Sort them by their notation number naturally (C1, C2, ..., C10, C11...)
    def get_notation_num(n):
        try:
            return int(n[1:])
        except:
            return 9999
    sorted_notations = sorted(conforming_groups.keys(), key=get_notation_num)
    
    if not sorted_notations:
        story_parts.append(Paragraph("No conforming column groups designed.", body_style))
    else:
        # Group them into sets of 5 columns
        chunk_size = 5
        chunks = [sorted_notations[i:i+chunk_size] for i in range(0, len(sorted_notations), chunk_size)]
        
        # Option B: a table with a label column on the left (so 6 columns total)
        # Column widths: 1 label column (130 pt) + 5 data columns (190 pt each) -> total 1080 pt
        col_w = [130] + [190] * 5
        
        # Define styles for the column schedule table cells
        lbl_style = ParagraphStyle(
            'ScheduleLabel', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor('#0F172A'), alignment=0
        )
        not_val_style = ParagraphStyle(
            'ScheduleNotation', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.HexColor('#1E293B'), alignment=1
        )
        cad_val_style = ParagraphStyle(
            'ScheduleCAD', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor('#3B82F6'), alignment=1
        )
        t_val_style = ParagraphStyle(
            'SchedulePlaceholder', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=13, textColor=colors.HexColor('#475569'), alignment=0
        )
        
        for chunk_idx, chunk in enumerate(chunks):
            row_images = [Paragraph("<b>Section</b>", lbl_style)]
            row_marks = [Paragraph("<b>Column Mark</b>", lbl_style)]
            row_cad_names = [Paragraph("<b>Suggested CAD</b>", lbl_style)]
            row_t1 = [Paragraph("<b>T1 (Ties Support)</b>", lbl_style)]
            row_t2 = [Paragraph("<b>T2 (Ties Span)</b>", lbl_style)]
            row_h1 = [Paragraph("<b>H1 (Confinement Ht)</b>", lbl_style)]
            
            for i in range(chunk_size):
                if i < len(chunk):
                    not_lbl = chunk[i]
                    col_data = conforming_groups[not_lbl]
                    cad_id = col_data['suggested_id']
                    
                    img_flowable = get_column_image(cad_id, max_w=170.0, max_h=130.0)
                    if img_flowable:
                        row_images.append(img_flowable)
                    else:
                        row_images.append(Paragraph("<font color='#EF4444'>No Image</font>", t_val_style))
                        
                    row_marks.append(Paragraph(not_lbl, not_val_style))
                    row_cad_names.append(Paragraph(cad_id, cad_val_style))
                    row_t1.append(Paragraph("T1", t_val_style))
                    row_t2.append(Paragraph("T2", t_val_style))
                    row_h1.append(Paragraph("H1", t_val_style))
                else:
                    row_images.append("")
                    row_marks.append("")
                    row_cad_names.append("")
                    row_t1.append("")
                    row_t2.append("")
                    row_h1.append("")
                    
            table_data = [
                row_images,
                row_marks,
                row_cad_names,
                row_t1,
                row_t2,
                row_h1
            ]
            
            schedule_table = Table(table_data, colWidths=col_w)
            schedule_table.setStyle(TableStyle([
                ('BOX', (0,0), (-1,-1), 1.5, colors.HexColor('#0F172A')),
                ('INNERGRID', (0,0), (-1,-1), 0.75, colors.HexColor('#CBD5E1')),
                ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#F8FAFC')),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('TOPPADDING', (0,0), (-1,-1), 8),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                ('LEFTPADDING', (0,0), (-1,-1), 8),
                ('RIGHTPADDING', (0,0), (-1,-1), 8),
            ]))
            
            story_parts.append(KeepTogether([schedule_table, Spacer(1, 20)]))
            
    story_parts.append(PageBreak())

    # ==================== SUMMARY SECTION ====================
    story_parts.append(Paragraph("Structural Optimization & Audit Executive Summary", h1_style))
    story_parts.append(Spacer(1, 5))
    story_parts.append(Paragraph(
        "This report reconciles the required reinforcement percentages computed by CSI ETABS concrete design with the standard column detailed options available inside the AutoCAD drawing schedule. "
        "The suggested columns represent the most cost-effective and steel-economical conforming choices, checking dimensions in both orientation angles. Columns marked with <b>REINFORCEMENT EXCEEDED</b> require either cross-section size expansions or custom detailed rebar schedules, as their required reinforcement exceeds the drawing limits.",
        body_style
    ))
    story_parts.append(Spacer(1, 15))

    # Key Performance Indicators Table (A3 size)
    kpi_data = [
        [
            Paragraph("<font color='#FFFFFF'><b>Total Columns</b></font>", cell_bold_style),
            Paragraph("<font color='#FFFFFF'><b>Conforming</b></font>", cell_bold_style),
            Paragraph("<font color='#FFFFFF'><b>Exceeded</b></font>", cell_bold_style),
            Paragraph("<font color='#FFFFFF'><b>Average Efficiency</b></font>", cell_bold_style),
        ],
        [
            Paragraph(f"<b>{total_cols}</b>", body_style),
            Paragraph(f"<font color='#10B981'><b>{conforming}</b></font>", body_style),
            Paragraph(f"<font color='#EF4444'><b>{exceeded}</b></font>" if exceeded else "0", body_style),
            Paragraph(f"<b>{avg_efficiency:.1f}%</b>", body_style),
        ]
    ]
    kpi_table = Table(kpi_data, colWidths=[270, 271, 271, 270])
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E293B')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0,0), (-1,-1), 12),
        ('BOTTOMPADDING', (0,0), (-1,-1), 12),
    ]))
    story_parts.append(kpi_table)
    story_parts.append(Spacer(1, 20))

    # ==================== MAIN AUDIT TABLE ====================
    story_parts.append(Paragraph("Column Mapping & Detail Selection Schedule", h1_style))
    story_parts.append(Spacer(1, 5))

    # Headers
    headers = [
        Paragraph("<b>Notation</b>", cell_bold_style),
        Paragraph("<b>Story Range</b>", cell_bold_style),
        Paragraph("<b>Column Label</b>", cell_bold_style),
        Paragraph("<b>Grid</b>", cell_bold_style),
        Paragraph("<b>ETABS Size</b>", cell_bold_style),
        Paragraph("<b>Req %</b>", cell_bold_style),
        Paragraph("<b>CAD Name</b>", cell_bold_style),
        Paragraph("<b>CAD %</b>", cell_bold_style),
        Paragraph("<b>Rebar Details</b>", cell_bold_style),
        Paragraph("<b>Eff %</b>", cell_bold_style),
    ]
    
    table_rows = [headers]
    
    sorted_cols = sorted(matched_columns, key=report_natural_sort_key)
    
    for idx, col in enumerate(sorted_cols):
        eff = col['efficiency']
        if col['status'] == 'REINFORCEMENT EXCEEDED':
            eff_color = '#EF4444' # Red
            cad_name = "<font color='#EF4444'><b>EXCEEDED</b></font>"
            pct_provided = f"{col['cad_pct']:.2f}%"
            callout = "Custom detail req."
        elif col['status'] == 'SIZE NOT FOUND':
            eff_color = '#F59E0B' # Orange
            cad_name = "<font color='#F59E0B'><b>SIZE NOT FOUND</b></font>"
            pct_provided = "N/A"
            callout = "Section size mismatch"
        else:
            pct_provided = f"{col['cad_pct']:.2f}%"
            cad_name = f"<b>{col['suggested_id']}</b>"
            callout = col.get('rebar_callout', 'N/A')
            if eff >= 85.0:
                  eff_color = '#10B981' # Green (Highly efficient)
            elif eff >= 50.0:
                  eff_color = '#3B82F6' # Blue (Satisfactory)
            else:
                  eff_color = '#F59E0B' # Orange (Over-designed)
 
        row = [
            Paragraph(col.get('group_notation', 'N/A'), cell_style),
            Paragraph(col['story_name'], cell_style),
            Paragraph(col['frame_name'], cell_style),
            Paragraph(col['grid_label'], cell_style),
            Paragraph(f"{col['width']:.0f}x{col['depth']:.0f}", cell_style),
            Paragraph(f"{col['rebar_pct']:.2f}%", cell_style),
            Paragraph(cad_name, cell_style),
            Paragraph(pct_provided, cell_style),
            Paragraph(callout, cell_style),
            Paragraph(f"<font color='{eff_color}'><b>{eff:.1f}%</b></font>", cell_style),
        ]
        table_rows.append(row)
 
    # Column widths summing to exactly 1082 (A3 Landscape printable width)
    col_widths = [75, 110, 100, 90, 110, 75, 140, 75, 237, 70]
    
    audit_table = Table(table_rows, colWidths=col_widths, repeatRows=1)
    
    t_styles = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
    ]
    
    for i in range(1, len(table_rows)):
        if i % 2 == 0:
            t_styles.append(('BACKGROUND', (0,i), (-1,i), colors.HexColor('#F8FAFC')))
            
    audit_table.setStyle(TableStyle(t_styles))
    story_parts.append(audit_table)

    # 3. Build document
    doc.build(story_parts, canvasmaker=NumberedCanvas)
    print("PDF report generated successfully.")

def report_natural_sort_key(col_item):
    notation = col_item.get('group_notation', '')
    if not notation or notation in ('N/A', 'Exceeded'):
        label = col_item.get('grid_label', '')
        label_sorted = [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', label)]
        return [1, label_sorted]
    notation_sorted = [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', notation)]
    return [0, notation_sorted]

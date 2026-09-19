import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import sys
import threading
import json
import subprocess
from datetime import datetime

# Import local custom modules
import etabs_connector
import matching_engine
import report_generator

# Set up CustomTkinter appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class ColumnDetailerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Configure window
        self.title("ETABS-to-CAD Column Detailer Pro")
        self.geometry("1200, 750")
        self.minsize(1000, 650)
        
        # Variables
        self.sap_model = None
        self.model_filename = "None"
        self.model_filepath = ""
        self.etabs_instances = []
        self.raw_etabs_data = None
        self.matched_columns = []
        
        # Matching engine
        self.matcher = matching_engine.MatchingEngine()
        
        # Build UI layout
        self.create_layout()
        self.log_message("System initialized. Connect to an active ETABS model to begin.")

    def create_layout(self):
        # Configure grid grid layout 1x2 (Sidebar, Main)
        self.grid_columnconfigure(0, weight=0, minsize=280)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # ==================== SIDEBAR ====================
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.sidebar.grid_rowconfigure(6, weight=1) # Spacer
        
        # App Title & Branding
        self.logo_label = ctk.CTkLabel(
            self.sidebar, 
            text="ETABS-to-CAD\nColumn Detailer Pro", 
            font=ctk.CTkFont(family="Inter", size=18, weight="bold")
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=(25, 20))
        
        # Separation line
        self.sep = ctk.CTkFrame(self.sidebar, height=2, fg_color="#334155")
        self.sep.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 20))
        
        # 1. Connection Dashboard Card
        self.conn_frame = ctk.CTkFrame(self.sidebar, fg_color="#1E293B")
        self.conn_frame.grid(row=2, column=0, padx=20, pady=(0, 15), sticky="ew")
        
        self.conn_title = ctk.CTkLabel(
            self.conn_frame, 
            text="ETABS CONNECTION STATUS", 
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            text_color="#64748B"
        )
        self.conn_title.grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")
        
        self.status_badge = ctk.CTkLabel(
            self.conn_frame,
            text="🔴 DISCONNECTED",
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            text_color="#EF4444"
        )
        self.status_badge.grid(row=1, column=0, padx=15, pady=(0, 5), sticky="w")
        
        self.model_lbl = ctk.CTkLabel(
            self.conn_frame,
            text="Model: None",
            font=ctk.CTkFont(family="Inter", size=10),
            text_color="#94A3B8",
            wraplength=230,
            justify="left"
        )
        self.model_lbl.grid(row=2, column=0, padx=15, pady=(0, 10), sticky="w")
        
        self.connect_btn = ctk.CTkButton(
            self.sidebar,
            text="🔌 Connect to ETABS",
            font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
            height=35,
            command=self.connect_etabs_threaded
        )
        self.connect_btn.grid(row=3, column=0, padx=20, pady=(0, 15), sticky="ew")
        
        # 2. Config Card
        self.config_frame = ctk.CTkFrame(self.sidebar, fg_color="#1E293B")
        self.config_frame.grid(row=4, column=0, padx=20, pady=0, sticky="ew")
        
        self.config_title = ctk.CTkLabel(
            self.config_frame,
            text="AUDIT & MATCH SETTINGS",
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            text_color="#64748B"
        )
        self.config_title.grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")
        
        # Safety buffer slider
        self.buffer_lbl = ctk.CTkLabel(
            self.config_frame,
            text="Longitudinal Rebar Buffer: 0.00%",
            font=ctk.CTkFont(family="Inter", size=11),
            text_color="#94A3B8"
        )
        self.buffer_lbl.grid(row=1, column=0, padx=15, pady=(5, 0), sticky="w")
        
        self.buffer_slider = ctk.CTkSlider(
            self.config_frame,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            command=self.on_buffer_slide
        )
        self.buffer_slider.set(0.0)
        self.buffer_slider.grid(row=2, column=0, padx=15, pady=(2, 12), sticky="ew")
        
        # Action Buttons
        self.run_btn = ctk.CTkButton(
            self.sidebar,
            text="⚡ Run Concrete Design Audit",
            font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
            height=38,
            fg_color="#3B82F6",
            hover_color="#2563EB",
            state="disabled",
            command=self.run_audit_threaded
        )
        self.run_btn.grid(row=5, column=0, padx=20, pady=(20, 10), sticky="ew")
        
        # Report Export Buttons
        self.report_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.report_frame.grid(row=7, column=0, padx=20, pady=(0, 25), sticky="ew")
        self.report_frame.columnconfigure(0, weight=1)
        self.report_frame.columnconfigure(1, weight=1)
        
        self.pdf_btn = ctk.CTkButton(
            self.report_frame,
            text="📄 Save PDF",
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            height=32,
            fg_color="#10B981",
            hover_color="#059669",
            state="disabled",
            command=self.export_report
        )
        self.pdf_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        
        self.folder_btn = ctk.CTkButton(
            self.report_frame,
            text="📁 Open Folder",
            font=ctk.CTkFont(family="Inter", size=11),
            height=32,
            fg_color="#475569",
            hover_color="#334155",
            state="disabled",
            command=self.open_output_folder
        )
        self.folder_btn.grid(row=0, column=1, padx=(5, 0), sticky="ew")

        # ==================== MAIN CONTENT ====================
        self.main_content = ctk.CTkFrame(self, fg_color="transparent")
        self.main_content.grid(row=0, column=1, sticky="nsew", padx=25, pady=25)
        self.main_content.grid_rowconfigure(1, weight=1)
        self.main_content.grid_columnconfigure(0, weight=3) # Main results tree takes more weight
        self.main_content.grid_columnconfigure(1, weight=1, minsize=290) # Grouping side panel
        
        # --- ROW 0: KPI DASHBOARD CONTAINER ---
        self.kpi_container = ctk.CTkFrame(self.main_content, fg_color="transparent")
        self.kpi_container.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 20))
        for col_idx in range(4):
            self.kpi_container.grid_columnconfigure(col_idx, weight=1, minsize=160)
            
        # KPI 1: Total Columns
        self.kpi1 = self.create_kpi_card(self.kpi_container, 0, "TOTAL COLUMNS", "0", "Columns extracted")
        # KPI 2: Conforming Suggestions
        self.kpi2 = self.create_kpi_card(self.kpi_container, 1, "CONFORMING MATCHES", "0", "0.0% satisfied", text_color="#10B981")
        # KPI 3: Exceeded Reinforcement
        self.kpi3 = self.create_kpi_card(self.kpi_container, 2, "EXCEEDED LIMITS", "0", "Requires redesign", text_color="#EF4444")
        # KPI 4: Match Efficiency Index
        self.kpi4 = self.create_kpi_card(self.kpi_container, 3, "AVG MATCH EFFICIENCY", "0.0%", "Economical design index", text_color="#3B82F6")
        
        # --- ROW 1: RESULTS GRID WRAPPER ---
        self.grid_frame = ctk.CTkFrame(self.main_content, fg_color="#1E293B", corner_radius=8)
        self.grid_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 15))
        self.grid_frame.grid_rowconfigure(1, weight=1)
        self.grid_frame.grid_columnconfigure(0, weight=1)
        
        # Grid Header / Filter Bar
        self.filter_bar = ctk.CTkFrame(self.grid_frame, fg_color="transparent")
        self.filter_bar.grid(row=0, column=0, sticky="ew", padx=15, pady=10)
        self.filter_bar.grid_columnconfigure(3, weight=1) # Spacer
        
        self.filter_title = ctk.CTkLabel(
            self.filter_bar, 
            text="🔍 Filter Results:  ", 
            font=ctk.CTkFont(family="Inter", size=11, weight="bold")
        )
        self.filter_title.grid(row=0, column=0, sticky="w")
        
        self.story_filter = ctk.CTkComboBox(
            self.filter_bar,
            values=["All Stories"],
            width=140,
            font=ctk.CTkFont(family="Inter", size=11),
            command=self.apply_filters
        )
        self.story_filter.grid(row=0, column=1, padx=(0, 10), sticky="w")
        
        self.status_filter = ctk.CTkComboBox(
            self.filter_bar,
            values=["All Statuses", "SUCCESS (Conforming)", "REINFORCEMENT EXCEEDED", "SIZE NOT FOUND"],
            width=200,
            font=ctk.CTkFont(family="Inter", size=11),
            command=self.apply_filters
        )
        self.status_filter.grid(row=0, column=2, sticky="w")
        
        # Color Legend (aligned to the right side of the filter bar)
        self.legend_frame = ctk.CTkFrame(self.filter_bar, fg_color="transparent")
        self.legend_frame.grid(row=0, column=4, sticky="e", padx=(10, 0))
        
        self.lbl_leg = ctk.CTkLabel(
            self.legend_frame, 
            text="Efficiency Legend: ", 
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            text_color="#64748B"
        )
        self.lbl_leg.grid(row=0, column=0, padx=(0, 5))
        
        self.leg_high = ctk.CTkLabel(
            self.legend_frame,
            text="🟢 High (≥85%)",
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            text_color="#10B981"
        )
        self.leg_high.grid(row=0, column=1, padx=5)
        
        self.leg_sat = ctk.CTkLabel(
            self.legend_frame,
            text="🔵 Good (50-85%)",
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            text_color="#3B82F6"
        )
        self.leg_sat.grid(row=0, column=2, padx=5)
        
        self.leg_low = ctk.CTkLabel(
            self.legend_frame,
            text="🟡 Low (<50%)",
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            text_color="#F59E0B"
        )
        self.leg_low.grid(row=0, column=3, padx=5)
        
        self.leg_exceeded = ctk.CTkLabel(
            self.legend_frame,
            text="🔴 Exceeded",
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            text_color="#EF4444"
        )
        self.leg_exceeded.grid(row=0, column=4, padx=(5, 0))
        
        # Treeview styled table
        self.setup_treeview()
        
        # ==================== GROUPING PANEL (RIGHT SIDE) ====================
        self.group_panel = ctk.CTkFrame(self.main_content, fg_color="#1E293B", corner_radius=8)
        self.group_panel.grid(row=1, column=1, sticky="nsew", padx=(15, 0), pady=(0, 15))
        self.group_panel.grid_columnconfigure(0, weight=1)
        self.group_panel.grid_rowconfigure(7, weight=1) # The summary tree frame stretches
        
        # Panel Title
        self.group_title = ctk.CTkLabel(
            self.group_panel,
            text="GROUPING & NOTATIONS",
            font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
            text_color="#3B82F6"
        )
        self.group_title.grid(row=0, column=0, padx=15, pady=(15, 10), sticky="w")
        
        # Auto-Grouping Control Card
        self.auto_group_card = ctk.CTkFrame(self.group_panel, fg_color="#0F172A", corner_radius=6)
        self.auto_group_card.grid(row=1, column=0, padx=15, pady=(0, 10), sticky="ew")
        self.auto_group_card.grid_columnconfigure(0, weight=1)
        
        self.ag_lbl = ctk.CTkLabel(
            self.auto_group_card,
            text="Auto-Merge Tolerance: 0.30%",
            font=ctk.CTkFont(family="Inter", size=11),
            text_color="#94A3B8"
        )
        self.ag_lbl.grid(row=0, column=0, padx=12, pady=(8, 2), sticky="w")
        
        self.ag_slider = ctk.CTkSlider(
            self.auto_group_card,
            from_=0.05,
            to=1.00,
            number_of_steps=19, # 0.05 increments
            command=self.on_ag_slide
        )
        self.ag_slider.set(0.30)
        self.ag_slider.grid(row=1, column=0, padx=12, pady=(2, 8), sticky="ew")
        
        self.ag_btn = ctk.CTkButton(
            self.group_panel,
            text="🔄 Auto-Group Columns",
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            height=30,
            fg_color="#475569",
            hover_color="#334155",
            state="disabled",
            command=self.run_auto_grouping
        )
        self.ag_btn.grid(row=2, column=0, padx=15, pady=(0, 12), sticky="ew")
        
        # Separation line
        self.sep_group = ctk.CTkFrame(self.group_panel, height=1, fg_color="#334155")
        self.sep_group.grid(row=3, column=0, sticky="ew", padx=15, pady=(0, 12))
        
        # Manual Override Card
        self.manual_card = ctk.CTkFrame(self.group_panel, fg_color="#0F172A", corner_radius=6)
        self.manual_card.grid(row=4, column=0, padx=15, pady=(0, 10), sticky="ew")
        self.manual_card.grid_columnconfigure(0, weight=1)
        
        self.man_title = ctk.CTkLabel(
            self.manual_card,
            text="MANUAL NOTATION OVERRIDE",
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            text_color="#64748B"
        )
        self.man_title.grid(row=0, column=0, padx=12, pady=(8, 4), sticky="w")
        
        self.sel_lbl = ctk.CTkLabel(
            self.manual_card,
            text="Selected: None",
            font=ctk.CTkFont(family="Inter", size=10),
            text_color="#94A3B8",
            wraplength=250,
            justify="left"
        )
        self.sel_lbl.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="w")
        
        self.entry_frame = ctk.CTkFrame(self.manual_card, fg_color="transparent")
        self.entry_frame.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="ew")
        self.entry_frame.grid_columnconfigure(0, weight=1)
        
        self.notation_entry = ctk.CTkEntry(
            self.entry_frame,
            placeholder_text="e.g. C1",
            font=ctk.CTkFont(family="Inter", size=11),
            height=28
        )
        self.notation_entry.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        
        self.apply_notation_btn = ctk.CTkButton(
            self.entry_frame,
            text="Apply",
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            width=60,
            height=28,
            command=self.apply_manual_notation
        )
        self.apply_notation_btn.grid(row=0, column=1, sticky="e")
        
        # Separation line 2
        self.sep_group2 = ctk.CTkFrame(self.group_panel, height=1, fg_color="#334155")
        self.sep_group2.grid(row=5, column=0, sticky="ew", padx=15, pady=(0, 10))
        
        # Group Summary Section
        self.summary_title = ctk.CTkLabel(
            self.group_panel,
            text="ACTIVE GROUPS SUMMARY",
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            text_color="#64748B"
        )
        self.summary_title.grid(row=6, column=0, padx=15, pady=(0, 5), sticky="w")
        
        # Treeview to display group summary
        self.setup_summary_treeview()
        
        # --- ROW 2: REAL-TIME CONSOLE LOGGER ---
        self.log_frame = ctk.CTkFrame(self.main_content, height=80, fg_color="#0F172A")
        self.log_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.log_frame.grid_propagate(False)
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(0, weight=1)
        
        self.log_text = tk.Text(
            self.log_frame,
            fg="#94A3B8",
            bg="#0F172A",
            font=("Consolas", 9),
            bd=0,
            highlightthickness=0
        )
        self.log_text.grid(row=0, column=0, padx=10, pady=5, sticky="nsew")
        self.log_text.config(state="disabled")

    def create_kpi_card(self, parent, col_idx, title, val, footer, text_color=None):
        card = ctk.CTkFrame(parent, fg_color="#1E293B", corner_radius=6)
        card.grid(row=0, column=col_idx, padx=5 if col_idx > 0 else (0, 5), sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        
        lbl_title = ctk.CTkLabel(
            card, 
            text=title, 
            font=ctk.CTkFont(family="Inter", size=9, weight="bold"),
            text_color="#64748B"
        )
        lbl_title.grid(row=0, column=0, padx=12, pady=(10, 2), sticky="w")
        
        lbl_val = ctk.CTkLabel(
            card, 
            text=val, 
            font=ctk.CTkFont(family="Inter", size=22, weight="bold"),
            text_color=text_color if text_color else "#FFFFFF"
        )
        lbl_val.grid(row=1, column=0, padx=12, pady=(0, 2), sticky="w")
        
        lbl_foot = ctk.CTkLabel(
            card, 
            text=footer, 
            font=ctk.CTkFont(family="Inter", size=9),
            text_color="#475569"
        )
        lbl_foot.grid(row=2, column=0, padx=12, pady=(0, 10), sticky="w")
        
        return {"val": lbl_val, "foot": lbl_foot}

    def setup_treeview(self):
        style = ttk.Style()
        style.theme_use("default")
        
        # Dark grid theme styling
        style.configure(
            "Treeview",
            background="#1E293B",
            foreground="#E2E8F0",
            fieldbackground="#1E293B",
            rowheight=25,
            font=("Inter", 9),
            borderwidth=0
        )
        style.map(
            "Treeview",
            background=[("selected", "#334155")],
            foreground=[("selected", "#FFFFFF")]
        )
        style.configure(
            "Treeview.Heading",
            background="#0F172A",
            foreground="#94A3B8",
            font=("Inter", 9, "bold"),
            borderwidth=0
        )
        
        self.tree_scroll = ttk.Scrollbar(self.grid_frame)
        self.tree_scroll.grid(row=1, column=1, sticky="ns", pady=5)
        
        cols = ("notation", "story", "frame", "grid", "size", "req_pct", "cad_name", "cad_pct", "callout", "efficiency")
        self.tree = ttk.Treeview(
            self.grid_frame,
            columns=cols,
            show="headings",
            yscrollcommand=self.tree_scroll.set
        )
        self.tree.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.tree_scroll.config(command=self.tree.yview)
        
        # Bind selection event
        self.tree.bind("<<TreeviewSelect>>", self.on_main_tree_select)
        
        # Headings setup
        headings = {
            "notation": "Notation",
            "story": "Story Range",
            "frame": "Column Label",
            "grid": "Grid",
            "size": "ETABS Size",
            "req_pct": "Req Rebar %",
            "cad_name": "Suggested CAD",
            "cad_pct": "Provided %",
            "callout": "Rebar Details",
            "efficiency": "Efficiency"
        }
        widths = {
            "notation": 65,
            "story": 110,
            "frame": 95,
            "grid": 75,
            "size": 95,
            "req_pct": 90,
            "cad_name": 120,
            "cad_pct": 85,
            "callout": 160,
            "efficiency": 85
        }
        
        for cid, text in headings.items():
            self.tree.heading(cid, text=text, anchor="w")
            self.tree.column(cid, width=widths[cid], minwidth=40, stretch=True)
            
        # Color tags
        self.tree.tag_configure("high_eff", foreground="#10B981") # Green
        self.tree.tag_configure("sat_eff", foreground="#3B82F6")  # Blue
        self.tree.tag_configure("low_eff", foreground="#F59E0B")  # Orange
        self.tree.tag_configure("exceeded", foreground="#EF4444") # Red

    def log_message(self, msg):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def on_buffer_slide(self, val):
        self.buffer_lbl.configure(text=f"Longitudinal Rebar Buffer: {val:.2f}%")

    def connect_etabs_threaded(self):
        self.connect_btn.configure(state="disabled", text="🔌 Connecting...")
        threading.Thread(target=self.connect_etabs, daemon=True).start()

    def connect_etabs(self):
        try:
            res = etabs_connector.connect_to_etabs(gui_callback=True)
            if isinstance(res, list):
                # Multiple running instances found
                self.etabs_instances = res
                self.show_instance_selection_dialog()
            elif res[0] is not None:
                self.sap_model, self.model_filename, self.model_filepath = res
                self.on_connection_success()
            else:
                self.on_connection_failed("No active ETABS models found running.")
        except Exception as e:
            self.on_connection_failed(str(e))

    def show_instance_selection_dialog(self):
        # UI dialog to select PID
        dialog = ctk.CTkToplevel(self)
        dialog.title("Select ETABS Instance")
        dialog.geometry("450x300")
        dialog.transient(self)
        dialog.grab_set()
        
        lbl = ctk.CTkLabel(
            dialog,
            text="Multiple active ETABS models detected.\nPlease select the target process to map:",
            font=ctk.CTkFont(family="Inter", size=12),
            justify="left"
        )
        lbl.pack(padx=20, pady=(20, 10), fill="x")
        
        instance_names = [f"PID {inst['pid']} - {inst['filename']}" for inst in self.etabs_instances]
        
        combo = ctk.CTkComboBox(dialog, values=instance_names, width=380)
        combo.pack(padx=20, pady=10)
        combo.set(instance_names[0])
        
        def on_select():
            selected_idx = combo.get()
            # Resolve index
            for idx, name in enumerate(instance_names):
                if name == selected_idx:
                    inst = self.etabs_instances[idx]
                    self.sap_model = inst['sap_model']
                    self.model_filename = inst['filename']
                    self.model_filepath = inst['filepath']
                    self.on_connection_success()
                    break
            dialog.destroy()
            
        btn = ctk.CTkButton(dialog, text="Connect Selected Instance", command=on_select)
        btn.pack(padx=20, pady=25)

    def on_connection_success(self):
        self.status_badge.configure(text="🟢 CONNECTED", text_color="#10B981")
        self.model_lbl.configure(text=f"Model: {self.model_filename}")
        self.connect_btn.configure(state="normal", text="🔌 Refresh Connection")
        self.run_btn.configure(state="normal")
        self.log_message(f"Successfully connected to active ETABS model: '{self.model_filename}'")

    def on_connection_failed(self, err_msg):
        self.status_badge.configure(text="🔴 DISCONNECTED", text_color="#EF4444")
        self.model_lbl.configure(text="Model: None")
        self.connect_btn.configure(state="normal", text="🔌 Connect to ETABS")
        self.run_btn.configure(state="disabled")
        self.log_message(f"Connection failed: {err_msg}")
        messagebox.showerror("ETABS Connection Error", f"Failed to connect to active ETABS instance:\n{err_msg}")

    def run_audit_threaded(self):
        self.run_btn.configure(state="disabled", text="⚡ Auditing Design...")
        self.pdf_btn.configure(state="disabled")
        self.folder_btn.configure(state="disabled")
        self.tree.delete(*self.tree.get_children())
        
        threading.Thread(target=self.run_audit, daemon=True).start()

    def run_audit(self):
        try:
            self.log_message("Scanning ETABS structural database tables...")
            
            def status_cb(msg):
                self.log_message(msg)
                
            res = etabs_connector.extract_column_data(self.sap_model, status_callback=status_cb)
            if not res:
                self.run_failed("Could not retrieve concrete column design results. Check if concrete design has been run.")
                return
                
            self.raw_etabs_data = res
            self.log_message("Data successfully extracted from ETABS. Running matching engine...")
            
            # Map columns
            buffer_val = self.buffer_slider.get()
            self.matched_columns = self.matcher.match_all_columns(self.raw_etabs_data, buffer_pct=buffer_val)
            
            # Auto-group columns with current tolerance
            tolerance = self.ag_slider.get()
            self.matched_columns = self.matcher.auto_group_columns(self.matched_columns, tolerance=tolerance)
            
            # Update GUI results
            self.after(0, self.update_results_grid)
        except Exception as e:
            self.run_failed(str(e))
 
    def run_failed(self, err_msg):
        self.run_btn.configure(state="normal", text="⚡ Run Concrete Design Audit")
        self.log_message(f"Audit analysis crashed: {err_msg}")
        messagebox.showerror("Structural Audit Failed", f"An error occurred during database analysis:\n{err_msg}")
 
    def update_results_grid(self):
        # 1. Update KPI Dashboard Cards
        total_cols = len(self.matched_columns)
        conforming = sum(1 for c in self.matched_columns if c['status'] == 'SUCCESS')
        exceeded = sum(1 for c in self.matched_columns if c['status'] == 'REINFORCEMENT EXCEEDED')
        
        valid_effs = [c['efficiency'] for c in self.matched_columns if c['status'] == 'SUCCESS']
        avg_eff = sum(valid_effs) / len(valid_effs) if valid_effs else 0.0
        
        self.kpi1['val'].configure(text=str(total_cols))
        self.kpi2['val'].configure(text=str(conforming))
        self.kpi2['foot'].configure(text=f"{conforming / total_cols * 100.0:.1f}% satisfied" if total_cols > 0 else "0.0% satisfied")
        self.kpi3['val'].configure(text=str(exceeded))
        self.kpi3['foot'].configure(text="Requires concrete redesign" if exceeded > 0 else "All frames safe")
        self.kpi4['val'].configure(text=f"{avg_eff:.1f}%")
        
        # 2. Populate Filters
        stories = sorted(list(set([c['story_name'] for c in self.matched_columns])))
        self.story_filter.configure(values=["All Stories"] + stories)
        self.story_filter.set("All Stories")
        self.status_filter.set("All Statuses")
        
        # 3. Load Treeview Table
        self.populate_tree(self.matched_columns)
        
        # 4. Load/Enable Grouping Panel
        self.update_group_summary()
        self.ag_btn.configure(state="normal")
        
        self.run_btn.configure(state="normal", text="⚡ Run Concrete Design Audit")
        self.pdf_btn.configure(state="normal")
        self.folder_btn.configure(state="normal")
        self.log_message(f"Audit completed: {total_cols} columns analyzed. {conforming} conforming suggestions matched.")
 
    def populate_tree(self, columns_list):
        self.tree.delete(*self.tree.get_children())
        
        for col in columns_list:
            eff = col['efficiency']
            
            # Map details
            if col['status'] == 'REINFORCEMENT EXCEEDED':
                cad_name = "EXCEEDED"
                cad_pct = f"{col['cad_pct']:.2f}%"
                rebar_callout = "Custom detail req."
                tag = "exceeded"
            elif col['status'] == 'SIZE NOT FOUND':
                cad_name = "SIZE NOT FOUND"
                cad_pct = "N/A"
                rebar_callout = "Aspect ratio mismatch"
                tag = "low_eff"
            else:
                cad_name = col['suggested_id']
                cad_pct = f"{col['cad_pct']:.2f}%"
                rebar_callout = col.get('rebar_callout', 'N/A')
                if eff >= 85.0:
                    tag = "high_eff"
                elif eff >= 50.0:
                    tag = "sat_eff"
                else:
                    tag = "low_eff"
                    
            self.tree.insert(
                "",
                tk.END,
                values=(
                    col.get('group_notation', 'N/A'),
                    col['story_name'],
                    col['frame_name'],
                    col['grid_label'],
                    f"{col['width']:.0f} x {col['depth']:.0f}",
                    f"{col['rebar_pct']:.2f}%",
                    cad_name,
                    cad_pct,
                    rebar_callout,
                    f"{eff:.1f}%"
                ),
                tags=(tag,)
            )

    def apply_filters(self, _=None):
        if not self.matched_columns:
            return
            
        story = self.story_filter.get()
        status_sel = self.status_filter.get()
        
        filtered = []
        for col in self.matched_columns:
            # Filter story
            story_match = (story == "All Stories" or col['story_name'] == story)
            
            # Filter status
            status_match = True
            if status_sel == "SUCCESS (Conforming)":
                status_match = (col['status'] == "SUCCESS")
            elif status_sel == "REINFORCEMENT EXCEEDED":
                status_match = (col['status'] == "REINFORCEMENT EXCEEDED")
            elif status_sel == "SIZE NOT FOUND":
                status_match = (col['status'] == "SIZE NOT FOUND")
                
            if story_match and status_match:
                filtered.append(col)
                
        self.populate_tree(filtered)
        self.log_message(f"Filter applied: showing {len(filtered)} / {len(self.matched_columns)} columns.")

    def export_report(self):
        if not self.matched_columns:
            return
            
        # Select output folder
        default_dir = os.path.dirname(self.model_filepath) if self.model_filepath else os.path.expanduser("~/Documents")
        if not os.path.exists(default_dir):
            default_dir = os.path.expanduser("~/Documents")
            
        file_path = filedialog.asksaveasfilename(
            initialdir=default_dir,
            initialfile="Column_Reconciliation_Report.pdf",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")]
        )
        
        if not file_path:
            return
            
        try:
            buffer_val = self.buffer_slider.get()
            report_generator.generate_pdf_report(
                self.matched_columns,
                self.model_filename,
                buffer_val,
                file_path
            )
            self.log_message(f"Structural report successfully saved to: {file_path}")
            
            # Prompt to open
            ans = messagebox.askyesno(
                "Report Saved Successfully",
                "Your structural auditing PDF report has been generated!\nWould you like to open it now?"
            )
            if ans:
                os.startfile(file_path)
        except Exception as e:
            self.log_message(f"Error compiling PDF report: {e}")
            messagebox.showerror("Report Compilation Error", f"Could not compile PDF report:\n{e}")

    def open_output_folder(self):
        model_dir = os.path.dirname(self.model_filepath) if self.model_filepath else None
        if model_dir and os.path.exists(model_dir):
            os.startfile(model_dir)
            self.log_message(f"Opened active directory folder: '{model_dir}'")
        else:
            doc_dir = os.path.expanduser("~/Documents")
            os.startfile(doc_dir)
            self.log_message(f"Opened default folder: '{doc_dir}'")

    def on_ag_slide(self, val):
        self.ag_lbl.configure(text=f"Auto-Merge Tolerance: {val:.2f}%")
        
    def run_auto_grouping(self):
        if not self.matched_columns:
            return
            
        tolerance = self.ag_slider.get()
        self.log_message(f"Re-running auto-grouping with tolerance {tolerance:.2f}%...")
        
        self.matched_columns = self.matcher.auto_group_columns(self.matched_columns, tolerance=tolerance)
        self.populate_tree(self.matched_columns)
        self.update_group_summary()
        self.log_message("Auto-grouping completed successfully.")
        
    def apply_manual_notation(self):
        if not self.matched_columns:
            messagebox.showerror("Error", "No active audit data to group.")
            return
            
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Warning", "Please select one or more columns from the table to modify.")
            return
            
        new_notation = self.notation_entry.get().strip()
        if not new_notation:
            messagebox.showwarning("Warning", "Please enter a valid notation label (e.g. C1).")
            return
            
        # Resolve target frame names
        selected_frames = []
        for item in selected_items:
            values = self.tree.item(item, "values")
            selected_frames.append(values[2]) # frame_name
            
        # Backup matched columns in case of size consistency validation failure
        backup_cols = json.loads(json.dumps(self.matched_columns))
        
        # Apply the new notation
        for c in self.matched_columns:
            if c['frame_name'] in selected_frames:
                c['group_notation'] = new_notation
                
        # Recalculate group suggestions and validate same-size constraint
        errors = self.matcher.recalculate_groups(self.matched_columns)
        if errors:
            # Revert and display error
            self.matched_columns = backup_cols
            err_msg = "\n".join(errors)
            self.log_message(f"Manual grouping failed: {err_msg}")
            messagebox.showerror("Grouping Size Validation Failed", f"Could not apply notation:\n{err_msg}")
            return
            
        # Refresh UI treeview and summary
        self.populate_tree(self.matched_columns)
        self.update_group_summary()
        self.log_message(f"Manually assigned notation '{new_notation}' to columns: {', '.join(selected_frames)}")
        
    def update_group_summary(self):
        self.summary_tree.delete(*self.summary_tree.get_children())
        if not self.matched_columns:
            return
            
        # Group columns by notation
        groups = {}
        for c in self.matched_columns:
            notation = c.get('group_notation', '').strip()
            if not notation or notation in ('N/A', 'Exceeded', 'Default', '-'):
                continue
            if notation not in groups:
                groups[notation] = []
            groups[notation].append(c)
            
        # Populate summary treeview sorted naturally
        for notation in sorted(groups.keys(), key=self.matcher.natural_sort_key):
            cols = groups[notation]
            size_str = f"{cols[0]['width']:.0f}x{cols[0]['depth']:.0f}"
            callout = cols[0]['rebar_callout']
            qty = len(cols)
            
            self.summary_tree.insert(
                "",
                tk.END,
                values=(notation, size_str, callout, qty)
            )
            
    def setup_summary_treeview(self):
        self.summary_frame = ctk.CTkFrame(self.group_panel, fg_color="transparent")
        self.summary_frame.grid(row=7, column=0, padx=15, pady=(0, 15), sticky="nsew")
        self.summary_frame.grid_rowconfigure(0, weight=1)
        self.summary_frame.grid_columnconfigure(0, weight=1)
        
        self.summary_scroll = ttk.Scrollbar(self.summary_frame)
        self.summary_scroll.grid(row=0, column=1, sticky="ns")
        
        self.summary_tree = ttk.Treeview(
            self.summary_frame,
            columns=("notation", "size", "callout", "count"),
            show="headings",
            yscrollcommand=self.summary_scroll.set,
            height=6
        )
        self.summary_tree.grid(row=0, column=0, sticky="nsew")
        self.summary_scroll.config(command=self.summary_tree.yview)
        
        self.summary_tree.heading("notation", text="Group", anchor="w")
        self.summary_tree.heading("size", text="Size", anchor="w")
        self.summary_tree.heading("callout", text="Rebar", anchor="w")
        self.summary_tree.heading("count", text="Qty", anchor="w")
        
        self.summary_tree.column("notation", width=50, minwidth=30, stretch=True)
        self.summary_tree.column("size", width=70, minwidth=50, stretch=True)
        self.summary_tree.column("callout", width=90, minwidth=60, stretch=True)
        self.summary_tree.column("count", width=40, minwidth=30, stretch=True)
        
    def on_main_tree_select(self, event=None):
        selected_items = self.tree.selection()
        if not selected_items:
            self.sel_lbl.configure(text="Selected: None")
            self.notation_entry.delete(0, tk.END)
            return
            
        selected_frames = []
        selected_notations = set()
        
        for item in selected_items:
            values = self.tree.item(item, "values")
            # Values index: 0 is notation, 1 is story, 2 is frame_name
            notation = values[0]
            frame_name = values[2]
            selected_frames.append(frame_name)
            selected_notations.add(notation)
            
        frames_str = ", ".join(selected_frames[:3])
        if len(selected_frames) > 3:
            frames_str += f" (+{len(selected_frames) - 3} more)"
            
        self.sel_lbl.configure(text=f"Selected: {frames_str}")
        self.notation_entry.delete(0, tk.END)
        if len(selected_notations) == 1:
            self.notation_entry.insert(0, list(selected_notations)[0])

if __name__ == "__main__":
    app = ColumnDetailerApp()
    app.mainloop()

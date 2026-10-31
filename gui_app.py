import os
import sys
# Set COM initialization flags to Multi-Threaded Apartment (MTA) model before importing any COM/pywin32 packages.
# This prevents cross-apartment violations and threading crashes when accessing ETABS COM object from background threads.
sys.coinit_flags = 2

import json
import math
import re
import tempfile
import threading
from datetime import datetime

from PyQt6.QtCore import QUrl, pyqtSignal, pyqtSlot, QObject, Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QGridLayout, QLabel, QSlider, QPushButton, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QComboBox, QLineEdit, QTextEdit,
    QFileDialog, QMessageBox, QSplitter, QDialog, QScrollArea, QStackedWidget,
    QAbstractItemView
)
from PyQt6.QtGui import QFont, QColor, QPalette, QBrush
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebChannel import QWebChannel

# Import local custom modules
import etabs_connector
import matching_engine
import report_generator

# Custom QWebEnginePage to capture and route JavaScript console messages thread-safely
class DiagnosticWebEnginePage(QWebEnginePage):
    def __init__(self, log_signal, parent=None):
        super().__init__(parent)
        self.log_signal = log_signal

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        try:
            src = os.path.basename(sourceID) if sourceID else "inline"
        except Exception:
            src = "inline"
        log_msg = f"JS Console [{src}:{lineNumber}]: {message}"
        self.log_signal.emit(log_msg)

# QWebChannel bridge object
class PyQtConnector(QObject):
    columnSelected = pyqtSignal(str)
    maximizeToggled = pyqtSignal()
    multipleColumnsSelected = pyqtSignal(str)

    @pyqtSlot(str)
    def select_column(self, frame_name):
        """Called from JavaScript when a column is clicked on the Plotly plan."""
        self.columnSelected.emit(frame_name)

    @pyqtSlot()
    def toggle_maximize(self):
        """Called from JavaScript when the custom maximize button in Plotly ModeBar is clicked."""
        self.maximizeToggled.emit()

    @pyqtSlot(str)
    def select_multiple_columns(self, frame_names_str):
        """Called from JavaScript when multiple columns are selected on the Plotly plan."""
        self.multipleColumnsSelected.emit(frame_names_str)

# Multiple instance selection dialog
class ETABSSelectionDialog(QDialog):
    def __init__(self, instances, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select ETABS Instance")
        self.setMinimumWidth(450)
        self.setMinimumHeight(200)
        self.instances = instances
        self.selected_instance = None
        
        self.setStyleSheet("""
            QDialog {
                background-color: #1E293B;
                border: 1px solid #334155;
            }
            QLabel {
                color: #E2E8F0;
                font-family: "Inter", sans-serif;
                font-size: 12px;
            }
            QComboBox {
                background-color: #0F172A;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 8px;
                color: #E2E8F0;
                font-family: "Inter", sans-serif;
            }
            QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                font-family: "Inter", sans-serif;
                font-weight: bold;
                border-radius: 6px;
                padding: 10px;
                border: none;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
        """)
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        lbl = QLabel("Multiple active ETABS models detected.\nPlease select the target process to connect:")
        layout.addWidget(lbl)
        
        self.combo = QComboBox()
        for idx, inst in enumerate(instances):
            self.combo.addItem(f"PID {inst['pid']} - {os.path.basename(inst['filename'])}", idx)
        layout.addWidget(self.combo)
        
        btn = QPushButton("🔌 Connect Selected Instance")
        btn.clicked.connect(self.on_accept)
        layout.addWidget(btn)
        
        self.setLayout(layout)
        
    def on_accept(self):
        idx = self.combo.currentData()
        self.selected_instance = self.instances[idx]
        self.accept()

    def get_selected_instance(self):
        return self.selected_instance

# Main Application Window
class ColumnDetailerApp(QMainWindow):
    # Signals for thread-safe UI updates from background threads
    logSignal = pyqtSignal(str)
    connectionSuccessSignal = pyqtSignal()
    connectionFailedSignal = pyqtSignal(str)
    connectionMultipleSignal = pyqtSignal(list)
    auditCompletedSignal = pyqtSignal()
    auditFailedSignal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        
        # Configure window
        self.setWindowTitle("ETABS-to-CAD Column Detailer Pro")
        self.resize(1300, 850)
        self.setMinimumSize(1100, 700)
        
        # State variables
        self.sap_model = None
        self.model_filename = "None"
        self.model_filepath = ""
        self.etabs_instances = []
        self.raw_etabs_data = None
        self.matched_columns = []
        self.selected_frame_name = None
        self.plan_maximized = False
        
        # Execution and manual mode state tracking
        self.execution_mode = "AUTO"
        self.temp_execution_mode = "AUTO"
        self.notations_generated = False
        self.selected_frame_names = []
        self._updating_selection = False

        # Buffer actually used by the last completed run (None until first run)
        self.applied_buffer_pct = None
        self._pending_buffer_pct = None
        
        # Color palette for unique group color-coding
        self.NOTATION_COLORS = [
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
        
        # Distinct color palettes for merged column groups (dark background, bright accent)
        self.MERGE_GROUP_COLORS = [
            {"bg": "#0D3A31", "accent": "#34D399"},  # Emerald Green
            {"bg": "#2E1065", "accent": "#C084FC"},  # Violet Purple
            {"bg": "#451A03", "accent": "#FBBF24"},  # Amber Gold
            {"bg": "#083344", "accent": "#38BDF8"},  # Cyan Blue
            {"bg": "#4C0519", "accent": "#F472B6"},  # Rose Pink
            {"bg": "#1E1B4B", "accent": "#818CF8"},  # Indigo Blue
            {"bg": "#431407", "accent": "#FB923C"},  # Terracotta Coral
            {"bg": "#1A2E05", "accent": "#A3E635"},  # Lime Green
            {"bg": "#311B92", "accent": "#D8B4FE"},  # Deep Lavender
            {"bg": "#064E3B", "accent": "#2DD4BF"},  # Turquoise Mint
            {"bg": "#3A2E00", "accent": "#FDE047"},  # Warm Yellow
            {"bg": "#3F0713", "accent": "#FDA4AF"},  # Crimson Ruby
        ]
        
        # Tracking manual overrides
        self.manual_overrides_log = []
        
        # Matching engine
        self.matcher = matching_engine.MatchingEngine()
        
        # Setup QtWebChannel
        self.connector = PyQtConnector()
        self.connector.columnSelected.connect(self.on_plotly_column_selected)
        self.connector.maximizeToggled.connect(self.toggle_maximize_plan)
        self.connector.multipleColumnsSelected.connect(self.on_plotly_multiple_columns_selected)
        self.web_channel = QWebChannel()
        self.web_channel.registerObject("pyconnector", self.connector)
        
        # Connect signals for thread-safe GUI updates
        self.logSignal.connect(self.log_message)
        self.connectionSuccessSignal.connect(self.on_connection_success)
        self.connectionFailedSignal.connect(self.on_connection_failed)
        self.connectionMultipleSignal.connect(self.on_connection_multiple)
        self.auditCompletedSignal.connect(self.on_audit_completed)
        self.auditFailedSignal.connect(self.on_audit_failed)
        
        # Set up QSS stylesheet
        self.setup_stylesheet()
        
        # Build UI layout
        self.create_layout()
        self.log_message("System initialized. Connect to an active ETABS model to begin.")
        
    def setup_stylesheet(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0F172A;
            }
            QWidget {
                font-family: "Inter", "Segoe UI", sans-serif;
                color: #E2E8F0;
            }
            QFrame#sidebar {
                background-color: #1E293B;
                border-right: 1px solid #334155;
            }
            QFrame#card {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QFrame#panel-inner {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QLabel#logo-lbl {
                font-size: 16px;
                font-weight: bold;
                color: #FFFFFF;
            }
            QLabel#badge-disconnected {
                color: #EF4444;
                font-weight: bold;
                font-size: 11px;
            }
            QLabel#badge-connected {
                color: #10B981;
                font-weight: bold;
                font-size: 11px;
            }
            QLabel#card-title {
                font-size: 10px;
                font-weight: bold;
                color: #64748B;
            }
            QLabel#kpi-title {
                font-size: 9px;
                font-weight: bold;
                color: #64748B;
            }
            QLabel#kpi-value {
                font-size: 22px;
                font-weight: bold;
                color: #FFFFFF;
            }
            QLabel#kpi-footer {
                font-size: 9px;
                color: #475569;
            }
            QPushButton {
                background-color: #334155;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                color: #E2E8F0;
            }
            QPushButton:hover {
                background-color: #475569;
            }
            QPushButton:disabled {
                background-color: #1E293B;
                border-color: #334155;
                color: #475569;
            }
            QPushButton#primary-btn {
                background-color: #3B82F6;
                border: 1px solid #2563EB;
            }
            QPushButton#primary-btn:hover {
                background-color: #2563EB;
            }
            QPushButton#secondary-btn {
                background-color: #1E293B;
                border: 1px solid #334155;
                padding: 6px 12px;
                font-size: 11px;
            }
            QPushButton#secondary-btn:hover {
                background-color: #334155;
            }
            QPushButton#success-btn {
                background-color: #10B981;
                border: 1px solid #059669;
                font-size: 10px;
                padding: 8px 4px;
            }
            QPushButton#success-btn:hover {
                background-color: #059669;
            }
            QPushButton#folder-btn {
                font-size: 10px;
                padding: 8px 4px;
            }
            QTabWidget::pane {
                border: 1px solid #334155;
                background-color: #1E293B;
                border-radius: 8px;
            }
            QTabBar::tab {
                background-color: #0F172A;
                border: 1px solid #334155;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                color: #94A3B8;
            }
            QTabBar::tab:selected {
                background-color: #1E293B;
                color: #3B82F6;
                border-bottom: 2px solid #3B82F6;
            }
            QTabBar::tab:hover:!selected {
                background-color: #1E293B;
                color: #F8FAFC;
            }
            QTableWidget {
                background-color: #1E293B;
                gridline-color: #334155;
                border: none;
                alternate-background-color: #162032;
                color: #E2E8F0;
                font-size: 13px;
            }
            QHeaderView::section {
                background-color: #0F172A;
                color: #94A3B8;
                padding: 6px;
                border: none;
                font-weight: bold;
                font-size: 13px;
            }
            QComboBox, QLineEdit {
                background-color: #0F172A;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 6px;
                color: #E2E8F0;
            }
            QComboBox:hover, QLineEdit:hover {
                border-color: #475569;
            }
            QTextEdit#console {
                background-color: #0F172A;
                color: #94A3B8;
                border: 1px solid #334155;
                border-radius: 6px;
                font-family: "Consolas", monospace;
                font-size: 11px;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #334155;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #3B82F6;
                width: 12px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #2563EB;
            }
            QMessageBox {
                background-color: #1E293B;
            }
            QMessageBox QLabel {
                color: #E2E8F0;
                font-size: 12px;
            }
            QMessageBox QPushButton {
                min-width: 70px;
            }
        """)

    def create_layout(self):
        # Create central stacked widget to transition between Startup Screen and Workspace
        self.central_stacked = QStackedWidget()
        self.setCentralWidget(self.central_stacked)
        
        # Build Startup Screen
        self.startup_widget = self.create_startup_screen()
        self.central_stacked.addWidget(self.startup_widget)
        
        # Build Main Workspace
        self.workspace_widget = self.create_main_workspace()
        self.central_stacked.addWidget(self.workspace_widget)
        
        # Show Startup Screen first
        self.central_stacked.setCurrentWidget(self.startup_widget)

    def create_startup_screen(self):
        startup = QWidget()
        startup.setObjectName("startup-screen")
        startup.setStyleSheet("""
            QWidget#startup-screen {
                background-color: #0F172A;
            }
            QFrame#glass-card {
                background-color: rgba(30, 41, 59, 0.75);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 16px;
            }
            QLabel#startup-title {
                font-family: "Outfit", "Inter", sans-serif;
                font-size: 24px;
                font-weight: 800;
                color: #FFFFFF;
                letter-spacing: 0.5px;
            }
            QLabel#startup-subtitle {
                font-family: "Inter", sans-serif;
                font-size: 13px;
                color: #94A3B8;
            }
            QFrame#status-panel {
                background-color: rgba(15, 23, 42, 0.6);
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 8px;
            }
            QLabel#status-title {
                font-size: 11px;
                font-weight: bold;
                color: #64748B;
            }
            QPushButton#mode-card-btn {
                background-color: rgba(30, 41, 59, 0.5);
                border: 2px solid #334155;
                border-radius: 12px;
                padding: 12px;
                text-align: center;
                color: #E2E8F0;
            }
            QPushButton#mode-card-btn:hover {
                background-color: rgba(59, 130, 246, 0.1);
                border-color: #3B82F6;
            }
            QPushButton#mode-card-btn:checked {
                background-color: rgba(59, 130, 246, 0.15);
                border-color: #3B82F6;
            }
            QLabel#mode-title {
                font-size: 15px;
                font-weight: bold;
                color: #FFFFFF;
                background: transparent;
            }
            QLabel#mode-desc {
                font-size: 11px;
                color: #94A3B8;
                background: transparent;
            }
            QPushButton#launch-btn {
                background-color: #3B82F6;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: bold;
                padding: 12px;
                border-radius: 8px;
                border: none;
            }
            QPushButton#launch-btn:hover {
                background-color: #2563EB;
            }
            QPushButton#launch-btn:disabled {
                background-color: #1E293B;
                color: #475569;
                border: 1px solid #334155;
            }
        """)
        
        layout = QVBoxLayout(startup)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        card = QFrame()
        card.setObjectName("glass-card")
        card.setFixedWidth(520)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(35, 35, 35, 35)
        card_layout.setSpacing(20)
        
        # Logo Icon + Title
        title_layout = QVBoxLayout()
        title_layout.setSpacing(6)
        title_lbl = QLabel("🏢 ETABS-to-CAD Column Detailer Pro")
        title_lbl.setObjectName("startup-title")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_lbl = QLabel("Professional concrete column auditing & CAD schedule generator")
        sub_lbl.setObjectName("startup-subtitle")
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(title_lbl)
        title_layout.addWidget(sub_lbl)
        card_layout.addLayout(title_layout)
        
        # Connection status dashboard inside card
        status_panel = QFrame()
        status_panel.setObjectName("status-panel")
        spanel_layout = QHBoxLayout(status_panel)
        spanel_layout.setContentsMargins(15, 12, 15, 12)
        
        stat_text_layout = QVBoxLayout()
        stat_lbl_title = QLabel("ETABS CONNECTION STATUS")
        stat_lbl_title.setObjectName("status-title")
        self.startup_status_badge = QLabel("🔴 DISCONNECTED")
        self.startup_status_badge.setObjectName("badge-disconnected")
        self.startup_model_lbl = QLabel("Model: None")
        self.startup_model_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        stat_text_layout.addWidget(stat_lbl_title)
        stat_text_layout.addWidget(self.startup_status_badge)
        stat_text_layout.addWidget(self.startup_model_lbl)
        spanel_layout.addLayout(stat_text_layout)
        
        spanel_layout.addStretch()
        
        self.startup_connect_btn = QPushButton("🔌 Connect to ETABS")
        self.startup_connect_btn.setObjectName("primary-btn")
        self.startup_connect_btn.clicked.connect(self.connect_etabs_threaded)
        spanel_layout.addWidget(self.startup_connect_btn)
        
        card_layout.addWidget(status_panel)
        
        # Mode Selection Header
        mode_hdr = QLabel("SELECT EXECUTION MODE")
        mode_hdr.setObjectName("status-title")
        card_layout.addWidget(mode_hdr)
        
        # Mode buttons (Custom styled selector cards)
        self.mode_group_layout = QHBoxLayout()
        self.mode_group_layout.setSpacing(15)
        
        # AUTO mode selector
        self.auto_mode_btn = QPushButton()
        self.auto_mode_btn.setObjectName("mode-card-btn")
        self.auto_mode_btn.setCheckable(True)
        self.auto_mode_btn.setChecked(True) # default
        self.auto_mode_btn.clicked.connect(self.select_auto_mode)
        auto_btn_layout = QVBoxLayout(self.auto_mode_btn)
        auto_btn_layout.setContentsMargins(0, 0, 0, 0)
        auto_btn_layout.setSpacing(4)
        m1_lbl = QLabel("⚡ AUTO Mode")
        m1_lbl.setObjectName("mode-title")
        m1_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        auto_btn_layout.addWidget(m1_lbl)
        self.mode_group_layout.addWidget(self.auto_mode_btn)
        
        # MANUAL mode selector
        self.manual_mode_btn = QPushButton()
        self.manual_mode_btn.setObjectName("mode-card-btn")
        self.manual_mode_btn.setCheckable(True)
        self.manual_mode_btn.clicked.connect(self.select_manual_mode)
        manual_btn_layout = QVBoxLayout(self.manual_mode_btn)
        manual_btn_layout.setContentsMargins(0, 0, 0, 0)
        manual_btn_layout.setSpacing(4)
        m2_lbl = QLabel("🛠️ MANUAL Mode")
        m2_lbl.setObjectName("mode-title")
        m2_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        manual_btn_layout.addWidget(m2_lbl)
        self.mode_group_layout.addWidget(self.manual_mode_btn)
        
        card_layout.addLayout(self.mode_group_layout)
        
        # Launch button
        self.launch_btn = QPushButton("🚀 Launch Workspace")
        self.launch_btn.setObjectName("launch-btn")
        self.launch_btn.setEnabled(False) # Enabled when connected
        self.launch_btn.clicked.connect(self.launch_workspace)
        card_layout.addWidget(self.launch_btn)
        
        layout.addWidget(card)
        return startup

    def select_auto_mode(self):
        self.auto_mode_btn.setChecked(True)
        self.manual_mode_btn.setChecked(False)
        self.temp_execution_mode = "AUTO"

    def select_manual_mode(self):
        self.auto_mode_btn.setChecked(False)
        self.manual_mode_btn.setChecked(True)
        self.temp_execution_mode = "MANUAL"

    def launch_workspace(self):
        self.execution_mode = getattr(self, 'temp_execution_mode', 'AUTO')
        self.undo_stack = []
        if hasattr(self, 'undo_btn'):
            self.undo_btn.setEnabled(False)
            
        # Configure layout/controls based on selected execution mode
        if self.execution_mode == "AUTO":
            # Show original UI controls
            self.ag_btn.setVisible(True)
            self.ag_lbl.setVisible(True)
            self.ag_slider.setVisible(True)
            
            # Hide manual actions
            self.manual_actions_widget.setVisible(False)
            
            # Show "Notation" column in table
            self.results_table.setColumnHidden(0, False)
            
            # Set default sort
            self.sort_filter.blockSignals(True)
            self.sort_filter.setCurrentIndex(0) # Default (Story & Grid)
            self.sort_filter.blockSignals(False)
            
            self.log_message("Launched workspace in AUTO mode.")
        else:
            # MANUAL mode configuration
            # Hide auto grouping settings
            self.ag_btn.setVisible(False)
            self.ag_lbl.setVisible(False)
            self.ag_slider.setVisible(False)
            
            # Show manual actions
            self.manual_actions_widget.setVisible(True)
            
            # Hide "Notation" column until notations are generated
            self.results_table.setColumnHidden(0, True)
            
            # Sort initially by Req Rebar % (Ascending)
            self.sort_filter.blockSignals(True)
            self.sort_filter.setCurrentIndex(1)
            self.sort_filter.blockSignals(False)
            
            self.notations_generated = False
            self.selected_frame_names = []
            
            # Hide notations groups filters on plan layout initially
            self.notation_lbl.setVisible(False)
            self.notation_buttons_container.setVisible(False)
            
            # Hide override cards in MANUAL mode until notations are generated
            self.override_card.setVisible(False)
            self.groups_card.setVisible(False)
            
            self.log_message("Launched workspace in MANUAL mode.")
            
        # Hide connection dashboard in the workspace sidebar since it is already connected
        self.connect_btn.setVisible(False)
        if hasattr(self, 'conn_card'):
            self.conn_card.setVisible(False)
            
        # Switch central stacked widget to workspace
        self.central_stacked.setCurrentWidget(self.workspace_widget)

    def go_back_to_startup(self):
        self.central_stacked.setCurrentWidget(self.startup_widget)
        self.log_message("Returned to Startup Screen.")

    def create_main_workspace(self):
        workspace = QWidget()
        main_layout = QHBoxLayout(workspace)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # ==================== SIDEBAR ====================
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(290)
        sidebar_outer_layout = QVBoxLayout(self.sidebar)
        sidebar_outer_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_outer_layout.setSpacing(0)
        
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        sidebar_inner = QFrame()
        sidebar_inner.setStyleSheet("background-color: transparent;")
        sidebar_layout = QVBoxLayout(sidebar_inner)
        sidebar_layout.setContentsMargins(15, 20, 15, 20)
        sidebar_layout.setSpacing(15)
        
        # Logo branding
        logo_lbl = QLabel("ETABS-to-CAD\nColumn Detailer Pro")
        logo_lbl.setObjectName("logo-lbl")
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(logo_lbl)
        
        # Sep line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #334155;")
        sidebar_layout.addWidget(sep)
        
        # KPIs Section Header
        kpis_title = QLabel("PROJECT SUMMARY KPIs")
        kpis_title.setObjectName("card-title")
        kpis_title.setStyleSheet("color: #3B82F6; font-size: 10px; font-weight: bold; margin-top: 5px;")
        sidebar_layout.addWidget(kpis_title)
        
        self.kpi1 = self.create_kpi_card("TOTAL COLUMNS", "0", "Columns extracted")
        self.kpi2 = self.create_kpi_card("CONFORMING SUGGESTIONS", "0", "0.0% satisfied", text_color="#10B981")
        self.kpi3 = self.create_kpi_card("EXCEEDED LIMITS", "0", "All frames safe", text_color="#EF4444")
        self.kpi4 = self.create_kpi_card("AVG EFFICIENCY", "0.0%", "Economical design index", text_color="#3B82F6")
        self.kpi5 = self.create_kpi_card("ACTIVE GROUPS", "0", "Notation groups", text_color="#EC4899")
        
        sidebar_layout.addWidget(self.kpi1["widget"])
        sidebar_layout.addWidget(self.kpi2["widget"])
        sidebar_layout.addWidget(self.kpi3["widget"])
        sidebar_layout.addWidget(self.kpi4["widget"])
        sidebar_layout.addWidget(self.kpi5["widget"])
        
        # Sep line 2
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #334155;")
        sidebar_layout.addWidget(sep2)
        
        # 1. Connection Dashboard Card
        self.conn_card = QFrame()
        self.conn_card.setObjectName("card")
        conn_layout = QVBoxLayout(self.conn_card)
        conn_layout.setContentsMargins(15, 12, 15, 12)
        conn_layout.setSpacing(8)
        
        conn_title = QLabel("ETABS CONNECTION STATUS")
        conn_title.setObjectName("card-title")
        conn_layout.addWidget(conn_title)
        
        self.status_badge = QLabel("🔴 DISCONNECTED")
        self.status_badge.setObjectName("badge-disconnected")
        conn_layout.addWidget(self.status_badge)
        
        self.model_lbl = QLabel("Model: None")
        self.model_lbl.setWordWrap(True)
        self.model_lbl.setStyleSheet("color: #94A3B8; font-size: 10px;")
        conn_layout.addWidget(self.model_lbl)
        
        sidebar_layout.addWidget(self.conn_card)
        
        self.connect_btn = QPushButton("🔌 Connect to ETABS")
        self.connect_btn.clicked.connect(self.connect_etabs_threaded)
        sidebar_layout.addWidget(self.connect_btn)
        
        # 2. Safety settings Card
        config_card = QFrame()
        config_card.setObjectName("card")
        config_layout = QVBoxLayout(config_card)
        config_layout.setContentsMargins(15, 12, 15, 12)
        config_layout.setSpacing(10)
        
        config_title = QLabel("AUDIT & MATCH SETTINGS")
        config_title.setObjectName("card-title")
        config_layout.addWidget(config_title)
        
        # Buffer slider
        self.buffer_lbl = QLabel("Longitudinal Rebar Buffer: 0.00%")
        self.buffer_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        self.buffer_lbl.setWordWrap(True)
        config_layout.addWidget(self.buffer_lbl)

        self.buffer_slider = QSlider(Qt.Orientation.Horizontal)
        self.buffer_slider.setRange(0, 50)
        self.buffer_slider.setValue(0)
        self.buffer_slider.valueChanged.connect(self.on_buffer_slide)
        config_layout.addWidget(self.buffer_slider)
        
        # Auto-merge tolerance slider
        self.ag_lbl = QLabel("Auto-Merge Tolerance: 0.15%")
        self.ag_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        config_layout.addWidget(self.ag_lbl)
        
        self.ag_slider = QSlider(Qt.Orientation.Horizontal)
        self.ag_slider.setRange(5, 100)
        self.ag_slider.setValue(15)
        self.ag_slider.valueChanged.connect(self.on_ag_slide)
        config_layout.addWidget(self.ag_slider)
        
        sidebar_layout.addWidget(config_card)
        
        # Run Concrete Audit button
        self.run_btn = QPushButton("⚡ Run")
        self.run_btn.setObjectName("primary-btn")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self.run_audit_threaded)
        sidebar_layout.addWidget(self.run_btn)
        
        # Auto-group button
        self.ag_btn = QPushButton("🔄 Auto-Group Columns")
        self.ag_btn.setEnabled(False)
        self.ag_btn.clicked.connect(self.run_auto_grouping)
        sidebar_layout.addWidget(self.ag_btn)
        
        sidebar_layout.addStretch()
        
        # Report & Folder buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        
        self.pdf_btn = QPushButton("📄 Save PDF")
        self.pdf_btn.setObjectName("success-btn")
        self.pdf_btn.setEnabled(False)
        self.pdf_btn.clicked.connect(self.export_report)
        btn_row.addWidget(self.pdf_btn)
        
        self.folder_btn = QPushButton("📁 Folder")
        self.folder_btn.setObjectName("folder-btn")
        self.folder_btn.setEnabled(False)
        self.folder_btn.clicked.connect(self.open_output_folder)
        btn_row.addWidget(self.folder_btn)
        
        sidebar_layout.addLayout(btn_row)
        
        sidebar_scroll.setWidget(sidebar_inner)
        sidebar_outer_layout.addWidget(sidebar_scroll)
        
        main_layout.addWidget(self.sidebar)
        
        # ==================== MAIN WORKSPACE ====================
        workspace_container = QWidget()
        workspace_layout = QVBoxLayout(workspace_container)
        workspace_layout.setContentsMargins(20, 20, 20, 20)
        workspace_layout.setSpacing(15)
        self.workspace_layout = workspace_layout
        
        # Workspace Header with Sidebar toggle (wrapped inside self.header_frame)
        self.header_frame = QFrame()
        self.header_frame.setStyleSheet("background: transparent; border: none;")
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        self.toggle_sidebar_btn = QPushButton("◀ Hide Sidebar")
        self.toggle_sidebar_btn.setObjectName("secondary-btn")
        self.toggle_sidebar_btn.clicked.connect(self.toggle_sidebar)
        header_layout.addWidget(self.toggle_sidebar_btn)
        
        self.back_to_startup_btn = QPushButton("🏠 Back to Startup")
        self.back_to_startup_btn.setObjectName("secondary-btn")
        self.back_to_startup_btn.clicked.connect(self.go_back_to_startup)
        header_layout.addWidget(self.back_to_startup_btn)
        
        header_layout.addStretch()
        workspace_layout.addWidget(self.header_frame)
        
        # 1b. Unified Global Filter Bar (Notations & Sizes)
        self.filter_buttons_frame = QFrame()
        self.filter_buttons_frame.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QLabel {
                font-size: 11px;
                font-weight: bold;
                color: #94A3B8;
                border: none;
                background: transparent;
            }
        """)
        filter_buttons_layout = QVBoxLayout(self.filter_buttons_frame)
        filter_buttons_layout.setContentsMargins(15, 10, 15, 10)
        filter_buttons_layout.setSpacing(8)
        
        self.notation_filter_row = QHBoxLayout()
        self.notation_filter_row.setSpacing(6)
        self.notation_lbl = QLabel("🏷️ Notation Groups:")
        self.notation_filter_row.addWidget(self.notation_lbl)
        
        self.notation_buttons_container = QWidget()
        self.notation_buttons_container.setStyleSheet("border: none; background: transparent;")
        self.notation_buttons_layout = QHBoxLayout(self.notation_buttons_container)
        self.notation_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.notation_buttons_layout.setSpacing(6)
        self.notation_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.notation_filter_row.addWidget(self.notation_buttons_container)
        self.notation_filter_row.addStretch()
        filter_buttons_layout.addLayout(self.notation_filter_row)
        
        self.size_filter_row = QHBoxLayout()
        self.size_filter_row.setSpacing(6)
        self.size_lbl = QLabel("📐 ETABS Sizes:")
        self.size_filter_row.addWidget(self.size_lbl)
        
        self.size_buttons_container = QWidget()
        self.size_buttons_container.setStyleSheet("border: none; background: transparent;")
        self.size_buttons_layout = QHBoxLayout(self.size_buttons_container)
        self.size_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.size_buttons_layout.setSpacing(6)
        self.size_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.size_filter_row.addWidget(self.size_buttons_container)
        self.size_filter_row.addStretch()
        filter_buttons_layout.addLayout(self.size_filter_row)
        
        self.filter_buttons_frame.setVisible(False)
        workspace_layout.addWidget(self.filter_buttons_frame)
        
        # 2. Main tabs container
        self.tabs = QTabWidget()
        
        # Tab 1: Structural Plan Layout (Plotly)
        tab_plan = QWidget()
        tab_plan_layout = QHBoxLayout(tab_plan)
        tab_plan_layout.setContentsMargins(10, 10, 10, 10)
        tab_plan_layout.setSpacing(15)
        self.tab_plan_layout = tab_plan_layout
        
        # QSplitter splits Plotly View and the Right Panel
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # QWebEngineView and Custom Diagnostic Page for Plotly Plan
        self.webview = QWebEngineView()
        self.web_page = DiagnosticWebEnginePage(self.logSignal, self.webview)
        self.webview.setPage(self.web_page)
        self.webview.page().setBackgroundColor(QColor("#0F172A"))
        self.webview.page().setWebChannel(self.web_channel)
        self.webview.setStyleSheet("background-color: #0F172A;")
        
        self.filter_buttons = []
        self.size_filter_buttons = []
        
        # Plan container to keep webview
        self.plan_container = QWidget()
        plan_container_layout = QHBoxLayout(self.plan_container)
        plan_container_layout.setContentsMargins(0, 0, 0, 0)
        plan_container_layout.setSpacing(5)
        plan_container_layout.addWidget(self.webview)
        
        placeholder_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8" />
            <style>
                body {
                    background-color: #0F172A;
                    color: #64748B;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    height: 100vh;
                    margin: 0;
                    text-align: center;
                }
                .container {
                    padding: 20px;
                }
                h3 {
                    color: #94A3B8;
                    margin-bottom: 8px;
                }
                p {
                    margin: 0;
                    font-size: 13px;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h3>No Structural Plan Loaded</h3>
                <p>Please connect to an active ETABS model and run a concrete design audit to visualize the layout.</p>
            </div>
        </body>
        </html>
        """
        self.webview.setHtml(placeholder_html)
        self.splitter.addWidget(self.plan_container)
        
        # Right Side Panel for Overrides, Groups, Log
        self.right_panel = QScrollArea()
        self.right_panel.setWidgetResizable(True)
        self.right_panel.setFixedWidth(360)
        self.right_panel.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        panel_inner = QFrame()
        panel_inner.setObjectName("panel-inner")
        panel_layout = QVBoxLayout(panel_inner)
        panel_layout.setContentsMargins(15, 15, 15, 15)
        panel_layout.setSpacing(15)
        
        # Panel Title & Sleek ModeBar Fullscreen indicator row
        title_row = QHBoxLayout()
        panel_title = QLabel("INTERACTIVE CONTROL & OVERRIDES")
        panel_title.setObjectName("card-title")
        panel_title.setStyleSheet("color: #3B82F6; font-size: 11px;")
        title_row.addWidget(panel_title)
        title_row.addStretch()
        panel_layout.addLayout(title_row)
        
        # A. Selection Card
        self.sel_card = QFrame()
        self.sel_card.setObjectName("card")
        self.sel_card.setStyleSheet("background-color: #0F172A;")
        sel_layout = QVBoxLayout(self.sel_card)
        sel_layout.setSpacing(8)
        
        sel_title = QLabel("SELECTED COLUMN DETAILS")
        sel_title.setObjectName("card-title")
        sel_layout.addWidget(sel_title)
        
        self.sel_frame_lbl = QLabel("Frame: None Selected")
        self.sel_frame_lbl.setStyleSheet("font-weight: bold; color: #FFFFFF;")
        sel_layout.addWidget(self.sel_frame_lbl)
        
        self.sel_size_lbl = QLabel("Size: N/A")
        self.sel_size_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        sel_layout.addWidget(self.sel_size_lbl)
        
        self.sel_angle_lbl = QLabel("Orientation angle: N/A")
        self.sel_angle_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        sel_layout.addWidget(self.sel_angle_lbl)
        
        self.sel_rebar_lbl = QLabel("Required Rebar: N/A")
        self.sel_rebar_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        sel_layout.addWidget(self.sel_rebar_lbl)
        
        self.sel_notation_lbl = QLabel("Current Notation: N/A")
        self.sel_notation_lbl.setStyleSheet("color: #38BDF8; font-weight: bold; font-size: 12px;")
        sel_layout.addWidget(self.sel_notation_lbl)
        
        panel_layout.addWidget(self.sel_card)
        
        # B. Manual Override Card
        self.override_card = QFrame()
        self.override_card.setObjectName("card")
        self.override_card.setStyleSheet("background-color: #0F172A;")
        override_layout = QVBoxLayout(self.override_card)
        override_layout.setSpacing(10)
        
        override_title = QLabel("MANUAL NOTATION OVERRIDE")
        override_title.setObjectName("card-title")
        override_layout.addWidget(override_title)
        
        override_layout.addWidget(QLabel("Select/Enter New Notation:\n(Enforces Same Section Size Guard)"))
        
        self.notation_combo = QComboBox()
        self.notation_combo.setEditable(True)
        self.notation_combo.setPlaceholderText("Select C1, C2 or Type New")
        self.notation_combo.setEnabled(False)
        override_layout.addWidget(self.notation_combo)
        
        self.apply_override_btn = QPushButton("Apply Notation Override")
        self.apply_override_btn.setEnabled(False)
        self.apply_override_btn.clicked.connect(self.apply_manual_override)
        override_layout.addWidget(self.apply_override_btn)
        
        self.resequence_btn = QPushButton("🔢 Resequence Notations")
        self.resequence_btn.setEnabled(False)
        self.resequence_btn.setToolTip("Compact notation gaps (e.g. C9 to C11 becomes C9 to C10)")
        self.resequence_btn.clicked.connect(lambda: self.resequence_notations(prompt_success=True))
        override_layout.addWidget(self.resequence_btn)
        
        panel_layout.addWidget(self.override_card)
        
        # C. Active Groups Summary Card
        self.groups_card = QFrame()
        self.groups_card.setObjectName("card")
        self.groups_card.setStyleSheet("background-color: #0F172A;")
        groups_layout = QVBoxLayout(self.groups_card)
        groups_layout.setSpacing(6)
        
        groups_header = QHBoxLayout()
        groups_title = QLabel("ACTIVE SCHEDULE GROUPS SUMMARY")
        groups_title.setObjectName("card-title")
        groups_header.addWidget(groups_title)
        
        self.groups_max_btn = QPushButton("⛶")
        self.groups_max_btn.setToolTip("Maximize/Restore Table")
        self.groups_max_btn.setFixedSize(20, 20)
        self.groups_max_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #3B82F6;
                font-weight: bold;
                font-size: 12px;
                padding: 0px;
            }
            QPushButton:hover {
                color: #2563EB;
            }
        """)
        self.groups_max_btn.clicked.connect(self.toggle_maximize_groups_summary)
        groups_header.addWidget(self.groups_max_btn)
        groups_layout.addLayout(groups_header)
        
        self.groups_table = QTableWidget()
        self.groups_table.setColumnCount(4)
        self.groups_table.setHorizontalHeaderLabels(["Group", "Size", "Rebar", "Qty"])
        self.groups_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.groups_table.setFixedHeight(120)
        self.groups_table.verticalHeader().setVisible(False)
        groups_layout.addWidget(self.groups_table)
        
        panel_layout.addWidget(self.groups_card)
        
        # D. Manual Override Running Log Card
        self.log_card = QFrame()
        self.log_card.setObjectName("card")
        self.log_card.setStyleSheet("background-color: #0F172A;")
        log_layout = QVBoxLayout(self.log_card)
        log_layout.setSpacing(6)
        
        log_title = QLabel("MANUAL OVERRIDE HISTORY LOG")
        log_title.setObjectName("card-title")
        log_layout.addWidget(log_title)
        
        self.override_log_view = QTextEdit()
        self.override_log_view.setReadOnly(True)
        self.override_log_view.setFixedHeight(120)
        self.override_log_view.setObjectName("console")
        self.override_log_view.setPlaceholderText("No manual overrides registered in this session.")
        log_layout.addWidget(self.override_log_view)
        
        panel_layout.addWidget(self.log_card)
        
        panel_layout.addStretch()
        self.right_panel.setWidget(panel_inner)
        
        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([840, 360])
        
        tab_plan_layout.addWidget(self.splitter)
        self.tabs.addTab(tab_plan, "🗺️ Structural Plan Layout")
        
        # Tab 2: Column Audit Table
        tab_table = QWidget()
        tab_table_layout = QVBoxLayout(tab_table)
        tab_table_layout.setContentsMargins(15, 15, 15, 15)
        tab_table_layout.setSpacing(10)
        
        # Filter row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(15)
        
        filter_row.addWidget(QLabel("🔍 Filter Results:  "))
        
        self.story_filter = QComboBox()
        self.story_filter.addItem("All Stories")
        self.story_filter.currentIndexChanged.connect(self.apply_filters)
        filter_row.addWidget(self.story_filter)
        
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All Statuses", "SUCCESS (Conforming)", "REINFORCEMENT EXCEEDED", "SIZE NOT FOUND"])
        self.status_filter.currentIndexChanged.connect(self.apply_filters)
        filter_row.addWidget(self.status_filter)
        
        # Sort Selector
        filter_row.addWidget(QLabel("   ⇅ Sort By: "))
        self.sort_filter = QComboBox()
        self.sort_filter.addItems([
            "Default (Story & Grid)",
            "Req Rebar % (Ascending)",
            "Req Rebar % (Descending)",
            "Provided % (Ascending)",
            "Provided % (Descending)",
            "Efficiency (Ascending)",
            "Efficiency (Descending)",
            "Notation (Ascending)",
            "Notation (Descending)"
        ])
        self.sort_filter.currentIndexChanged.connect(self.apply_filters)
        filter_row.addWidget(self.sort_filter)
        
        filter_row.addStretch()
        tab_table_layout.addLayout(filter_row)
        
        # MANUAL Actions widget (Merge & Generate Notations)
        self.manual_actions_widget = QWidget()
        manual_actions_layout = QHBoxLayout(self.manual_actions_widget)
        manual_actions_layout.setContentsMargins(0, 5, 0, 5)
        manual_actions_layout.setSpacing(15)
        
        self.merge_btn = QPushButton("🔗 Merge Selected Columns")
        self.merge_btn.setObjectName("primary-btn")
        self.merge_btn.clicked.connect(self.merge_selected_columns)
        manual_actions_layout.addWidget(self.merge_btn)
        
        self.gen_notations_btn = QPushButton("🏷️ Generate Notations")
        self.gen_notations_btn.setObjectName("success-btn")
        self.gen_notations_btn.clicked.connect(self.generate_manual_notations)
        manual_actions_layout.addWidget(self.gen_notations_btn)
        
        self.undo_btn = QPushButton("↩️ Undo Last Change")
        self.undo_btn.setObjectName("secondary-btn")
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self.undo_last_change)
        manual_actions_layout.addWidget(self.undo_btn)
        
        manual_actions_layout.addStretch()
        self.manual_actions_widget.setVisible(False)
        tab_table_layout.addWidget(self.manual_actions_widget)
        
        # Results table
        self.results_table = QTableWidget()
        cols = ["Notation", "Grid", "ETABS Size", "Req Rebar %", "Suggested CAD", "Provided %", "Rebar Details", "Efficiency"]
        self.results_table.setColumnCount(len(cols))
        self.results_table.setHorizontalHeaderLabels(cols)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.itemDoubleClicked.connect(self.on_table_item_double_clicked)
        
        # Support Extended Selection (drag-select and Ctrl+click)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.itemSelectionChanged.connect(self.on_table_selection_changed)
        
        tab_table_layout.addWidget(self.results_table)
        self.tabs.addTab(tab_table, "📊 Column Audit Schedule")
        workspace_layout.addWidget(self.tabs)
        
        # 3. Console logger (wrapped inside self.log_frame)
        self.log_frame = QFrame()
        self.log_frame.setFixedHeight(90)
        self.log_frame_layout = QVBoxLayout(self.log_frame)
        self.log_frame_layout.setContentsMargins(0, 0, 0, 0)
        
        self.log_text = QTextEdit()
        self.log_text.setObjectName("console")
        self.log_text.setReadOnly(True)
        self.log_frame_layout.addWidget(self.log_text)
        workspace_layout.addWidget(self.log_frame)
        
        main_layout.addWidget(workspace_container)
        main_layout.setStretch(1, 1)
        return workspace

    def create_kpi_card(self, title, val, footer, text_color=None):
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 8, 12, 8)
        card_layout.setSpacing(2)
        
        lbl_title = QLabel(title)
        lbl_title.setObjectName("kpi-title")
        card_layout.addWidget(lbl_title)
        
        lbl_val = QLabel(val)
        lbl_val.setObjectName("kpi-value")
        lbl_val.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {text_color or '#FFFFFF'};")
        card_layout.addWidget(lbl_val)
        
        lbl_foot = QLabel(footer)
        lbl_foot.setObjectName("kpi-footer")
        card_layout.addWidget(lbl_foot)
        
        return {"widget": card, "val": lbl_val, "foot": lbl_foot}

    def create_legend_label(self, text, color):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
        return lbl

    def log_message(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {msg}")
        self.log_text.ensureCursorVisible()

    def on_buffer_slide(self, val):
        pct = val / 100.0
        text = f"Longitudinal Rebar Buffer: {pct:.2f}%"
        # Results only change on Run; flag when the slider no longer matches them
        if self.applied_buffer_pct is not None and pct != self.applied_buffer_pct:
            text += f" (not applied, results use {self.applied_buffer_pct:.2f}% until Run)"
            self.buffer_lbl.setStyleSheet("color: #F59E0B; font-size: 11px;")
        else:
            self.buffer_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        self.buffer_lbl.setText(text)

    def on_ag_slide(self, val):
        pct = val / 100.0
        self.ag_lbl.setText(f"Auto-Merge Tolerance: {pct:.2f}%")

    def toggle_sidebar(self):
        """Collapses or expands the Left Control Sidebar Frame."""
        if self.sidebar.isVisible():
            self.sidebar.setVisible(False)
            self.toggle_sidebar_btn.setText("▶ Show Sidebar")
            self.log_message("Sidebar collapsed.")
        else:
            self.sidebar.setVisible(True)
            self.toggle_sidebar_btn.setText("◀ Hide Sidebar")
            self.log_message("Sidebar expanded.")

    def toggle_maximize_plan(self):
        """Toggles full viewport maximization of structural plan view, hiding peripheral frames."""
        if not self.plan_maximized:
            # Save sidebar visibility state and hide sidebar
            self.sidebar_was_visible = self.sidebar.isVisible()
            self.sidebar.setVisible(False)
            
            # Hide surrounding elements
            self.header_frame.setVisible(False)
            self.log_frame.setVisible(False)
            # Hide tab bar buttons itself to reclaim tab button margins
            self.tabs.tabBar().setVisible(False)
            
            # Remove layout margins and spacing for a premium edge-to-edge full screen appearance
            if hasattr(self, 'workspace_layout'):
                self.workspace_layout.setContentsMargins(0, 0, 0, 0)
                self.workspace_layout.setSpacing(0)
            if hasattr(self, 'tab_plan_layout'):
                self.tab_plan_layout.setContentsMargins(0, 0, 0, 0)
                self.tab_plan_layout.setSpacing(0)
            
            self.plan_maximized = True
            self.log_message("Structural layout maximized to full screen viewport.")
        else:
            # Restore sidebar visibility
            if hasattr(self, 'sidebar_was_visible'):
                self.sidebar.setVisible(self.sidebar_was_visible)
            else:
                self.sidebar.setVisible(True)
                
            # Restore surrounding elements
            self.header_frame.setVisible(True)
            self.log_frame.setVisible(True)
            self.tabs.tabBar().setVisible(True)
            
            # Restore layout margins and spacing
            if hasattr(self, 'workspace_layout'):
                self.workspace_layout.setContentsMargins(20, 20, 20, 20)
                self.workspace_layout.setSpacing(15)
            if hasattr(self, 'tab_plan_layout'):
                self.tab_plan_layout.setContentsMargins(10, 10, 10, 10)
                self.tab_plan_layout.setSpacing(15)
            
            self.plan_maximized = False
            self.log_message("Structural layout restored to regular view.")

    # ==================== CONNECT TO ETABS ====================
    def connect_etabs_threaded(self):
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("🔌 Connecting...")
        if hasattr(self, 'startup_connect_btn'):
            self.startup_connect_btn.setEnabled(False)
            self.startup_connect_btn.setText("🔌 Connecting...")
        # Force Qt to update UI before starting connection
        QApplication.processEvents()
        self.connect_etabs()

    def connect_etabs(self):
        import comtypes
        try:
            try:
                comtypes.CoInitialize()
            except Exception:
                pass
            res = etabs_connector.connect_to_etabs(gui_callback=True)
            if isinstance(res, list):
                self.on_connection_multiple(res)
            elif res[0] is not None:
                self.sap_model, self.model_filename, self.model_filepath = res
                self.on_connection_success()
            else:
                import traceback
                try:
                    import diagnose_etabs
                    diagnose_etabs.run_diagnostics()
                except Exception as diag_err:
                    print(f"Failed running diagnostics: {diag_err}")
                self.on_connection_failed("No active ETABS models found running.\n\nA debug report 'etabs_diagnostic_report.txt' has been generated in your project folder.")
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            try:
                import diagnose_etabs
                diagnose_etabs.run_diagnostics()
            except Exception as diag_err:
                print(f"Failed running diagnostics: {diag_err}")
            self.on_connection_failed(f"Error: {str(e)}\n\n(A debug report 'etabs_diagnostic_report.txt' has been generated in your project folder.)")

    def on_connection_multiple(self, instances):
        self.etabs_instances = instances
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("🔌 Connect to ETABS")
        if hasattr(self, 'startup_connect_btn'):
            self.startup_connect_btn.setEnabled(True)
            self.startup_connect_btn.setText("🔌 Connect to ETABS")
        self.show_instance_selection_dialog()

    def show_instance_selection_dialog(self):
        dialog = ETABSSelectionDialog(self.etabs_instances, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            inst = dialog.get_selected_instance()
            self.sap_model = inst['sap_model']
            self.model_filename = inst['filename']
            self.model_filepath = inst['filepath']
            self.on_connection_success()

    def on_connection_success(self):
        self.status_badge.setText("🟢 CONNECTED")
        self.status_badge.setStyleSheet("color: #10B981; font-weight: bold;")
        self.model_lbl.setText(f"Model: {self.model_filename}")
        self.connect_btn.setText("🔌 Refresh Connection")
        self.connect_btn.setEnabled(True)
        self.run_btn.setEnabled(True)
        
        # Update startup screen controls
        if hasattr(self, 'startup_status_badge'):
            self.startup_status_badge.setText("🟢 CONNECTED")
            self.startup_status_badge.setStyleSheet("color: #10B981; font-weight: bold;")
            self.startup_model_lbl.setText(f"Model: {self.model_filename}")
            self.startup_connect_btn.setText("🔌 Refresh Connection")
            self.startup_connect_btn.setEnabled(True)
            self.launch_btn.setEnabled(True)
            
        self.log_message(f"Successfully connected to active ETABS model: '{self.model_filename}'")

    def on_connection_failed(self, err_msg):
        self.status_badge.setText("🔴 DISCONNECTED")
        self.status_badge.setStyleSheet("color: #EF4444; font-weight: bold;")
        self.model_lbl.setText("Model: None")
        self.connect_btn.setText("🔌 Connect to ETABS")
        self.connect_btn.setEnabled(True)
        self.run_btn.setEnabled(False)
        
        # Update startup screen controls
        if hasattr(self, 'startup_status_badge'):
            self.startup_status_badge.setText("🔴 DISCONNECTED")
            self.startup_status_badge.setStyleSheet("color: #EF4444; font-weight: bold;")
            self.startup_model_lbl.setText("Model: None")
            self.startup_connect_btn.setText("🔌 Connect to ETABS")
            self.startup_connect_btn.setEnabled(True)
            self.launch_btn.setEnabled(False)
            
        self.log_message(f"Connection failed: {err_msg}")
        QMessageBox.critical(self, "ETABS Connection Error", f"Failed to connect to active ETABS instance:\n{err_msg}")

    # ==================== RUN DESIGN AUDIT ====================
    def run_audit_threaded(self):
        # Re-running rebuilds matches from scratch, which drops manual merges and notations
        if self.execution_mode == "MANUAL" and self.matched_columns and (
            self.notations_generated or any(c.get('manual_group_id') for c in self.matched_columns)
        ):
            reply = QMessageBox.question(
                self,
                "Discard Manual Work?",
                "Running again will discard all merged groups and generated notations, "
                "and clear the undo history.\n\nDo you want to continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Read slider values here on the GUI thread; the worker must not touch widgets
        buffer_val = self.buffer_slider.value() / 100.0
        tolerance = self.ag_slider.value() / 100.0
        self._pending_buffer_pct = buffer_val

        self.run_btn.setEnabled(False)
        self.run_btn.setText("⚡ Running...")
        self.pdf_btn.setEnabled(False)
        self.folder_btn.setEnabled(False)
        self.ag_btn.setEnabled(False)
        self.resequence_btn.setEnabled(False)
        
        # Clear previous selection details
        self.selected_frame_name = None
        self.sel_frame_lbl.setText("Frame: None Selected")
        self.sel_size_lbl.setText("Size: N/A")
        self.sel_angle_lbl.setText("Orientation angle: N/A")
        self.sel_rebar_lbl.setText("Required Rebar: N/A")
        self.sel_notation_lbl.setText("Current Notation: N/A")
        self.notation_combo.clear()
        self.notation_combo.setEnabled(False)
        self.apply_override_btn.setEnabled(False)
        
        # Hide the filter panel while loading new data
        if hasattr(self, 'filter_buttons_frame'):
            self.filter_buttons_frame.setVisible(False)
            
        self.undo_stack = []
        if hasattr(self, 'undo_btn'):
            self.undo_btn.setEnabled(False)
            
        threading.Thread(target=self.run_audit, args=(buffer_val, tolerance), daemon=True).start()

    def run_audit(self, buffer_val, tolerance):
        import comtypes
        try:
            comtypes.CoInitialize()
            self.logSignal.emit("Scanning ETABS structural database tables...")
            
            def status_cb(msg):
                self.logSignal.emit(msg)
                
            res = etabs_connector.extract_column_data(self.sap_model, status_callback=status_cb)
            if not res:
                self.auditFailedSignal.emit("Could not retrieve concrete column design results. Check if concrete design has been run.")
                return
                
            self.raw_etabs_data = res
            self.logSignal.emit("Data successfully extracted from ETABS. Running matching engine...")
            
            # Map columns
            self.matched_columns = self.matcher.match_all_columns(self.raw_etabs_data, buffer_pct=buffer_val)

            if self.execution_mode == "AUTO":
                # Auto-group columns with current tolerance
                self.matched_columns = self.matcher.auto_group_columns(self.matched_columns, tolerance=tolerance)
            else:
                # In MANUAL mode, do not group or generate notations automatically
                for c in self.matched_columns:
                    c['group_notation'] = ''
                    c['manual_group_id'] = None
                    c['original_suggested_id'] = c.get('original_suggested_id', c['suggested_id'])
                    c['original_cad_pct'] = c.get('original_cad_pct', c['cad_pct'])
                    c['original_rebar_callout'] = c.get('original_rebar_callout', c.get('rebar_callout', 'N/A'))
            
            self.logSignal.emit("Audit completed. Rendering visual structural layouts...")
            self.auditCompletedSignal.emit()
            
        except Exception as e:
            self.auditFailedSignal.emit(str(e))
        finally:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass

    def on_audit_completed(self):
        # Record the buffer these results were matched with and refresh the slider label
        self.applied_buffer_pct = self._pending_buffer_pct
        self.on_buffer_slide(self.buffer_slider.value())

        if self.execution_mode == "MANUAL":
            # Fresh matches carry no notations, so return to the pre-notation state
            self.notations_generated = False
            self.selected_frame_names = []
            self.override_card.setVisible(False)
            self.groups_card.setVisible(False)

        # Generate Plotly plan and update layouts on main thread safely
        html_content = self.generate_plotly_html()
        
        # Resolve base directory path for local file loading security in QtWebEngine
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.webview.setHtml(html_content, QUrl.fromLocalFile(base_dir + "/"))
        
        # Refresh results schedule views
        self.update_results_grid()

    def on_audit_failed(self, err_msg):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("⚡ Run")
        self.log_message(f"Audit analysis failed: {err_msg}")
        QMessageBox.critical(self, "Structural Audit Failed", f"An error occurred during database analysis:\n{err_msg}")

    def update_results_grid(self):
        # 1. Update KPI Dashboard Cards
        total_cols = len(self.matched_columns)
        conforming = sum(1 for c in self.matched_columns if c['status'] == 'SUCCESS')
        exceeded = sum(1 for c in self.matched_columns if c['status'] == 'REINFORCEMENT EXCEEDED')
        
        valid_effs = [c['efficiency'] for c in self.matched_columns if c['status'] == 'SUCCESS']
        avg_eff = sum(valid_effs) / len(valid_effs) if valid_effs else 0.0
        
        unique_notations = set()
        for c in self.matched_columns:
            notation = c.get('group_notation', '').strip()
            if notation and notation not in ('N/A', 'Exceeded', 'Default', '-'):
                unique_notations.add(notation)
        
        self.kpi1['val'].setText(str(total_cols))
        self.kpi2['val'].setText(str(conforming))
        self.kpi2['foot'].setText(f"{conforming / total_cols * 100.0:.1f}% satisfied" if total_cols > 0 else "0.0% satisfied")
        self.kpi3['val'].setText(str(exceeded))
        self.kpi3['foot'].setText("Requires concrete redesign" if exceeded > 0 else "All frames safe")
        self.kpi4['val'].setText(f"{avg_eff:.1f}%")
        self.kpi5['val'].setText(str(len(unique_notations)))
        
        # 2. Populate Story & Status Filters
        stories = sorted(list(set([c['story_name'] for c in self.matched_columns])), key=self.matcher.natural_sort_key)
        self.story_filter.blockSignals(True)
        self.story_filter.clear()
        self.story_filter.addItem("All Stories")
        self.story_filter.addItems(stories)
        self.story_filter.blockSignals(False)
        
        self.status_filter.blockSignals(True)
        self.status_filter.setCurrentIndex(0)
        self.status_filter.blockSignals(False)
        
        # 3. Load/Enable Grouping Panel
        self.update_group_summary()
        
        # 4. Generate and Apply Unified Global Filters
        self.update_filter_buttons()
        
        # Enable GUI actions
        self.run_btn.setEnabled(True)
        self.run_btn.setText("⚡ Run")
        if self.execution_mode == "AUTO":
            self.ag_btn.setEnabled(True)
            self.resequence_btn.setEnabled(True)
        else:
            self.ag_btn.setEnabled(False)
            self.resequence_btn.setEnabled(self.notations_generated)
        self.pdf_btn.setEnabled(True)
        self.folder_btn.setEnabled(True)
        
        # Show dynamic filter panel if we have matched columns
        if hasattr(self, 'filter_buttons_frame') and self.matched_columns:
            self.filter_buttons_frame.setVisible(True)
            
        # In MANUAL mode, adjust table column visibility and sorting
        if self.execution_mode == "MANUAL":
            self.results_table.setColumnHidden(0, not self.notations_generated)
            if not self.notations_generated:
                self.sort_filter.blockSignals(True)
                self.sort_filter.setCurrentIndex(1) # Sort by Req Rebar % (Ascending)
                self.sort_filter.blockSignals(False)
        
        self.log_message(f"Audit completed: {total_cols} columns analyzed. {conforming} conforming suggestions matched.")

    def populate_tree(self, columns_list):
        self.results_table.setRowCount(0)
        self.results_table.setRowCount(len(columns_list))
        
        for idx, col in enumerate(columns_list):
            eff = col['efficiency']
            
            # Map status detail tags
            if col['status'] == 'REINFORCEMENT EXCEEDED':
                cad_name = "EXCEEDED"
                cad_pct = f"{col['cad_pct']:.2f}%"
                rebar_callout = "Custom detail req."
                color = QColor("#EF4444")
            elif col['status'] == 'SIZE NOT FOUND':
                cad_name = "SIZE NOT FOUND"
                cad_pct = "N/A"
                rebar_callout = "Aspect ratio mismatch"
                color = QColor("#F59E0B")
            else:
                cad_name = col['suggested_id']
                cad_pct = f"{col['cad_pct']:.2f}%"
                rebar_callout = col.get('rebar_callout', 'N/A')
                
                # Dynamic Notation group color coding
                color = QColor(self.get_column_status_color(col))
                
            is_merged = col.get('manual_group_id') is not None
            grid_label = col['grid_label']
            merge_colors = self.get_merge_group_colors(col.get('manual_group_id')) if is_merged else None
            
            if is_merged:
                grid_label = f"✓ {grid_label}"
                    
            row_items = [
                col.get('group_notation', 'N/A'),
                grid_label,
                f"{col['width']:.0f} x {col['depth']:.0f}",
                f"{col['rebar_pct']:.2f}%",
                cad_name,
                cad_pct,
                rebar_callout,
                f"{eff:.1f}%"
            ]
            
            for c_idx, val in enumerate(row_items):
                item = QTableWidgetItem(str(val))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c_idx in (0, 4, 5, 6, 7):
                    item.setForeground(QBrush(color))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                
                if is_merged and merge_colors:
                    # Distinct dark background color for each unique merged group
                    item.setBackground(QBrush(QColor(merge_colors["bg"])))
                    # Distinct accent color and bold font for grid label to stand out distinctly as merged
                    if c_idx == 1:
                        item.setForeground(QBrush(QColor(merge_colors["accent"])))
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                        
                item.setData(Qt.ItemDataRole.UserRole, col['frame_name'])
                self.results_table.setItem(idx, c_idx, item)

    def apply_filters(self, _=None):
        self.apply_global_filters()

    def run_auto_grouping(self):
        if not self.matched_columns:
            return
            
        tolerance = self.ag_slider.value() / 100.0
        self.log_message(f"Re-running auto-grouping with tolerance {tolerance:.2f}%...")
        
        self.matched_columns = self.matcher.auto_group_columns(self.matched_columns, tolerance=tolerance)
        self.update_group_summary()
        
        # Clear selected column view and refresh Plotly Layout to match new groups
        self.selected_frame_name = None
        self.sel_frame_lbl.setText("Frame: None Selected")
        self.sel_size_lbl.setText("Size: N/A")
        self.sel_angle_lbl.setText("Orientation angle: N/A")
        self.sel_rebar_lbl.setText("Required Rebar: N/A")
        self.sel_notation_lbl.setText("Current Notation: N/A")
        self.notation_combo.clear()
        self.notation_combo.setEnabled(False)
        self.apply_override_btn.setEnabled(False)
        
        # Refresh layouts and filters
        self.update_filter_buttons()
        self.log_message("Auto-grouping completed successfully.")

    def update_group_summary(self):
        self.groups_table.setRowCount(0)
        if not self.matched_columns:
            if hasattr(self, 'filter_buttons_frame'):
                self.filter_buttons_frame.setVisible(False)
            return
            
        groups = {}
        for c in self.matched_columns:
            notation = c.get('group_notation', '').strip()
            if not notation or notation in ('N/A', 'Exceeded', 'Default', '-'):
                continue
            if notation not in groups:
                groups[notation] = []
            groups[notation].append(c)
            
        self.groups_table.setRowCount(len(groups))
        for idx, notation in enumerate(sorted(groups.keys(), key=self.matcher.natural_sort_key)):
            cols = groups[notation]
            size_str = f"{cols[0]['width']:.0f}x{cols[0]['depth']:.0f}"
            callout = cols[0]['rebar_callout']
            qty = len(cols)
            
            row_items = [notation, size_str, callout, str(qty)]
            
            # Resolve notation group color coding
            color = QColor(self.get_notation_color_string(notation))
            
            for col_idx, val in enumerate(row_items):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col_idx in (0, 1, 2):
                    item.setForeground(QBrush(color))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.groups_table.setItem(idx, col_idx, item)
                
        # Dynamic Column Auto-Fitting & Reactive Pane/Splitter Scaling
        self.groups_table.resizeColumnsToContents()
        total_width = sum(self.groups_table.columnWidth(i) for i in range(self.groups_table.columnCount()))
        
        # Ideal panel width: sum of columns + margins and vertical scrollbar padding
        ideal_panel_width = total_width + 60
        ideal_panel_width = max(340, min(500, ideal_panel_width))
        
        if hasattr(self, 'right_panel') and hasattr(self, 'splitter'):
            self.right_panel.setFixedWidth(ideal_panel_width)
            total_splitter_width = self.splitter.width()
            if total_splitter_width <= 0:
                total_splitter_width = 1200  # Fallback startup width
            self.splitter.setSizes([total_splitter_width - ideal_panel_width, ideal_panel_width])
                
        # Update dynamic side filter buttons
        self.update_filter_buttons()

    def get_all_button_qss(self):
        return """
            QPushButton {
                background-color: #1E293B;
                border: 2px solid #E2E8F0;
                border-radius: 6px;
                color: #E2E8F0;
                font-size: 10px;
                font-weight: bold;
                padding: 6px 2px;
                min-height: 18px;
            }
            QPushButton:hover {
                background-color: rgba(226, 232, 240, 0.15);
                color: #FFFFFF;
            }
            QPushButton:checked {
                background-color: #E2E8F0;
                border: 2px solid #FFFFFF;
                color: #0F172A;
            }
        """

    def get_filter_button_qss(self, color_hex):
        return f"""
            QPushButton {{
                background-color: #1E293B;
                border: 2px solid {color_hex};
                border-radius: 6px;
                color: {color_hex};
                font-size: 10px;
                font-weight: bold;
                padding: 6px 2px;
                min-height: 18px;
            }}
            QPushButton:hover {{
                background-color: {self.hex_to_rgba(color_hex, 0.15)};
                color: #FFFFFF;
            }}
            QPushButton:checked {{
                background-color: {color_hex};
                border: 2px solid #FFFFFF;
                color: #FFFFFF;
            }}
        """

    def update_filter_buttons(self):
        # 1. Save currently checked notations & sizes to preserve states across updates
        checked_notations = set()
        if hasattr(self, 'filter_buttons'):
            for btn in self.filter_buttons:
                if btn.isChecked():
                    checked_notations.add(btn.text())
        all_notations_was_checked = hasattr(self, 'all_filter_btn') and self.all_filter_btn.isChecked()
        
        checked_sizes = set()
        if hasattr(self, 'size_filter_buttons'):
            for btn in self.size_filter_buttons:
                if btn.isChecked():
                    checked_sizes.add(btn.text())
        all_sizes_was_checked = hasattr(self, 'all_size_filter_btn') and self.all_size_filter_btn.isChecked()
        
        # 2. Clear existing dynamic button widgets in layouts
        while self.notation_buttons_layout.count():
            item = self.notation_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
                
        while self.size_buttons_layout.count():
            item = self.size_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
                
        self.filter_buttons = []
        self.size_filter_buttons = []
        
        if not self.matched_columns:
            return
            
        # 3. Populate Notations Filters
        unique_notations = set()
        for c in self.matched_columns:
            notation = c.get('group_notation', '').strip()
            if notation and notation not in ('N/A', 'Exceeded', 'Default', '-'):
                unique_notations.add(notation)
                
        sorted_notations = sorted(list(unique_notations), key=self.matcher.natural_sort_key)
        
        # Add "ALL" button for Notations
        self.all_filter_btn = QPushButton("ALL")
        self.all_filter_btn.setCheckable(True)
        self.all_filter_btn.setStyleSheet(self.get_all_button_qss())
        self.all_filter_btn.clicked.connect(lambda: self.on_notation_filter_clicked(self.all_filter_btn))
        self.notation_buttons_layout.addWidget(self.all_filter_btn)
        
        for notation in sorted_notations:
            color_hex = self.get_notation_color_string(notation)
            btn = QPushButton(notation)
            btn.setCheckable(True)
            if notation in checked_notations and not all_notations_was_checked:
                btn.setChecked(True)
            btn.setStyleSheet(self.get_filter_button_qss(color_hex))
            btn.clicked.connect(lambda checked, b=btn: self.on_notation_filter_clicked(b))
            self.notation_buttons_layout.addWidget(btn)
            self.filter_buttons.append(btn)
            
        any_not_checked = any(b.isChecked() for b in self.filter_buttons)
        self.all_filter_btn.setChecked(not any_not_checked)
        
        # 4. Populate ETABS Size Filters
        unique_sizes = set()
        for c in self.matched_columns:
            unique_sizes.add(f"{c['width']:.0f}x{c['depth']:.0f}")
            
        def size_sort_key(s):
            try:
                parts = s.split('x')
                return [float(p) for p in parts]
            except Exception:
                return [0.0, 0.0]
                
        sorted_sizes = sorted(list(unique_sizes), key=size_sort_key)
        
        # Add "ALL" button for Sizes
        self.all_size_filter_btn = QPushButton("ALL")
        self.all_size_filter_btn.setCheckable(True)
        self.all_size_filter_btn.setStyleSheet(self.get_all_button_qss())
        self.all_size_filter_btn.clicked.connect(lambda: self.on_size_filter_clicked(self.all_size_filter_btn))
        self.size_buttons_layout.addWidget(self.all_size_filter_btn)
        
        for size in sorted_sizes:
            btn = QPushButton(size)
            btn.setCheckable(True)
            if size in checked_sizes and not all_sizes_was_checked:
                btn.setChecked(True)
            btn.setStyleSheet(self.get_filter_button_qss("#38BDF8"))
            btn.clicked.connect(lambda checked, b=btn: self.on_size_filter_clicked(b))
            self.size_buttons_layout.addWidget(btn)
            self.size_filter_buttons.append(btn)
            
        any_size_checked = any(b.isChecked() for b in self.size_filter_buttons)
        self.all_size_filter_btn.setChecked(not any_size_checked)
        
        # Show/Hide notation labels and buttons based on MANUAL mode notations_generated flag
        if self.execution_mode == "MANUAL" and not self.notations_generated:
            self.notation_lbl.setVisible(False)
            self.notation_buttons_container.setVisible(False)
        else:
            self.notation_lbl.setVisible(True)
            self.notation_buttons_container.setVisible(True)
            
        # Apply global dynamic filtered state instantly
        self.apply_global_filters()

    def on_notation_filter_clicked(self, clicked_btn):
        modifiers = QApplication.keyboardModifiers()
        ctrl_pressed = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        
        if clicked_btn == self.all_filter_btn:
            if clicked_btn.isChecked():
                for btn in self.filter_buttons:
                    btn.blockSignals(True)
                    btn.setChecked(False)
                    btn.blockSignals(False)
            else:
                any_checked = any(btn.isChecked() for btn in self.filter_buttons)
                if not any_checked:
                    clicked_btn.blockSignals(True)
                    clicked_btn.setChecked(True)
                    clicked_btn.blockSignals(False)
        else:
            if not ctrl_pressed:
                # Exclusive selection
                for btn in self.filter_buttons:
                    if btn != clicked_btn:
                        btn.blockSignals(True)
                        btn.setChecked(False)
                        btn.blockSignals(False)
                clicked_btn.blockSignals(True)
                clicked_btn.setChecked(True)
                clicked_btn.blockSignals(False)
                self.all_filter_btn.blockSignals(True)
                self.all_filter_btn.setChecked(False)
                self.all_filter_btn.blockSignals(False)
            else:
                # Multi-select toggle
                if clicked_btn.isChecked():
                    self.all_filter_btn.blockSignals(True)
                    self.all_filter_btn.setChecked(False)
                    self.all_filter_btn.blockSignals(False)
                else:
                    any_checked = any(btn.isChecked() for btn in self.filter_buttons)
                    if not any_checked:
                        self.all_filter_btn.blockSignals(True)
                        self.all_filter_btn.setChecked(True)
                        self.all_filter_btn.blockSignals(False)
                        
        self.apply_global_filters()

    def on_size_filter_clicked(self, clicked_btn):
        modifiers = QApplication.keyboardModifiers()
        ctrl_pressed = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        
        if clicked_btn == self.all_size_filter_btn:
            if clicked_btn.isChecked():
                for btn in self.size_filter_buttons:
                    btn.blockSignals(True)
                    btn.setChecked(False)
                    btn.blockSignals(False)
            else:
                any_checked = any(btn.isChecked() for btn in self.size_filter_buttons)
                if not any_checked:
                    clicked_btn.blockSignals(True)
                    clicked_btn.setChecked(True)
                    clicked_btn.blockSignals(False)
        else:
            if not ctrl_pressed:
                # Exclusive selection
                for btn in self.size_filter_buttons:
                    if btn != clicked_btn:
                        btn.blockSignals(True)
                        btn.setChecked(False)
                        btn.blockSignals(False)
                clicked_btn.blockSignals(True)
                clicked_btn.setChecked(True)
                clicked_btn.blockSignals(False)
                self.all_size_filter_btn.blockSignals(True)
                self.all_size_filter_btn.setChecked(False)
                self.all_size_filter_btn.blockSignals(False)
            else:
                # Multi-select toggle
                if clicked_btn.isChecked():
                    self.all_size_filter_btn.blockSignals(True)
                    self.all_size_filter_btn.setChecked(False)
                    self.all_size_filter_btn.blockSignals(False)
                else:
                    any_checked = any(btn.isChecked() for btn in self.size_filter_buttons)
                    if not any_checked:
                        self.all_size_filter_btn.blockSignals(True)
                        self.all_size_filter_btn.setChecked(True)
                        self.all_size_filter_btn.blockSignals(False)
                        
        self.apply_global_filters()

    def apply_global_filters(self):
        if not self.matched_columns:
            return
            
        # 1. Block signals for all filter buttons to avoid recursive trigger loops
        all_buttons = self.filter_buttons + self.size_filter_buttons + [self.all_filter_btn, self.all_size_filter_btn]
        for btn in all_buttons:
            btn.blockSignals(True)

        try:
            # 2. Determine checked states before visibility update
            show_all_notations = hasattr(self, 'all_filter_btn') and self.all_filter_btn.isChecked()
            active_notations = [btn.text() for btn in self.filter_buttons if btn.isChecked()] if not show_all_notations else []
            
            show_all_sizes = hasattr(self, 'all_size_filter_btn') and self.all_size_filter_btn.isChecked()
            active_sizes = [btn.text() for btn in self.size_filter_buttons if btn.isChecked()] if not show_all_sizes else []

            # 3. Calculate valid notations based on active_sizes
            if show_all_sizes or not active_sizes:
                valid_notations = set(c.get('group_notation', '').strip() for c in self.matched_columns)
            else:
                valid_notations = set()
                active_sizes_set = set(active_sizes)
                for c in self.matched_columns:
                    size_str = f"{c['width']:.0f}x{c['depth']:.0f}"
                    if size_str in active_sizes_set:
                        notation = c.get('group_notation', '').strip()
                        if notation:
                            valid_notations.add(notation)

            # 4. Calculate valid sizes based on active_notations
            if show_all_notations or not active_notations:
                valid_sizes = set(f"{c['width']:.0f}x{c['depth']:.0f}" for c in self.matched_columns)
            else:
                valid_sizes = set()
                active_notations_set = set(active_notations)
                for c in self.matched_columns:
                    notation = c.get('group_notation', '').strip()
                    if notation in active_notations_set:
                        valid_sizes.add(f"{c['width']:.0f}x{c['depth']:.0f}")

            # 5. Update Notation buttons visibility and check states
            for btn in self.filter_buttons:
                notation = btn.text()
                if notation in valid_notations:
                    btn.setVisible(True)
                else:
                    btn.setVisible(False)
                    btn.setChecked(False)

            # Check if any visible notation button remains checked
            any_notation_checked = any(btn.isChecked() for btn in self.filter_buttons if btn.isVisible())
            if not any_notation_checked:
                self.all_filter_btn.setChecked(True)
                show_all_notations = True
                active_notations = []
                # Re-evaluate valid sizes as all sizes are now valid under ALL notations
                valid_sizes = set(f"{c['width']:.0f}x{c['depth']:.0f}" for c in self.matched_columns)

            # 6. Update Size buttons visibility and check states
            for btn in self.size_filter_buttons:
                size_str = btn.text()
                if size_str in valid_sizes:
                    btn.setVisible(True)
                else:
                    btn.setVisible(False)
                    btn.setChecked(False)

            # Check if any visible size button remains checked
            any_size_checked = any(btn.isChecked() for btn in self.size_filter_buttons if btn.isVisible())
            if not any_size_checked:
                self.all_size_filter_btn.setChecked(True)
                show_all_sizes = True
                active_sizes = []
                # Re-evaluate valid notations as all notations are now valid under ALL sizes
                valid_notations = set(c.get('group_notation', '').strip() for c in self.matched_columns)
                for btn in self.filter_buttons:
                    notation = btn.text()
                    btn.setVisible(notation in valid_notations)
                    if notation not in valid_notations:
                        btn.setChecked(False)
                # Recalculate if any visible notation button is checked
                any_notation_checked = any(btn.isChecked() for btn in self.filter_buttons if btn.isVisible())
                if not any_notation_checked:
                    self.all_filter_btn.setChecked(True)
                    show_all_notations = True
                    active_notations = []

            # 7. Finalized filter sets for actual filtering run
            show_all_notations = self.all_filter_btn.isChecked()
            active_notations = [btn.text() for btn in self.filter_buttons if btn.isChecked()] if not show_all_notations else []
            
            show_all_sizes = self.all_size_filter_btn.isChecked()
            active_sizes = [btn.text() for btn in self.size_filter_buttons if btn.isChecked()] if not show_all_sizes else []

        finally:
            # 8. Always unblock signals
            for btn in all_buttons:
                btn.blockSignals(False)
        
        story = self.story_filter.currentText() if hasattr(self, 'story_filter') else "All Stories"
        status_sel = self.status_filter.currentText() if hasattr(self, 'status_filter') else "All Statuses"
        
        # 1. Filter matched_columns in Python
        filtered_columns = []
        for c in self.matched_columns:
            notation = c.get('group_notation', '').strip()
            size_str = f"{c['width']:.0f}x{c['depth']:.0f}"
            story_val = c['story_name']
            status_val = c['status']
            
            notation_match = show_all_notations or (notation in active_notations)
            size_match = show_all_sizes or (size_str in active_sizes)
            story_match = (story == "All Stories" or story_val == story)
            
            status_match = True
            if status_sel == "SUCCESS (Conforming)":
                status_match = (status_val == "SUCCESS")
            elif status_sel == "REINFORCEMENT EXCEEDED":
                status_match = (status_val == "REINFORCEMENT EXCEEDED")
            elif status_sel == "SIZE NOT FOUND":
                status_match = (status_val == "SIZE NOT FOUND")
                
            if notation_match and size_match and story_match and status_match:
                filtered_columns.append(c)
                
        # 1.5. Sort filtered columns
        sort_by = self.sort_filter.currentText() if hasattr(self, 'sort_filter') else "Default (Story & Grid)"
        if sort_by == "Req Rebar % (Ascending)":
            filtered_columns.sort(key=lambda x: x.get('rebar_pct') if isinstance(x.get('rebar_pct'), (int, float)) else 0.0)
        elif sort_by == "Req Rebar % (Descending)":
            filtered_columns.sort(key=lambda x: x.get('rebar_pct') if isinstance(x.get('rebar_pct'), (int, float)) else 0.0, reverse=True)
        elif sort_by == "Provided % (Ascending)":
            filtered_columns.sort(key=lambda x: x.get('cad_pct') if isinstance(x.get('cad_pct'), (int, float)) else 0.0)
        elif sort_by == "Provided % (Descending)":
            filtered_columns.sort(key=lambda x: x.get('cad_pct') if isinstance(x.get('cad_pct'), (int, float)) else 0.0, reverse=True)
        elif sort_by == "Efficiency (Ascending)":
            filtered_columns.sort(key=lambda x: x.get('efficiency') if isinstance(x.get('efficiency'), (int, float)) else 0.0)
        elif sort_by == "Efficiency (Descending)":
            filtered_columns.sort(key=lambda x: x.get('efficiency') if isinstance(x.get('efficiency'), (int, float)) else 0.0, reverse=True)
        elif sort_by == "Notation (Ascending)":
            filtered_columns.sort(key=lambda x: self.matcher.natural_sort_key(x.get('group_notation', '')))
        elif sort_by == "Notation (Descending)":
            filtered_columns.sort(key=lambda x: self.matcher.natural_sort_key(x.get('group_notation', '')), reverse=True)
        elif sort_by == "Default (Story & Grid)":
            # Default hierarchical sorting: Story name naturally, then Frame name naturally
            filtered_columns.sort(key=lambda x: (
                self.matcher.natural_sort_key(x.get('story_name', '')),
                self.matcher.natural_sort_key(x.get('frame_name', ''))
            ))
                 
        # 2. Populate columns schedule table
        self.populate_tree(filtered_columns)
        
        # 3. Regenerate Plotly plan traces for only filtered columns
        d_res = self.get_plotly_data(filtered_columns)
        
        js_newData = json.dumps(d_res["traces"])
        js_newTraceMap = json.dumps(d_res["notation_traces_map"])
        js_newNotationsMap = json.dumps(d_res["column_notations_map"])
        js_newCoordsMap = json.dumps(d_res["column_coords_map"])
        js_newTextCoords = json.dumps(d_res["original_text_coords"])
        js_newTextIndexMap = json.dumps(d_res["column_text_index_map"])
        
        self.webview.page().runJavaScript(
            f"reactPlot({js_newData}, {js_newTraceMap}, {js_newNotationsMap}, {js_newCoordsMap}, {js_newTextCoords}, {js_newTextIndexMap}, {d_res['text_trace_idx']}, {d_res['selection_highlight_idx']}, {d_res['group_highlight_idx']})"
        )
        
        # 4. Handle selected column visibility
        if self.selected_frame_name:
            still_visible = any(c['frame_name'] == self.selected_frame_name for c in filtered_columns)
            if not still_visible:
                self.selected_frame_name = None
                self.sel_frame_lbl.setText("Frame: None Selected")
                self.sel_size_lbl.setText("Size: N/A")
                self.sel_angle_lbl.setText("Orientation angle: N/A")
                self.sel_rebar_lbl.setText("Required Rebar: N/A")
                self.sel_notation_lbl.setText("Current Notation: N/A")
                self.notation_combo.clear()
                self.notation_combo.setEnabled(False)
                self.apply_override_btn.setEnabled(False)
                self.webview.page().runJavaScript("highlightColumn('')")
            else:
                self.webview.page().runJavaScript(f"highlightColumn('{self.selected_frame_name}')")
                
        self.log_message(f"Global filters synced: showing {len(filtered_columns)} / {len(self.matched_columns)} columns.")

    def apply_plan_filter(self):
        self.apply_global_filters()

    def toggle_maximize_groups_summary(self):
        if not hasattr(self, 'groups_summary_maximized'):
            self.groups_summary_maximized = False
            
        if not self.groups_summary_maximized:
            # Hide other widgets inside the right panel to maximize the table
            self.sel_card.setVisible(False)
            self.override_card.setVisible(False)
            self.log_card.setVisible(False)
            
            # Stretch table height to show entries
            self.groups_table.setFixedHeight(450)
            self.groups_max_btn.setText("🗗")  # Restore icon
            self.groups_summary_maximized = True
            self.log_message("Active Schedule Groups Summary table maximized.")
        else:
            # Restore sibling widgets in the right panel
            self.sel_card.setVisible(True)
            self.override_card.setVisible(True)
            self.log_card.setVisible(True)
            
            # Restore original table height
            self.groups_table.setFixedHeight(120)
            self.groups_max_btn.setText("⛶")  # Maximize icon
            self.groups_summary_maximized = False
            self.log_message("Active Schedule Groups Summary table restored.")

    # ==================== INTERACTIVE SELECTION CALLBACK ====================
    def on_plotly_column_selected(self, frame_name):
        self.selected_frame_name = frame_name
        if frame_name:
            self.log_message(f"Selected column frame: {frame_name}")
        
        col = None
        for c in self.matched_columns:
            if c['frame_name'] == frame_name:
                col = c
                break
                
        if not col:
            self.sel_frame_lbl.setText("Frame: N/A")
            self.sel_size_lbl.setText("Size: N/A")
            self.sel_angle_lbl.setText("Orientation angle: N/A")
            self.sel_rebar_lbl.setText("Required Rebar: N/A")
            self.sel_notation_lbl.setText("Current Notation: N/A")
            self.notation_combo.setEnabled(False)
            self.apply_override_btn.setEnabled(False)
            return
            
        self.sel_frame_lbl.setText(f"Frame: {col['frame_name']}")
        self.sel_size_lbl.setText(f"Size: {col['width']:.0f} x {col['depth']:.0f} mm")
        self.sel_angle_lbl.setText(f"Orientation angle: {col['angle']:.1f}°")
        self.sel_rebar_lbl.setText(f"Required Rebar: {col['rebar_pct']:.2f}% (Story {col['story_name']})")
        
        if self.execution_mode == "MANUAL" and not self.notations_generated:
            self.sel_notation_lbl.setText("Current Notation: Not Generated")
            self.notation_combo.setEnabled(False)
            self.apply_override_btn.setEnabled(False)
        else:
            self.sel_notation_lbl.setText(f"Current Notation: {col.get('group_notation', 'N/A')}")
            self.populate_notation_combobox_guard(col)

    def on_plotly_multiple_columns_selected(self, frame_names_str):
        if hasattr(self, '_updating_selection') and self._updating_selection:
            return
            
        self._updating_selection = True
        try:
            if not frame_names_str:
                self.selected_frame_names = []
            else:
                self.selected_frame_names = [f.strip() for f in frame_names_str.split(",") if f.strip()]
                
            if self.selected_frame_names:
                self.log_message(f"Selected multiple columns on plan: {self.selected_frame_names}")
                
            self.results_table.clearSelection()
            
            if self.selected_frame_names:
                for row in range(self.results_table.rowCount()):
                    item = self.results_table.item(row, 1)
                    if item:
                        f_name = item.data(Qt.ItemDataRole.UserRole)
                        if f_name in self.selected_frame_names:
                            # Select all cell items in this row to highlight it without clearing other rows
                            for col_idx in range(self.results_table.columnCount()):
                                cell_item = self.results_table.item(row, col_idx)
                                if cell_item:
                                    cell_item.setSelected(True)
                            
            if self.selected_frame_names:
                self.on_plotly_column_selected(self.selected_frame_names[0])
            else:
                self.on_plotly_column_selected("")
        finally:
            self._updating_selection = False

    def on_table_selection_changed(self):
        if hasattr(self, '_updating_selection') and self._updating_selection:
            return
            
        self._updating_selection = True
        try:
            selected_items = self.results_table.selectedItems()
            selected_frames = []
            for item in selected_items:
                f_name = item.data(Qt.ItemDataRole.UserRole)
                if f_name and f_name not in selected_frames:
                    selected_frames.append(f_name)
                    
            self.selected_frame_names = selected_frames
            
            # Sync selection highlight on Plotly plan
            js_frames = json.dumps(selected_frames)
            self.webview.page().runJavaScript(f"highlightMultipleColumns({js_frames})")
            
            if selected_frames:
                self.on_plotly_column_selected(selected_frames[0])
            else:
                self.on_plotly_column_selected("")
        finally:
            self._updating_selection = False

    def on_table_item_double_clicked(self, item):
        frame_name = item.data(Qt.ItemDataRole.UserRole)
        if frame_name:
            self.tabs.setCurrentIndex(0)
            
            # If a filter is currently active and the target column's notation is not selected,
            # reset filters to "ALL" to make the column visible.
            col_notation = None
            for c in self.matched_columns:
                if c['frame_name'] == frame_name:
                    col_notation = c.get('group_notation')
                    break
                    
            if col_notation and hasattr(self, 'all_filter_btn') and not self.all_filter_btn.isChecked():
                active_notations = [btn.text() for btn in self.filter_buttons if btn.isChecked()]
                if col_notation not in active_notations:
                    self.all_filter_btn.setChecked(True)
                    self.on_filter_button_clicked(self.all_filter_btn)
                    
            self.on_plotly_column_selected(frame_name)
            self.webview.page().runJavaScript(f"highlightColumn('{frame_name}')")

    def on_group_summary_clicked(self, row, col_idx):
        """Triggered when a row is clicked in the Active Schedule Groups Summary table."""
        item = self.groups_table.item(row, 0)
        if item:
            notation = item.text()
            self.log_message(f"Isolating structural plan layout for group notation: '{notation}'")
            self.webview.page().runJavaScript(f"highlightGroup('{notation}')")

    def populate_notation_combobox_guard(self, target_col):
        self.notation_combo.blockSignals(True)
        self.notation_combo.clear()
        
        t_w = round(target_col['width'])
        t_d = round(target_col['depth'])
        
        compatible_notations = set()
        for c in self.matched_columns:
            notation = c.get('group_notation', '').strip()
            if not notation or notation in ('N/A', 'Exceeded', 'Default', '-'):
                continue
                
            c_w = round(c['width'])
            c_d = round(c['depth'])
            
            # Dimension matches supporting rotated states
            normal = (abs(c_w - t_w) < 10 and abs(c_d - t_d) < 10)
            rotated = (abs(c_w - t_d) < 10 and abs(c_d - t_w) < 10)
            if normal or rotated:
                compatible_notations.add(notation)
                
        sorted_notations = sorted(list(compatible_notations), key=self.matcher.natural_sort_key)
        self.notation_combo.addItems(sorted_notations)
        
        curr_not = target_col.get('group_notation', '')
        self.notation_combo.setCurrentText(curr_not)
        
        self.notation_combo.setEnabled(True)
        self.apply_override_btn.setEnabled(True)
        self.notation_combo.blockSignals(False)

    # ==================== APPLY MANUAL OVERRIDE ====================
    def apply_manual_override(self):
        if not self.matched_columns or not self.selected_frame_name:
            return
            
        new_notation = self.notation_combo.currentText().strip()
        if not new_notation:
            QMessageBox.warning(self, "Invalid Notation", "Please enter a valid notation label (e.g. C1).")
            return
            
        col = None
        for c in self.matched_columns:
            if c['frame_name'] == self.selected_frame_name:
                col = c
                break
                
        if not col:
            return
            
        old_notation = col.get('group_notation', 'N/A')
        if old_notation == new_notation:
            return
            
        # Guard: Strict Same-Size constraint check
        t_w = round(col['width'])
        t_d = round(col['depth'])
        
        size_mismatch = False
        mismatched_size = None
        for c in self.matched_columns:
            notation = c.get('group_notation', '').strip()
            if notation == new_notation:
                c_w = round(c['width'])
                c_d = round(c['depth'])
                
                normal = (abs(c_w - t_w) < 10 and abs(c_d - t_d) < 10)
                rotated = (abs(c_w - t_d) < 10 and abs(c_d - t_w) < 10)
                if not (normal or rotated):
                    size_mismatch = True
                    mismatched_size = f"{c_w:.0f}x{c_d:.0f}"
                    break
                    
        if size_mismatch:
            err_msg = f"Accidental Size Mismatch Blocked:\n\nNotation '{new_notation}' is already assigned to a different section size ({mismatched_size} mm).\nYou cannot group column stacks of different physical dimensions under the same notation label."
            QMessageBox.critical(self, "Size Validation Failed", err_msg)
            self.log_message(f"Blocked manual override: size mismatch on notation '{new_notation}'")
            return
            
        # Save undo state before modification
        self.save_undo_state()
            
        # Backup for safe reverts
        backup_cols = json.loads(json.dumps(self.matched_columns))
        col['group_notation'] = new_notation
        
        errors = self.matcher.recalculate_groups(self.matched_columns)
        if errors:
            self.matched_columns = backup_cols
            err_msg = "\n".join(errors)
            QMessageBox.critical(self, "Group Recalculation Failed", f"Could not apply notation:\n{err_msg}")
            return
            
        # Log override
        override_entry = f"• {col['frame_name']} ({col['width']:.0f}x{col['depth']:.0f}): {old_notation} ➔ {new_notation}"
        self.manual_overrides_log.append(override_entry)
        self.override_log_view.append(override_entry)
        
        new_color = self.get_column_status_color(col)
        self.sel_notation_lbl.setText(f"Current Notation: {new_notation}")
        
        # Generate the combined multiline label for screen display (using <br> for Plotly compatibility)
        w_cm = col['width'] / 10.0
        d_cm = col['depth'] / 10.0
        if col['shape'] == "Circular":
            label_text = f"{new_notation}<br>D{w_cm:.0f}"
        else:
            label_text = f"{new_notation}<br>{w_cm:.0f}X{d_cm:.0f}"
            
        # UI Refresh: update group summary first, then update dynamic filter buttons (which also filters, sorts, and redraws plan)
        self.update_group_summary()
        self.update_filter_buttons()
        
        # Maintain visual selection highlight
        self.webview.page().runJavaScript(f"highlightColumn('{col['frame_name']}')")
        
        self.log_message(f"Manual override applied: {col['frame_name']} assigned to '{new_notation}'")

    def get_notation_color_string(self, notation):
        """Returns a distinct unique hex color for each naturally sorted notation group."""
        if not notation or notation in ('N/A', 'Default', '-'):
            return "#475569"  # Dark Slate Gray for white background contrast
        if notation == "Exceeded":
            return "#DC2626"  # Stronger Warning Red
            
        # Extract unique sorted list of notation labels
        unique_notations = sorted(
            list(set(c.get('group_notation', '').strip() for c in self.matched_columns if c.get('group_notation', '').strip())),
            key=self.matcher.natural_sort_key
        )
        if notation in unique_notations:
            idx = unique_notations.index(notation) % len(self.NOTATION_COLORS)
            return self.NOTATION_COLORS[idx]
        return "#475569"

    def get_unique_merge_group_ids(self):
        """Returns a deterministic list of unique manual_group_ids in order of appearance."""
        group_ids = []
        if hasattr(self, 'matched_columns') and self.matched_columns:
            for c in self.matched_columns:
                gid = c.get('manual_group_id')
                if gid and gid not in group_ids:
                    group_ids.append(gid)
        return group_ids

    def get_merge_group_colors(self, manual_group_id):
        """Returns dict with 'bg' and 'accent' hex colors for a given manual_group_id."""
        if not manual_group_id:
            return None
        unique_ids = self.get_unique_merge_group_ids()
        if manual_group_id in unique_ids:
            idx = unique_ids.index(manual_group_id) % len(self.MERGE_GROUP_COLORS)
            return self.MERGE_GROUP_COLORS[idx]
        return self.MERGE_GROUP_COLORS[0]

    def get_column_status_color(self, col):
        """Returns the notation group color for success columns, caution red for exceeded."""
        status = col['status']
        if status == 'REINFORCEMENT EXCEEDED':
            return '#DC2626' # Strong Warning Red
        elif status == 'SIZE NOT FOUND':
            return '#D97706' # Darker Amber for high contrast
        else:
            return self.get_notation_color_string(col.get('group_notation', ''))

    def resequence_notations(self, prompt_success=True):
        if not self.matched_columns:
            return False
            
        # 1. Identify all unique group notations that follow the "C<number>" pattern
        unique_notations = set()
        for c in self.matched_columns:
            notation = c.get('group_notation', '').strip()
            if notation and re.match(r"^C\d+$", notation):
                unique_notations.add(notation)
                
        if not unique_notations:
            if prompt_success:
                QMessageBox.information(self, "Resequence Notations", "No standard 'C<number>' notations found to resequence.")
            return False
            
        # 2. Sort the unique notations naturally to determine their correct order
        # (e.g., C1, C2, C9, C11, C12...)
        sorted_notations = sorted(list(unique_notations), key=self.matcher.natural_sort_key)
        
        # 3. Check if they are already sequential starting from C1
        # Expected sequence: C1, C2, C3... up to len(sorted_notations)
        expected_notations = [f"C{i}" for i in range(1, len(sorted_notations) + 1)]
        
        if sorted_notations == expected_notations:
            if prompt_success:
                QMessageBox.information(self, "Resequence Notations", "Column notations are already perfectly sequential. No action needed.")
            return True
            
        # Save undo state before modification
        self.save_undo_state()
            
        # 4. Generate the mapping from old notation to new sequential notation
        mapping = {}
        for idx, old_notation in enumerate(sorted_notations, 1):
            mapping[old_notation] = f"C{idx}"
            
        # 5. Backup current matched columns in case we need to revert
        backup_cols = json.loads(json.dumps(self.matched_columns))
        
        # 6. Apply mapping to all columns
        for c in self.matched_columns:
            notation = c.get('group_notation', '').strip()
            if notation in mapping:
                c['group_notation'] = mapping[notation]
                
        # 7. Recalculate group matching/rebar parameters to ensure everything matches the new notation labels
        errors = self.matcher.recalculate_groups(self.matched_columns)
        if errors:
            self.matched_columns = backup_cols
            err_msg = "\n".join(errors)
            QMessageBox.critical(self, "Resequence Failed", f"Could not resequence notations due to calculation error:\n{err_msg}")
            return False
            
        # 8. Log the changes in the override log
        changes_logged = []
        for old_not, new_not in mapping.items():
            if old_not != new_not:
                log_msg = f"• Resequenced group notation: {old_not} ➔ {new_not}"
                self.manual_overrides_log.append(log_msg)
                self.override_log_view.append(log_msg)
                changes_logged.append(f"{old_not} ➔ {new_not}")
                
        if changes_logged:
            self.log_message(f"Resequenced notations: {', '.join(changes_logged)}")
            
        # 9. Refresh UI components: update group summary first, then update dynamic filter buttons (which also filters, sorts, and redraws plan)
        self.update_group_summary()
        self.update_filter_buttons()
        
        # Clear active selection highlight to avoid old name sync mismatch
        self.selected_frame_name = None
        self.sel_frame_lbl.setText("Frame: None Selected")
        self.sel_size_lbl.setText("Size: N/A")
        self.sel_angle_lbl.setText("Orientation angle: N/A")
        self.sel_rebar_lbl.setText("Required Rebar: N/A")
        self.sel_notation_lbl.setText("Current Notation: N/A")
        self.notation_combo.clear()
        self.notation_combo.setEnabled(False)
        self.apply_override_btn.setEnabled(False)
        self.webview.page().runJavaScript("highlightColumn('')")
        
        if prompt_success:
            QMessageBox.information(
                self, 
                "Resequence Successful", 
                f"Successfully compressed notation gaps!\n\nRenamed:\n" + "\n".join(changes_logged)
            )
        return True

    # ==================== SAVE PROFESSIONAL PDF ====================
    def export_report(self):
        if not self.matched_columns:
            return
            
        if self.execution_mode == "MANUAL" and not self.notations_generated:
            QMessageBox.warning(
                self,
                "Generate Notations Required",
                "Please generate notations (by clicking 'Generate Notations') before exporting the PDF report."
            )
            return
            
        # Scan for sequence gaps
        unique_notations = set()
        for c in self.matched_columns:
            notation = c.get('group_notation', '').strip()
            if notation and re.match(r"^C\d+$", notation):
                unique_notations.add(notation)
                
        if unique_notations:
            sorted_notations = sorted(list(unique_notations), key=self.matcher.natural_sort_key)
            expected_notations = [f"C{i}" for i in range(1, len(sorted_notations) + 1)]
            if sorted_notations != expected_notations:
                ans = QMessageBox.question(
                    self,
                    "Non-Sequential Notations Detected",
                    "We detected gaps or non-sequential numbers in your column group notations (e.g. after manual merging/edits).\n\n"
                    "Would you like to automatically resequence them to C1, C2, C3... (no gaps) before generating the PDF report?\n\n"
                    "(Highly recommended for a professional, polished layout.)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
                )
                if ans == QMessageBox.StandardButton.Cancel:
                    return
                elif ans == QMessageBox.StandardButton.Yes:
                    success = self.resequence_notations(prompt_success=False)
                    if not success:
                        ans_cont = QMessageBox.question(
                            self,
                            "Resequence Failed",
                            "Automatic resequencing failed. Would you like to proceed with exporting the PDF report anyway?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )
                        if ans_cont == QMessageBox.StandardButton.No:
                            return

        default_dir = os.path.dirname(self.model_filepath) if self.model_filepath else os.path.expanduser("~/Documents")
        if not os.path.exists(default_dir):
            default_dir = os.path.expanduser("~/Documents")
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Structural Reconciliation PDF Report",
            os.path.join(default_dir, "Column_Reconciliation_Report.pdf"),
            "PDF Files (*.pdf)"
        )
        
        if not file_path:
            return
            
        try:
            # Report the buffer the results were matched with, not the slider's current position
            buffer_val = self.applied_buffer_pct if self.applied_buffer_pct is not None else 0.0
            report_generator.generate_pdf_report(
                self.matched_columns,
                self.model_filename,
                buffer_val,
                file_path,
                raw_etabs_data=self.raw_etabs_data
            )
            self.log_message(f"Structural report successfully saved to: {file_path}")
            
            ans = QMessageBox.question(
                self,
                "Report Saved Successfully",
                "Your structural auditing PDF report has been generated!\nWould you like to open it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ans == QMessageBox.StandardButton.Yes:
                os.startfile(file_path)
        except Exception as e:
            self.log_message(f"Error compiling PDF report: {e}")
            QMessageBox.critical(self, "Report Compilation Error", f"Could not compile PDF report:\n{e}")

    def open_output_folder(self):
        model_dir = os.path.dirname(self.model_filepath) if self.model_filepath else None
        if model_dir and os.path.exists(model_dir):
            os.startfile(model_dir)
            self.log_message(f"Opened active directory folder: '{model_dir}'")
        else:
            doc_dir = os.path.expanduser("~/Documents")
            os.startfile(doc_dir)
            self.log_message(f"Opened default folder: '{doc_dir}'")

    # ==================== GENERATE INTERACTIVE PLOTLY HTML ====================
    def get_plotly_data(self, columns=None):
        if columns is None:
            columns = self.matched_columns
        x_grids = self.raw_etabs_data.get('x_grids', []) if self.raw_etabs_data else []
        y_grids = self.raw_etabs_data.get('y_grids', []) if self.raw_etabs_data else []
        
        # Always compute global boundaries using ALL matched columns
        # so grid lines and grid labels stay at constant, static positions
        full_cols = self.matched_columns if self.matched_columns else columns
        cols_x = [c['x'] for c in full_cols] if full_cols else []
        cols_y = [c['y'] for c in full_cols] if full_cols else []
        
        if cols_x:
            x_min, x_max = min(cols_x), max(cols_x)
        else:
            x_min, x_max = 0.0, 10.0
            
        if cols_y:
            y_min, y_max = min(cols_y), max(cols_y)
        else:
            y_min, y_max = 0.0, 10.0
            
        pad = 3.0
        
        traces = []
        column_notations_map = {}
        column_coords_map = {}
        original_text_coords = {}
        column_text_index_map = {}
        notation_traces_map = {}
        
        bubble_x = []
        bubble_y = []
        bubble_text = []
        
        grid_lines_x = []
        grid_lines_y = []
        
        def process_grid_val(label, val, is_x=True):
            if is_x:
                grid_lines_x.extend([val, val, None])
                grid_lines_y.extend([y_min - pad, y_max + pad, None])
                bubble_x.extend([val, val])
                bubble_y.extend([y_max + pad + 0.4, y_min - pad - 0.4])
                bubble_text.extend([label, label])
            else:
                grid_lines_x.extend([x_min - pad, x_max + pad, None])
                grid_lines_y.extend([val, val, None])
                bubble_x.extend([x_min - pad - 0.4, x_max + pad + 0.4])
                bubble_y.extend([val, val])
                bubble_text.extend([label, label])
                
        # X Grids
        for g in x_grids:
            if isinstance(g, tuple):
                process_grid_val(g[0], g[1], is_x=True)
            elif isinstance(g, dict):
                g_type = g.get('type')
                g_id = g.get('id', '')
                if g_type == 'X_Cartesian':
                    process_grid_val(g_id, g['ordinate'], is_x=True)
                elif g_type == 'General':
                    grid_lines_x.extend([g['x1'], g['x2'], None])
                    grid_lines_y.extend([g['y1'], g['y2'], None])
                    dx = g['x2'] - g['x1']
                    dy = g['y2'] - g['y1']
                    alpha = math.atan2(dy, dx)
                    bubble_x.extend([g['x1'] - 0.4 * math.cos(alpha), g['x2'] + 0.4 * math.cos(alpha)])
                    bubble_y.extend([g['y1'] - 0.4 * math.sin(alpha), g['y2'] + 0.4 * math.sin(alpha)])
                    bubble_text.extend([g_id, g_id])

        # Y Grids
        for g in y_grids:
            if isinstance(g, tuple):
                process_grid_val(g[0], g[1], is_x=False)
            elif isinstance(g, dict):
                g_type = g.get('type')
                g_id = g.get('id', '')
                if g_type == 'Y_Cartesian':
                    process_grid_val(g_id, g['ordinate'], is_x=False)
                elif g_type == 'General':
                    grid_lines_x.extend([g['x1'], g['x2'], None])
                    grid_lines_y.extend([g['y1'], g['y2'], None])
                    dx = g['x2'] - g['x1']
                    dy = g['y2'] - g['y1']
                    alpha = math.atan2(dy, dx)
                    bubble_x.extend([g['x1'] - 0.4 * math.cos(alpha), g['x2'] + 0.4 * math.cos(alpha)])
                    bubble_y.extend([g['y1'] - 0.4 * math.sin(alpha), g['y2'] + 0.4 * math.sin(alpha)])
                    bubble_text.extend([g_id, g_id])

        # Add single unified WebGL grid trace
        if grid_lines_x:
            traces.append({
                "type": "scattergl",
                "x": grid_lines_x,
                "y": grid_lines_y,
                "mode": "lines",
                "line": {"color": "#CBD5E1", "width": 1.0, "dash": "dash"},
                "hoverinfo": "skip",
                "showlegend": False
            })

        # Bubble markers (WebGL)
        if bubble_x:
            traces.append({
                "type": "scattergl",
                "x": bubble_x,
                "y": bubble_y,
                "mode": "markers+text",
                "marker": {
                    "size": 22,
                    "color": "#1E293B",
                    "line": {"color": "#64748B", "width": 1.5}
                },
                "text": bubble_text,
                "textposition": "middle center",
                "textfont": {"size": 8, "color": "#FFFFFF", "family": "Inter, sans-serif"},
                "hoverinfo": "skip",
                "showlegend": False
            })

        # Columns
        unique_merge_ids = self.get_unique_merge_group_ids()
        polygon_groups = {}
        for c in columns:
            cx = c['x']
            cy = c['y']
            angle = c['angle']
            w = c['width']
            d = c['depth']
            shape = c['shape']
            frame_name = c['frame_name']
            notation = c.get('group_notation', 'N/A')
            
            column_notations_map[frame_name] = notation
            
            status_color = self.get_column_status_color(c)
            
            is_merged = c.get('manual_group_id') is not None
            gid = c.get('manual_group_id')
            merge_colors = self.get_merge_group_colors(gid) if is_merged else None
            
            if is_merged and gid in unique_merge_ids:
                group_num = unique_merge_ids.index(gid) + 1
                merged_status = f"<b>[Merged Group #{group_num} ✓]</b> "
            else:
                merged_status = ""
            
            hover_text = (
                f"<b>Column: {frame_name} {merged_status}</b><br>"
                f"Story Range: {c['story_name']}<br>"
                f"Grid Label: {c['grid_label']}<br>"
                f"Dimensions: {w:.0f} x {d:.0f} mm ({shape})<br>"
                f"Orientation Angle: {angle:.1f}°<br>"
                f"Required Rebar: {c['rebar_pct']:.2f}%<br>"
                f"Suggested CAD: {c['suggested_id']}<br>"
                f"Provided Rebar %: {c['cad_pct']:.2f}%<br>"
                f"Efficiency Index: {c['efficiency']:.1f}%"
            )
            
            rx = []
            ry = []
            if shape == "Circular":
                r = (w / 1000.0) / 2.0
                steps = 32
                for step in range(steps + 1):
                    theta = 2.0 * math.pi * step / steps
                    rx.append(cx + r * math.cos(theta))
                    ry.append(cy + r * math.sin(theta))
            else:
                alpha = math.radians(angle + 90)
                hw = (w / 1000.0) / 2.0
                hd = (d / 1000.0) / 2.0
                
                corners = [
                    (-hw, -hd),
                    (hw, -hd),
                    (hw, hd),
                    (-hw, hd),
                    (-hw, -hd)
                ]
                
                for dx, dy in corners:
                    rx.append(cx + dx * math.cos(alpha) - dy * math.sin(alpha))
                    ry.append(cy + dx * math.sin(alpha) + dy * math.cos(alpha))
                    
            column_coords_map[frame_name] = {"x": rx, "y": ry}
            
            line_color = merge_colors["accent"] if (is_merged and merge_colors) else status_color
            line_width = 3.5 if is_merged else 1.5
            fill_color = self.hex_to_rgba(merge_colors["accent"], 0.20) if (is_merged and merge_colors) else self.hex_to_rgba(status_color, 0.25)
            
            key = (notation, shape, line_color, is_merged, gid)
            if key not in polygon_groups:
                polygon_groups[key] = {
                    "x": [],
                    "y": [],
                    "hovertext": [],
                    "customdata": [],
                    "notation": notation,
                    "color": line_color,
                    "line_width": line_width,
                    "fill_color": fill_color
                }
            
            polygon_groups[key]["x"].extend(rx + [None])
            polygon_groups[key]["y"].extend(ry + [None])
            
            n_points = len(rx) + 1
            polygon_groups[key]["hovertext"].extend([hover_text] * n_points)
            polygon_groups[key]["customdata"].extend([{"frame_name": frame_name}] * n_points)

        # Append consolidated polygon traces (WebGL)
        for key, g in polygon_groups.items():
            notation, shape, color, is_merged, gid = key
            trace_idx = len(traces)
            
            if notation not in notation_traces_map:
                notation_traces_map[notation] = []
            notation_traces_map[notation].append(trace_idx)
            
            name_suffix = f" [Merged Group #{unique_merge_ids.index(gid)+1}]" if (is_merged and gid in unique_merge_ids) else ""
            
            traces.append({
                "type": "scattergl",
                "x": g["x"],
                "y": g["y"],
                "fill": "toself",
                "fillcolor": g["fill_color"],
                "line": {"color": g["color"], "width": g["line_width"]},
                "mode": "lines",
                "name": f"Group {notation} ({shape})" + name_suffix,
                "hoveron": "fills+points",
                "hoverinfo": "text",
                "text": g["hovertext"],
                "hoverlabel": {
                    "bgcolor": "#1E293B",
                    "bordercolor": g["color"],
                    "font": {"color": "#E2E8F0", "family": "Inter, sans-serif", "size": 11}
                },
                "customdata": g["customdata"],
                "showlegend": False
            })

        # Append consolidated text label trace (isolated WebGL mode='text')
        text_trace_x = []
        text_trace_y = []
        text_trace_text = []
        text_trace_colors = []
        text_trace_hover = []
        text_trace_customdata = []
        
        for idx, c in enumerate(columns):
            cx = c['x']
            cy = c['y']
            angle = c['angle']
            w = c['width']
            d = c['depth']
            shape = c['shape']
            frame_name = c['frame_name']
            notation = c.get('group_notation', '').strip()
            
            status_color = self.get_column_status_color(c)
            
            is_merged = c.get('manual_group_id') is not None
            gid = c.get('manual_group_id')
            merge_colors = self.get_merge_group_colors(gid) if is_merged else None
            
            merge_mark = " ✓" if is_merged else ""
            if is_merged and gid in unique_merge_ids:
                group_num = unique_merge_ids.index(gid) + 1
                merged_status = f"<b>[Merged Group #{group_num} ✓]</b> "
            else:
                merged_status = ""
            
            if self.execution_mode == "MANUAL" and not self.notations_generated:
                if shape == "Circular":
                    y_extent = (w / 1000.0) / 2.0
                    label_text = f"C-D{w/10.0:.0f}{merge_mark}"
                else:
                    alpha = math.radians(angle + 90)
                    hw = (w / 1000.0) / 2.0
                    hd = (d / 1000.0) / 2.0
                    y_extent = abs(hw * math.sin(alpha)) + abs(hd * math.cos(alpha))
                    label_text = f"C-{w/10.0:.0f}X{d/10.0:.0f}{merge_mark}"
            else:
                notation_display = notation if notation else "N/A"
                if shape == "Circular":
                    y_extent = (w / 1000.0) / 2.0
                    label_text = f"{notation_display}{merge_mark}<br>D{w/10.0:.0f}"
                else:
                    alpha = math.radians(angle + 90)
                    hw = (w / 1000.0) / 2.0
                    hd = (d / 1000.0) / 2.0
                    y_extent = abs(hw * math.sin(alpha)) + abs(hd * math.cos(alpha))
                    label_text = f"{notation_display}{merge_mark}<br>{w/10.0:.0f}X{d/10.0:.0f}"
                
            cy_text = cy - y_extent - 0.55
            
            hover_text = (
                f"<b>Column: {frame_name} {merged_status}</b><br>"
                f"Story Range: {c['story_name']}<br>"
                f"Grid Label: {c['grid_label']}<br>"
                f"Dimensions: {w:.0f} x {d:.0f} mm ({shape})<br>"
                f"Orientation Angle: {angle:.1f}°<br>"
                f"Required Rebar: {c['rebar_pct']:.2f}%<br>"
                f"Suggested CAD: {c['suggested_id']}<br>"
                f"Provided Rebar %: {c['cad_pct']:.2f}%<br>"
                f"Efficiency Index: {c['efficiency']:.1f}%"
            )
            
            text_trace_x.append(cx)
            text_trace_y.append(cy_text)
            text_trace_text.append(label_text)
            text_color = merge_colors["accent"] if (is_merged and merge_colors) else status_color
            text_trace_colors.append(text_color)
            text_trace_hover.append(hover_text)
            text_trace_customdata.append({"frame_name": frame_name})
            
            original_text_coords[frame_name] = {"x": cx, "y": cy_text}
            column_text_index_map[frame_name] = idx

        text_trace_idx = len(traces)
        traces.append({
            "type": "scatter",
            "x": text_trace_x,
            "y": text_trace_y,
            "mode": "text",
            "text": text_trace_text,
            "textposition": "bottom center",
            "textfont": {
                "size": 8,
                "color": text_trace_colors,
                "family": "Inter, sans-serif",
                "weight": "bold"
            },
            "name": "Column Labels",
            "hoverinfo": "text",
            "hovertext": text_trace_hover,
            "hoverlabel": {
                "bgcolor": "#1E293B",
                "bordercolor": "#2563EB",
                "font": {"color": "#E2E8F0", "family": "Inter, sans-serif", "size": 11}
            },
            "customdata": text_trace_customdata,
            "showlegend": True
        })

        # Selection Highlight Trace
        selection_highlight_idx = len(traces)
        traces.append({
            "type": "scatter",
            "x": [],
            "y": [],
            "fill": "toself",
            "fillcolor": "rgba(37, 99, 235, 0.15)",
            "line": {"color": "#2563EB", "width": 4.0},
            "mode": "lines",
            "name": "Selection Highlight",
            "hoverinfo": "skip",
            "showlegend": False,
            "visible": False
        })
        
        # Group Highlight Trace
        group_highlight_idx = len(traces)
        traces.append({
            "type": "scatter",
            "x": [],
            "y": [],
            "fill": "toself",
            "fillcolor": "rgba(37, 99, 235, 0.08)",
            "line": {"color": "#2563EB", "width": 3.0, "dash": "dash"},
            "mode": "lines",
            "name": "Group Highlight",
            "hoverinfo": "skip",
            "showlegend": False,
            "visible": False
        })

        layout = {
            "plot_bgcolor": "#FFFFFF",
            "paper_bgcolor": "#FFFFFF",
            "margin": {"l": 20, "r": 20, "t": 20, "b": 20},
            "xaxis": {
                "showgrid": False,
                "zeroline": False,
                "showticklabels": False,
                "range": [x_min - pad - 1.0, x_max + pad + 1.0]
            },
            "yaxis": {
                "showgrid": False,
                "zeroline": False,
                "showticklabels": False,
                "range": [y_min - pad - 1.0, y_max + pad + 1.0],
                "scaleanchor": "x",
                "scaleratio": 1.0
            },
            "dragmode": "pan",
            "hovermode": "closest",
            "showlegend": True,
            "legend": {
                "x": 1.02,
                "y": 1,
                "xanchor": "left",
                "yanchor": "top",
                "bgcolor": "rgba(255, 255, 255, 0.9)",
                "bordercolor": "#CBD5E1",
                "borderwidth": 1,
                "font": {"family": "Inter, sans-serif", "size": 10, "color": "#1E293B"}
            }
        }
        
        return {
            "traces": traces,
            "layout": layout,
            "notation_traces_map": notation_traces_map,
            "column_notations_map": column_notations_map,
            "column_coords_map": column_coords_map,
            "original_text_coords": original_text_coords,
            "column_text_index_map": column_text_index_map,
            "text_trace_idx": text_trace_idx,
            "selection_highlight_idx": selection_highlight_idx,
            "group_highlight_idx": group_highlight_idx
        }

    def generate_plotly_html(self):
        d_res = self.get_plotly_data()
        
        html_template = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <title>Structural Plan Layout</title>
    <!-- Try loading local plotly.min.js first, fall back to online CDN if offline load fails -->
    <script src="plotly.min.js"></script>
    <script>
        if (typeof Plotly === 'undefined') {
            console.warn("Local plotly.min.js not found or blocked. Falling back to CDN...");
            var script = document.createElement('script');
            script.src = "https://cdn.plot.ly/plotly-2.24.1.min.js";
            document.head.appendChild(script);
        } else {
            console.log("Successfully loaded local offline plotly.min.js");
        }
    </script>
    <script type="text/javascript" src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
        body {
            margin: 0;
            padding: 0;
            background-color: #FFFFFF;
            color: #0F172A;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            overflow: hidden;
            width: 100vw;
            height: 100vh;
        }
        #plot-div {
            width: 100vw;
            height: 100vh;
        }
        #plot-div g.textpoint text {
            font-size: var(--zoom-font-size, 8px) !important;
        }
        .modebar-container {
            right: 15px !important;
            top: 15px !important;
        }
        #error-banner {
            display: none;
            position: absolute;
            top: 10px;
            left: 10px;
            right: 10px;
            background-color: #FEE2E2;
            border: 1px solid #FCA5A5;
            color: #991B1B;
            padding: 12px 16px;
            border-radius: 6px;
            font-size: 13px;
            z-index: 99999;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }
    </style>
</head>
<body>
    <div id="error-banner">
        <strong>⚠️ Structural Plot Loading Error:</strong>
        <span id="error-message"></span>
    </div>
    <div id="plot-div"></div>
    <script>
        window.plotLoaded = false;
        // Global Javascript error boundary
        window.onerror = function(message, source, lineno, colno, error) {
            var errStack = (error && error.stack) ? "\\nStack: " + error.stack : "";
            console.error("JS Error captured: " + message + " at " + source + ":" + lineno + errStack);
            var banner = document.getElementById('error-banner');
            if (banner) {
                banner.style.display = 'block';
                var msgSpan = document.getElementById('error-message');
                if (msgSpan) {
                    msgSpan.textContent = message + " (Line: " + lineno + ", File: " + (source ? source.split('/').pop() : 'unknown') + ")" + (error ? " [See console log for stack trace]" : "");
                }
            }
            return false;
        };
        var plotData = {PLOT_DATA};
        var plotLayout = {PLOT_LAYOUT};
        var notationTracesMap = {NOTATION_TRACES_MAP};
        var columnNotationsMap = {NOTATIONS_MAP};
        var columnCoordsMap = {COORDS_MAP};
        var originalTextCoords = {TEXT_COORDS};
        var columnTextIndexMap = {TEXT_INDEX_MAP};
        var textTraceIndex = {TEXT_TRACE_IDX};
        var selectionHighlightIndex = {SEL_HIGHLIGHT_IDX};
        var groupHighlightIndex = {GRP_HIGHLIGHT_IDX};
        var currentSelectedFrame = "";
        var selectedFrames = [];
        
        Plotly.newPlot('plot-div', plotData, plotLayout, {
            responsive: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['autoScale2d'],
            modeBarButtonsToAdd: [{
                name: 'Maximize/Restore Plan View',
                icon: {
                    'width': 1000,
                    'height': 1000,
                    'path': 'M100 100h300v100H200v200H100V100zm800 0H600v100h200v200h100V100zM100 900h300v-100H200v-200H100v300zm800 0H600v-100h200v-200h100v300z'
                },
                click: function(gd) {
                    if (pyconnector) {
                        pyconnector.toggle_maximize();
                    }
                }
            }],
            doubleClick: 'reset',
            scrollZoom: true
        }).then(function() {
            window.plotLoaded = true;
            console.log("Initial Plotly.newPlot finished successfully.");
        });

        // Initialize QWebChannel
        var pyconnector = null;
        if (typeof qt !== 'undefined') {
            new QWebChannel(qt.webChannelTransport, function (channel) {
                pyconnector = channel.objects.pyconnector;
                console.log("QWebChannel established successfully.");
            });
        }

        function highlightMultipleColumns(frameNames) {
            if (!window.plotLoaded) return;
            var highlightX = [];
            var highlightY = [];
            
            for (var i = 0; i < frameNames.length; i++) {
                var fName = frameNames[i];
                var coords = columnCoordsMap[fName];
                if (coords) {
                    highlightX = highlightX.concat(coords.x).concat([null]);
                    highlightY = highlightY.concat(coords.y).concat([null]);
                }
            }
            
            if (highlightX.length > 0) {
                Plotly.restyle('plot-div', {
                    'x': [highlightX],
                    'y': [highlightY],
                    'visible': [true]
                }, [selectionHighlightIndex]);
            } else {
                Plotly.restyle('plot-div', {
                    'x': [[]],
                    'y': [[]],
                    'visible': [false]
                }, [selectionHighlightIndex]);
            }
        }

        function highlightColumn(frameName) {
            if (!window.plotLoaded) return;
            currentSelectedFrame = frameName;
            if (frameName) {
                highlightMultipleColumns([frameName]);
            } else {
                highlightMultipleColumns([]);
            }
        }

        function highlightGroup(groupNotation) {
            if (!window.plotLoaded) return;
            currentSelectedFrame = "";
            // Clear single selection highlight
            Plotly.restyle('plot-div', {
                'x': [[]],
                'y': [[]],
                'visible': [false]
            }, [selectionHighlightIndex]);

            // Draw group outline path (separated by nulls)
            var groupX = [];
            var groupY = [];
            
            for (var frame in columnCoordsMap) {
                if (columnNotationsMap[frame] === groupNotation) {
                    var coords = columnCoordsMap[frame];
                    groupX = groupX.concat(coords.x).concat([null]);
                    groupY = groupY.concat(coords.y).concat([null]);
                }
            }
            
            if (groupX.length > 0) {
                Plotly.restyle('plot-div', {
                    'x': [groupX],
                    'y': [groupY],
                    'visible': [true]
                }, [groupHighlightIndex]);
            } else {
                Plotly.restyle('plot-div', {
                    'x': [[]],
                    'y': [[]],
                    'visible': [false]
                }, [groupHighlightIndex]);
            }
        }

        function filterColumnsByNotations(activeNotations) {
            if (!window.plotLoaded) return;
            var showAll = (activeNotations.length === 0);
            
            // 1. Toggle visibility of grouped polygon traces
            var traceIndices = [];
            var visibilities = [];
            
            for (var notation in notationTracesMap) {
                var traces = notationTracesMap[notation];
                var isVisible = showAll || activeNotations.indexOf(notation) !== -1;
                for (var i = 0; i < traces.length; i++) {
                    traceIndices.push(traces[i]);
                    visibilities.push(isVisible ? true : 'legendonly');
                }
            }
            
            if (traceIndices.length > 0) {
                Plotly.restyle('plot-div', {
                    'visible': visibilities
                }, traceIndices);
            }
            
            // 2. Hide text markers of non-matching columns by setting coordinate values to null
            var textX = [];
            var textY = [];
            
            var textCustomData = plotData[textTraceIndex].customdata;
            for (var i = 0; i < textCustomData.length; i++) {
                var fName = textCustomData[i].frame_name;
                var notation = columnNotationsMap[fName];
                var isVisible = showAll || activeNotations.indexOf(notation) !== -1;
                
                if (isVisible) {
                    var orig = originalTextCoords[fName];
                    textX.push(orig.x);
                    textY.push(orig.y);
                } else {
                    textX.push(null);
                    textY.push(null);
                }
            }
            
            Plotly.restyle('plot-div', {
                'x': [textX],
                'y': [textY]
            }, [textTraceIndex]);
        }

        function reactPlot(newData, newTraceMap, newNotationsMap, newCoordsMap, newTextCoords, newTextIndexMap, newTextTraceIdx, newSelHighlightIdx, newGrpHighlightIdx) {
            plotData = newData;
            notationTracesMap = newTraceMap;
            columnNotationsMap = newNotationsMap;
            columnCoordsMap = newCoordsMap;
            originalTextCoords = newTextCoords;
            columnTextIndexMap = newTextIndexMap;
            if (newTextTraceIdx !== undefined) textTraceIndex = newTextTraceIdx;
            if (newSelHighlightIdx !== undefined) selectionHighlightIndex = newSelHighlightIdx;
            if (newGrpHighlightIdx !== undefined) groupHighlightIndex = newGrpHighlightIdx;
            
            if (window.plotLoaded) {
                Plotly.react('plot-div', plotData, plotLayout);
                highlightMultipleColumns(selectedFrames);
            }
        }

        var plotEl = document.getElementById('plot-div');
        plotEl.on('plotly_click', function(data) {
            if (data.points && data.points.length > 0) {
                var pt = data.points[0];
                if (pt.customdata && pt.customdata.frame_name) {
                    var fName = pt.customdata.frame_name;
                    var ctrlPressed = (data.event && (data.event.ctrlKey || data.event.metaKey));
                    
                    if (ctrlPressed) {
                        var idx = selectedFrames.indexOf(fName);
                        if (idx > -1) {
                            selectedFrames.splice(idx, 1);
                        } else {
                            selectedFrames.push(fName);
                        }
                    } else {
                        selectedFrames = [fName];
                    }
                    
                    highlightMultipleColumns(selectedFrames);
                    if (pyconnector) {
                        pyconnector.select_multiple_columns(selectedFrames.join(","));
                    }
                }
            }
        });

        plotEl.on('plotly_selected', function(eventData) {
            if (eventData && eventData.points && eventData.points.length > 0) {
                var frames = [];
                for (var i = 0; i < eventData.points.length; i++) {
                    var pt = eventData.points[i];
                    if (pt.customdata && pt.customdata.frame_name) {
                        if (frames.indexOf(pt.customdata.frame_name) === -1) {
                            frames.push(pt.customdata.frame_name);
                        }
                    }
                }
                selectedFrames = frames;
                highlightMultipleColumns(selectedFrames);
                if (pyconnector) {
                    pyconnector.select_multiple_columns(selectedFrames.join(","));
                }
            } else {
                selectedFrames = [];
                highlightMultipleColumns([]);
                if (pyconnector) {
                    pyconnector.select_multiple_columns("");
                }
            }
        });

        plotEl.on('plotly_doubleclick', function() {
            selectedFrames = [];
            highlightMultipleColumns([]);
            if (pyconnector) {
                pyconnector.select_multiple_columns("");
            }
        });

        // Dynamic CAD/PDF-style Zoom Font Scaling using performant CSS Variables
        var initialXRange = plotLayout.xaxis.range;
        var initialRangeWidth = initialXRange[1] - initialXRange[0];
        var baseFontSize = 8;
        var animationFrameId = null;

        plotEl.on('plotly_relayout', function(eventData) {
            var currentRange = plotEl.layout.xaxis.range;
            if (currentRange && currentRange.length >= 2) {
                var currentWidth = currentRange[1] - currentRange[0];
                var zoomFactor = initialRangeWidth / currentWidth;
                
                var newSize = baseFontSize * zoomFactor;
                newSize = Math.max(4, Math.min(36, newSize));
                
                if (animationFrameId) {
                    cancelAnimationFrame(animationFrameId);
                }
                animationFrameId = requestAnimationFrame(function() {
                    plotEl.style.setProperty('--zoom-font-size', newSize + 'px');
                });
            }
        });

        // Let ESC key clear the selection in the plan view
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape' || event.key === 'Esc' || event.keyCode === 27) {
                console.log("Escape key pressed: clearing box/lasso selection.");
                selectedFrames = [];
                highlightMultipleColumns([]);
                if (pyconnector) {
                    pyconnector.select_multiple_columns("");
                }
                if (window.plotLoaded) {
                    try {
                        console.log("Plot layout before clear: " + JSON.stringify(plotEl.layout));
                        
                        // Preserve current zoom/pan range
                        if (plotEl.layout && plotEl.layout.xaxis && plotEl.layout.xaxis.range) {
                            plotLayout.xaxis.range = plotEl.layout.xaxis.range;
                        }
                        if (plotEl.layout && plotEl.layout.yaxis && plotEl.layout.yaxis.range) {
                            plotLayout.yaxis.range = plotEl.layout.yaxis.range;
                        }
                        
                        // Clear layout selections (box/lasso outlines) from layout object
                        plotLayout.selections = [];
                        if (plotEl.layout) {
                            plotEl.layout.selections = [];
                        }
                        
                        // Clear selected points on all traces explicitly (using null instead of delete)
                        if (plotData) {
                            for (var i = 0; i < plotData.length; i++) {
                                if (plotData[i]) {
                                    plotData[i].selectedpoints = null;
                                }
                            }
                        }
                        
                        // Log SVG zoomlayer contents to PyQt console
                        var zoomLayer = plotEl.querySelector('.zoomlayer');
                        if (zoomLayer) {
                            console.log("Zoomlayer HTML content before cleaning: " + zoomLayer.innerHTML);
                            // Manually clear selection shapes from the DOM
                            var outlines = zoomLayer.querySelectorAll('.select-outline, [class*="select-outline"], rect, path');
                            console.log("Found " + outlines.length + " outline elements to remove.");
                            outlines.forEach(function(el) {
                                el.remove();
                            });
                        }
                        
                        // Re-render plot
                        console.log("Invoking Plotly.react...");
                        Plotly.react('plot-div', plotData, plotLayout);
                        console.log("Plotly.react finished.");
                        
                        // Restore highlights
                        highlightMultipleColumns(selectedFrames);
                    } catch (err) {
                        console.error("CRITICAL: Error in ESC handler: " + err.message + "\\nStack: " + err.stack);
                    }
                }
            }
        });
    </script>
</body>
</html>"""
        
        html_content = (html_template
                        .replace("{PLOT_DATA}", json.dumps(d_res["traces"]))
                        .replace("{PLOT_LAYOUT}", json.dumps(d_res["layout"]))
                        .replace("{NOTATION_TRACES_MAP}", json.dumps(d_res["notation_traces_map"]))
                        .replace("{NOTATIONS_MAP}", json.dumps(d_res["column_notations_map"]))
                        .replace("{COORDS_MAP}", json.dumps(d_res["column_coords_map"]))
                        .replace("{TEXT_COORDS}", json.dumps(d_res["original_text_coords"]))
                        .replace("{TEXT_INDEX_MAP}", json.dumps(d_res["column_text_index_map"]))
                        .replace("{TEXT_TRACE_IDX}", str(d_res["text_trace_idx"]))
                        .replace("{SEL_HIGHLIGHT_IDX}", str(d_res["selection_highlight_idx"]))
                        .replace("{GRP_HIGHLIGHT_IDX}", str(d_res["group_highlight_idx"])))
        
        return html_content

    def hex_to_rgba(self, hex_val, alpha):
        h = hex_val.lstrip('#')
        rgb = tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
        return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha})"

    def merge_selected_columns(self):
        if not self.matched_columns:
            return
            
        selected_frames = getattr(self, 'selected_frame_names', [])
        if len(selected_frames) < 2:
            QMessageBox.warning(self, "Selection Required", "Please select at least 2 columns to merge.\n(Use Ctrl+Click in the table/plan, or Box Select on the plan.)")
            return
            
        selected_cols = [c for c in self.matched_columns if c['frame_name'] in selected_frames]
        
        # Check size mismatch
        sizes = set((round(c['width']), round(c['depth'])) for c in selected_cols)
        if len(sizes) > 1:
            QMessageBox.warning(
                self, 
                "Size Mismatch Blocked", 
                f"Selected columns must have the same cross-sectional size to be merged.\nFound sizes: {list(sizes)}"
            )
            return
            
        # Save undo state before modification
        self.save_undo_state()
            
        # Find maximum cad_pct among selection to determine the group design envelope
        max_cad_col = max(selected_cols, key=lambda c: c['cad_pct'])
        target_cad_id = max_cad_col['suggested_id']
        target_cad_pct = max_cad_col['cad_pct']
        target_cad_area = max_cad_col['cad_area']
        target_rebar_callout = max_cad_col['rebar_callout']
        target_status = max_cad_col['status']
        target_reason = max_cad_col['reason']
        
        # Resolve group ID (merge existing group IDs if any selected column already belongs to a manual group)
        existing_group_ids = set(c.get('manual_group_id') for c in selected_cols if c.get('manual_group_id'))
        if existing_group_ids:
            group_id = list(existing_group_ids)[0]
        else:
            group_id = f"g_{datetime.now().strftime('%Y%m%d%H%M%S')}_{selected_cols[0]['frame_name']}"
            
        # Apply worst-case suggestion parameters to all columns in the merged group
        merged_frames = []
        for c in self.matched_columns:
            if c['frame_name'] in selected_frames or (c.get('manual_group_id') in existing_group_ids and c.get('manual_group_id') is not None):
                c['manual_group_id'] = group_id
                c['suggested_id'] = target_cad_id
                c['cad_pct'] = target_cad_pct
                c['cad_area'] = target_cad_area
                c['rebar_callout'] = target_rebar_callout
                c['status'] = target_status
                c['reason'] = target_reason
                if target_cad_pct > 0.0:
                    c['efficiency'] = min(100.0, (c['rebar_pct'] / target_cad_pct) * 100.0)
                else:
                    c['efficiency'] = 100.0
                merged_frames.append(c['frame_name'])
                
        # Log the merge action
        log_entry = f"• Merged columns {merged_frames} to group suggested CAD: '{target_cad_id}' ({target_cad_pct:.2f}%)"
        self.manual_overrides_log.append(log_entry)
        self.override_log_view.append(log_entry)
        self.log_message(f"Merged columns successfully: {selected_frames}")
        
        # Clear selections and refresh schedule views
        self.results_table.clearSelection()
        self.selected_frame_names = []
        
        self.update_results_grid()
        self.webview.page().runJavaScript("highlightMultipleColumns([])")
        
        QMessageBox.information(
            self,
            "Columns Merged",
            f"Successfully merged {len(selected_frames)} columns!\n\nSuggested CAD assigned: {target_cad_id} ({target_rebar_callout})"
        )

    def generate_manual_notations(self):
        if not self.matched_columns:
            return
            
        # Save undo state before modification
        self.save_undo_state()
            
        # 1. Backup old notations to track changes
        old_notations = {c['frame_name']: c.get('group_notation', '') for c in self.matched_columns}
        
        # 2. Distinguish success and non-conforming columns
        conforming_cols = [c for c in self.matched_columns if c['status'] == 'SUCCESS']
        non_conforming_cols = [c for c in self.matched_columns if c['status'] != 'SUCCESS']
        
        # 3. Group conforming columns by manual_group_id (or frame_name if size 1)
        groups = {}
        for c in conforming_cols:
            g_id = c.get('manual_group_id')
            if not g_id:
                g_id = f"single_{c['frame_name']}"
            if g_id not in groups:
                groups[g_id] = []
            groups[g_id].append(c)
            
        # 4. Sort groups by section area (size) ascending, then by maximum CAD rebar percentage ascending
        def group_sort_key(item):
            g_id, cols = item
            first_col = cols[0]
            area = first_col['width'] * first_col['depth']
            max_cad_pct = max(c['cad_pct'] for c in cols)
            return (area, max_cad_pct)
            
        sorted_groups = sorted(groups.items(), key=group_sort_key)
        
        # 5. Assign sequential C-notations C1, C2, C3...
        notation_counter = 1
        for g_id, cols in sorted_groups:
            notation_label = f"C{notation_counter}"
            notation_counter += 1
            for c in cols:
                c['group_notation'] = notation_label
                
        # 6. Non-conforming columns do not get standard sequential notations
        for c in non_conforming_cols:
            c['group_notation'] = "Exceeded" if c['status'] == 'REINFORCEMENT EXCEEDED' else "N/A"
            
        # 7. Compare and log changed notations
        changes_log = []
        seen_shifts = set()
        unique_shifts = []
        for c in self.matched_columns:
            f_name = c['frame_name']
            old_not = old_notations.get(f_name, '').strip()
            new_not = c.get('group_notation', '').strip()
            if old_not and old_not != new_not and old_not not in ('N/A', 'Exceeded', '', '-'):
                changes_log.append(f"• {f_name}: {old_not} ➔ {new_not}")
                shift_pair = (old_not, new_not)
                if shift_pair not in seen_shifts:
                    seen_shifts.add(shift_pair)
                    unique_shifts.append(shift_pair)
                
        if changes_log:
            self.override_log_view.append("<b>[Notation Shifts Log]</b>")
            for change in changes_log:
                self.override_log_view.append(change)
                self.manual_overrides_log.append(change)
                
        self.notations_generated = True
        
        # 8. Unhide and show override and groups cards in the right panel
        self.override_card.setVisible(True)
        self.groups_card.setVisible(True)
        
        # 9. Refresh results grid (unhides column 0 in table, updates filters)
        self.update_results_grid()
        
        # 10. Enable resequence button
        self.resequence_btn.setEnabled(True)
        
        self.log_message(f"Manually triggered notations generated successfully. Groups: {notation_counter - 1}")
        
        if changes_log:
            # Sort unique shifts naturally by the old notation for clean presentation
            unique_shifts.sort(key=lambda pair: self.matcher.natural_sort_key(pair[0]))
            pop_up_shifts = [f"• {old} ➔ {new}" for old, new in unique_shifts]
            
            QMessageBox.information(
                self,
                "Notations Generated",
                f"Notations generated successfully!\n\nSome column notations have shifted:\n" + "\n".join(pop_up_shifts)
            )
        else:
            QMessageBox.information(
                self,
                "Notations Generated",
                "Notations generated successfully!"
            )

    def save_undo_state(self):
        if not hasattr(self, 'undo_stack'):
            self.undo_stack = []
        # Store a deep copy of self.matched_columns and other relevant states
        state = {
            'matched_columns': json.loads(json.dumps(self.matched_columns)),
            'notations_generated': self.notations_generated,
            'manual_overrides_log': list(self.manual_overrides_log),
            'override_log_view_html': self.override_log_view.toHtml() if hasattr(self, 'override_log_view') else ""
        }
        self.undo_stack.append(state)
        # Limit stack size to 50 to prevent excessive memory consumption
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)
        # Enable undo button
        if hasattr(self, 'undo_btn'):
            self.undo_btn.setEnabled(True)

    def undo_last_change(self):
        if not hasattr(self, 'undo_stack') or not self.undo_stack:
            return
            
        state = self.undo_stack.pop()
        
        # Restore state
        self.matched_columns = state['matched_columns']
        self.notations_generated = state['notations_generated']
        self.manual_overrides_log = state['manual_overrides_log']
        if hasattr(self, 'override_log_view') and state['override_log_view_html']:
            self.override_log_view.setHtml(state['override_log_view_html'])
            
        # Update undo button enabled state
        if hasattr(self, 'undo_btn'):
            self.undo_btn.setEnabled(len(self.undo_stack) > 0)
            
        # Refresh results schedule views
        self.update_results_grid()
        self.update_group_summary()
        self.update_filter_buttons()
        
        # Update visibility of panels/columns based on notations_generated
        if self.execution_mode == "MANUAL":
            self.results_table.setColumnHidden(0, not self.notations_generated)
            self.override_card.setVisible(self.notations_generated)
            self.groups_card.setVisible(self.notations_generated)
            
            self.notation_lbl.setVisible(self.notations_generated)
            self.notation_buttons_container.setVisible(self.notations_generated)
            self.resequence_btn.setEnabled(self.notations_generated)
            
        # Clear/refresh selection
        self.selected_frame_names = []
        self.results_table.clearSelection()
        self.webview.page().runJavaScript("highlightMultipleColumns([])")
        
        self.log_message("Undone last manual change.")





if __name__ == "__main__":
    # Hide initial console window on Windows if run via python.exe
    if sys.platform == "win32":
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
            
    app = QApplication(sys.argv)
    
    font = QFont("Inter")
    if not font.exactMatch():
        font = QFont("Segoe UI")
    app.setFont(font)
    
    window = ColumnDetailerApp()
    window.showMaximized()
    sys.exit(app.exec())

"""Tema oscuro tipo consola broadcast (inspirado en la distribución de XPlayout)."""

BG = "#1b1b1b"
PANEL = "#242424"
PANEL2 = "#2c2c2c"
BORDER = "#0e0e0e"
BORDER_LIGHT = "#3d3d3d"
TEXT = "#dcdcdc"
TEXT_DIM = "#9a9a9a"
ACCENT = "#e5871e"      # naranja Axel-like para valores en curso
ONAIR = "#d61e1e"
GREEN = "#4be36a"
BLUE_ROW = "#2f63c5"

QSS = f"""
* {{
    font-family: "Segoe UI", "Noto Sans", "DejaVu Sans", Arial, sans-serif;
    font-size: 12px;
    color: {TEXT};
}}
QMainWindow, QDialog, QWidget#root {{
    background: {BG};
}}
QWidget#panel {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 4px;
}}
QWidget#panelDark {{
    background: #141414;
    border: 1px solid {BORDER};
    border-radius: 4px;
}}
QLabel#appTitle {{
    font-size: 22px; font-weight: bold; color: #f2f2f2; letter-spacing: 1px;
}}
QLabel#appSub {{
    font-size: 9px; color: {TEXT_DIM};
}}
QLabel#dateLabel {{
    font-size: 15px; font-weight: bold; color: #f0f0f0;
}}
QLabel#clipTitle {{
    font-size: 15px; font-weight: bold; color: {GREEN};
    background: #101010; border: 1px solid {BORDER}; border-radius: 3px; padding: 2px 6px;
}}
QLabel#clipPath, QLabel#clipInfo {{
    color: #bdbdbd; font-size: 11px;
}}
QLabel#fieldName {{
    color: {TEXT_DIM}; font-size: 10px; font-weight: bold;
}}
QLabel#fieldValue {{
    background: #0d0d0d; color: #f4f4f4; border: 1px solid #060606; border-radius: 3px;
    padding: 3px 8px; font-size: 14px; font-weight: bold;
    font-family: "Consolas", "DejaVu Sans Mono", "Courier New", monospace;
}}
QLabel#fieldValueAccent {{
    background: #0d0d0d; color: {ACCENT}; border: 1px solid #060606; border-radius: 3px;
    padding: 3px 8px; font-size: 14px; font-weight: bold;
    font-family: "Consolas", "DejaVu Sans Mono", "Courier New", monospace;
}}
QLabel#fieldValueGreen {{
    background: #0d0d0d; color: {GREEN}; border: 1px solid #060606; border-radius: 3px;
    padding: 3px 8px; font-size: 14px; font-weight: bold;
    font-family: "Consolas", "DejaVu Sans Mono", "Courier New", monospace;
}}
QLabel#sectionTitle {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #3a3a3a, stop:1 #262626);
    color: #e8e8e8; font-size: 10px; font-weight: bold; padding: 3px 8px;
    border: 1px solid {BORDER}; border-bottom: none; letter-spacing: 1px;
}}
QLabel#onAir {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #3a1010, stop:1 #200808);
    color: #6f3b3b; font-size: 13px; font-weight: bold; border: 1px solid #120404;
    border-radius: 3px; padding: 6px 10px; letter-spacing: 1px;
}}
QLabel#onAir[active="true"] {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ff3b3b, stop:1 #b80f0f);
    color: #ffffff; border: 1px solid #ff8080;
}}
QLabel#statusChip {{
    background: #0f0f0f; color: {TEXT_DIM}; border: 1px solid #050505; border-radius: 3px; padding: 2px 6px; font-size: 10px;
}}
QLabel#thumb {{
    background: #000; border: 1px solid #3a3a3a;
}}
QLabel#rtmpChip {{
    background: #101010; color: {TEXT_DIM}; border: 1px solid #050505; border-radius: 3px; padding: 3px 6px; font-size: 10px; font-weight: bold;
}}
QLabel#rtmpChip[active="true"] {{
    color: #ffffff; background: #7a1010; border: 1px solid #c03030;
}}

QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4b4b4b, stop:0.5 #3a3a3a, stop:0.51 #313131, stop:1 #262626);
    border: 1px solid {BORDER}; border-radius: 3px; padding: 4px 10px; color: #ececec; min-height: 20px;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #5a5a5a, stop:0.5 #474747, stop:0.51 #3c3c3c, stop:1 #2f2f2f);
    border: 1px solid #5a5a5a;
}}
QPushButton:pressed, QPushButton:checked {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1f1f1f, stop:1 #333333);
    color: #ffffff; border: 1px solid #101010;
}}
QPushButton:disabled {{
    color: #6b6b6b; background: #2a2a2a; border: 1px solid #1a1a1a;
}}
QPushButton#funcBtn {{
    font-size: 10px; font-weight: bold; padding: 6px 4px; min-height: 24px;
}}
QPushButton#funcBtn:checked {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #2f5f9f, stop:1 #1f3f6f);
    border: 1px solid #4f7fbf;
}}
QPushButton#modeBtn {{
    font-size: 10px; padding: 3px 8px; min-height: 18px;
}}
QPushButton#modeBtn:checked {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #3d7a3d, stop:1 #245224);
    color: #ffffff; border: 1px solid #56a656;
}}
QPushButton#gridBtn {{
    font-size: 10px; padding: 4px 6px; min-height: 20px;
}}
QPushButton#transport, QPushButton#transportPause {{
    font-size: 22px; font-weight: bold; min-width: 58px; min-height: 40px; padding: 0px;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #505050, stop:0.5 #3b3b3b, stop:0.51 #2e2e2e, stop:1 #222222);
}}
QPushButton#transportPause {{ font-size: 16px; }}
QPushButton#transport:checked {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1a5f1a, stop:1 #0f3f0f);
    color: #7dff7d; border: 1px solid #3fbf3f;
}}
QPushButton#transportPause:checked {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #7a6a10, stop:1 #4a3f08);
    color: #ffe45c; border: 1px solid #c8b03a;
}}
QPushButton#lockBtn:checked {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #a02020, stop:1 #601010);
    color: #ffffff;
}}
QPushButton#winMin {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f5d442, stop:1 #c9a800);
    color: #201800; font-weight: bold; min-width: 22px; max-width: 22px; min-height: 18px; max-height: 18px; padding: 0;
}}
QPushButton#winClose {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f04a4a, stop:1 #b01010);
    color: #ffffff; font-weight: bold; min-width: 22px; max-width: 22px; min-height: 18px; max-height: 18px; padding: 0;
}}
QPushButton#danger {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #a83030, stop:1 #6a1515);
    color: #fff; font-weight: bold;
}}
QPushButton#danger:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #c03a3a, stop:1 #7a1a1a);
}}
QPushButton#primary {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #3a78c8, stop:1 #234f8a);
    color: #fff; font-weight: bold;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4a88d8, stop:1 #2a5f9a);
}}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit, QTextEdit, QPlainTextEdit {{
    background: #121212; border: 1px solid #060606; border-radius: 3px; padding: 3px 6px; color: #eeeeee;
    selection-background-color: {BLUE_ROW};
}}
QComboBox:hover, QLineEdit:hover {{ border: 1px solid #4a4a4a; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{
    image: none; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid #cfcfcf; margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: #1a1a1a; border: 1px solid #000; selection-background-color: {BLUE_ROW}; color: #eee; outline: none;
}}
QComboBox#modeCombo {{
    font-size: 10px; padding: 2px 6px; min-height: 18px;
}}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button, QDateEdit::up-button, QDateEdit::down-button {{
    background: #2e2e2e; border: 1px solid #0a0a0a; width: 14px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow, QDateEdit::up-arrow {{
    border-left: 3px solid transparent; border-right: 3px solid transparent; border-bottom: 4px solid #ccc; width: 0; height: 0;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow, QDateEdit::down-arrow {{
    border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 4px solid #ccc; width: 0; height: 0;
}}

QTableWidget, QTableView, QListWidget, QListView, QTreeWidget, QTreeView {{
    background: #101010; alternate-background-color: #151515; border: 1px solid {BORDER};
    gridline-color: #262626; color: #e6e6e6; selection-background-color: {BLUE_ROW}; selection-color: #ffffff; outline: none;
}}
QTableWidget::item, QTableView::item {{ padding: 0px 4px; }}
QTableWidget::item:selected, QTableView::item:selected {{ background: {BLUE_ROW}; color: #ffffff; }}
QListWidget::item:selected {{ background: {BLUE_ROW}; color: #fff; }}
QHeaderView::section {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #3c3c3c, stop:1 #262626);
    color: #e2e2e2; padding: 3px 5px; border: 1px solid #0d0d0d; font-size: 10px; font-weight: bold;
}}
QTableCornerButton::section {{ background: #2a2a2a; border: 1px solid #0d0d0d; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; background: #141414; top: -1px; }}
QTabBar::tab {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #353535, stop:1 #222222);
    color: #bdbdbd; padding: 4px 14px; border: 1px solid {BORDER}; border-bottom: none;
    border-top-left-radius: 3px; border-top-right-radius: 3px; font-size: 10px; font-weight: bold; margin-right: 1px;
}}
QTabBar::tab:selected {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4d4d4d, stop:1 #333333); color: #ffffff;
}}
QTabBar::tab:hover {{ color: #ffffff; }}

QGroupBox {{
    border: 1px solid {BORDER_LIGHT}; border-radius: 4px; margin-top: 14px; padding-top: 6px; font-weight: bold; color: #cfcfcf;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; font-size: 10px; }}

QCheckBox, QRadioButton {{ spacing: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
QCheckBox::indicator {{ background: #101010; border: 1px solid #555; border-radius: 2px; }}
QCheckBox::indicator:checked {{ background: #3a78c8; border: 1px solid #7aa8e8; }}

QSlider::groove:horizontal {{ height: 5px; background: #0d0d0d; border: 1px solid #050505; border-radius: 3px; }}
QSlider::handle:horizontal {{
    width: 12px; margin: -5px 0; border-radius: 6px; border: 1px solid #111;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #8a8a8a, stop:1 #4a4a4a);
}}
QSlider::sub-page:horizontal {{ background: #4b8a3a; border-radius: 3px; }}
QSlider#seek::sub-page:horizontal {{ background: {ACCENT}; }}

QProgressBar {{ background: #0d0d0d; border: 1px solid #050505; border-radius: 3px; text-align: center; color: #fff; font-size: 10px; height: 12px; }}
QProgressBar::chunk {{ background: {ACCENT}; }}

QScrollBar:vertical {{ background: #161616; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #3f3f3f; min-height: 24px; border-radius: 3px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: #555; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: #161616; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #3f3f3f; min-width: 24px; border-radius: 3px; margin: 2px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QMenu {{ background: #1e1e1e; border: 1px solid #000; }}
QMenu::item {{ padding: 5px 24px; }}
QMenu::item:selected {{ background: {BLUE_ROW}; color: #fff; }}
QMenu::separator {{ height: 1px; background: #3a3a3a; margin: 3px 8px; }}
QMenuBar {{ background: {BG}; }}
QMenuBar::item:selected {{ background: {BLUE_ROW}; }}

QStatusBar {{ background: #161616; color: #bdbdbd; border-top: 1px solid #000; font-size: 11px; }}
QStatusBar::item {{ border: none; }}
QToolTip {{ background: #111; color: #eee; border: 1px solid #555; padding: 3px; }}
QSplitter::handle {{ background: #101010; }}
QSplitter::handle:horizontal {{ width: 4px; }}
QSplitter::handle:vertical {{ height: 4px; }}
QMessageBox {{ background: {PANEL}; }}
QFrame#hline {{ background: #000; max-height: 1px; min-height: 1px; }}
"""

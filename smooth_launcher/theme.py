"""Smooth Launcher visual system.

Design rules borrowed from the Minecraft UI playbook and adapted to desktop:
  - ONE accent (violet), used only for the primary action + active state.
  - Everything else lives on a neutral near-black scale, never pure #000.
  - One spacing unit (4px) and one radius scale, reused everywhere.
  - Every interactive element has hover + pressed feedback.
"""

COLORS = {
    "bg":        "#08090c",   # deepest layer
    "surface":   "#101218",   # sidebar / panels
    "surface2":  "#171a22",   # cards
    "surface3":  "#1f2330",   # inputs, raised chips
    "border":    "#242938",
    "border2":   "#323848",
    "text":      "#f2f3f7",
    "muted":     "#9aa0b4",
    "faint":     "#5a6076",
    "accent":    "#2f7cf6",
    "accent2":   "#4d9bff",
    "accent3":   "#7ec2ff",
    "glow":      "rgba(47,124,246,0.40)",
    "success":   "#3ddc84",
    "danger":    "#ff5f6d",
    "warn":      "#ffc247",
}


def stylesheet() -> str:
    c = COLORS
    return f"""
    * {{
        font-family: 'Inter', 'Segoe UI', sans-serif;
        color: {c['text']};
        outline: none;
    }}
    QWidget#Root {{ background: transparent; }}
    QFrame#Shell {{
        background: {c['bg']};
        border: 1px solid {c['border2']};
        border-radius: 14px;
    }}

    /* ── Sidebar ─────────────────────────────────────────────── */
    QWidget#Sidebar {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {c['surface']}, stop:1 {c['bg']});
        border-right: 1px solid {c['border']};
    }}
    QLabel#Logo {{
        font-size: 21px;
        font-weight: 800;
        letter-spacing: 1px;
        padding: 2px;
    }}
    QLabel#NavSection {{
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1.4px;
        color: {c['faint']};
        padding: 4px 6px;
    }}

    QPushButton#NavItem {{
        background: transparent;
        border: none;
        border-left: 3px solid transparent;
        border-radius: 8px;
        padding: 11px 12px;
        text-align: left;
        font-size: 13px;
        font-weight: 600;
        letter-spacing: 0.3px;
        color: {c['muted']};
    }}
    QPushButton#NavItem:hover {{
        background: {c['surface2']};
        color: {c['text']};
    }}
    QPushButton#NavItem:checked {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(47,124,246,0.24), stop:1 rgba(47,124,246,0.02));
        border-left: 3px solid {c['accent2']};
        color: {c['text']};
        font-weight: 700;
    }}
    QWidget#Sidebar, QFrame#Shell {{
        selection-background-color: {c['accent']};
    }}

    /* ── Cards ───────────────────────────────────────────────── */
    QFrame#Card {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {c['surface']}, stop:1 {c['bg']});
        border: 1px solid {c['border']};
        border-radius: 16px;
    }}
    QFrame#Card2 {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {c['surface2']}, stop:1 {c['surface']});
        border: 1px solid {c['border']};
        border-radius: 13px;
    }}
    QFrame#Card2:hover {{
        border: 1px solid {c['accent2']};
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {c['surface3']}, stop:1 {c['surface2']});
    }}

    QLabel#Title {{
        font-size: 26px; font-weight: 800; letter-spacing: -0.4px;
    }}
    QLabel#Subtitle {{ font-size: 12px; color: {c['muted']}; }}
    QLabel#CardTitle {{
        font-size: 15px; font-weight: 700; letter-spacing: -0.2px;
        color: {c['text']};
    }}
    QLabel#SectionLabel {{
        font-size: 10px; font-weight: 700; letter-spacing: 1.2px;
        color: {c['faint']};
    }}

    /* ── Inputs ──────────────────────────────────────────────── */
    QLineEdit, QComboBox {{
        background: {c['surface3']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 10px 12px;
        font-size: 13px;
        selection-background-color: {c['accent']};
    }}
    QLineEdit:hover, QComboBox:hover {{ border: 1px solid {c['border2']}; }}
    QLineEdit:focus, QComboBox:focus {{ border: 1px solid {c['accent2']}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox QAbstractItemView {{
        background: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        selection-background-color: {c['accent']};
        padding: 4px;
    }}

    /* ── Buttons ─────────────────────────────────────────────── */
    QPushButton#Primary {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {c['accent']}, stop:1 {c['accent3']});
        border: none;
        border-radius: 12px;
        padding: 13px 20px;
        font-size: 14px;
        font-weight: 800;
        letter-spacing: 1.2px;
        color: white;
    }}
    QPushButton#Primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {c['accent2']}, stop:1 {c['accent3']});
    }}
    QPushButton#Primary:pressed {{
        background: {c['accent']};
        padding-top: 14px; padding-bottom: 12px;
    }}
    QPushButton#Primary:disabled {{
        background: {c['surface3']}; color: {c['faint']};
    }}

    QPushButton#Secondary {{
        background: {c['surface3']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 10px 14px;
        font-size: 12px;
        font-weight: 600;
        color: {c['text']};
    }}
    QPushButton#Secondary:hover {{
        border: 1px solid {c['accent2']};
        background: {c['surface2']};
    }}
    QPushButton#Secondary:pressed {{ background: {c['surface']}; }}

    QPushButton#Ghost {{
        background: transparent; border: none; color: {c['faint']};
        padding: 6px 8px; border-radius: 8px; font-size: 12px;
    }}
    QPushButton#Ghost:hover {{ color: {c['danger']}; background: {c['surface2']}; }}

    /* ── Progress / slider ───────────────────────────────────── */
    QProgressBar {{
        background: {c['surface3']};
        border: none; border-radius: 5px;
        height: 8px; text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {c['accent']}, stop:1 {c['accent3']});
        border-radius: 5px;
    }}

    QSlider::groove:horizontal {{
        height: 6px; background: {c['surface3']}; border-radius: 3px;
    }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {c['accent']}, stop:1 {c['accent3']});
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: white; width: 16px; height: 16px;
        margin: -6px 0; border-radius: 8px;
    }}
    QSlider::handle:horizontal:hover {{ background: {c['accent3']}; }}

    /* ── Scrollbars ──────────────────────────────────────────── */
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: {c['surface3']}; border-radius: 4px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c['accent']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* ── Badges ──────────────────────────────────────────────── */
    QFrame#Divider {{ background: {c['border']}; max-height: 1px; border: none; }}
    QLabel#Hint {{ font-size: 11px; color: {c['faint']}; }}
    QLabel#Pill {{
        background: rgba(47,124,246,0.16); color: {c['accent3']};
        border-radius: 9px; padding: 3px 10px;
        font-size: 10px; font-weight: 700; letter-spacing: 0.6px;
    }}
    QToolTip {{
        background: {c['surface3']}; color: {c['text']};
        border: 1px solid {c['border2']}; border-radius: 8px; padding: 6px 8px;
    }}
    QLabel#Badge {{
        background: {c['surface3']}; color: {c['muted']};
        border-radius: 8px; padding: 3px 8px;
        font-size: 10px; font-weight: 700; letter-spacing: 0.5px;
    }}
    QLabel#BadgeMs {{
        background: rgba(47,124,246,0.20); color: {c['accent3']};
    }}
    QLabel#BadgeOff {{
        background: rgba(154,160,180,0.14); color: {c['muted']};
    }}
    QLabel#BadgeElyBy {{
        background: rgba(61,220,132,0.18); color: {c['success']};
    }}
    """

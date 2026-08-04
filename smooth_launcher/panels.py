"""Rich dashboard components that make the launcher feel full."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QPushButton)

from .theme import COLORS


class GradientHeader(QWidget):
    """Animated aurora hero. Two slow-drifting light blooms over a gradient —
    gives the page motion without stealing attention from the PLAY button."""

    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.subtitle = subtitle
        self.setFixedHeight(120)
        self._t = 0.0
        from PyQt6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)          # 25fps is plenty for a slow drift

    def _tick(self):
        self._t += 0.012
        self.update()

    def set_subtitle(self, text: str):
        self.subtitle = text
        self.update()

    def paintEvent(self, event):
        import math
        from PyQt6.QtGui import QRadialGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 16, 16)
        p.setClipPath(path)

        base = QLinearGradient(0, 0, w, h)
        base.setColorAt(0.0, QColor("#171a2e"))
        base.setColorAt(1.0, QColor("#0d0f18"))
        p.fillPath(path, base)

        # drifting blooms
        for i, (col, sx, sy, rad) in enumerate([
            (QColor(108, 92, 231, 150), 0.28, 0.35, 0.85),
            (QColor(167, 139, 250, 105), 0.72, 0.60, 0.70),
        ]):
            cx = w * (sx + 0.10 * math.sin(self._t + i * 2.1))
            cy = h * (sy + 0.28 * math.cos(self._t * 0.8 + i))
            r = w * rad
            g = QRadialGradient(cx, cy, r)
            g.setColorAt(0.0, col)
            g.setColorAt(1.0, QColor(col.red(), col.green(), col.blue(), 0))
            p.fillRect(0, 0, w, h, g)

        # top sheen
        sheen = QLinearGradient(0, 0, 0, h * 0.5)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 20))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(0, 0, w, int(h * 0.5), sheen)

        p.setPen(QColor("white"))
        f = p.font()
        f.setPointSize(22)
        f.setBold(True)
        p.setFont(f)
        p.drawText(26, 54, self.title)

        p.setPen(QColor(235, 235, 255, 175))
        f.setPointSize(10)
        f.setBold(False)
        p.setFont(f)
        p.drawText(27, 78, self.subtitle)
        p.end()


class StatTile(QFrame):
    """Small metric card: big value on top, quiet label under it."""

    def __init__(self, value: str, label: str, accent: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("Card2")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(2)

        self.value_lbl = QLabel(value)
        color = COLORS["accent2"] if accent else COLORS["text"]
        self.value_lbl.setStyleSheet(
            "font-size:17px; font-weight:700; color:%s;" % color)
        lay.addWidget(self.value_lbl)

        cap = QLabel(label.upper())
        cap.setStyleSheet(
            "font-size:10px; font-weight:600; color:%s;" % COLORS["faint"])
        lay.addWidget(cap)

    def set_value(self, text: str):
        self.value_lbl.setText(text)


class NewsPanel(QFrame):
    """Changelog / what's-new feed. Static entries — no network needed."""

    ENTRIES = [
        ("1.0.0", "Smooth Launcher is live",
         "Microsoft + offline login, Fabric & vanilla installs, resilient downloads."),
        ("Soon", "Smooth Client",
         "35+ HUD modules for 1.21.11, auto-installed straight from here."),
        ("Soon", "Cosmetics",
         "Wings and capes, visible to everyone running Smooth."),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        head = QLabel("WHAT'S NEW")
        head.setObjectName("SectionLabel")
        lay.addWidget(head)

        for tag, title, body in self.ENTRIES:
            lay.addWidget(self._entry(tag, title, body))
        lay.addStretch(1)

    def _entry(self, tag, title, body):
        row = QFrame()
        row.setObjectName("Card2")
        rl = QVBoxLayout(row)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(8)
        badge = QLabel(tag)
        badge.setObjectName("Badge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedWidth(46)
        top.addWidget(badge)
        t = QLabel(title)
        t.setStyleSheet("font-size:13px; font-weight:600;")
        top.addWidget(t)
        top.addStretch(1)
        rl.addLayout(top)

        b = QLabel(body)
        b.setWordWrap(True)
        b.setStyleSheet("font-size:11px; color:%s;" % COLORS["muted"])
        rl.addWidget(b)
        return row


class FriendsPreviewPanel(QFrame):
    """Compact friends list for the Play page sidebar — mirrors the full
    Friends page's saved list. Real presence needs a Smooth backend server,
    so this shows saved names only, not live online status (matches the
    honest note on the full Friends page — no fake "online" dots)."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        head = QLabel("FRIENDS")
        head.setObjectName("SectionLabel")
        lay.addWidget(head)

        self.holder = QVBoxLayout()
        self.holder.setSpacing(6)
        lay.addLayout(self.holder)
        lay.addStretch(1)
        self.refresh()

    def refresh(self):
        while self.holder.count():
            item = self.holder.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        friends = self.config.get("friends", [])
        friends = friends if isinstance(friends, list) else []
        if not friends:
            empty = QLabel("No friends saved yet — add some on the Friends page.")
            empty.setWordWrap(True)
            empty.setStyleSheet("font-size:11px; color:%s;" % COLORS["muted"])
            self.holder.addWidget(empty)
            return

        for name in friends[:8]:
            row = QFrame()
            row.setObjectName("Card2")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 7, 10, 7)
            rl.setSpacing(8)
            dot = QLabel("\u25cf")
            dot.setStyleSheet("color:%s; font-size:9px;" % COLORS["muted"])
            dot.setToolTip("Live status needs a Smooth backend server")
            rl.addWidget(dot)
            n = QLabel(name)
            n.setStyleSheet("font-size:12px;")
            rl.addWidget(n)
            rl.addStretch(1)
            self.holder.addWidget(row)


class SkinHead(QWidget):
    """Player head. Tries the real skin, falls back to an initial — never blocks."""

    def __init__(self, size: int = 56, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pix = None
        self._name = "?"
        self._loader = None

    def set_player(self, name: str, uuid: str = "", online: bool = False):
        self._name = name or "?"
        self._pix = None
        self.update()
        if online and uuid:
            self._loader = _SkinLoader(uuid)
            self._loader.done.connect(self._got)
            self._loader.start()

    def _got(self, data: bytes):
        pix = QPixmap()
        if data and pix.loadFromData(data):
            self._pix = pix
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.width()
        path = QPainterPath()
        path.addRoundedRect(0, 0, s, s, 10, 10)
        p.setClipPath(path)

        if self._pix is not None:
            p.drawPixmap(0, 0, s, s, self._pix)
        else:
            p.fillPath(path, QColor(COLORS["surface3"]))
            p.setPen(QColor(COLORS["accent2"]))
            f = p.font()
            f.setPointSize(int(s * 0.34))
            f.setBold(True)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       self._name[0].upper())
        p.end()


class _SkinLoader(QThread):
    done = pyqtSignal(bytes)

    def __init__(self, uuid: str):
        super().__init__()
        self.uuid = uuid.replace("-", "")

    def run(self):
        try:
            from . import network
            r = network.SESSION.get(
                "https://crafatar.com/avatars/%s?size=64&overlay" % self.uuid,
                timeout=6)
            if r.status_code == 200:
                self.done.emit(r.content)
                return
        except Exception:
            pass
        self.done.emit(b"")


class StatusBar(QFrame):
    """Thin bottom bar: connection dot, version, active account."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card2")
        self.setFixedHeight(30)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(8)

        self.dot = QLabel("●")
        self.dot.setStyleSheet("color:%s; font-size:11px;" % COLORS["faint"])
        lay.addWidget(self.dot)

        self.net = QLabel("Checking connection...")
        self.net.setStyleSheet("font-size:11px; color:%s;" % COLORS["muted"])
        lay.addWidget(self.net)
        lay.addStretch(1)

        ver = QLabel("Smooth Launcher v1.0.0")
        ver.setStyleSheet("font-size:11px; color:%s;" % COLORS["faint"])
        lay.addWidget(ver)

    def set_online(self, online: bool):
        color = COLORS["success"] if online else COLORS["warn"]
        self.dot.setStyleSheet("color:%s; font-size:11px;" % color)
        self.net.setText("Online" if online else "Offline — installed versions still play")
        self.net.setStyleSheet("font-size:11px; color:%s;" % COLORS["muted"])


class OnlineProbe(QThread):
    """Checks connectivity off the UI thread."""
    result = pyqtSignal(bool)

    def run(self):
        try:
            from . import network
            self.result.emit(network.is_online(timeout=4))
        except Exception:
            self.result.emit(False)


class TitleBar(QWidget):
    """Custom window chrome — drag to move, custom min/max/close buttons."""

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self._drag = None
        self.setFixedHeight(38)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 8, 0)
        lay.setSpacing(8)

        mark = QLabel("\u25c6")
        mark.setStyleSheet("color:%s; font-size:13px;" % COLORS["accent2"])
        lay.addWidget(mark)

        name = QLabel("Smooth Launcher")
        name.setStyleSheet("font-size:12px; font-weight:600; letter-spacing:0.4px;")
        lay.addWidget(name)
        lay.addStretch(1)

        for glyph, slot, danger in (
                ("\u2013", self.win.showMinimized, False),
                ("\u25a1", self._toggle_max, False),
                ("\u2715", self.win.close, True)):
            b = QPushButton(glyph)
            b.setFixedSize(30, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            hover = COLORS["danger"] if danger else COLORS["surface3"]
            fg = "white" if danger else COLORS["text"]
            b.setStyleSheet(
                "QPushButton{background:transparent;border:none;border-radius:7px;"
                "color:%s;font-size:12px;}"
                "QPushButton:hover{background:%s;color:%s;}"
                % (COLORS["muted"], hover, fg))
            b.clicked.connect(slot)
            lay.addWidget(b)

    def _toggle_max(self):
        if self.win.isMaximized():
            self.win.showNormal()
        else:
            self.win.showMaximized()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag and e.buttons() & Qt.MouseButton.LeftButton:
            if self.win.isMaximized():
                self.win.showNormal()
            self.win.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self._toggle_max()

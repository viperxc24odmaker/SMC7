"""Custom widgets that give the launcher its premium feel."""
from __future__ import annotations

from PyQt6.QtCore import (QEasingCurve, QPropertyAnimation, QRectF, Qt,
                          pyqtProperty, pyqtSignal)
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

from .theme import COLORS


class ToggleSwitch(QWidget):
    """An animated pill toggle — slides + colour-shifts on state change."""
    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._offset = 1.0 if checked else 0.0
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool):
        if value == self._checked:
            return
        self._checked = value
        self._animate()

    def _animate(self):
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if self._checked else 0.0)
        self._anim.start()

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self._animate()
        self.toggled.emit(self._checked)

    def get_offset(self):
        return self._offset

    def set_offset(self, value):
        self._offset = value
        self.update()

    offset = pyqtProperty(float, fget=get_offset, fset=set_offset)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        off = QColor(COLORS["surface3"])
        on = QColor(COLORS["accent"])
        r = int(off.red() + (on.red() - off.red()) * self._offset)
        g = int(off.green() + (on.green() - off.green()) * self._offset)
        b = int(off.blue() + (on.blue() - off.blue()) * self._offset)

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        p.fillPath(path, QColor(r, g, b))

        d = h - 6
        x = 3 + (w - d - 6) * self._offset
        knob = QPainterPath()
        knob.addEllipse(QRectF(x, 3, d, d))
        p.fillPath(knob, QColor("white"))
        p.end()


class Avatar(QWidget):
    """A simple round avatar with the player's initial and an accent ring."""

    def __init__(self, name: str, size: int = 40, parent=None):
        super().__init__(parent)
        self.name = name or "?"
        self.setFixedSize(size, size)

    def set_name(self, name: str):
        self.name = name or "?"
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.width()
        p.setBrush(QColor(COLORS["surface3"]))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, s, s)
        p.setPen(QColor(COLORS["accent2"]))
        font = p.font()
        font.setPointSize(int(s * 0.36))
        font.setBold(True)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.name[0].upper())
        p.end()

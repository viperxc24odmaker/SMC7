"""Post-install optimiser popup: None / Sodium+Lithium / VulkanMod."""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                             QProgressBar, QPushButton, QVBoxLayout, QWidget)

from . import network
from .theme import COLORS

API = "https://api.modrinth.com/v2"

# ── Verified versions (checked against Modrinth 2026-08-03) ──────────────────
PACKS = {
    "sodium_lithium": [
        # Sodium 0.8.13 + Lithium 0.21.4 — both 1.21.11 Fabric
        ("sodium",  "AANobbMI", "mc1.21.11-0.8.13-fabric",
         "sodium-fabric-0.8.13+mc1.21.11.jar"),
        ("lithium", "gvQqBUqZ", "mc1.21.11-0.21.4-fabric",
         "lithium-fabric-0.21.4+mc1.21.11.jar"),
    ],
    "vulkanmod": [
        # VulkanMod 0.6.3 — 1.21.11 Fabric
        ("vulkanmod", "JYQhtZtO", "0.6.3",
         "VulkanMod-0.6.3.jar"),
    ],
}


class _Downloader(QThread):
    progress = pyqtSignal(str, int)   # (label, 0-100)
    done     = pyqtSignal(bool, str)  # (ok, message)

    def __init__(self, mods_dir: Path, pack_key: str):
        super().__init__()
        self.mods_dir = mods_dir
        self.pack_key = pack_key

    def run(self):
        entries = PACKS[self.pack_key]
        mods_dir = self.mods_dir
        mods_dir.mkdir(parents=True, exist_ok=True)
        for name, project_id, version_id, filename in entries:
            target = mods_dir / filename
            if target.exists():
                self.progress.emit("%s already present." % filename, 100)
                continue
            try:
                self.progress.emit("Fetching %s metadata…" % name, 0)
                r = network.SESSION.get(
                    "%s/project/%s/version/%s" % (API, project_id, version_id),
                    timeout=15)
                r.raise_for_status()
                files = r.json().get("files", [])
                primary = next((f for f in files if f.get("primary")), files[0])
                url = primary["url"]

                self.progress.emit("Downloading %s…" % filename, 10)
                tmp = target.with_suffix(target.suffix + ".part")
                with network.SESSION.get(url, stream=True, timeout=60) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length") or 0)
                    got = 0
                    with open(tmp, "wb") as fh:
                        for chunk in resp.iter_content(65536):
                            if not chunk:
                                continue
                            fh.write(chunk)
                            got += len(chunk)
                            if total:
                                pct = 10 + int(got * 88 / total)
                                self.progress.emit("Downloading %s…" % filename, pct)
                os.replace(tmp, target)
                self.progress.emit("%s installed!" % filename, 100)
            except Exception as exc:
                self.done.emit(False,
                    "Failed on %s: %s\nCheck your connection and retry." % (name, exc))
                return
        self.done.emit(True, "All done! Restart Minecraft to use the new mods.")


class _OptionCard(QFrame):
    """One selectable option tile."""

    def __init__(self, key: str, title: str, desc: str, accent: str,
                 on_pick, parent=None):
        super().__init__(parent)
        self.key = key
        self.on_pick = on_pick
        self.setObjectName("Card2")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.selected = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)

        badge = QLabel(title)
        badge.setStyleSheet(
            "font-size:14px; font-weight:800; color:%s;" % accent)
        lay.addWidget(badge)

        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet("font-size:11px; color:%s;" % COLORS["muted"])
        lay.addWidget(d)

    def set_selected(self, v: bool):
        self.selected = v
        self.update()

    def mousePressEvent(self, e):
        self.on_pick(self)

    def enterEvent(self, e):
        if not self.selected:
            self.setStyleSheet("QFrame#Card2{border:1px solid %s;}" % COLORS["border2"])

    def leaveEvent(self, e):
        if not self.selected:
            self.setStyleSheet("")

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.selected:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QColor(COLORS["accent2"]))
            path = QPainterPath()
            path.addRoundedRect(1, 1, self.width()-2, self.height()-2, 12, 12)
            p.drawPath(path)
            p.end()


class OptimiserDialog(QDialog):
    """Choose a performance preset after a fresh Fabric install."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Smooth Optimiser")
        self.setModal(True)
        self.resize(520, 460)
        self._selected = None
        self._downloader = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(14)

        head = QLabel("Boost your performance")
        head.setObjectName("Title")
        lay.addWidget(head)

        sub = QLabel(
            "Pick a preset to install alongside Fabric.\n"
            "You can always install mods manually later.")
        sub.setObjectName("Subtitle")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # ── option cards ────────────────────────────────────────────────────
        self.cards: list[_OptionCard] = []
        options = [
            ("none",
             "None",
             "Skip for now — vanilla Fabric only.",
             COLORS["muted"]),
            ("sodium_lithium",
             "Sodium + Lithium",
             "Best frame rate + game logic optimisations. Most compatible with other mods.",
             COLORS["accent2"]),
            ("vulkanmod",
             "VulkanMod",
             "Replaces the renderer with Vulkan. Huge FPS gains — but incompatible with "
             "Sodium. Best if you have a modern GPU and don't use shader mods.",
             COLORS["warn"]),
        ]
        for key, title, desc, color in options:
            card = _OptionCard(key, title, desc, color, self._pick)
            self.cards.append(card)
            lay.addWidget(card)
        # default = none selected
        self._pick(self.cards[0])

        # ── progress area ────────────────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        lay.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setObjectName("Subtitle")
        self.status.hide()
        lay.addWidget(self.status)

        # ── buttons ──────────────────────────────────────────────────────────
        row = QHBoxLayout()
        row.setSpacing(10)
        skip = QPushButton("Skip")
        skip.setObjectName("Secondary")
        skip.clicked.connect(self.reject)
        row.addWidget(skip)
        row.addStretch(1)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("Primary")
        self.apply_btn.clicked.connect(self._apply)
        row.addWidget(self.apply_btn)
        lay.addLayout(row)

    def _pick(self, card: _OptionCard):
        self._selected = card.key
        for c in self.cards:
            c.set_selected(c is card)

    def _mods_dir(self) -> Path:
        return Path(self.config.effective_game_dir()) / "mods"

    def _apply(self):
        if self._selected == "none" or self._selected is None:
            self.accept()
            return

        self.apply_btn.setEnabled(False)
        for c in self.cards:
            c.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.status.show()
        self.status.setText("Starting download…")

        self._downloader = _Downloader(self._mods_dir(), self._selected)
        self._downloader.progress.connect(self._on_progress)
        self._downloader.done.connect(self._on_done)
        self._downloader.start()

    def _on_progress(self, label: str, pct: int):
        self.status.setText(label)
        self.progress.setValue(pct)

    def _on_done(self, ok: bool, msg: str):
        self.progress.hide()
        self.status.setText(msg)
        if ok:
            self.apply_btn.setText("Done!")
            self.apply_btn.setEnabled(True)
            self.apply_btn.clicked.disconnect()
            self.apply_btn.clicked.connect(self.accept)
        else:
            self.apply_btn.setText("Retry")
            self.apply_btn.setEnabled(True)
            for c in self.cards:
                c.setEnabled(True)
            self.apply_btn.clicked.disconnect()
            self.apply_btn.clicked.connect(self._apply)

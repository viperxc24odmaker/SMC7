"""Cosmetics, Skins and Friends tabs."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                             QInputDialog, QLabel, QMessageBox, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

from . import network
from .mods import fade_in
from .panels import SkinHead
from .theme import COLORS


def _lbl(text, obj=None):
    l = QLabel(text)
    if obj:
        l.setObjectName(obj)
    return l


def _head(root, title, sub):
    box = QVBoxLayout()
    box.setSpacing(2)
    box.addWidget(_lbl(title, "Title"))
    s = _lbl(sub, "Subtitle")
    box.addWidget(s)
    root.addLayout(box)
    return s


# ══════════════════════════════════════════════════════════════════════
# Cosmetics
# ══════════════════════════════════════════════════════════════════════

class CosmeticTile(QFrame):
    """A selectable cosmetic swatch. Selection = accent ring + check."""

    def __init__(self, cid: str, name: str, kind: str, color: str,
                 on_pick, parent=None):
        super().__init__(parent)
        self.setObjectName("Card2")
        self.cid = cid
        self.kind = kind
        self.color = color
        self.on_pick = on_pick
        self.selected = False
        self.setFixedSize(112, 128)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        lay.addStretch(1)
        cap = QLabel(name)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap.setStyleSheet("font-size:11px; font-weight:600;")
        lay.addWidget(cap)

    def set_selected(self, value: bool):
        self.selected = value
        self.update()

    def mousePressEvent(self, event):
        self.on_pick(self)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        # preview swatch: a cape shape or a pair of wings, drawn simply
        c = QColor(self.color)
        if self.cid == "":
            p.setPen(QColor(COLORS["faint"]))
            p.drawText(0, 30, w, 40, Qt.AlignmentFlag.AlignCenter, "None")
        elif self.kind == "cape":
            path = QPainterPath()
            path.addRoundedRect(w / 2 - 22, 22, 44, 58, 6, 6)
            p.fillPath(path, c)
            p.fillRect(int(w / 2 - 22), 22, 44, 8, c.darker(130))
        else:
            for sign in (-1, 1):
                path = QPainterPath()
                path.moveTo(w / 2, 30)
                path.quadTo(w / 2 + sign * 40, 34, w / 2 + sign * 30, 80)
                path.quadTo(w / 2 + sign * 14, 62, w / 2, 60)
                path.closeSubpath()
                p.fillPath(path, c)

        if self.selected:
            p.setPen(QColor(COLORS["accent2"]))
            path = QPainterPath()
            path.addRoundedRect(1, 1, self.width() - 2, self.height() - 2, 12, 12)
            p.drawPath(path)
            p.fillRect(self.width() - 22, 8, 14, 14, QColor(COLORS["accent2"]))
            p.setPen(QColor("white"))
            p.drawText(self.width() - 22, 8, 14, 14,
                       Qt.AlignmentFlag.AlignCenter, "\u2713")
        p.end()


class CosmeticsPage(QWidget):
    """Pick a cape and wings. Saved to config and read by Smooth Client."""

    CAPES = [
        ("", "None", "#333846"),
        ("aurora", "Aurora", "#6c5ce7"),
        ("ember", "Ember", "#ff5f6d"),
        ("mint", "Mint", "#3ddc84"),
        ("gold", "Gold", "#ffc247"),
        ("abyss", "Abyss", "#2b3350"),
    ]
    WINGS = [
        ("", "None", "#333846"),
        ("seraph", "Seraph", "#a78bfa"),
        ("phantom", "Phantom", "#4bc0ff"),
        ("crimson", "Crimson", "#ff5f6d"),
        ("verdant", "Verdant", "#3ddc84"),
    ]

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.cape_tiles = []
        self.wing_tiles = []

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 18)
        root.setSpacing(14)
        self.sub = _head(root, "Cosmetics",
                         "Visible to everyone running Smooth Client.")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(16)

        bl.addWidget(_lbl("CAPES", "SectionLabel"))
        bl.addWidget(self._grid(self.CAPES, "cape", self.cape_tiles))
        bl.addWidget(_lbl("WINGS", "SectionLabel"))
        bl.addWidget(self._grid(self.WINGS, "wings", self.wing_tiles))
        bl.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self._sync()

    def _grid(self, items, kind, store):
        holder = QFrame()
        holder.setObjectName("Card")
        g = QGridLayout(holder)
        g.setContentsMargins(16, 16, 16, 16)
        g.setSpacing(10)
        for i, (cid, name, color) in enumerate(items):
            tile = CosmeticTile(cid, name, kind, color, self._pick)
            store.append(tile)
            g.addWidget(tile, i // 5, i % 5)
            fade_in(tile, 200, delay=i * 30)
        g.setColumnStretch(5, 1)
        return holder

    def _pick(self, tile: CosmeticTile):
        key = "cosmetic_cape" if tile.kind == "cape" else "cosmetic_wings"
        self.config.set(key, tile.cid)
        self._sync()

    def _sync(self):
        cape = self.config.get("cosmetic_cape", "")
        wings = self.config.get("cosmetic_wings", "")
        for t in self.cape_tiles:
            t.set_selected(t.cid == cape)
        for t in self.wing_tiles:
            t.set_selected(t.cid == wings)
        self.sub.setText("Cape: %s   \u00b7   Wings: %s"
                         % (cape or "None", wings or "None"))


# ══════════════════════════════════════════════════════════════════════
# Skins
# ══════════════════════════════════════════════════════════════════════

class SkinUploader(QThread):
    """Uploads a skin PNG to Mojang. Microsoft accounts only."""
    done = pyqtSignal(bool, str)

    def __init__(self, token: str, path: str, model: str):
        super().__init__()
        self.token = token
        self.path = path
        self.model = model

    def run(self):
        try:
            with open(self.path, "rb") as fh:
                r = network.SESSION.post(
                    "https://api.minecraftservices.com/minecraft/profile/skins",
                    headers={"Authorization": "Bearer %s" % self.token},
                    data={"variant": self.model},
                    files={"file": ("skin.png", fh, "image/png")},
                    timeout=30)
            if r.status_code in (200, 204):
                self.done.emit(True, "Skin applied! Restart Minecraft to see it.")
            elif r.status_code == 401:
                self.done.emit(False, "Session expired — re-add the account.")
            else:
                self.done.emit(False, "Mojang rejected the upload (%d)." % r.status_code)
        except Exception as exc:
            self.done.emit(False, "Upload failed (%s). Check your connection."
                           % type(exc).__name__)


class SkinsPage(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.path = None
        self.model = "classic"
        self.worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 18)
        root.setSpacing(14)
        self.sub = _head(root, "Skins", "")

        card = QFrame()
        card.setObjectName("Card")
        cl = QHBoxLayout(card)
        cl.setContentsMargins(22, 20, 22, 20)
        cl.setSpacing(20)

        left = QVBoxLayout()
        left.setSpacing(8)
        self.preview = QLabel()
        self.preview.setFixedSize(128, 128)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(
            "background:%s; border:1px solid %s; border-radius:12px; color:%s;"
            % (COLORS["surface2"], COLORS["border"], COLORS["faint"]))
        self.preview.setText("No skin\nselected")
        left.addWidget(self.preview)
        cl.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(_lbl("SKIN FILE", "SectionLabel"))
        self.file_lbl = _lbl("Choose a 64x64 PNG.", "Subtitle")
        right.addWidget(self.file_lbl)

        pick = QPushButton("Choose PNG")
        pick.setObjectName("Secondary")
        pick.clicked.connect(self._pick)
        right.addWidget(pick)

        right.addWidget(_lbl("MODEL", "SectionLabel"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_classic = QPushButton("Classic")
        self.btn_slim = QPushButton("Slim")
        for b, m in ((self.btn_classic, "classic"), (self.btn_slim, "slim")):
            b.setObjectName("Secondary")
            b.setCheckable(True)
            b.clicked.connect(lambda _, mm=m: self._set_model(mm))
            row.addWidget(b)
        row.addStretch(1)
        right.addLayout(row)
        self._set_model("classic")

        self.apply = QPushButton("APPLY SKIN")
        self.apply.setObjectName("Primary")
        self.apply.clicked.connect(self._apply)
        right.addWidget(self.apply)

        self.status = _lbl("", "Subtitle")
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        right.addStretch(1)
        cl.addLayout(right, 1)

        root.addWidget(card)
        root.addStretch(1)
        self.refresh_mode()

    def refresh_mode(self):
        """Label the button honestly for the active account type."""
        acc = self.config.active()
        offline = bool(acc) and acc.get("type") != "microsoft"
        if not acc:
            self.sub.setText("Add an account to set a skin.")
            self.apply.setText("APPLY SKIN")
        elif offline:
            self.sub.setText(
                "Offline account — skins apply locally in singleplayer "
                "via Smooth Client.")
            self.apply.setText("SET LOCAL SKIN")
        else:
            self.sub.setText("Microsoft account — uploads to Mojang.")
            self.apply.setText("APPLY SKIN")

    def _set_model(self, m):
        self.model = m
        self.btn_classic.setChecked(m == "classic")
        self.btn_slim.setChecked(m == "slim")

    def _pick(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose skin", "", "PNG (*.png)")
        if not f:
            return
        self.path = f
        self.file_lbl.setText(Path(f).name)
        pix = QPixmap(f)
        if not pix.isNull():
            self.preview.setPixmap(
                pix.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.FastTransformation))

    def _apply(self):
        acc = self.config.active()
        if not acc:
            self.status.setText("Add an account first.")
            return
        if not self.path:
            self.status.setText("Choose a PNG first.")
            return

        if acc.get("type") != "microsoft":
            self._apply_local()
            return

        self.apply.setEnabled(False)
        self.status.setText("Uploading...")
        self.worker = SkinUploader(acc.get("token", ""), self.path, self.model)
        self.worker.done.connect(self._done)
        self.worker.start()

    def _apply_local(self):
        """Offline accounts: save the skin locally for Smooth Client to render.

        Mojang won't accept skins for offline profiles, so instead we drop the
        PNG where the mod can find it. Smooth Client then renders it on your own
        player in singleplayer / LAN. Other players on real servers won't see it.
        """
        import shutil
        try:
            dest_dir = Path(self.config.effective_game_dir()) / "smoothclient"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / "skin.png"
            shutil.copyfile(self.path, dest)
            self.config.set("local_skin", str(dest))
            self.config.set("local_skin_model", self.model)
            self.status.setText(
                "Saved as your local skin — Smooth Client will render it in "
                "singleplayer. (Servers still show your default skin.)")
        except OSError as exc:
            self.status.setText("Couldn't save the skin: %s" % exc)

    def _done(self, ok, msg):
        self.apply.setEnabled(True)
        self.status.setText(msg)


# ══════════════════════════════════════════════════════════════════════
# Friends
# ══════════════════════════════════════════════════════════════════════

class FriendsPage(QWidget):
    """A local friends list. Real presence needs a backend — see the note."""

    def __init__(self, config):
        super().__init__()
        self.config = config

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 18)
        root.setSpacing(14)

        top = QHBoxLayout()
        box = QVBoxLayout()
        box.setSpacing(2)
        box.addWidget(_lbl("Friends", "Title"))
        box.addWidget(_lbl("Your saved players.", "Subtitle"))
        top.addLayout(box)
        top.addStretch(1)
        add = QPushButton("+ Add friend")
        add.setObjectName("Primary")
        add.clicked.connect(self._add)
        top.addWidget(add)
        root.addLayout(top)

        note = QFrame()
        note.setObjectName("Card2")
        nl = QHBoxLayout(note)
        nl.setContentsMargins(14, 10, 14, 10)
        n = _lbl("Live online status needs a Smooth backend server — for now "
                 "this is your saved list.", "Subtitle")
        n.setWordWrap(True)
        nl.addWidget(n)
        root.addWidget(note)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.holder = QWidget()
        self.list = QVBoxLayout(self.holder)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(8)
        self.list.addStretch(1)
        self.scroll.setWidget(self.holder)
        root.addWidget(self.scroll, 1)

        self.rebuild()

    def friends(self):
        f = self.config.get("friends", [])
        return f if isinstance(f, list) else []

    def rebuild(self):
        while self.list.count() > 1:
            it = self.list.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

        fr = self.friends()
        if not fr:
            self.list.insertWidget(0, _lbl(
                "No friends added yet — tap \u201c+ Add friend\u201d.", "Subtitle"))
            return
        for i, name in enumerate(fr):
            row = QFrame()
            row.setObjectName("Card2")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 10, 14, 10)
            rl.setSpacing(12)
            head = SkinHead(38)
            head.set_player(name)
            rl.addWidget(head)
            n = QLabel(name)
            n.setStyleSheet("font-size:14px; font-weight:600;")
            rl.addWidget(n)
            rl.addStretch(1)
            badge = _lbl("SAVED", "Badge")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rl.addWidget(badge)
            rm = QPushButton("Remove")
            rm.setObjectName("Ghost")
            rm.clicked.connect(lambda _, nm=name: self._remove(nm))
            rl.addWidget(rm)
            self.list.insertWidget(self.list.count() - 1, row)
            fade_in(row, 200, delay=i * 30)

    def _add(self):
        name, ok = QInputDialog.getText(self, "Add friend", "Minecraft username:")
        name = (name or "").strip()
        if not (ok and name):
            return
        fr = self.friends()
        if name in fr:
            return
        fr.append(name)
        self.config.set("friends", fr)
        self.rebuild()

    def _remove(self, name):
        fr = [f for f in self.friends() if f != name]
        self.config.set("friends", fr)
        self.rebuild()

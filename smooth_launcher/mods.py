"""Mod browser — search Modrinth and install straight into the mods folder."""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import (QEasingCurve, QPropertyAnimation, Qt, QThread,
                          pyqtSignal)
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                             QLabel, QLineEdit, QProgressBar, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

from . import network
from .theme import COLORS

API = "https://api.modrinth.com/v2"
ICON_SIZE = 40


class IconWorker(QThread):
    """Fetches one project icon off the UI thread. Silent on failure."""
    loaded = pyqtSignal(bytes)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            r = network.SESSION.get(self.url, timeout=10)
            r.raise_for_status()
            self.loaded.emit(r.content)
        except Exception:
            pass  # card just keeps the placeholder glyph


def make_icon_label() -> QLabel:
    """Rounded placeholder icon slot; call load_icon_into() to fill it."""
    lbl = QLabel("▣")
    lbl.setFixedSize(ICON_SIZE, ICON_SIZE)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(
        "background:%s; border-radius:9px; font-size:16px; color:%s;"
        % (COLORS["surface3"], COLORS["faint"]))
    return lbl


def load_icon_into(label: QLabel, url: str, keep_alive_list: list):
    """Async-loads url into label as a rounded pixmap. Safe if url is falsy."""
    if not url:
        return
    worker = IconWorker(url)

    def _apply(data: bytes, lbl=label):
        try:
            pix = QPixmap()
            if not pix.loadFromData(data):
                return
            pix = pix.scaled(ICON_SIZE, ICON_SIZE,
                             Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                             Qt.TransformationMode.SmoothTransformation)
            lbl.setPixmap(pix)
            lbl.setStyleSheet(
                "border-radius:9px; background:%s;" % COLORS["surface3"])
        except RuntimeError:
            pass  # label was deleted (scrolled away / re-searched) mid-flight

    worker.loaded.connect(_apply)
    keep_alive_list.append(worker)
    worker.start()


def fade_in(widget, duration=220, delay=0):
    """Fade a widget in. Keeps a reference so the animation isn't GC'd."""
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    eff.setOpacity(0.15)
    anim = QPropertyAnimation(eff, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.15)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _detach():
        # Detaching the effect prevents ghosting/stale repaints.
        try:
            widget.setGraphicsEffect(None)
        except RuntimeError:
            pass

    anim.finished.connect(_detach)
    widget._fade_anim = anim
    if delay:
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(delay, anim.start)
    else:
        anim.start()
    return anim


class SearchWorker(QThread):
    """Queries Modrinth off the UI thread. Never raises into the UI."""
    results = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, query: str, mc_version: str, loader: str):
        super().__init__()
        self.query = query
        self.mc_version = mc_version
        self.loader = loader

    def run(self):
        facets = '[["project_type:mod"],["categories:%s"],["versions:%s"]]' % (
            self.loader, self.mc_version)
        try:
            r = network.SESSION.get(
                "%s/search" % API,
                params={"query": self.query, "facets": facets, "limit": 20},
                timeout=15)
            r.raise_for_status()
            self.results.emit(r.json().get("hits", []))
        except Exception as exc:
            self.failed.emit(
                "Couldn't reach Modrinth (%s). Check your connection and retry."
                % type(exc).__name__)


class InstallWorker(QThread):
    """Resolves a compatible version and downloads the .jar into /mods."""
    progress = pyqtSignal(int)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, project_id: str, name: str, mods_dir: Path,
                 mc_version: str, loader: str):
        super().__init__()
        self.project_id = project_id
        self.name = name
        self.mods_dir = mods_dir
        self.mc_version = mc_version
        self.loader = loader

    def run(self):
        try:
            r = network.SESSION.get(
                "%s/project/%s/version" % (API, self.project_id),
                params={"game_versions": '["%s"]' % self.mc_version,
                        "loaders": '["%s"]' % self.loader},
                timeout=15)
            r.raise_for_status()
            versions = r.json()
            if not versions:
                self.failed.emit(
                    "%s has no build for %s / %s yet."
                    % (self.name, self.mc_version, self.loader))
                return

            files = versions[0].get("files", [])
            primary = next((f for f in files if f.get("primary")), files[0])
            url, fname = primary["url"], primary["filename"]

            self.mods_dir.mkdir(parents=True, exist_ok=True)
            target = self.mods_dir / fname
            tmp = target.with_suffix(target.suffix + ".part")

            with network.SESSION.get(url, stream=True, timeout=30) as resp:
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
                            self.progress.emit(int(got * 100 / total))
            os.replace(tmp, target)
            self.done.emit(fname)
        except Exception as exc:
            self.failed.emit("Download failed (%s). Try again — nothing was "
                             "corrupted." % type(exc).__name__)


class ModCard(QFrame):
    """One search result. Hover lifts the border; install shows progress."""

    def __init__(self, hit: dict, on_install, icon_pool: list, parent=None):
        super().__init__(parent)
        self.setObjectName("Card2")
        self.hit = hit
        self.on_install = on_install
        self.setMouseTracking(True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(12)

        self.icon = make_icon_label()
        lay.addWidget(self.icon)
        load_icon_into(self.icon, hit.get("icon_url", ""), icon_pool)

        info = QVBoxLayout()
        info.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel(hit.get("title", "Unknown"))
        title.setStyleSheet("font-size:14px; font-weight:700;")
        top.addWidget(title)
        dl = QLabel("%s downloads" % _short(hit.get("downloads", 0)))
        dl.setObjectName("Badge")
        dl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(dl)
        top.addStretch(1)
        info.addLayout(top)

        desc = QLabel(hit.get("description", "")[:120])
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size:11px; color:%s;" % COLORS["muted"])
        info.addWidget(desc)
        lay.addLayout(info, 1)

        right = QVBoxLayout()
        right.setSpacing(4)
        self.btn = QPushButton("Install")
        self.btn.setObjectName("Secondary")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self._go)
        right.addWidget(self.btn)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.hide()
        right.addWidget(self.bar)
        lay.addLayout(right)

    def _go(self):
        self.btn.setEnabled(False)
        self.btn.setText("...")
        self.bar.show()
        self.on_install(self)

    def set_progress(self, v):
        self.bar.setValue(v)

    def set_done(self, ok: bool, label: str = ""):
        self.bar.hide()
        self.btn.setText("Installed" if ok else "Retry")
        self.btn.setEnabled(not ok)
        if ok:
            self.btn.setStyleSheet("color:%s;" % COLORS["success"])

    def enterEvent(self, event):
        self.setStyleSheet("QFrame#Card2 { border:1px solid %s; }" % COLORS["accent"])

    def leaveEvent(self, event):
        self.setStyleSheet("")


def _short(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if n >= 1_000_000:
        return "%.1fM" % (n / 1_000_000)
    if n >= 1_000:
        return "%.1fK" % (n / 1_000)
    return str(n)


class ModsPage(QWidget):
    """Search Modrinth and install mods for the selected version/loader."""

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.worker = None
        self.installers = []
        self.icon_workers = []

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 18)
        root.setSpacing(12)

        head = QVBoxLayout()
        head.setSpacing(2)
        t = QLabel("Mods")
        t.setObjectName("Title")
        head.addWidget(t)
        self.sub = QLabel("")
        self.sub.setObjectName("Subtitle")
        head.addWidget(self.sub)
        root.addLayout(head)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search mods — sodium, iris, waypoints...")
        self.search.returnPressed.connect(self.do_search)
        bar.addWidget(self.search, 1)
        btn = QPushButton("Search")
        btn.setObjectName("Primary")
        btn.clicked.connect(self.do_search)
        bar.addWidget(btn)
        root.addLayout(bar)

        self.status = QLabel("Search for a mod to get started.")
        self.status.setObjectName("Subtitle")
        root.addWidget(self.status)

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

        self.refresh_sub()

    def refresh_sub(self):
        loader = "Fabric" if self.config.get("loader") == "fabric" else "Vanilla"
        self.sub.setText("Installing for %s \u00b7 %s"
                         % (self.config.get("version"), loader))

    def mods_dir(self) -> Path:
        return Path(self.config.effective_game_dir()) / "mods"

    def _clear(self):
        while self.list.count() > 1:
            item = self.list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def do_search(self):
        q = self.search.text().strip()
        if not q:
            return
        if self.config.get("loader") != "fabric":
            self.status.setText(
                "Switch the loader to Fabric on the Play page to install mods.")
            return
        self.refresh_sub()
        self._clear()
        self.status.setText("Searching...")
        self.worker = SearchWorker(q, self.config.get("version"), "fabric")
        self.worker.results.connect(self._show)
        self.worker.failed.connect(self.status.setText)
        self.worker.start()

    def _show(self, hits):
        self._clear()
        self.icon_workers.clear()
        if not hits:
            self.status.setText("No mods matched that for this version.")
            return
        self.status.setText("%d results" % len(hits))
        for i, hit in enumerate(hits):
            card = ModCard(hit, self._install, self.icon_workers)
            self.list.insertWidget(self.list.count() - 1, card)
            fade_in(card, 200, delay=i * 35)   # staggered reveal

    def _install(self, card: ModCard):
        w = InstallWorker(card.hit.get("project_id", ""),
                          card.hit.get("title", "mod"),
                          self.mods_dir(),
                          self.config.get("version"), "fabric")
        w.progress.connect(card.set_progress)
        w.done.connect(lambda name, c=card: (c.set_done(True),
                                             self.status.setText("Installed %s" % name)))
        w.failed.connect(lambda msg, c=card: (c.set_done(False),
                                              self.status.setText(msg)))
        self.installers.append(w)
        w.start()

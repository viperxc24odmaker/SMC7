"""Mod browser — search Modrinth and install straight into the mods folder."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from PyQt6.QtCore import (QEasingCurve, QPropertyAnimation, Qt, QThread,
                          pyqtSignal)
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QFileDialog, QFrame, QGraphicsOpacityEffect,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QProgressBar, QPushButton, QScrollArea,
                             QStackedWidget, QVBoxLayout, QWidget)

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


class InstalledModsPanel(QWidget):
    """Lists .jar files sitting in the active instance's mods folder —
    enable/disable via the standard .jar.disabled rename trick (Fabric
    Loader skips anything not ending in .jar), plus delete."""

    def __init__(self, mods_dir_fn, parent=None):
        super().__init__(parent)
        self.mods_dir_fn = mods_dir_fn

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self.status = QLabel("")
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

    def _clear(self):
        while self.list.count() > 1:
            item = self.list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def refresh(self):
        self._clear()
        mods_dir = self.mods_dir_fn()
        if not mods_dir.exists():
            self.status.setText("No mods folder yet — install or upload a mod first.")
            return

        files = sorted(
            [f for f in mods_dir.iterdir()
             if f.is_file() and (f.suffix == ".jar" or f.name.endswith(".jar.disabled"))],
            key=lambda f: f.name.lower())

        if not files:
            self.status.setText("No mods installed for this instance yet.")
            return

        enabled = sum(1 for f in files if f.suffix == ".jar")
        self.status.setText("%d installed \u00b7 %d enabled" % (len(files), enabled))

        for f in files:
            self.list.insertWidget(self.list.count() - 1, self._row(f))

    def _row(self, path: Path):
        disabled = path.name.endswith(".jar.disabled")
        display_name = path.name[:-len(".disabled")] if disabled else path.name

        card = QFrame()
        card.setObjectName("Card2")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)

        try:
            size_mb = path.stat().st_size / (1024 * 1024)
        except OSError:
            size_mb = 0
        info = QVBoxLayout()
        info.setSpacing(2)
        name_lbl = QLabel(display_name)
        name_lbl.setStyleSheet(
            "font-size:13px; font-weight:600; %s"
            % ("color:%s;" % COLORS["muted"] if disabled else ""))
        info.addWidget(name_lbl)
        sub_lbl = QLabel("%.2f MB \u00b7 %s" % (size_mb, "Disabled" if disabled else "Enabled"))
        sub_lbl.setStyleSheet("font-size:10px; color:%s;" % COLORS["muted"])
        info.addWidget(sub_lbl)
        lay.addLayout(info, 1)

        toggle = QPushButton("Enable" if disabled else "Disable")
        toggle.setObjectName("Secondary")
        toggle.clicked.connect(lambda _, p=path, d=disabled: self._toggle(p, d))
        lay.addWidget(toggle)

        remove = QPushButton("Remove")
        remove.setObjectName("Ghost")
        remove.clicked.connect(lambda _, p=path, n=display_name: self._remove(p, n))
        lay.addWidget(remove)

        return card

    def _toggle(self, path: Path, currently_disabled: bool):
        try:
            if currently_disabled:
                path.rename(path.with_name(path.name[:-len(".disabled")]))
            else:
                path.rename(path.with_name(path.name + ".disabled"))
        except OSError as exc:
            QMessageBox.warning(self, "Couldn't toggle mod", str(exc))
        self.refresh()

    def _remove(self, path: Path, display_name: str):
        confirm = QMessageBox.question(
            self, "Remove mod",
            "Delete %s? This can't be undone." % display_name)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            path.unlink()
        except OSError as exc:
            QMessageBox.warning(self, "Couldn't remove mod", str(exc))
        self.refresh()


class ContentSearchWorker(QThread):
    results = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, query: str, project_type: str):
        super().__init__()
        self.query = query
        self.project_type = project_type

    def run(self):
        try:
            facets = '[["project_type:%s"]]' % self.project_type
            r = network.SESSION.get(
                "%s/search" % API,
                params={"query": self.query, "facets": facets, "limit": 20},
                timeout=15)
            r.raise_for_status()
            self.results.emit(r.json().get("hits", []))
        except Exception as exc:
            self.failed.emit("Couldn't reach Modrinth (%s)." % type(exc).__name__)


class ContentPacksPanel(QWidget):
    """Generic browse+install+manage panel for resource packs / data packs —
    single-file installs (unlike modpacks), so no manifest parsing needed."""

    def __init__(self, project_type: str, title: str, install_dir_fn, parent=None):
        super().__init__(parent)
        self.project_type = project_type
        self.install_dir_fn = install_dir_fn
        self.installers = []
        self.icon_workers = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search %s..." % title.lower())
        self.search.returnPressed.connect(self.do_search)
        bar.addWidget(self.search, 1)
        btn = QPushButton("Search")
        btn.setObjectName("Primary")
        btn.clicked.connect(self.do_search)
        bar.addWidget(btn)
        root.addLayout(bar)

        self.status = QLabel("Search for %s, or see what's installed below." % title.lower())
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

        self.refresh_installed()

    def _clear(self):
        while self.list.count() > 1:
            item = self.list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def do_search(self):
        q = self.search.text().strip()
        if not q:
            self.refresh_installed()
            return
        self._clear()
        self.status.setText("Searching...")
        w = ContentSearchWorker(q, self.project_type)
        w.results.connect(self._show_results)
        w.failed.connect(self.status.setText)
        self.installers.append(w)
        w.start()

    def _show_results(self, hits):
        self._clear()
        if not hits:
            self.status.setText("No results.")
            return
        self.status.setText("%d results" % len(hits))
        for hit in hits:
            self.list.insertWidget(self.list.count() - 1, self._result_card(hit))

    def _result_card(self, hit):
        card = QFrame()
        card.setObjectName("Card2")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)

        icon = make_icon_label()
        lay.addWidget(icon)
        load_icon_into(icon, hit.get("icon_url", ""), self.icon_workers)

        info = QVBoxLayout()
        info.setSpacing(2)
        info.addWidget(QLabel(hit.get("title", "Unknown")))
        desc = QLabel(hit.get("description", "")[:100])
        desc.setStyleSheet("font-size:10px; color:%s;" % COLORS["muted"])
        info.addWidget(desc)
        lay.addLayout(info, 1)

        install_btn = QPushButton("Install")
        install_btn.setObjectName("Secondary")
        install_btn.clicked.connect(lambda _, h=hit, b=None: self._install(h, install_btn))
        lay.addWidget(install_btn)
        return card

    def _install(self, hit, btn):
        btn.setEnabled(False)
        btn.setText("...")
        try:
            r = network.SESSION.get(
                "%s/project/%s/version" % (API, hit.get("project_id", "")),
                timeout=15)
            r.raise_for_status()
            versions = r.json()
            if not versions:
                raise RuntimeError("no versions found")
            files = versions[0].get("files", [])
            primary = next((f for f in files if f.get("primary")), files[0])
            dest_dir = self.install_dir_fn()
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / primary["filename"]
            resp = network.SESSION.get(primary["url"], stream=True, timeout=30)
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(65536):
                    if chunk:
                        fh.write(chunk)
            btn.setText("Installed")
            self.refresh_installed()
        except Exception as exc:
            btn.setText("Retry")
            btn.setEnabled(True)
            QMessageBox.warning(self, "Install failed", str(exc))

    def refresh_installed(self):
        self._clear()
        install_dir = self.install_dir_fn()
        if not install_dir.exists():
            self.status.setText("Nothing installed yet.")
            return
        files = sorted([f for f in install_dir.iterdir() if f.is_file()],
                       key=lambda f: f.name.lower())
        if not files:
            self.status.setText("Nothing installed yet.")
            return
        self.status.setText("%d installed" % len(files))
        for f in files:
            self.list.insertWidget(self.list.count() - 1, self._installed_row(f))

    def _installed_row(self, path: Path):
        card = QFrame()
        card.setObjectName("Card2")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)
        lay.addWidget(QLabel(path.name), 1)
        remove = QPushButton("Remove")
        remove.setObjectName("Ghost")
        remove.clicked.connect(lambda _, p=path: self._remove(p))
        lay.addWidget(remove)
        return card

    def _remove(self, path: Path):
        try:
            path.unlink()
        except OSError as exc:
            QMessageBox.warning(self, "Couldn't remove", str(exc))
        self.refresh_installed()


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

        # Browse / Installed tabs — same page, two views, matches the
        # launcher's existing tab-button pattern elsewhere.
        tabs = QHBoxLayout()
        tabs.setSpacing(8)
        self.tab_browse = QPushButton("Browse")
        self.tab_browse.setObjectName("Secondary")
        self.tab_browse.setCheckable(True)
        self.tab_browse.setChecked(True)
        self.tab_browse.clicked.connect(lambda: self._switch_tab(0))
        tabs.addWidget(self.tab_browse)
        self.tab_installed = QPushButton("Installed")
        self.tab_installed.setObjectName("Secondary")
        self.tab_installed.setCheckable(True)
        self.tab_installed.clicked.connect(lambda: self._switch_tab(1))
        tabs.addWidget(self.tab_installed)
        self.tab_packs = QPushButton("Modpacks")
        self.tab_packs.setObjectName("Secondary")
        self.tab_packs.setCheckable(True)
        self.tab_packs.clicked.connect(lambda: self._switch_tab(2))
        tabs.addWidget(self.tab_packs)
        self.tab_resource = QPushButton("Resource Packs")
        self.tab_resource.setObjectName("Secondary")
        self.tab_resource.setCheckable(True)
        self.tab_resource.clicked.connect(lambda: self._switch_tab(3))
        tabs.addWidget(self.tab_resource)
        self.tab_data = QPushButton("Data Packs")
        self.tab_data.setObjectName("Secondary")
        self.tab_data.setCheckable(True)
        self.tab_data.clicked.connect(lambda: self._switch_tab(4))
        tabs.addWidget(self.tab_data)
        tabs.addStretch(1)
        upload_btn = QPushButton("+ Upload Mod")
        upload_btn.setObjectName("Primary")
        upload_btn.clicked.connect(self._upload_mod)
        tabs.addWidget(upload_btn)
        root.addLayout(tabs)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # -- Browse view (existing search UI) --
        browse_view = QWidget()
        bl = QVBoxLayout(browse_view)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(12)

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
        bl.addLayout(bar)

        self.status = QLabel("Search for a mod to get started.")
        self.status.setObjectName("Subtitle")
        bl.addWidget(self.status)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.holder = QWidget()
        self.list = QVBoxLayout(self.holder)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(8)
        self.list.addStretch(1)
        self.scroll.setWidget(self.holder)
        bl.addWidget(self.scroll, 1)

        self.stack.addWidget(browse_view)

        # -- Installed view --
        self.installed_panel = InstalledModsPanel(self.mods_dir)
        self.stack.addWidget(self.installed_panel)

        # -- Modpacks view (existing ModpacksPage, embedded as a tab) --
        from .modpacks import ModpacksPage
        self.modpacks_panel = ModpacksPage(self.config)
        self.stack.addWidget(self.modpacks_panel)

        # -- Resource Packs / Data Packs --
        self.resource_panel = ContentPacksPanel(
            "resourcepack", "Resource Packs", self.resourcepacks_dir)
        self.stack.addWidget(self.resource_panel)
        self.data_panel = ContentPacksPanel(
            "datapack", "Data Packs", self.datapacks_dir)
        self.stack.addWidget(self.data_panel)

        self.refresh_sub()

    def resourcepacks_dir(self) -> Path:
        return Path(self.config.effective_game_dir()) / "resourcepacks"

    def datapacks_dir(self) -> Path:
        # NOTE: real datapacks live per-world (saves/<world>/datapacks), not
        # instance-wide — this is a simplification so they're at least
        # manageable from one place. Move manually into a world's datapacks
        # folder if you need per-world control.
        return Path(self.config.effective_game_dir()) / "datapacks"

    def _switch_tab(self, index):
        self.stack.setCurrentIndex(index)
        for i, b in enumerate((self.tab_browse, self.tab_installed, self.tab_packs,
                               self.tab_resource, self.tab_data)):
            b.setChecked(i == index)
        if index == 1:
            self.installed_panel.refresh()
        elif index == 3:
            self.resource_panel.refresh_installed()
        elif index == 4:
            self.data_panel.refresh_installed()

    def _upload_mod(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select mod .jar file(s)", "", "Mod files (*.jar)")
        if not paths:
            return
        dest_dir = self.mods_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        copied, failed = 0, []
        for p in paths:
            src = Path(p)
            try:
                shutil.copy2(src, dest_dir / src.name)
                copied += 1
            except OSError as exc:
                failed.append("%s (%s)" % (src.name, exc))
        if failed:
            QMessageBox.warning(
                self, "Some files failed",
                "Copied %d file(s).\nFailed:\n%s" % (copied, "\n".join(failed)))
        else:
            QMessageBox.information(
                self, "Upload complete", "Added %d mod file(s)." % copied)
        self._switch_tab(1)

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

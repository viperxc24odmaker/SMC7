"""Modpack browser — search Modrinth modpacks and install a full .mrpack
(manifest + mod files + overrides) into its own instance folder."""
from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QProgressBar, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from . import network
from .mods import fade_in, load_icon_into, make_icon_label
from .theme import COLORS

API = "https://api.modrinth.com/v2"


class PackSearchWorker(QThread):
    results = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, query: str, mc_version: str, loader: str):
        super().__init__()
        self.query = query
        self.mc_version = mc_version
        self.loader = loader

    def run(self):
        groups = ['["project_type:modpack"]', '["versions:%s"]' % self.mc_version]
        if self.loader:
            groups.insert(1, '["categories:%s"]' % self.loader)
        facets = "[%s]" % ",".join(groups)
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


class PackInstallWorker(QThread):
    """Downloads a .mrpack, resolves every file in its manifest, applies
    overrides, and drops the result into instances/<pack name>/."""
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, project_id: str, name: str, instances_root: Path,
                 mc_version: str, loader: str, icon_url: str = ""):
        super().__init__()
        self.project_id = project_id
        self.name = name
        self.instances_root = instances_root
        self.mc_version = mc_version
        self.loader = loader
        self.icon_url = icon_url

    def run(self):
        tmp_mrpack = None
        try:
            params = {"game_versions": '["%s"]' % self.mc_version}
            if self.loader:
                params["loaders"] = '["%s"]' % self.loader
            r = network.SESSION.get(
                "%s/project/%s/version" % (API, self.project_id),
                params=params, timeout=15)
            r.raise_for_status()
            versions = r.json()
            if not versions:
                self.failed.emit(
                    "%s has no build for %s yet." % (self.name, self.mc_version))
                return
            chosen = versions[0]
            # the pack defines its own loader — use it so the instance is correct
            self.loader = (chosen.get("loaders") or [self.loader or "fabric"])[0]

            files = chosen.get("files", [])
            primary = next((f for f in files if f.get("primary")), files[0])
            url = primary["url"]

            safe_name = "".join(c for c in self.name if c.isalnum() or c in " -_").strip()
            inst_dir = self.instances_root / safe_name
            inst_dir.mkdir(parents=True, exist_ok=True)
            tmp_mrpack = inst_dir / ".pack_download.mrpack"

            self.status.emit("Downloading pack manifest...")
            with network.SESSION.get(url, stream=True, timeout=30) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length") or 0)
                got = 0
                with open(tmp_mrpack, "wb") as fh:
                    for chunk in resp.iter_content(65536):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        got += len(chunk)
                        if total:
                            self.progress.emit(int(got * 40 / total))  # 0-40%

            with zipfile.ZipFile(tmp_mrpack) as zf:
                index = json.loads(zf.read("modrinth.index.json"))
                pack_files = index.get("files", [])
                total_files = max(len(pack_files), 1)

                for i, f in enumerate(pack_files):
                    env = f.get("env", {})
                    if env.get("client") == "unsupported":
                        continue
                    rel_path = f["path"]
                    dl_urls = f.get("downloads", [])
                    if not dl_urls:
                        continue
                    dest = inst_dir / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    self.status.emit("Fetching %s" % os.path.basename(rel_path))
                    self._download_first_ok(dl_urls, dest)
                    self.progress.emit(40 + int((i + 1) * 50 / total_files))  # 40-90%

                self.status.emit("Applying overrides...")
                for entry in zf.namelist():
                    if entry.startswith("overrides/") and not entry.endswith("/"):
                        rel = entry[len("overrides/"):]
                        target = inst_dir / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(entry) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)

            (inst_dir / ".smooth_pack_meta.json").write_text(json.dumps({
                "name": self.name, "mc_version": self.mc_version,
                "loader": self.loader, "icon_url": self.icon_url,
                "dependencies": index.get("dependencies", {}),
            }))

            self.progress.emit(100)
            self.done.emit(safe_name)
        except Exception as exc:
            self.failed.emit("Modpack install failed (%s). Nothing was left "
                             "half-broken — safe to retry." % type(exc).__name__)
        finally:
            if tmp_mrpack and tmp_mrpack.exists():
                try:
                    tmp_mrpack.unlink()
                except OSError:
                    pass

    def _download_first_ok(self, urls: list, dest: Path):
        last_exc = None
        for u in urls:
            try:
                with network.SESSION.get(u, stream=True, timeout=30) as resp:
                    resp.raise_for_status()
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    with open(tmp, "wb") as fh:
                        for chunk in resp.iter_content(65536):
                            if chunk:
                                fh.write(chunk)
                    os.replace(tmp, dest)
                    return
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc


class PackCard(QFrame):
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
        self.btn = QPushButton("Install Pack")
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

    def set_status(self, msg):
        self.btn.setToolTip(msg)

    def set_done(self, ok: bool):
        self.bar.hide()
        self.btn.setText("Installed" if ok else "Retry")
        self.btn.setEnabled(not ok)
        if ok:
            self.btn.setStyleSheet("color:%s;" % COLORS["success"])


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


class ModpacksPage(QWidget):
    """Search Modrinth modpacks and install each as its own instance."""

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
        t = QLabel("Modpacks")
        t.setObjectName("Title")
        head.addWidget(t)
        self.sub = QLabel("Each pack installs as its own instance")
        self.sub.setObjectName("Subtitle")
        head.addWidget(self.sub)
        root.addLayout(head)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search modpacks — cobblemon, better mc, skyblock...")
        self.search.returnPressed.connect(self.do_search)
        bar.addWidget(self.search, 1)
        self.loader_filter = QComboBox()
        for lbl, val in [("All loaders", ""), ("Fabric", "fabric"), ("Forge", "forge"),
                         ("NeoForge", "neoforge"), ("Quilt", "quilt")]:
            self.loader_filter.addItem(lbl, val)
        self.loader_filter.setFixedWidth(130)
        bar.addWidget(self.loader_filter)
        btn = QPushButton("Search")
        btn.setObjectName("Primary")
        btn.clicked.connect(self.do_search)
        bar.addWidget(btn)
        root.addLayout(bar)

        self.status = QLabel("Search for a modpack to get started.")
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

    def instances_dir(self) -> Path:
        return self.config.instances_dir

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
        self._clear()
        self.icon_workers.clear()
        self.status.setText("Searching...")
        loader = self.loader_filter.currentData() or ""
        self.worker = PackSearchWorker(q, self.config.get("version"), loader)
        self.worker.results.connect(self._show)
        self.worker.failed.connect(self.status.setText)
        self.worker.start()

    def _show(self, hits):
        self._clear()
        if not hits:
            self.status.setText("No modpacks matched that for this version.")
            return
        self.status.setText("%d results" % len(hits))
        for i, hit in enumerate(hits):
            card = PackCard(hit, self._install, self.icon_workers)
            self.list.insertWidget(self.list.count() - 1, card)
            fade_in(card, 200, delay=i * 35)

    def _install(self, card: PackCard):
        loader = self.loader_filter.currentData() or ""
        w = PackInstallWorker(card.hit.get("project_id", ""),
                              card.hit.get("title", "modpack"),
                              self.instances_dir(),
                              self.config.get("version"), loader,
                              card.hit.get("icon_url", ""))
        w.progress.connect(card.set_progress)
        w.status.connect(card.set_status)
        w.done.connect(lambda folder, c=card: (c.set_done(True),
                       self._register_instance(folder),
                       self.status.setText("Installed to instances/%s" % folder)))
        w.failed.connect(lambda msg, c=card: (c.set_done(False),
                                              self.status.setText(msg)))
        self.installers.append(w)
        w.start()

    def _register_instance(self, folder: str):
        """Turn a freshly installed modpack into a selectable profile,
        picked up next time the Play page's instance selector refreshes."""
        try:
            meta_path = self.instances_dir() / folder / ".smooth_pack_meta.json"
            meta = json.loads(meta_path.read_text())
            self.config.add_or_update_profile({
                "name": meta.get("name", folder),
                "version": meta.get("mc_version", self.config.get("version")),
                "loader": meta.get("loader", "fabric"),
                "game_dir": str(self.instances_dir() / folder),
                "icon_url": meta.get("icon_url", ""),
                "kind": "modpack",
            })
        except (OSError, ValueError):
            pass

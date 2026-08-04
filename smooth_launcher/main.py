"""Smooth Launcher — main window, pages, and entry point."""
from __future__ import annotations

import sys
import os
import webbrowser

from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (QApplication, QComboBox, QGraphicsDropShadowEffect, QFileDialog, QFrame,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QMessageBox, QProgressBar, QPushButton,
                             QScrollArea, QSlider, QStackedWidget, QVBoxLayout,
                             QWidget, QDialog)

from . import backend, network
from .mods import ModsPage, IconWorker, fade_in
from .modpacks import ModpacksPage
from .optimiser import OptimiserDialog
from .pages import CosmeticsPage, FriendsPage, SkinsPage
from .config import Config
from .panels import (FriendsPreviewPanel, GradientHeader, NewsPanel,
                     OnlineProbe, SkinHead, StatTile, StatusBar, TitleBar)
from .theme import COLORS, stylesheet
from .widgets import Avatar, ToggleSwitch

# QtWebEngine is deliberately NOT used: it bundles all of Chromium (~150MB).
# Microsoft login uses the system browser + a tiny localhost callback instead.
HAS_WEBENGINE = False


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _label(text, obj=None):
    lbl = QLabel(text)
    if obj:
        lbl.setObjectName(obj)
    return lbl


def _card(obj="Card"):
    f = QFrame()
    f.setObjectName(obj)
    return f


# --------------------------------------------------------------------------
# Version loader (off the UI thread so startup never blocks)
# --------------------------------------------------------------------------

class VersionsLoader(QThread):
    loaded = pyqtSignal(list)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        versions = network.fetch_release_versions(self.config.cache_dir)
        self.loaded.emit(versions)


# --------------------------------------------------------------------------
# Microsoft login dialog
# --------------------------------------------------------------------------

class _CallbackServer(QThread):
    """Tiny one-shot localhost server that catches the OAuth redirect."""
    got_url = pyqtSignal(str)

    def __init__(self, port: int):
        super().__init__()
        self.port = port
        self._srv = None

    def run(self):
        import http.server
        holder = {}

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(inner):
                holder["path"] = inner.path
                inner.send_response(200)
                inner.send_header("Content-Type", "text/html")
                inner.end_headers()
                inner.wfile.write(
                    b"<html><body style='background:#0d0e12;color:#f5f6fa;"
                    b"font-family:sans-serif;text-align:center;padding-top:80px'>"
                    b"<h2>Signed in!</h2><p>You can close this tab and return "
                    b"to Smooth Launcher.</p></body></html>")

            def log_message(inner, *args):
                pass

        try:
            self._srv = http.server.HTTPServer(("127.0.0.1", self.port), H)
            self._srv.timeout = 180
            self._srv.handle_request()
        except Exception:
            pass
        finally:
            try:
                if self._srv:
                    self._srv.server_close()
            except Exception:
                pass
        if holder.get("path"):
            self.got_url.emit("http://127.0.0.1:%d%s" % (self.port, holder["path"]))

    def stop(self):
        try:
            if self._srv:
                self._srv.server_close()
        except Exception:
            pass


class MicrosoftLoginDialog(QDialog):
    account_ready = pyqtSignal(dict)

    PORT = 5285

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Sign in with Microsoft")
        self.resize(460, 250)
        self._state = None
        self._verifier = None
        self._done = False
        self.server = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        cid = config.get("client_id")
        redirect = config.get("redirect_uri")
        if not cid:
            layout.addWidget(_label(
                "Add your Azure Client ID in Settings first, then try again.",
                "Subtitle"))
            b = QPushButton("Got it")
            b.setObjectName("Primary")
            b.clicked.connect(self.reject)
            layout.addWidget(b)
            return

        try:
            url, self._state, self._verifier = backend.ms_login_url(cid, redirect)
        except Exception as exc:
            layout.addWidget(_label("Couldn't start login: %s" % exc, "Subtitle"))
            return
        self._url = url

        layout.addWidget(_label(
            "Your browser will open for Microsoft sign-in. Come back here when "
            "it says you're signed in.", "Subtitle"))

        open_btn = QPushButton("Open Microsoft login")
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(self._start)
        layout.addWidget(open_btn)

        layout.addWidget(_label(
            "Not redirecting automatically? Paste the URL you landed on:",
            "SectionLabel"))
        self.paste = QLineEdit()
        self.paste.setPlaceholderText("http://127.0.0.1:5285/?code=...")
        layout.addWidget(self.paste)
        man = QPushButton("Finish sign in")
        man.setObjectName("Secondary")
        man.clicked.connect(lambda: self._complete(self.paste.text().strip()))
        layout.addWidget(man)
        layout.addStretch(1)

    def _start(self):
        if str(self.config.get("redirect_uri")).startswith("http://127.0.0.1"):
            self.server = _CallbackServer(self.PORT)
            self.server.got_url.connect(self._complete)
            self.server.start()
        webbrowser.open(self._url)

    def _complete(self, url):
        if self._done or not url:
            return
        cid = self.config.get("client_id")
        redirect = self.config.get("redirect_uri")
        try:
            account = backend.ms_complete_from_url(
                cid, redirect, url, self._state, self._verifier)
            self._done = True
            self.account_ready.emit(account)
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Sign in failed",
                                "Couldn't finish sign in:\n%s" % exc)

    def closeEvent(self, event):
        if self.server:
            self.server.stop()
        super().closeEvent(event)


def _qurl(url: str):
    from PyQt6.QtCore import QUrl
    return QUrl(url)


class ElyByLoginDialog(QDialog):
    """Username/password login for Ely.by — no browser needed, this is a
    plain Yggdrasil POST, unlike Microsoft's OAuth redirect flow."""
    account_ready = pyqtSignal(dict)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Sign in with Ely.by")
        self.resize(380, 220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        layout.addWidget(_label(
            "Ely.by lets you play with a free non-premium account — "
            "skins and capes come from your Ely.by profile.", "Subtitle"))

        layout.addWidget(_label("USERNAME OR EMAIL", "SectionLabel"))
        self.user_field = QLineEdit()
        layout.addWidget(self.user_field)

        layout.addWidget(_label("PASSWORD", "SectionLabel"))
        self.pass_field = QLineEdit()
        self.pass_field.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.pass_field)

        self.error_label = _label("", "Subtitle")
        self.error_label.setStyleSheet("color:#ff6b6b;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        btn = QPushButton("Sign in")
        btn.setObjectName("Primary")
        btn.clicked.connect(self._submit)
        layout.addWidget(btn)

        signup = _label(
            "Don't have an account? Create one free at ely.by", "Subtitle")
        layout.addWidget(signup)
        layout.addStretch(1)

    def _submit(self):
        username = self.user_field.text().strip()
        password = self.pass_field.text()
        if not username or not password:
            self._show_error("Enter both a username and password.")
            return
        if not network.is_online():
            self._show_error("You're offline — Ely.by sign-in needs a connection.")
            return
        try:
            account = backend.elyby_authenticate(username, password)
            self.account_ready.emit(account)
            self.accept()
        except Exception as exc:
            self._show_error(_elyby_friendly_error(exc))

    def _show_error(self, msg):
        self.error_label.setText(msg)
        self.error_label.show()


def _elyby_friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "403" in text or "ForbiddenOperationException" in text:
        return "Wrong username or password."
    if any(w in text.lower() for w in ("timeout", "connection", "resolve", "ssl")):
        return "Couldn't reach Ely.by — check your connection and try again."
    return "Sign in failed: %s" % text


# --------------------------------------------------------------------------
# Play page
# --------------------------------------------------------------------------

class PlayPage(QWidget):
    def __init__(self, config, get_account):
        super().__init__()
        self.config = config
        self.get_account = get_account
        self.worker = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 18)
        outer.setSpacing(14)

        self.header = GradientHeader("Ready to play", "Pick a version and jump in.")
        outer.addWidget(self.header)

        cols = QHBoxLayout()
        cols.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(12)
        cols.addLayout(left, 3)

        news = NewsPanel()
        news.setFixedWidth(230)
        cols.addWidget(news, 0)

        self.friends_panel = FriendsPreviewPanel(self.config)
        self.friends_panel.setFixedWidth(230)
        cols.addWidget(self.friends_panel, 0)
        outer.addLayout(cols, 1)

        root = left

        # player strip
        pcard = _card("Card")
        pl = QHBoxLayout(pcard)
        pl.setContentsMargins(16, 12, 16, 12)
        pl.setSpacing(12)
        self.head = SkinHead(52)
        pl.addWidget(self.head)
        pinfo = QVBoxLayout()
        pinfo.setSpacing(2)
        self.pname = QLabel("No account")
        self.pname.setStyleSheet("font-size:16px; font-weight:700;")
        pinfo.addWidget(self.pname)
        self.pkind = _label("Add one in Accounts", "Subtitle")
        pinfo.addWidget(self.pkind)
        pl.addLayout(pinfo)
        pl.addStretch(1)
        root.addWidget(pcard)

        # stat tiles
        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.tile_version = StatTile("--", "Version", accent=True)
        self.tile_loader = StatTile("--", "Loader")
        self.tile_ram = StatTile("--", "Memory")
        self.tile_launches = StatTile("0", "Launches")
        for t in (self.tile_version, self.tile_loader, self.tile_ram, self.tile_launches):
            stats.addWidget(t)
        root.addLayout(stats)

        card = _card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 24, 24, 24)
        cl.setSpacing(16)

        # version + loader row
        row = QHBoxLayout()
        row.setSpacing(14)

        vbox = QVBoxLayout()
        vbox.setSpacing(6)
        vbox.addWidget(_label("VERSION", "SectionLabel"))
        self.version_combo = QComboBox()
        self.version_combo.addItem("Loading versions...")
        self.version_combo.setEnabled(False)
        vbox.addWidget(self.version_combo)
        row.addLayout(vbox, 2)

        lbox = QVBoxLayout()
        lbox.setSpacing(6)
        lbox.addWidget(_label("LOADER", "SectionLabel"))
        self.loader_combo = QComboBox()
        self.loader_combo.addItems(["Fabric", "Vanilla"])
        self.loader_combo.setCurrentText(
            "Fabric" if self.config.get("loader") == "fabric" else "Vanilla")
        self.loader_combo.currentTextChanged.connect(self._loader_changed)
        lbox.addWidget(self.loader_combo)
        row.addLayout(lbox, 1)

        cl.addLayout(row)

        # instance selector — Lunar-style: base Minecraft or any modpack,
        # each with its own icon, version, loader and save data.
        ibox = QVBoxLayout()
        ibox.setSpacing(6)
        ibox.addWidget(_label("INSTANCE", "SectionLabel"))
        self.instance_combo = QComboBox()
        self.instance_combo.setIconSize(QSize(22, 22))
        self.instance_combo.currentIndexChanged.connect(self._instance_changed)
        ibox.addWidget(self.instance_combo)
        cl.addLayout(ibox)
        self._instance_icon_workers = []
        self._suspend_instance_signal = False
        self.refresh_instances()

        self.account_line = _label("", "Subtitle")
        self.account_line.hide()

        # Big centered pill launch button — Lunar-style green, not full-width.
        self.play_btn = QPushButton("LAUNCH")
        self.play_btn.setObjectName("Primary")
        self.play_btn.setFixedSize(280, 56)
        self.play_btn.setStyleSheet("""
            QPushButton#Primary {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #3ddc84, stop:1 #2bb86a);
                color: #0b1410;
                font-size: 15px;
                font-weight: 800;
                letter-spacing: 1px;
                border-radius: 14px;
            }
            QPushButton#Primary:hover { background: #45e792; }
            QPushButton#Primary:disabled { background: #3a4048; color: #7a8290; }
        """)
        _glow = QGraphicsDropShadowEffect(self.play_btn)
        _glow.setBlurRadius(42)
        _glow.setOffset(0, 8)
        _glow.setColor(QColor(61, 220, 132, 160))
        self.play_btn.setGraphicsEffect(_glow)
        self.play_btn.clicked.connect(self.on_play)
        _play_row = QHBoxLayout()
        _play_row.addStretch(1)
        _play_row.addWidget(self.play_btn)
        _play_row.addStretch(1)
        cl.addLayout(_play_row)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        cl.addWidget(self.progress)

        self.status = _label("", "Subtitle")
        cl.addWidget(self.status)

        root.addWidget(card)
        root.addStretch(1)

        # load versions in the background
        self.vloader = VersionsLoader(self.config)
        self.vloader.loaded.connect(self._versions_loaded)
        self.vloader.start()

        self.refresh_account()

    # -- instance selector (Lunar-style) ------------------------------------
    def _default_icon(self) -> QIcon:
        ico_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(ico_path):
            return QIcon(ico_path)
        return QIcon()

    def refresh_instances(self):
        """Rebuild the dropdown from config.profiles() — base Minecraft
        plus every installed modpack, each with its own icon."""
        self.instance_combo.blockSignals(True)
        self.instance_combo.clear()
        self._instance_icon_workers.clear()

        self.instance_combo.addItem(self._default_icon(),
                                    "Default (Vanilla / Fabric)", None)

        active_name = None
        active = self.config.active_profile()
        if active and self.config.get("game_dir"):
            active_name = active.get("name")

        select_index = 0
        for prof in self.config.profiles():
            self.instance_combo.addItem(QIcon(), prof.get("name", "Instance"), prof)
            idx = self.instance_combo.count() - 1
            url = prof.get("icon_url")
            if url:
                self._load_combo_icon(idx, url)
            if prof.get("name") == active_name:
                select_index = idx

        self.instance_combo.setCurrentIndex(select_index)
        self.instance_combo.blockSignals(False)

    def _load_combo_icon(self, index: int, url: str):
        worker = IconWorker(url)

        def _apply(data: bytes, i=index):
            try:
                pix = QPixmap()
                if pix.loadFromData(data):
                    self.instance_combo.setItemIcon(
                        i, QIcon(pix.scaled(22, 22)))
            except RuntimeError:
                pass  # combo was rebuilt mid-fetch, ignore

        worker.loaded.connect(_apply)
        self._instance_icon_workers.append(worker)
        worker.start()

    def _instance_changed(self, index):
        if index < 0:
            return
        data = self.instance_combo.itemData(index)
        if data:
            self.config.set_active_profile(data["name"])
            self.config.set("game_dir", data.get("game_dir", ""))
            self.config.set("version", data.get("version", self.config.get("version")))
            self.config.set("loader", data.get("loader", "fabric"))
        else:
            self.config.data["active_profile"] = None
            self.config.set("game_dir", "")

        self.loader_combo.blockSignals(True)
        self.loader_combo.setCurrentText(
            "Fabric" if self.config.get("loader") == "fabric" else "Vanilla")
        self.loader_combo.blockSignals(False)

        v_idx = self.version_combo.findText(self.config.get("version"))
        if v_idx >= 0:
            self.version_combo.blockSignals(True)
            self.version_combo.setCurrentIndex(v_idx)
            self.version_combo.blockSignals(False)

        self.refresh_tiles()

    # -- version handling --------------------------------------------------
    def _versions_loaded(self, versions):
        self.version_combo.clear()
        self.version_combo.addItems(versions)
        self.version_combo.setEnabled(True)
        want = self.config.get("version")
        idx = self.version_combo.findText(want)
        if idx >= 0:
            self.version_combo.setCurrentIndex(idx)
        elif versions:
            self.config.set("version", versions[0])
        self.version_combo.currentTextChanged.connect(
            lambda v: self.config.set("version", v))

    def _loader_changed(self, text):
        self.config.set("loader", "fabric" if text == "Fabric" else "vanilla")
        self.refresh_tiles()

    # -- account -----------------------------------------------------------
    def refresh_account(self):
        acc = self.get_account()
        if acc:
            kind = "Microsoft" if acc.get("type") == "microsoft" else "Offline"
            self.account_line.setText("Playing as  %s" % acc["name"])
            self.pname.setText(acc["name"])
            self.pkind.setText("%s account" % kind)
            self.head.set_player(acc["name"], acc.get("uuid", ""),
                                 acc.get("type") == "microsoft")
            self.header.set_subtitle("Welcome back, %s." % acc["name"])
            self.play_btn.setEnabled(True)
        else:
            self.pname.setText("No account")
            self.pkind.setText("Add one in the Accounts tab")
            self.head.set_player("?")
            self.header.set_subtitle("Add an account to get started.")
            self.play_btn.setEnabled(False)
        self.refresh_tiles()

    def refresh_tiles(self):
        self.tile_version.set_value(self.config.get("version") or "--")
        self.tile_loader.set_value(
            "Fabric" if self.config.get("loader") == "fabric" else "Vanilla")
        ram = int(self.config.get("ram_mb", 2048))
        self.tile_ram.set_value("%.1f GB" % (ram / 1024))
        self.tile_launches.set_value(str(self.config.get("launch_count", 0)))

    # -- launch ------------------------------------------------------------
    def on_play(self):
        acc = self.get_account()
        if not acc:
            return
        self.play_btn.setEnabled(False)
        self.play_btn.setText("WORKING...")
        self.progress.show()
        self.progress.setRange(0, 0)  # indeterminate until we get a max
        self.status.setText("Starting up...")

        self.worker = backend.LaunchWorker(self.config, dict(acc))
        self.worker.status.connect(self.status.setText)
        self.worker.maximum.connect(self._set_max)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished_ok.connect(self._launched)
        # show optimiser popup whenever Fabric is freshly installed
        self.worker.finished_ok.connect(self._maybe_optimise)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _set_max(self, m):
        if m > 0:
            self.progress.setRange(0, m)

    def _maybe_optimise(self):
        """Only show the popup once per fresh install, not on every launch."""
        key = "optimiser_shown_%s" % self.config.get("version")
        if not self.config.get(key):
            self.config.set(key, True)
            dlg = OptimiserDialog(self.config, self)
            dlg.exec()

    def _launched(self):
        self.config.set("launch_count", int(self.config.get("launch_count", 0)) + 1)
        self.refresh_tiles()
        self.status.setText("Minecraft is starting — have fun! 🎮")
        self.progress.hide()
        self._reset_button()
        if not self.config.get("keep_launcher_open"):
            QApplication.quit()

    def _failed(self, msg):
        self.progress.hide()
        self._reset_button()
        self.status.setText("")
        QMessageBox.warning(self, "Couldn't launch", msg)

    def _reset_button(self):
        self.play_btn.setEnabled(True)
        self.play_btn.setText("LAUNCH")


# --------------------------------------------------------------------------
# Accounts page
# --------------------------------------------------------------------------

class AccountsPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self.config = config

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.addWidget(_label("Accounts", "Title"))
        title_box.addWidget(_label("Microsoft and offline profiles.", "Subtitle"))
        header.addLayout(title_box)
        header.addStretch(1)

        ms_btn = QPushButton("+ Microsoft")
        ms_btn.setObjectName("Primary")
        ms_btn.clicked.connect(self.add_microsoft)
        ely_btn = QPushButton("+ Ely.by")
        ely_btn.setObjectName("Secondary")
        ely_btn.clicked.connect(self.add_elyby)
        off_btn = QPushButton("+ Offline")
        off_btn.setObjectName("Secondary")
        off_btn.clicked.connect(self.add_offline)
        header.addWidget(off_btn)
        header.addWidget(ely_btn)
        header.addWidget(ms_btn)
        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.container = QWidget()
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setContentsMargins(0, 6, 0, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)

        self.rebuild()

    def rebuild(self):
        # clear existing rows (keep the trailing stretch)
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        accounts = self.config.accounts()
        if not accounts:
            empty = _label("No accounts yet — add a Microsoft or offline profile.",
                           "Subtitle")
            self.list_layout.insertWidget(0, empty)
            return

        active = self.config.get("active_account")
        for acc in accounts:
            self.list_layout.insertWidget(
                self.list_layout.count() - 1,
                self._account_row(acc, acc.get("uuid") == active))

    def _account_row(self, acc, is_active):
        card = _card("Card2")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)

        lay.addWidget(Avatar(acc.get("name", "?"), 42))

        info = QVBoxLayout()
        info.setSpacing(2)
        name = _label(acc.get("name", "Player"))
        name.setStyleSheet("font-size:15px; font-weight:600;")
        info.addWidget(name)
        badge_text = {"microsoft": "Microsoft", "elyby": "Ely.by"}.get(
            acc.get("type"), "Offline")
        badge_obj = {"microsoft": "BadgeMs", "elyby": "BadgeElyBy"}.get(
            acc.get("type"), "BadgeOff")
        badge = _label(badge_text, "Badge")
        badge.setObjectName(badge_obj)
        badge.setFixedWidth(80)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.addWidget(badge)
        lay.addLayout(info)
        lay.addStretch(1)

        if is_active:
            active_lbl = _label("● Active")
            active_lbl.setStyleSheet("color:%s; font-weight:600;" % COLORS["success"])
            lay.addWidget(active_lbl)
        else:
            use = QPushButton("Use")
            use.setObjectName("Secondary")
            use.clicked.connect(lambda _, u=acc["uuid"]: self._set_active(u))
            lay.addWidget(use)

        rm = QPushButton("Remove")
        rm.setObjectName("Ghost")
        rm.clicked.connect(lambda _, u=acc["uuid"]: self._remove(u))
        lay.addWidget(rm)
        return card

    def _set_active(self, uuid):
        self.config.set_active(uuid)
        self.rebuild()
        self.changed.emit()

    def _remove(self, uuid):
        self.config.remove_account(uuid)
        self.rebuild()
        self.changed.emit()

    def add_offline(self):
        name, ok = QInputDialog.getText(self, "Offline account", "Username:")
        if ok and name.strip():
            acc = backend.make_offline_account(name)
            self.config.add_or_update_account(acc)
            self.rebuild()
            self.changed.emit()

    def add_microsoft(self):
        if not self.config.get("client_id"):
            QMessageBox.information(
                self, "Client ID needed",
                "Add your Azure Client ID in Settings first, then sign in.")
            return
        dlg = MicrosoftLoginDialog(self.config, self)
        dlg.account_ready.connect(self._ms_ready)
        dlg.exec()

    def _ms_ready(self, account):
        self.config.add_or_update_account(account)
        self.rebuild()
        self.changed.emit()

    def add_elyby(self):
        dlg = ElyByLoginDialog(self.config, self)
        dlg.account_ready.connect(self._elyby_ready)
        dlg.exec()

    def _elyby_ready(self, account):
        self.config.add_or_update_account(account)
        self.rebuild()
        self.changed.emit()


# --------------------------------------------------------------------------
# Settings page
# --------------------------------------------------------------------------

class SettingsPage(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        body = QWidget()
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)

        root.addWidget(_label("Settings", "Title"))

        # --- Microsoft / Azure ---
        auth_card = _card()
        al = QVBoxLayout(auth_card)
        al.setContentsMargins(22, 20, 22, 20)
        al.setSpacing(8)
        al.addWidget(_label("MICROSOFT LOGIN", "SectionLabel"))
        al.addWidget(_label(
            "Paste the Application (client) ID from your Azure app registration.",
            "Subtitle"))
        self.client_id = QLineEdit(self.config.get("client_id"))
        self.client_id.setPlaceholderText("Azure Client ID")
        al.addWidget(self.client_id)
        al.addWidget(_label("Redirect URI (leave default unless yours differs):",
                            "SectionLabel"))
        self.redirect = QLineEdit(self.config.get("redirect_uri"))
        al.addWidget(self.redirect)
        root.addWidget(auth_card)

        # --- Game ---
        game_card = _card()
        gl = QVBoxLayout(game_card)
        gl.setContentsMargins(22, 20, 22, 20)
        gl.setSpacing(10)
        gl.addWidget(_label("GAME", "SectionLabel"))

        self.ram_label = _label("")
        gl.addWidget(self.ram_label)
        self.ram = QSlider(Qt.Orientation.Horizontal)
        self.ram.setRange(512, 16384)
        self.ram.setSingleStep(512)
        self.ram.setPageStep(1024)
        self.ram.setValue(int(self.config.get("ram_mb", 2048)))
        self.ram.valueChanged.connect(self._ram_changed)
        self._ram_changed(self.ram.value())
        gl.addWidget(self.ram)

        gl.addWidget(_label("Game directory (blank = default .minecraft):",
                            "SectionLabel"))
        gdir_row = QHBoxLayout()
        self.game_dir = QLineEdit(self.config.get("game_dir"))
        gdir_row.addWidget(self.game_dir)
        gbrowse = QPushButton("Browse")
        gbrowse.setObjectName("Secondary")
        gbrowse.clicked.connect(self._pick_dir)
        gdir_row.addWidget(gbrowse)
        gl.addLayout(gdir_row)

        gl.addWidget(_label("Java path (blank = auto-detect):", "SectionLabel"))
        jrow = QHBoxLayout()
        self.java_path = QLineEdit(self.config.get("java_path"))
        jrow.addWidget(self.java_path)
        jbrowse = QPushButton("Browse")
        jbrowse.setObjectName("Secondary")
        jbrowse.clicked.connect(self._pick_java)
        jrow.addWidget(jbrowse)
        gl.addLayout(jrow)

        keep_row = QHBoxLayout()
        keep_row.addWidget(_label("Keep launcher open after Play"))
        keep_row.addStretch(1)
        self.keep_toggle = ToggleSwitch(bool(self.config.get("keep_launcher_open")))
        keep_row.addWidget(self.keep_toggle)
        gl.addLayout(keep_row)

        root.addWidget(game_card)

        save = QPushButton("Save settings")
        save.setObjectName("Primary")
        save.clicked.connect(self.save)
        root.addWidget(save)
        root.addStretch(1)

    def _ram_changed(self, value):
        gb = value / 1024
        self.ram_label.setText("Memory:  %d MB  (%.1f GB)" % (value, gb))

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose game directory")
        if d:
            self.game_dir.setText(d)

    def _pick_java(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose Java executable")
        if f:
            self.java_path.setText(f)

    def save(self):
        self.config.set("client_id", self.client_id.text().strip())
        self.config.set("redirect_uri", self.redirect.text().strip()
                        or self.config.get("redirect_uri"))
        self.config.set("ram_mb", int(self.ram.value()))
        self.config.set("game_dir", self.game_dir.text().strip())
        self.config.set("java_path", self.java_path.text().strip())
        self.config.set("keep_launcher_open", self.keep_toggle.isChecked())
        QMessageBox.information(self, "Saved", "Settings saved.")


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------

class MainWindow(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setObjectName("Root")
        self.setWindowTitle("Smooth Launcher")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._edge = None          # which edge is being dragged
        self._start = None         # (globalPos, geometry) when the drag began
        self.MARGIN = 6            # px hit-zone around the window border
        self.resize(1010, 680)
        self.setMinimumSize(880, 600)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        shell.setSpacing(0)

        frame = QFrame()
        frame.setObjectName("Shell")
        shell.addWidget(frame)

        vshell = QVBoxLayout(frame)
        vshell.setContentsMargins(0, 0, 0, 0)
        vshell.setSpacing(0)
        vshell.addWidget(TitleBar(self))

        body = QWidget()
        vshell.addWidget(body, 1)

        outer = QHBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # sidebar
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(68)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(10, 22, 10, 18)
        sl.setSpacing(6)

        logo = QLabel()
        logo.setObjectName("Logo")
        logo.setText('<span id="LogoAccent" style="color:%s">S</span>'
                     % COLORS["accent2"])
        logo.setTextFormat(Qt.TextFormat.RichText)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl.addWidget(logo)
        sl.addSpacing(16)

        _s1 = QLabel("PLAY")
        _s1.setObjectName("NavSection")
        _s1.hide()
        sl.addWidget(_s1)

        self.nav_play = self._nav("  ▶   Play")
        self.nav_acc = self._nav("  ◍   Accounts")
        self.nav_mods = self._nav("  ▣   Mods")
        self.nav_packs = self._nav("  ▤   Modpacks")
        self.nav_cos = self._nav("  ✦   Cosmetics")
        self.nav_skins = self._nav("  ◈   Skins")
        self.nav_friends = self._nav("  ●   Friends")
        self.nav_set = self._nav("  ⚙   Settings")
        sl.addWidget(self.nav_play)
        sl.addWidget(self.nav_acc)
        sl.addWidget(self.nav_mods)
        sl.addWidget(self.nav_packs)
        sl.addSpacing(10)
        _s3 = QLabel("PROFILE")
        _s3.setObjectName("NavSection")
        _s3.hide()
        sl.addWidget(_s3)
        sl.addWidget(self.nav_cos)
        sl.addWidget(self.nav_skins)
        sl.addWidget(self.nav_friends)
        sl.addSpacing(10)
        _s2 = QLabel("SYSTEM")
        _s2.setObjectName("NavSection")
        _s2.hide()
        sl.addWidget(_s2)
        sl.addWidget(self.nav_set)
        sl.addStretch(1)

        # active-account chip — icon rail only shows the avatar, full name
        # lives in the tooltip (set alongside chip_name.setText elsewhere)
        self.chip = _card("Card2")
        chip_l = QHBoxLayout(self.chip)
        chip_l.setContentsMargins(6, 6, 6, 6)
        chip_l.setSpacing(0)
        self.chip_avatar = Avatar("?", 30)
        chip_l.addWidget(self.chip_avatar, 0, Qt.AlignmentFlag.AlignCenter)
        self.chip_name = _label("No account")
        self.chip_name.hide()
        sl.addWidget(self.chip)
        tip = QLabel("v1.0.0")
        tip.setObjectName("Hint")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip.setStyleSheet("font-size:8px;")
        sl.addWidget(tip)

        outer.addWidget(sidebar)

        # pages
        self.stack = QStackedWidget()
        self.play_page = PlayPage(self.config, self.config.active)
        self.accounts_page = AccountsPage(self.config)
        self.mods_page = ModsPage(self.config)
        self.packs_page = ModpacksPage(self.config)
        self.cos_page = CosmeticsPage(self.config)
        self.skins_page = SkinsPage(self.config)
        self.friends_page = FriendsPage(self.config)
        self.settings_page = SettingsPage(self.config)
        self.accounts_page.changed.connect(self._accounts_changed)
        self.stack.addWidget(self.play_page)
        self.stack.addWidget(self.accounts_page)
        self.stack.addWidget(self.mods_page)
        self.stack.addWidget(self.packs_page)
        self.stack.addWidget(self.cos_page)
        self.stack.addWidget(self.skins_page)
        self.stack.addWidget(self.friends_page)
        self.stack.addWidget(self.settings_page)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.stack, 1)
        self.status_bar = StatusBar()
        rl.addWidget(self.status_bar)
        outer.addWidget(right, 1)

        self.probe = OnlineProbe()
        self.probe.result.connect(self.status_bar.set_online)
        self.probe.start()

        self.nav_play.clicked.connect(lambda: self._go(0, self.nav_play))
        self.nav_acc.clicked.connect(lambda: self._go(1, self.nav_acc))
        self.nav_mods.clicked.connect(lambda: self._go(2, self.nav_mods))
        self.nav_packs.clicked.connect(lambda: self._go(3, self.nav_packs))
        self.nav_cos.clicked.connect(lambda: self._go(4, self.nav_cos))
        self.nav_skins.clicked.connect(lambda: self._go(5, self.nav_skins))
        self.nav_friends.clicked.connect(lambda: self._go(6, self.nav_friends))
        self.nav_set.clicked.connect(lambda: self._go(7, self.nav_set))
        self._go(0, self.nav_play)
        self._update_chip()

    # ── frameless resizing ──────────────────────────────────────────────
    def _edge_at(self, pos):
        """Return which border the cursor is on, or None."""
        m, w, h = self.MARGIN, self.width(), self.height()
        x, y = pos.x(), pos.y()
        left, right = x <= m, x >= w - m
        top, bottom = y <= m, y >= h - m
        if top and left: return "tl"
        if top and right: return "tr"
        if bottom and left: return "bl"
        if bottom and right: return "br"
        if left: return "l"
        if right: return "r"
        if top: return "t"
        if bottom: return "b"
        return None

    _CURSORS = {
        "l": Qt.CursorShape.SizeHorCursor,  "r": Qt.CursorShape.SizeHorCursor,
        "t": Qt.CursorShape.SizeVerCursor,  "b": Qt.CursorShape.SizeVerCursor,
        "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
        "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
    }

    def mouseMoveEvent(self, event):
        if self._edge and self._start:
            self._do_resize(event.globalPosition().toPoint())
            return
        if not self.isMaximized():
            edge = self._edge_at(event.position().toPoint())
            self.setCursor(self._CURSORS.get(edge, Qt.CursorShape.ArrowCursor))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            edge = self._edge_at(event.position().toPoint())
            if edge:
                self._edge = edge
                self._start = (event.globalPosition().toPoint(), self.geometry())
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._edge = None
        self._start = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def _do_resize(self, gpos):
        origin, geo = self._start
        dx = gpos.x() - origin.x()
        dy = gpos.y() - origin.y()
        left, top = geo.left(), geo.top()
        right, bottom = geo.right(), geo.bottom()
        e = self._edge

        if "l" in e: left += dx
        if "r" in e: right += dx
        if "t" in e: top += dy
        if "b" in e: bottom += dy

        # respect the minimum size so the layout never gets crushed
        minw, minh = self.minimumWidth(), self.minimumHeight()
        if right - left < minw:
            if "l" in e: left = right - minw
            else: right = left + minw
        if bottom - top < minh:
            if "t" in e: top = bottom - minh
            else: bottom = top + minh

        self.setGeometry(left, top, right - left, bottom - top)

    def leaveEvent(self, event):
        if not self._edge:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def _nav(self, text):
        # Icon-only rail (Lunar-style) — the glyph is the first non-space
        # character, full label lives in the tooltip instead of on-button.
        icon = text.strip().split(None, 1)[0]
        btn = QPushButton(icon)
        btn.setObjectName("NavItem")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(text.strip().split(None, 1)[1] if len(text.strip().split(None, 1)) > 1 else text.strip())
        btn.setFixedSize(44, 44)
        btn.setStyleSheet("font-size:17px;")
        return btn

    def _go(self, index, active_btn):
        self.stack.setCurrentIndex(index)
        fade_in(self.stack.currentWidget(), 180)   # smooth page transition
        if index == 0:
            self.play_page.refresh_instances()
            self.play_page.friends_panel.refresh()
        elif index == 2:
            self.mods_page.refresh_sub()
        elif index == 5:
            self.skins_page.refresh_mode()
        for b in (self.nav_play, self.nav_acc, self.nav_mods, self.nav_packs,
                  self.nav_cos, self.nav_skins, self.nav_friends, self.nav_set):
            b.setChecked(b is active_btn)

    def _accounts_changed(self):
        self.play_page.refresh_account()
        self.skins_page.refresh_mode()
        self._update_chip()

    def _update_chip(self):
        acc = self.config.active()
        if acc:
            self.chip_avatar.set_name(acc.get("name", "?"))
            self.chip_name.setText(acc.get("name", "Player"))
            self.chip.setToolTip(acc.get("name", "Player"))
        else:
            self.chip_avatar.set_name("?")
            self.chip_name.setText("No account")
            self.chip.setToolTip("No account — open Accounts")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Smooth Launcher")
    import os
    from PyQt6.QtGui import QIcon
    _ico = os.path.join(os.path.dirname(__file__), "icon.png")
    if os.path.exists(_ico):
        app.setWindowIcon(QIcon(_ico))
    app.setStyleSheet(stylesheet())
    config = Config()
    win = MainWindow(config)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

"""Minecraft operations: accounts, installation, and launching.

All heavy/network work runs on a QThread worker so the UI never freezes, and
every network touch is wrapped so a dropped connection produces a friendly
error signal instead of a crash.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import uuid as uuidlib

import minecraft_launcher_lib as mll
from PyQt6.QtCore import QThread, pyqtSignal

from . import network


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------

def offline_uuid(name: str) -> str:
    """Replicate Java's UUID.nameUUIDFromBytes("OfflinePlayer:"+name).

    This produces the exact same UUID vanilla assigns to an offline player,
    so worlds/inventories stay consistent.
    """
    data = ("OfflinePlayer:" + name).encode("utf-8")
    digest = bytearray(hashlib.md5(data).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30  # version 3
    digest[8] = (digest[8] & 0x3F) | 0x80  # RFC 4122 variant
    return str(uuidlib.UUID(bytes=bytes(digest)))


def make_offline_account(name: str) -> dict:
    name = name.strip()
    return {
        "type": "offline",
        "name": name,
        "uuid": offline_uuid(name),
        "token": "0",
    }


# ---- Microsoft OAuth helpers (auth-code flow) ----------------------------

def ms_login_url(client_id: str, redirect_uri: str):
    """Return (login_url, state, code_verifier)."""
    return mll.microsoft_account.get_secure_login_data(client_id, redirect_uri)


def ms_url_has_code(url: str) -> bool:
    try:
        return mll.microsoft_account.url_contains_auth_code(url)
    except Exception:
        return False


def ms_complete_from_url(client_id: str, redirect_uri: str, url: str,
                         state: str, code_verifier: str) -> dict:
    """Finish login given the redirected URL. Returns an account dict."""
    auth_code = mll.microsoft_account.parse_auth_code_url(url, state)
    login = network.resilient(
        mll.microsoft_account.complete_login,
        client_id, None, redirect_uri, auth_code, code_verifier,
    )
    return {
        "type": "microsoft",
        "name": login["name"],
        "uuid": login["id"],
        "token": login["access_token"],
        "refresh_token": login.get("refresh_token", ""),
    }


def ms_refresh(client_id: str, redirect_uri: str, refresh_token: str) -> dict | None:
    """Try to refresh an access token silently. Returns updated fields or None."""
    try:
        data = network.resilient(
            mll.microsoft_account.complete_refresh,
            client_id, None, redirect_uri, refresh_token,
        )
        return {
            "name": data["name"],
            "uuid": data["id"],
            "token": data["access_token"],
            "refresh_token": data.get("refresh_token", refresh_token),
        }
    except Exception:
        return None


# ---- Ely.by helpers (Yggdrasil auth for non-premium accounts) ------------
#
# Ely.by speaks the old Mojang Yggdrasil auth protocol, so this is a plain
# username/password POST — no browser redirect needed, unlike Microsoft.
# Skins/capes need authlib-injector pointed at Ely.by's session server at
# launch time (see ensure_authlib_injector + LaunchWorker._build_options).

ELYBY_AUTH_SERVER = "https://authserver.ely.by"
AUTHLIB_INJECTOR_VERSION = "1.2.5"
AUTHLIB_INJECTOR_URL = (
    "https://github.com/yushijinhun/authlib-injector/releases/download/"
    "v%s/authlib-injector-%s.jar" % (AUTHLIB_INJECTOR_VERSION, AUTHLIB_INJECTOR_VERSION)
)


def elyby_authenticate(username: str, password: str) -> dict:
    """Log in with an Ely.by username/password. Returns an account dict."""
    client_token = str(uuidlib.uuid4())
    payload = {
        "agent": {"name": "Minecraft", "version": 1},
        "username": username.strip(),
        "password": password,
        "clientToken": client_token,
        "requestUser": False,
    }
    resp = network.resilient(
        network.SESSION.post,
        "%s/auth/authenticate" % ELYBY_AUTH_SERVER,
        json=payload, timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()

    profile = body.get("selectedProfile") or {}
    return {
        "type": "elyby",
        "name": profile.get("name", username.strip()),
        "uuid": _dashed_uuid(profile.get("id", "")),
        "token": body["accessToken"],
        "client_token": body.get("clientToken", client_token),
    }


def elyby_refresh(account: dict) -> dict | None:
    """Refresh an Ely.by access token using its stored clientToken."""
    try:
        payload = {
            "accessToken": account.get("token", ""),
            "clientToken": account.get("client_token", ""),
            "requestUser": False,
        }
        resp = network.resilient(
            network.SESSION.post,
            "%s/auth/refresh" % ELYBY_AUTH_SERVER,
            json=payload, timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        profile = body.get("selectedProfile") or {}
        return {
            "name": profile.get("name", account.get("name", "Player")),
            "uuid": _dashed_uuid(profile.get("id", "")) or account.get("uuid"),
            "token": body["accessToken"],
            "client_token": body.get("clientToken", account.get("client_token", "")),
        }
    except Exception:
        return None


def _dashed_uuid(raw: str) -> str:
    """Ely.by returns UUIDs without dashes — normalise to the standard form."""
    raw = (raw or "").replace("-", "")
    if len(raw) != 32:
        return raw
    return "%s-%s-%s-%s-%s" % (raw[0:8], raw[8:12], raw[12:16], raw[16:20], raw[20:32])


def ensure_authlib_injector(cache_dir) -> str | None:
    """Downloads authlib-injector.jar once and caches it — required so the
    game fetches skins/capes from Ely.by's session server instead of
    Mojang's, which would otherwise 404 for non-premium accounts."""
    from pathlib import Path
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    jar_path = cache_dir / ("authlib-injector-%s.jar" % AUTHLIB_INJECTOR_VERSION)
    if jar_path.exists():
        return str(jar_path)
    try:
        resp = network.resilient(
            lambda: network.SESSION.get(AUTHLIB_INJECTOR_URL, timeout=30, stream=True),
            retries=3,
        )
        resp.raise_for_status()
        with open(jar_path, "wb") as fh:
            for chunk in resp.iter_content(65536):
                if chunk:
                    fh.write(chunk)
        return str(jar_path)
    except Exception:
        return None  # launch still proceeds — just no custom skins this run


# --------------------------------------------------------------------------
# Install + launch worker
# --------------------------------------------------------------------------

class LaunchWorker(QThread):
    """Installs the requested version (and Fabric if needed) then launches.

    Signals:
        status(str)    - human readable step
        progress(int)  - current progress value
        maximum(int)   - progress bar max
        finished_ok()  - launched successfully
        failed(str)    - friendly error message
    """
    status = pyqtSignal(str)
    progress = pyqtSignal(int)
    maximum = pyqtSignal(int)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, config, account: dict):
        super().__init__()
        self.config = config
        self.account = account
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    # progress callback dict expected by minecraft-launcher-lib
    def _callback(self):
        return {
            "setStatus": lambda s: self.status.emit(str(s)),
            "setProgress": lambda v: self.progress.emit(int(v)),
            "setMax": lambda v: self.maximum.emit(int(v)),
        }

    def run(self):
        try:
            self._maybe_refresh_token()
            game_dir = self.config.effective_game_dir()
            mc_version = self.config.get("version")
            loader = self.config.get("loader")
            cb = self._callback()

            installed_ids = _installed_ids(game_dir)

            # Decide the version id we will actually launch.
            if loader == "fabric":
                launch_id = self._ensure_fabric(mc_version, game_dir, cb, installed_ids)
            else:
                launch_id = mc_version
                if launch_id not in installed_ids:
                    self._require_online("install Minecraft")
                    self.status.emit("Installing Minecraft %s..." % mc_version)
                    network.resilient(
                        mll.install.install_minecraft_version,
                        mc_version, game_dir, callback=cb, retries=5,
                    )

            if self._cancelled:
                return

            self.status.emit("Building launch command...")
            options = self._build_options(game_dir)
            command = mll.command.get_minecraft_command(launch_id, game_dir, options)

            self.status.emit("Launching Minecraft...")
            _spawn(command, game_dir)
            self.finished_ok.emit()

        except _OfflineError as exc:
            self.failed.emit(str(exc))
        except FileNotFoundError:
            self.failed.emit(
                "Java wasn't found. Install Java 17+ (or set a Java path in "
                "Settings) and try again."
            )
        except Exception as exc:  # noqa: BLE001 - last line of defence
            self.failed.emit(_friendly_error(exc))

    # -- helpers -----------------------------------------------------------
    def _ensure_fabric(self, mc_version, game_dir, cb, installed_ids) -> str:
        loader_ver = None
        try:
            loader_ver = network.resilient(mll.fabric.get_latest_loader_version)
        except Exception:
            loader_ver = None

        if loader_ver:
            fabric_id = "fabric-loader-%s-%s" % (loader_ver, mc_version)
            if fabric_id in installed_ids:
                return fabric_id

        # need network to install
        self._require_online("install Fabric")
        self.status.emit("Installing Minecraft %s..." % mc_version)
        network.resilient(
            mll.install.install_minecraft_version,
            mc_version, game_dir, callback=cb, retries=5,
        )
        self.status.emit("Installing Fabric loader...")
        network.resilient(
            mll.fabric.install_fabric,
            mc_version, game_dir, loader_version=loader_ver, callback=cb, retries=5,
        )
        # re-detect the freshly installed fabric id
        for vid in _installed_ids(game_dir):
            if vid.startswith("fabric-loader-") and vid.endswith("-" + mc_version):
                return vid
        raise RuntimeError("Fabric installed but its version id couldn't be found.")

    def _build_options(self, game_dir) -> dict:
        ram = int(self.config.get("ram_mb", 2048))
        jvm = ["-Xmx%dM" % ram, "-Xms%dM" % max(512, ram // 2)]
        if self.account.get("type") == "elyby":
            jar = ensure_authlib_injector(self.config.cache_dir / "authlib-injector")
            if jar:
                jvm.insert(0, "-javaagent:%s=%s" % (jar, ELYBY_AUTH_SERVER))
        opts = {
            "username": self.account.get("name", "Player"),
            "uuid": self.account.get("uuid", offline_uuid("Player")),
            "token": self.account.get("token", "0"),
            "jvmArguments": jvm,
            "launcherName": "SmoothLauncher",
            "launcherVersion": "1.0",
            "gameDirectory": game_dir,
        }
        java_path = self.config.get("java_path")
        if java_path:
            opts["executablePath"] = java_path
        return opts

    def _maybe_refresh_token(self):
        """Silently refresh a Microsoft or Ely.by token so the session stays
        valid. If we're offline or it fails, we keep the existing token —
        singleplayer still launches fine, so a refresh failure never blocks Play.
        """
        if self.account.get("type") == "microsoft":
            rt = self.account.get("refresh_token")
            cid = self.config.get("client_id")
            redirect = self.config.get("redirect_uri")
            if not (rt and cid) or not network.is_online():
                return
            self.status.emit("Refreshing session...")
            updated = ms_refresh(cid, redirect, rt)
            if updated:
                self.account.update(updated)
                try:
                    self.config.add_or_update_account(self.account)
                except Exception:
                    pass
        elif self.account.get("type") == "elyby":
            if not network.is_online():
                return
            self.status.emit("Refreshing session...")
            updated = elyby_refresh(self.account)
            if updated:
                self.account.update(updated)
                try:
                    self.config.add_or_update_account(self.account)
                except Exception:
                    pass

    def _require_online(self, action: str):
        if not network.is_online():
            raise _OfflineError(
                "You're offline, so I can't %s. Connect to the internet and "
                "try again — anything already installed still launches offline."
                % action
            )


class _OfflineError(Exception):
    pass


def _installed_ids(game_dir) -> set:
    try:
        return {v["id"] for v in mll.utils.get_installed_versions(game_dir)}
    except Exception:
        return set()


def _spawn(command, cwd):
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(command, cwd=cwd, creationflags=creationflags)


def _friendly_error(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    low = text.lower()
    if any(w in low for w in ("timeout", "connection", "resolve", "network",
                              "ssl", "temporarily", "max retries")):
        return ("Network hiccup while downloading: %s\nCheck your connection "
                "and hit Play again — downloads resume where they left off."
                % text)
    return "Something went wrong: %s" % text

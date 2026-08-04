"""Persistent configuration + account storage for Smooth Launcher.

Everything is stored as JSON in the user's app-data folder so it survives
restarts. Reads/writes are defensive: a corrupt or missing file never crashes
the launcher, it just falls back to sane defaults.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "SmoothClientLauncher"

# Default redirect used by public desktop Minecraft launchers. Divine can
# override this in Settings if their Azure app registers a different one.
DEFAULT_REDIRECT = "http://127.0.0.1:5285/"


def app_data_dir() -> Path:
    """Return a writable per-user folder for our data, creating it if needed."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = Path(base) / APP_NAME
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        d = Path(os.path.expanduser("~")) / (".%s" % APP_NAME.lower())
        d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULTS = {
    "client_id": "",              # Azure Application (client) ID — user pastes theirs
    "redirect_uri": DEFAULT_REDIRECT,
    "ram_mb": 2048,               # allocated heap
    "game_dir": "",               # empty => use default .minecraft
    "java_path": "",              # empty => auto-detect
    "version": "1.21.11",         # default target (client test version)
    "loader": "fabric",           # "vanilla" | "fabric"
    "keep_launcher_open": True,
    "accounts": [],               # list of account dicts
    "active_account": None,       # uuid of the active account
    "profiles": [],               # list of profile dicts (Lunar-style)
    "active_profile": None,       # name of the active profile
}


class Config:
    def __init__(self) -> None:
        self.dir = app_data_dir()
        self.path = self.dir / "config.json"
        self.data = dict(DEFAULTS)
        self.load()

    # ---- persistence -----------------------------------------------------
    def load(self) -> None:
        try:
            if self.path.exists():
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    # merge so new keys added in updates still get defaults
                    merged = dict(DEFAULTS)
                    merged.update(loaded)
                    self.data = merged
        except (OSError, ValueError, json.JSONDecodeError):
            # corrupt file — keep defaults, don't crash
            self.data = dict(DEFAULTS)

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            tmp.replace(self.path)  # atomic-ish, avoids half-written files
        except OSError:
            pass

    # ---- convenience accessors ------------------------------------------
    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value) -> None:
        self.data[key] = value
        self.save()

    @property
    def cache_dir(self) -> Path:
        c = self.dir / "cache"
        c.mkdir(exist_ok=True)
        return c

    @property
    def instances_dir(self) -> Path:
        """Where modpack instances + per-profile game folders live.
        %APPDATA%/SmoothClientLauncher/instances/<name>/"""
        d = self.dir / "instances"
        d.mkdir(exist_ok=True)
        return d

    @property
    def profiles_dir(self) -> Path:
        """Metadata for Lunar-style profiles (separate from instance data
        itself). %APPDATA%/SmoothClientLauncher/profiles/"""
        d = self.dir / "profiles"
        d.mkdir(exist_ok=True)
        return d

    @property
    def default_game_dir(self) -> Path:
        """Vanilla/default .minecraft-equivalent, kept inside our own
        appdata folder so nothing touches the real .minecraft install."""
        d = self.dir / "instances" / "default"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def effective_game_dir(self) -> str:
        gd = self.get("game_dir")
        if gd:
            return gd
        prof = self.active_profile()
        if prof and prof.get("game_dir"):
            return prof["game_dir"]
        return str(self.default_game_dir)

    # ---- profiles (Lunar-style: name + version + loader + own dir) -------
    def profiles(self) -> list:
        return list(self.data.get("profiles", []))

    def add_or_update_profile(self, profile: dict) -> None:
        """profile needs at least: name, version, loader. game_dir is
        auto-derived under instances/<name>/ if not given."""
        if not profile.get("game_dir"):
            safe = "".join(c for c in profile["name"] if c.isalnum() or c in " -_").strip()
            pd = self.instances_dir / safe
            pd.mkdir(parents=True, exist_ok=True)
            profile["game_dir"] = str(pd)
        profs = self.data.get("profiles", [])
        for i, p in enumerate(profs):
            if p.get("name") == profile.get("name"):
                profs[i] = profile
                break
        else:
            profs.append(profile)
        self.data["profiles"] = profs
        self.data["active_profile"] = profile.get("name")
        self.save()

    def remove_profile(self, name: str) -> None:
        profs = [p for p in self.data.get("profiles", []) if p.get("name") != name]
        self.data["profiles"] = profs
        if self.data.get("active_profile") == name:
            self.data["active_profile"] = profs[0]["name"] if profs else None
        self.save()

    def set_active_profile(self, name: str) -> None:
        self.data["active_profile"] = name
        self.save()

    def active_profile(self) -> dict | None:
        name = self.data.get("active_profile")
        for p in self.data.get("profiles", []):
            if p.get("name") == name:
                return p
        profs = self.data.get("profiles", [])
        return profs[0] if profs else None

    # ---- accounts --------------------------------------------------------
    def accounts(self) -> list:
        return list(self.data.get("accounts", []))

    def add_or_update_account(self, account: dict) -> None:
        accts = self.data.get("accounts", [])
        for i, a in enumerate(accts):
            if a.get("uuid") == account.get("uuid"):
                accts[i] = account
                break
        else:
            accts.append(account)
        self.data["accounts"] = accts
        self.data["active_account"] = account.get("uuid")
        self.save()

    def remove_account(self, uuid: str) -> None:
        accts = [a for a in self.data.get("accounts", []) if a.get("uuid") != uuid]
        self.data["accounts"] = accts
        if self.data.get("active_account") == uuid:
            self.data["active_account"] = accts[0]["uuid"] if accts else None
        self.save()

    def set_active(self, uuid: str) -> None:
        self.data["active_account"] = uuid
        self.save()

    def active(self) -> dict | None:
        uid = self.data.get("active_account")
        for a in self.data.get("accounts", []):
            if a.get("uuid") == uid:
                return a
        accts = self.data.get("accounts", [])
        return accts[0] if accts else None

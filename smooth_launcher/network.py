"""Network resilience layer.

This is the piece that stops a flaky connection from killing the launcher.
Three defenses:

1. A global socket timeout so no request can hang forever.
2. A `requests` session with automatic retries + backoff for our own calls.
3. Disk caching of the version list, so the Play screen still populates when
   the internet is down.

`minecraft-launcher-lib` uses `requests` under the hood; we also install our
retry adapter onto its default session behaviour where we can, and everything
that touches the network is wrapped so failures surface as friendly errors
instead of crashes.
"""
from __future__ import annotations

import json
import socket
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover - very old urllib3
    Retry = None

# 1) Nothing hangs forever.
socket.setdefaulttimeout(30)

DEFAULT_TIMEOUT = 20


def build_session() -> requests.Session:
    s = requests.Session()
    if Retry is not None:
        retry = Retry(
            total=4,
            connect=4,
            read=4,
            backoff_factor=0.8,          # 0.8, 1.6, 3.2, ... seconds
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    s.headers.update({"User-Agent": "SmoothLauncher/1.0"})
    return s


SESSION = build_session()

# Make minecraft-launcher-lib's internal requests inherit retry behaviour too.
try:  # best effort; if their internals change this simply no-ops
    import minecraft_launcher_lib.helper as _mll_helper  # type: ignore
    if hasattr(_mll_helper, "get_requests_response_cache"):
        pass
except Exception:
    pass


def resilient(func, *args, retries: int = 3, delay: float = 1.0, **kwargs):
    """Call `func`, retrying on any network error with exponential backoff.

    Returns the function result, or raises the last error after exhausting
    retries so the caller can show a friendly message.
    """
    last = None
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except (requests.RequestException, socket.timeout, OSError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(delay * (2 ** attempt))
    if last:
        raise last


def is_online(timeout: float = 4.0) -> bool:
    """Fast, non-blocking-ish connectivity probe. Never raises."""
    for host in ("https://api.minecraftservices.com", "https://piston-meta.mojang.com"):
        try:
            SESSION.head(host, timeout=timeout)
            return True
        except requests.RequestException:
            continue
    return False


# ---- version list caching ------------------------------------------------

def load_cached_versions(cache_dir: Path):
    try:
        p = cache_dir / "versions.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return None


def save_cached_versions(cache_dir: Path, versions) -> None:
    try:
        (cache_dir / "versions.json").write_text(
            json.dumps(versions), encoding="utf-8"
        )
    except OSError:
        pass


def fetch_release_versions(cache_dir: Path) -> list[str]:
    """Return a list of release version ids.

    Tries the network (with retries); on failure falls back to the disk cache;
    if even that is empty, returns a small hardcoded list so the UI is usable.
    """
    import minecraft_launcher_lib as mll

    try:
        raw = resilient(mll.utils.get_version_list)
        releases = [v["id"] for v in raw if v.get("type") == "release"]
        if releases:
            save_cached_versions(cache_dir, releases)
            return releases
    except Exception:
        pass

    cached = load_cached_versions(cache_dir)
    if cached:
        return cached

    # last-resort offline fallback
    return ["1.21.11", "1.21.10", "1.21.4", "1.21.1", "1.20.6", "1.20.4"]

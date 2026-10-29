"""MCP Connect service — write/remove Claude Desktop config entry for yt-summarizer."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ENTRY_NAME = "yt-summarizer"
DEFAULT_YT_URL = "http://localhost:9010"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """app/backend/services/ -> app/backend/ -> app/ -> project root"""
    return Path(__file__).parent.parent.parent.parent


def _mcp_server_path() -> Path:
    """app/mcp_server.py"""
    return Path(__file__).parent.parent.parent / "mcp_server.py"


def _find_python() -> str:
    """Return venv Python path if it exists, else sys.executable."""
    root = _project_root()
    if sys.platform == "win32":
        candidates = [
            root / ".venv" / "Scripts" / "python.exe",
            root / "app" / "backend" / ".venv" / "Scripts" / "python.exe",
        ]
    else:
        candidates = [
            root / ".venv" / "bin" / "python",
            root / "app" / "backend" / ".venv" / "bin" / "python",
        ]
    for c in candidates:
        if c.exists():
            return str(c)
    # When the backend runs inside a venv, sys.executable IS the venv Python.
    return sys.executable


def _real_localappdata() -> str:
    """Return the real %LOCALAPPDATA% path, bypassing Store app folder virtualization."""
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        return localappdata
    # Fallback: ask PowerShell for the real path (avoids Store package virtualization)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetFolderPath('LocalApplicationData')"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def desktop_config_dirs() -> list[Path]:
    """Return Claude Desktop config directories that exist on this machine.

    Claude Desktop 4.29+ (Store build) writes to:
      %LOCALAPPDATA%\\Claude-Data\\claude_<package_id>\\claude_desktop_config.json

    Older builds used:
      %APPDATA%\\Claude\\claude_desktop_config.json
      %LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming\\Claude\\

    When the new location exists, we prefer it and skip the old ones (writing to
    old paths is harmless but misleading — Desktop no longer reads them).
    """
    if sys.platform != "win32":
        if sys.platform == "darwin":
            d = Path.home() / "Library" / "Application Support" / "Claude"
        else:
            xdg = os.environ.get("XDG_CONFIG_HOME", "")
            d = Path(xdg) / "Claude" if xdg else Path.home() / ".config" / "Claude"
        return [d] if d.exists() else []

    localappdata = _real_localappdata()
    appdata = os.environ.get("APPDATA", "")

    # --- New location: Claude Desktop 4.29+ ---
    new_dirs: list[Path] = []
    if localappdata:
        claude_data = Path(localappdata) / "Claude-Data"
        if claude_data.is_dir():
            for pkg in claude_data.iterdir():
                # Matches "claude_pzs8sxrjxfjjc" and similar
                if pkg.is_dir() and pkg.name.startswith("claude_"):
                    new_dirs.append(pkg)

    if new_dirs:
        # New location found — use only it; old paths are no longer read by Desktop
        return new_dirs

    # --- Legacy locations (pre-4.29) ---
    legacy: list[Path] = []
    if appdata:
        legacy.append(Path(appdata) / "Claude")
    if localappdata:
        packages = Path(localappdata) / "Packages"
        if packages.is_dir():
            for pkg in packages.iterdir():
                if pkg.name.startswith("Claude_") or pkg.name.startswith("AnthropicClaude"):
                    candidate = pkg / "LocalCache" / "Roaming" / "Claude"
                    if candidate.is_dir():
                        legacy.append(candidate)
    return [d for d in legacy if d.exists()]


def is_docker() -> bool:
    return os.path.exists("/.dockerenv") or os.environ.get("DOCKER", "").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Desktop running detection
# ---------------------------------------------------------------------------

def desktop_running() -> bool | None:
    """
    Return True if Claude Desktop is running, False if not, None if unknown.
    Must not confuse Claude Code CLI (claude.exe) with Claude Desktop.
    """
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Process -Name claude -ErrorAction SilentlyContinue | "
                 "Select-Object -ExpandProperty Path"],
                capture_output=True, text=True, timeout=20,
            )
            paths = result.stdout.strip().splitlines()
            if not paths:
                return False
            for p in paths:
                # A path we can't read = assume Desktop
                if not p.strip():
                    return True
                p_lower = p.lower()
                if "\\windowsapps\\claude_" in p_lower or "\\anthropicclaude\\" in p_lower:
                    return True
            return False
        elif sys.platform == "darwin":
            result = subprocess.run(
                ["pgrep", "-x", "Claude"],
                capture_output=True, timeout=20,
            )
            return result.returncode == 0
        else:
            result = subprocess.run(
                ["pgrep", "-x", "claude-desktop"],
                capture_output=True, timeout=20,
            )
            return result.returncode == 0
    except Exception:
        return None  # unknown — fail closed


# ---------------------------------------------------------------------------
# Config read/write
# ---------------------------------------------------------------------------

def _config_file(d: Path) -> Path:
    return d / "claude_desktop_config.json"


def _read_config(path: Path) -> tuple[dict, bool]:
    """Return (data, is_broken). Broken = invalid JSON or not a dict or mcpServers not a dict."""
    if not path.exists():
        return {}, False
    try:
        text = path.read_text(encoding="utf-8-sig") or "{}"
        data = json.loads(text)
        if not isinstance(data, dict):
            return {}, True
        if "mcpServers" in data and not isinstance(data["mcpServers"], dict):
            return {}, True
        return data, False
    except (json.JSONDecodeError, OSError):
        return {}, True


def _write_config(path: Path, data: dict) -> None:
    """Atomic write: .tmp then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _backup_config(path: Path) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = path.with_suffix(f".json.bak-{ts}")
    try:
        bak.write_bytes(path.read_bytes())
        return str(bak)
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Entry builder
# ---------------------------------------------------------------------------

def _build_entry() -> dict:
    return {
        "command": _find_python(),
        "args": [str(_mcp_server_path())],
        "env": {"YT_SUMMARIZER_URL": DEFAULT_YT_URL},
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_status() -> dict:
    """Check config files and return current status."""
    if is_docker():
        return {
            "status": "docker_mode",
            "config_paths": [],
            "entry_exists": False,
            "manual_config": _manual_config_snippet(),
        }

    dirs = desktop_config_dirs()
    if not dirs:
        return {"status": "file_not_found", "config_paths": [], "entry_exists": False}

    connected_paths: list[str] = []
    all_paths: list[str] = []
    for d in dirs:
        cfg = _config_file(d)
        all_paths.append(str(cfg))
        data, broken = _read_config(cfg)
        if not broken and data.get("mcpServers", {}).get(ENTRY_NAME):
            connected_paths.append(str(cfg))

    if connected_paths:
        return {
            "status": "connected",
            "config_paths": connected_paths,
            "entry_exists": True,
            "entry": data.get("mcpServers", {}).get(ENTRY_NAME),  # type: ignore[possibly-undefined]
        }
    return {
        "status": "not_connected",
        "config_paths": all_paths,
        "entry_exists": False,
    }


def connect(confirm: bool = False, replace_broken: bool = False) -> dict:
    """
    Plan or execute the connection.
    If confirm=False: return what WOULD be done (plan).
    If confirm=True: write to all config dirs and return result.
    """
    if is_docker():
        return {
            "ok": False,
            "error": "docker_mode",
            "manual_config": _manual_config_snippet(),
        }

    dirs = desktop_config_dirs()
    if not dirs:
        return {
            "ok": False,
            "error": "no_config_dir",
            "message": "Claude Desktop config directory not found. Install Claude Desktop and start it once.",
        }

    running = desktop_running()
    if running is True:
        return {
            "ok": False,
            "error": "desktop_running",
            "message": "Close Claude Desktop completely (including the tray), then try again.",
        }
    if running is None:
        return {
            "ok": False,
            "error": "desktop_status_unknown",
            "message": "Could not determine if Claude Desktop is running. Close it first, then try again.",
        }

    entry = _build_entry()
    actions: list[dict] = []

    for d in dirs:
        cfg = _config_file(d)
        data, broken = _read_config(cfg)

        if broken and not replace_broken:
            return {
                "ok": False,
                "error": "broken_config",
                "path": str(cfg),
                "message": "Config file has invalid JSON. Pass replace_broken=true to overwrite it (a backup will be made).",
            }

        existing = data.get("mcpServers", {}).get(ENTRY_NAME) if not broken else None
        if existing == entry:
            actions.append({"path": str(cfg), "action": "unchanged"})
        elif broken:
            actions.append({"path": str(cfg), "action": "replace_broken"})
        elif existing:
            actions.append({"path": str(cfg), "action": "update"})
        else:
            actions.append({"path": str(cfg), "action": "add"})

    if not confirm:
        return {"planned": True, "actions": actions, "entry": entry}

    # --- Execute ---
    results: list[dict] = []
    for act in actions:
        path = Path(act["path"])
        data, broken = _read_config(path)
        backup_path = ""

        if act["action"] in ("replace_broken", "update", "add"):
            if path.exists():
                backup_path = _backup_config(path)
            if broken or not isinstance(data, dict):
                data = {}
            data.setdefault("mcpServers", {})[ENTRY_NAME] = entry
            try:
                _write_config(path, data)
                # Read back from disk to verify
                written, _ = _read_config(path)
                wrote_ok = written.get("mcpServers", {}).get(ENTRY_NAME) == entry
                results.append({
                    "path": str(path),
                    "action": act["action"],
                    "backup": backup_path,
                    "verified": wrote_ok,
                })
            except OSError as e:
                results.append({"path": str(path), "action": act["action"], "error": str(e)})
        else:  # unchanged
            results.append({"path": str(path), "action": "unchanged"})

    all_ok = all("error" not in r for r in results)
    return {
        "ok": all_ok,
        "results": results,
        "entry": entry,
        "message": "Connected. Restart Claude Desktop to load the new server." if all_ok else "Some writes failed.",
    }


def disconnect() -> dict:
    """Remove the yt-summarizer entry from all config files."""
    if is_docker():
        return {"ok": False, "error": "docker_mode"}

    dirs = desktop_config_dirs()
    if not dirs:
        return {"ok": False, "error": "no_config_dir"}

    results: list[dict] = []
    for d in dirs:
        cfg = _config_file(d)
        data, broken = _read_config(cfg)
        if broken or ENTRY_NAME not in data.get("mcpServers", {}):
            results.append({"path": str(cfg), "action": "skipped"})
            continue
        backup = _backup_config(cfg)
        del data["mcpServers"][ENTRY_NAME]
        try:
            _write_config(cfg, data)
            results.append({"path": str(cfg), "action": "removed", "backup": backup})
        except OSError as e:
            results.append({"path": str(cfg), "action": "error", "error": str(e)})

    return {
        "ok": all(r["action"] in ("removed", "skipped") for r in results),
        "results": results,
        "message": "Disconnected. Restart Claude Desktop to apply changes.",
    }


def _manual_config_snippet() -> str:
    entry = _build_entry()
    return json.dumps({"mcpServers": {ENTRY_NAME: entry}}, indent=2)

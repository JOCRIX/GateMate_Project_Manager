"""Pinned toolchain auto-download / extract for GateMate Project Manager.

One-time machine setup: downloads fixed versions, extracts them, runs OSS CAD
``environment.ps1`` side-effects, and persists User environment variables / PATH
so tools work for all future projects (and external terminals after logon).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen


ProgressCallback = Callable[[str, int, int, str], None]


@dataclass(frozen=True)
class PinnedComponent:
    """One pinned archive to download and unpack."""

    key: str
    title: str
    version: str
    url: str
    archive_name: str
    sha256: Optional[str] = None
    extract_subdir: str = ""


# Exact pinned toolchain set for Auto-Setup (do not use \"latest\" links).
PINNED_COMPONENTS: Tuple[PinnedComponent, ...] = (
    PinnedComponent(
        key="oss_cad_suite",
        title="OSS CAD Suite",
        version="2026-08-10",
        url=(
            "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/"
            "2026-08-10/oss-cad-suite-windows-x64-20260810.tgz"
        ),
        archive_name="oss-cad-suite-windows-x64-20260810.tgz",
        sha256="818a5bc96c0e0719e2e21da0d2cf6fbbeed959689657202b5b942cf26af4e502",
        extract_subdir="oss-cad-suite",
    ),
    PinnedComponent(
        key="ghdl",
        title="GHDL",
        version="v5.0.1 Windows (mcode, mingw64 standalone)",
        url="https://github.com/ghdl/ghdl/releases/download/v5.0.1/ghdl-mcode-5.0.1-mingw64.zip",
        archive_name="ghdl-mcode-5.0.1-mingw64.zip",
        sha256=None,
        extract_subdir="ghdl",
    ),
    PinnedComponent(
        key="gtkwave",
        title="GTKWave",
        version="3.3.100 (win64 portable)",
        # No official MSI/silent installer — SourceForge ships a zip. We install
        # portably (extract + User PATH), which is the silent equivalent.
        url=(
            "https://downloads.sourceforge.net/project/gtkwave/"
            "gtkwave-3.3.100-bin-win64/gtkwave-3.3.100-bin-win64.zip"
        ),
        archive_name="gtkwave-3.3.100-bin-win64.zip",
        sha256=None,
        extract_subdir="gtkwave",
    ),
)


logger = logging.getLogger("ToolchainAutoSetup")


def get_global_settings_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".cc_project_manager", "settings.json")


def load_global_settings() -> dict:
    path = get_global_settings_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.debug("Could not load global settings: %s", e)
    return {}


def save_global_settings(settings: dict) -> None:
    path = get_global_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    settings = dict(settings or {})
    settings["last_updated"] = time.time()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def get_global_toolchain_defaults() -> Dict[str, str]:
    """Return machine-wide tool paths saved by Auto-Setup (may be empty)."""
    block = load_global_settings().get("toolchain_autosetup") or {}
    paths = block.get("tool_paths") or {}
    return {k: v for k, v in paths.items() if v}


def _http_get(url: str, timeout: int = 120):
    req = Request(
        url,
        headers={
            "User-Agent": "GateMate-Project-Manager-AutoSetup/0.4",
            "Accept": "*/*",
        },
    )
    return urlopen(req, timeout=timeout)


def download_file(
    url: str,
    dest_path: str,
    *,
    expected_sha256: Optional[str] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    chunk_size: int = 256 * 1024,
) -> str:
    """Download ``url`` to ``dest_path`` with optional SHA-256 verification."""
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    hasher = hashlib.sha256()
    downloaded = 0

    with _http_get(url) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        with open(dest_path, "wb") as out:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total)

    digest = hasher.hexdigest().lower()
    if expected_sha256:
        expected = expected_sha256.lower().strip()
        if digest != expected:
            try:
                os.remove(dest_path)
            except OSError:
                pass
            raise ValueError(
                f"SHA-256 mismatch for {os.path.basename(dest_path)}: "
                f"got {digest}, expected {expected}"
            )
    return digest


def extract_archive(archive_path: str, dest_dir: str) -> None:
    """Extract a ``.zip`` / ``.tgz`` / ``.tar.gz`` archive into ``dest_dir``."""
    os.makedirs(dest_dir, exist_ok=True)
    lower = archive_path.lower()
    if lower.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_dir)
        return
    if lower.endswith((".tgz", ".tar.gz", ".tar")):
        with tarfile.open(archive_path, "r:*") as tf:
            tf.extractall(dest_dir)
        return
    raise ValueError(f"Unsupported archive type: {archive_path}")


def find_executable(root: str, names: List[str]) -> Optional[str]:
    """Return the first matching executable under ``root`` (recursive)."""
    wanted = {n.lower() for n in names}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower() in wanted:
                return os.path.join(dirpath, name)
    return None


def find_oss_cad_suite_root(install_root: str) -> Optional[str]:
    """Locate extracted OSS CAD Suite root (folder containing environment.ps1)."""
    candidates = [
        os.path.join(install_root, "oss-cad-suite"),
        install_root,
    ]
    for root in candidates:
        if os.path.isfile(os.path.join(root, "environment.ps1")):
            return os.path.abspath(root)
        nested = os.path.join(root, "oss-cad-suite")
        if os.path.isfile(os.path.join(nested, "environment.ps1")):
            return os.path.abspath(nested)
    try:
        for name in os.listdir(install_root):
            path = os.path.join(install_root, name)
            if os.path.isfile(os.path.join(path, "environment.ps1")):
                return os.path.abspath(path)
    except OSError:
        pass
    return None


def resolve_tool_paths(install_root: str) -> Dict[str, str]:
    """Locate installed tool binaries under the auto-setup root."""
    paths: Dict[str, str] = {}
    install_root = os.path.abspath(install_root)

    oss = find_oss_cad_suite_root(install_root)
    if oss:
        yosys = find_executable(oss, ["yosys.exe", "yosys"])
        nextpnr = find_executable(oss, ["nextpnr-himbaechel.exe", "nextpnr-himbaechel"])
        gmpack = find_executable(oss, ["gmpack.exe", "gmpack"])
        if yosys:
            paths["yosys"] = yosys
        if nextpnr:
            paths["nextpnr_himbaechel"] = nextpnr
        if gmpack:
            paths["gmpack"] = gmpack

    for root in (os.path.join(install_root, "ghdl"), install_root):
        ghdl = find_executable(root, ["ghdl.exe", "ghdl"])
        if ghdl:
            paths["ghdl"] = ghdl
            break

    for root in (os.path.join(install_root, "gtkwave"), install_root):
        gtk = find_executable(root, ["gtkwave.exe", "gtkwave"])
        if gtk:
            paths["gtkwave"] = gtk
            break

    return paths


# --- Windows persistent environment (User hive) ---------------------------------

def _broadcast_env_change() -> None:
    try:
        import ctypes
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            5000,
            None,
        )
    except Exception as e:
        logger.debug("Could not broadcast environment change: %s", e)


def set_user_env_var(name: str, value: str) -> None:
    """Persist a User environment variable (HKCU\\Environment)."""
    if os.name != "nt":
        os.environ[name] = value
        return
    import winreg

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ | winreg.KEY_SET_VALUE
    )
    try:
        winreg.SetValueEx(key, name, 0, winreg.REG_EXPAND_SZ, value)
    finally:
        winreg.CloseKey(key)
    os.environ[name] = value
    _broadcast_env_change()


def prepend_user_path(directories: List[str]) -> List[str]:
    """Prepend directories to the User PATH. Returns directories that were newly added."""
    cleaned = []
    for d in directories:
        if not d:
            continue
        nd = os.path.normpath(os.path.abspath(d))
        if os.path.isdir(nd) and nd not in cleaned:
            cleaned.append(nd)

    if os.name != "nt":
        path = os.environ.get("PATH", "")
        parts = [p for p in path.split(os.pathsep) if p]
        added = []
        for d in reversed(cleaned):
            if d not in parts:
                parts.insert(0, d)
                added.append(d)
        os.environ["PATH"] = os.pathsep.join(parts)
        return added

    import winreg

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ | winreg.KEY_SET_VALUE
    )
    try:
        try:
            current, _regtype = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current = ""
        parts = [p for p in str(current).split(";") if p]
        lower_map = {p.lower(): p for p in parts}
        added = []
        for d in reversed(cleaned):
            if d.lower() not in lower_map:
                parts.insert(0, d)
                lower_map[d.lower()] = d
                added.append(d)
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, ";".join(parts))
    finally:
        winreg.CloseKey(key)

    path_parts = [p for p in os.environ.get("PATH", "").split(";") if p]
    for d in reversed(cleaned):
        if d not in path_parts:
            path_parts.insert(0, d)
    os.environ["PATH"] = ";".join(path_parts)
    _broadcast_env_change()
    return added


def run_oss_cad_environment_ps1(oss_root: str) -> None:
    """Run OSS CAD Suite ``environment.ps1`` (updates pixbuf cache, etc.)."""
    ps1 = os.path.join(oss_root, "environment.ps1")
    if not os.path.isfile(ps1):
        raise FileNotFoundError(f"environment.ps1 not found under {oss_root}")

    root = oss_root if oss_root.endswith(("\\", "/")) else oss_root + os.sep

    def _ps_single_quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        f"$env:YOSYSHQ_ROOT = {_ps_single_quote(root)}; . {_ps_single_quote(ps1)}",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=oss_root,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"environment.ps1 failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout or '').strip()}"
        )


def persist_oss_cad_user_environment(oss_root: str) -> None:
    """Write durable User env vars equivalent to ``environment.ps1`` / ``environment.bat``."""
    root = os.path.abspath(oss_root)
    root_slash = root if root.endswith(("\\", "/")) else root + "\\"
    bin_dir = os.path.join(root, "bin")
    lib_dir = os.path.join(root, "lib")

    set_user_env_var("YOSYSHQ_ROOT", root_slash)
    set_user_env_var("SSL_CERT_FILE", os.path.join(root, "etc", "cacert.pem"))
    set_user_env_var("PYTHON_EXECUTABLE", os.path.join(root, "lib", "python3.exe"))
    set_user_env_var("QT_PLUGIN_PATH", os.path.join(root, "lib", "qt6", "plugins"))
    set_user_env_var("QT_LOGGING_RULES", "*=false")
    set_user_env_var("GTK_EXE_PREFIX", root)
    set_user_env_var("GTK_DATA_PREFIX", root)
    set_user_env_var(
        "GDK_PIXBUF_MODULEDIR",
        os.path.join(root, "lib", "gdk-pixbuf-2.0", "2.10.0", "loaders"),
    )
    set_user_env_var(
        "GDK_PIXBUF_MODULE_FILE",
        os.path.join(root, "lib", "gdk-pixbuf-2.0", "2.10.0", "loaders.cache"),
    )
    set_user_env_var(
        "OPENFPGALOADER_SOJ_DIR",
        os.path.join(root, "share", "openFPGALoader"),
    )
    prepend_user_path([bin_dir, lib_dir])


def finalize_machine_setup(install_root: str, resolved: Dict[str, str]) -> List[str]:
    """One-time machine configuration after archives are extracted.

    - OSS CAD: run ``environment.ps1``, persist User env + PATH
    - GHDL: add ``bin`` to User PATH
    - GTKWave: portable silent install = extract already done; add exe dir to PATH
    - Save global defaults for all future GateMate projects
    - Also apply DIRECT paths to the currently open project (if any)
    """
    notes: List[str] = []
    install_root = os.path.abspath(install_root)

    if " " in install_root:
        notes.append(
            "WARNING: install path contains spaces; OSS CAD Suite recommends a path without spaces."
        )

    oss = find_oss_cad_suite_root(install_root)
    if oss:
        try:
            notes.append(f"OSS CAD: running environment.ps1 in {oss}")
            run_oss_cad_environment_ps1(oss)
            notes.append("OSS CAD: environment.ps1 completed")
        except Exception as e:
            notes.append(f"OSS CAD: environment.ps1 warning: {e}")
        try:
            persist_oss_cad_user_environment(oss)
            notes.append("OSS CAD: persisted YOSYSHQ_ROOT + User PATH (bin/lib)")
        except Exception as e:
            notes.append(f"OSS CAD: failed to persist User environment: {e}")
    else:
        notes.append("OSS CAD: suite root not found — skipped environment.ps1")

    ghdl = resolved.get("ghdl")
    if ghdl:
        try:
            added = prepend_user_path([os.path.dirname(ghdl)])
            notes.append(
                f"GHDL: User PATH += {os.path.dirname(ghdl)}"
                + ("" if added else " (already present)")
            )
        except Exception as e:
            notes.append(f"GHDL: PATH update failed: {e}")

    gtk = resolved.get("gtkwave")
    if gtk:
        try:
            # Portable silent install: zip has no MSI; PATH makes it available system-wide
            added = prepend_user_path([os.path.dirname(gtk)])
            notes.append(
                f"GTKWave: portable install; User PATH += {os.path.dirname(gtk)}"
                + ("" if added else " (already present)")
            )
        except Exception as e:
            notes.append(f"GTKWave: PATH update failed: {e}")

    try:
        settings = load_global_settings()
        settings["toolchain_autosetup"] = {
            "install_root": install_root,
            "yosyshq_root": oss or "",
            "tool_paths": resolved,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "pinned": {
                c.key: {"version": c.version, "url": c.url, "sha256": c.sha256}
                for c in PINNED_COMPONENTS
            },
        }
        save_global_settings(settings)
        notes.append(f"Saved machine defaults to {get_global_settings_path()}")
    except Exception as e:
        notes.append(f"Could not save global settings: {e}")

    # Prefer PATH in the open project (tools are now on User PATH); keep DIRECT as backup.
    try:
        from .toolchain_manager import ToolChainManager
        from .simulation_manager import SimulationManager

        tcm = ToolChainManager()
        for tool in ("ghdl", "yosys", "nextpnr_himbaechel", "gmpack"):
            path = resolved.get(tool)
            if path and tcm.add_tool_path(tool, path):
                tcm.set_tool_preference(tool, "PATH")
                notes.append(f"Current project: {tool} PATH (+ DIRECT backup {path})")
        if gtk:
            sim = SimulationManager()
            if sim.add_gtkwave_path(gtk):
                try:
                    sim.set_gtkwave_preference("PATH")
                except Exception:
                    pass
                notes.append(f"Current project: gtkwave PATH (+ DIRECT backup {gtk})")
    except Exception as e:
        notes.append(f"Current project path update skipped: {e}")

    notes.append(
        "Note: new terminals / apps pick up PATH after a logoff/logon or Explorer restart."
    )
    return notes


def apply_paths_to_project(resolved: Dict[str, str], install_root: str = "") -> List[str]:
    """Finalize machine-wide setup (name kept for dialog compatibility)."""
    root = install_root or (load_global_settings().get("toolchain_autosetup") or {}).get(
        "install_root", ""
    )
    if not root:
        for p in resolved.values():
            if p:
                root = os.path.dirname(os.path.dirname(p))
                break
    return finalize_machine_setup(root or os.getcwd(), resolved)


def _install_one(
    component: PinnedComponent,
    install_root: str,
    downloads_dir: str,
    progress: Optional[ProgressCallback],
) -> None:
    def emit(cur: int, total: int, status: str) -> None:
        if progress:
            progress(component.key, cur, total, status)

    archive_path = os.path.join(downloads_dir, component.archive_name)
    emit(0, 0, f"Downloading {component.archive_name}…")

    def on_dl(done: int, total: int) -> None:
        emit(done, total, f"Downloading… {done // (1024 * 1024)} MB")

    download_file(
        component.url,
        archive_path,
        expected_sha256=component.sha256,
        progress=on_dl,
    )
    emit(1, 1, "Download complete — extracting…")

    extract_dir = (
        os.path.join(install_root, component.extract_subdir)
        if component.extract_subdir
        else install_root
    )
    if component.extract_subdir and os.path.isdir(extract_dir):
        shutil.rmtree(extract_dir, ignore_errors=True)
    os.makedirs(extract_dir, exist_ok=True)

    if component.key == "oss_cad_suite":
        extract_archive(archive_path, install_root)
    else:
        extract_archive(archive_path, extract_dir)

    emit(1, 1, "Extracted")


def run_autosetup(
    install_root: str,
    *,
    progress: Optional[ProgressCallback] = None,
    max_workers: int = 3,
) -> Dict[str, str]:
    """Download + extract all pinned components in parallel under ``install_root``."""
    install_root = os.path.abspath(install_root)
    if " " in install_root:
        logger.warning(
            "Install path contains spaces (%s); OSS CAD Suite recommends avoiding spaces.",
            install_root,
        )
    os.makedirs(install_root, exist_ok=True)
    downloads_dir = os.path.join(install_root, "downloads")
    os.makedirs(downloads_dir, exist_ok=True)

    errors: Dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _install_one, comp, install_root, downloads_dir, progress
            ): comp
            for comp in PINNED_COMPONENTS
        }
        for fut in as_completed(futures):
            comp = futures[fut]
            try:
                fut.result()
                if progress:
                    progress(comp.key, 1, 1, "OK")
            except Exception as e:
                logger.exception("Auto-setup failed for %s", comp.key)
                errors[comp.key] = str(e)
                if progress:
                    progress(comp.key, 0, 1, f"FAILED: {e}")

    if errors:
        detail = "; ".join(f"{k}: {v}" for k, v in errors.items())
        raise RuntimeError(f"Auto-setup incomplete — {detail}")

    return resolve_tool_paths(install_root)


# --- Optional VS Code + TerosHDL ------------------------------------------------

# Stable Windows user installer (no admin). Redirect always serves current stable.
VSCODE_USER_SETUP_URL = "https://update.code.visualstudio.com/latest/win32-x64-user/stable"
VSCODE_INSTALLER_NAME = "VSCodeUserSetup-x64.exe"
TEROSHDL_EXTENSION_ID = "teros-technology.teroshdl"


def _default_user_code_cmd() -> str:
    """Default User-setup CLI path (works even when PATH is stale after install)."""
    local = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(local, "Programs", "Microsoft VS Code", "bin", "code.cmd")


def _candidate_code_clis() -> List[str]:
    """Known absolute ``code`` locations — never rely on a bare ``code`` command.

    After a silent install the User PATH is updated in the registry, but the
    *current* process still has the old PATH. Prefer on-disk install paths first.
    """
    candidates: List[str] = []

    local = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    for base in (
        os.path.join(local, "Programs", "Microsoft VS Code"),
        os.path.join(program_files, "Microsoft VS Code"),
        os.path.join(program_files_x86, "Microsoft VS Code"),
    ):
        for rel in (
            ("bin", "code.cmd"),
            ("bin", "code.exe"),
            ("code.cmd",),
            ("code.exe",),
        ):
            path = os.path.join(base, *rel)
            if os.path.isfile(path):
                candidates.append(path)

    # PATH last — may be stale in this process after a fresh install
    which = shutil.which("code") or shutil.which("code.cmd")
    if which:
        candidates.append(which)

    seen = set()
    out = []
    for c in candidates:
        key = os.path.normcase(os.path.abspath(c))
        if key not in seen:
            seen.add(key)
            out.append(os.path.abspath(c))
    return out


def find_code_cli() -> Optional[str]:
    """Return an absolute working ``code.cmd`` / ``code.exe`` path, or None."""
    for cli in _candidate_code_clis():
        try:
            result = subprocess.run(
                [cli, "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
            if result.returncode == 0:
                return cli
        except Exception:
            continue
    return None


def is_vscode_installed() -> bool:
    return find_code_cli() is not None


def is_teroshdl_installed(code_cli: Optional[str] = None) -> bool:
    cli = code_cli or find_code_cli()
    if not cli:
        return False
    try:
        result = subprocess.run(
            [cli, "--list-extensions"],
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
        )
        if result.returncode != 0:
            return False
        installed = {line.strip().lower() for line in (result.stdout or "").splitlines()}
        return TEROSHDL_EXTENSION_ID.lower() in installed
    except Exception:
        return False


def download_and_install_vscode(
    downloads_dir: str,
    *,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> str:
    """Download the stable VS Code user installer and run it silently.

    Returns an absolute path to ``code.cmd`` (does not use bare ``code`` / PATH).
    """
    os.makedirs(downloads_dir, exist_ok=True)
    installer = os.path.join(downloads_dir, VSCODE_INSTALLER_NAME)

    def emit(cur: int, total: int, status: str) -> None:
        if progress:
            progress(cur, total, status)

    emit(0, 0, "Downloading VS Code user installer…")

    def on_dl(done: int, total: int) -> None:
        emit(done, total, f"Downloading VS Code… {done // (1024 * 1024)} MB")

    download_file(VSCODE_USER_SETUP_URL, installer, progress=on_dl)
    emit(1, 1, "Installing VS Code silently…")

    # User setup: no admin. Keep PATH registration; do not auto-launch Code.
    args = [
        installer,
        "/VERYSILENT",
        "/NORESTART",
        "/SUPPRESSMSGBOXES",
        "/MERGETASKS=!runcode,addtopath",
    ]
    result = subprocess.run(args, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"VS Code installer failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout or '').strip()}"
        )

    # Do NOT call bare "code" here — PATH is not refreshed in this process.
    # Probe the default user install location first, then other known paths.
    default_cmd = _default_user_code_cmd()
    for _ in range(30):
        if os.path.isfile(default_cmd):
            try:
                probe = subprocess.run(
                    [default_cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    shell=False,
                )
                if probe.returncode == 0:
                    emit(1, 1, f"VS Code installed ({default_cmd})")
                    return os.path.abspath(default_cmd)
            except Exception:
                pass
        cli = find_code_cli()
        if cli:
            emit(1, 1, f"VS Code installed ({cli})")
            return cli
        time.sleep(0.5)

    raise RuntimeError(
        "VS Code installer finished but code.cmd was not found under "
        rf"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\. "
        "Open a new terminal or reinstall VS Code."
    )


def install_teroshdl_extension(code_cli: Optional[str] = None) -> None:
    """Install TerosHDL using an absolute ``code`` CLI path (never bare ``code``)."""
    cli = code_cli or find_code_cli()
    if not cli:
        raise RuntimeError(
            "Cannot install TerosHDL: VS Code CLI not found "
            r"(expected %LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd)"
        )
    if not os.path.isabs(cli):
        raise RuntimeError(f"Refusing non-absolute VS Code CLI path: {cli!r}")

    result = subprocess.run(
        [cli, "--install-extension", TEROSHDL_EXTENSION_ID, "--force"],
        capture_output=True,
        text=True,
        timeout=300,
        shell=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"TerosHDL install failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout or '').strip()}"
        )


def setup_vscode_and_teroshdl(
    install_root: str,
    *,
    progress: Optional[ProgressCallback] = None,
) -> List[str]:
    """Ensure VS Code is present, then install the TerosHDL extension.

    Soft-failures are returned as notes (does not raise) so toolchain setup
    can still succeed when this optional step has problems.
    """
    notes: List[str] = []
    key = "vscode"

    def emit(cur: int, total: int, status: str) -> None:
        if progress:
            progress(key, cur, total, status)

    try:
        downloads_dir = os.path.join(os.path.abspath(install_root), "downloads")
        cli = find_code_cli()
        if cli:
            notes.append(f"VS Code: already installed ({cli})")
            emit(1, 1, "VS Code already installed")
        else:
            notes.append("VS Code: not found — downloading user installer")
            emit(0, 0, "Downloading VS Code…")

            def on_vs(cur: int, total: int, status: str) -> None:
                emit(cur, total, status)

            cli = download_and_install_vscode(downloads_dir, progress=on_vs)
            notes.append(f"VS Code: installed ({cli})")

        emit(1, 1, "Installing TerosHDL extension…")
        if is_teroshdl_installed(cli):
            notes.append(f"TerosHDL: already installed ({TEROSHDL_EXTENSION_ID})")
            emit(1, 1, "TerosHDL already installed")
        else:
            install_teroshdl_extension(cli)
            notes.append(f"TerosHDL: installed ({TEROSHDL_EXTENSION_ID})")
            emit(1, 1, "TerosHDL installed")

        # Remember in global settings
        try:
            settings = load_global_settings()
            block = settings.setdefault("toolchain_autosetup", {})
            block["vscode"] = {
                "code_cli": cli,
                "teroshdl": TEROSHDL_EXTENSION_ID,
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            save_global_settings(settings)
        except Exception as e:
            notes.append(f"Could not save VS Code status to global settings: {e}")

        if progress:
            progress(key, 1, 1, "OK")
    except Exception as e:
        logger.exception("VS Code / TerosHDL setup failed")
        notes.append(f"VS Code / TerosHDL setup FAILED: {e}")
        if progress:
            progress(key, 0, 1, f"FAILED: {e}")

    return notes

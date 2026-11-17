"""Find the game's installation and the player's data folder (D-047).

``chancellor setup`` writes what this finds into the user's config, so nobody has to
type paths. Where EU4 can be:

* in a **Steam** library: the registry names Steam's folder, whose
  ``steamapps/libraryfolders.vdf`` lists every library;
* wherever an **installer** put it (GOG and others): Windows' list of installed
  programs records an ``InstallLocation``;
* in a **usual folder** on any drive (``Games``, ``SteamLibrary``, ``GOG Games``).

A folder counts when it has the game's executable and ``common``; its version comes from
``launcher-settings.json``. With several (old installs linger), the newest version wins.

The player's data (saves, settings, mods) is in *Documents*/Paradox Interactive/Europa
Universalis IV, and *Documents* is often redirected (OneDrive), so on Windows it is
asked of the system rather than assumed.
"""

from __future__ import annotations

import json
import os
import re
import string
import sys
from dataclasses import dataclass
from pathlib import Path

GAME_FOLDER = "Europa Universalis IV"
STEAM_APP_ID = "236850"
EXECUTABLES = ("eu4.exe", "eu4", "eu4.app")
_VERSION = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?")
_VDF_PATH = re.compile(r'"path"\s+"([^"]+)"')


@dataclass(frozen=True)
class GameInstall:
    """One installation of the game.

    Attributes:
        path: The folder.
        version: The version from ``launcher-settings.json`` (``v1.37.0.0``), if any.
        found_by: How it was found (``steam``, ``installed programs``, ``usual folder``).
    """

    path: Path
    version: str | None
    found_by: str

    @property
    def version_key(self) -> tuple[int, ...]:
        """The version as numbers, for comparing (unknown sorts first)."""
        match = _VERSION.search(self.version or "")
        return tuple(int(g) for g in match.groups() if g is not None) if match else (0,)


def find_game_installs() -> list[GameInstall]:
    """Every installation found, newest version first."""
    seen: dict[str, GameInstall] = {}
    sources = [
        ("steam", _steam_candidates()),
        ("installed programs", _registry_candidates()),
        ("usual folder", _usual_candidates()),
    ]
    for found_by, candidates in sources:
        for folder in candidates:
            if not is_game_dir(folder):
                continue
            key = os.path.normcase(str(folder.resolve()))
            if key not in seen:
                seen[key] = GameInstall(folder, game_version(folder), found_by)
    return sorted(seen.values(), key=lambda g: g.version_key, reverse=True)


def is_game_dir(folder: Path) -> bool:
    """Whether a folder holds the game: its executable and ``common``."""
    try:
        return (folder / "common").is_dir() and any(
            (folder / name).exists() for name in EXECUTABLES
        )
    except OSError:
        return False


def game_version(folder: Path) -> str | None:
    """The version in ``launcher-settings.json`` (``rawVersion``), if readable."""
    try:
        data = json.loads((folder / "launcher-settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("rawVersion") or data.get("version") if isinstance(data, dict) else None
    return str(value) if value else None


def find_user_dir() -> Path | None:
    """The player's EU4 data folder, if it exists (it holds ``save games``)."""
    for documents in _documents_candidates():
        folder = documents / "Paradox Interactive" / GAME_FOLDER
        if folder.is_dir():
            return folder
    return None


def steam_library_folders(vdf_text: str) -> list[Path]:
    """The library folders listed in Steam's ``libraryfolders.vdf``."""
    return [Path(m.replace("\\\\", "\\")) for m in _VDF_PATH.findall(vdf_text)]


# --- candidates ---------------------------------------------------------------------------


def _steam_candidates() -> list[Path]:
    roots = []
    if sys.platform == "win32":
        for hive, key, value in (
            ("HKEY_CURRENT_USER", r"Software\Valve\Steam", "SteamPath"),
            ("HKEY_LOCAL_MACHINE", r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        ):
            found = _registry_value(hive, key, value)
            if found:
                roots.append(Path(found))
    elif sys.platform == "darwin":
        roots.append(Path.home() / "Library" / "Application Support" / "Steam")
    else:
        roots += [Path.home() / ".steam" / "steam", Path.home() / ".local" / "share" / "Steam"]
    libraries: list[Path] = []
    for root in roots:
        libraries.append(root)
        try:
            vdf = (root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8")
        except OSError:
            continue
        libraries += steam_library_folders(vdf)
    return [library / "steamapps" / "common" / GAME_FOLDER for library in libraries]


def _registry_candidates() -> list[Path]:
    """``InstallLocation`` of installed programs named like the game (Windows)."""
    if sys.platform != "win32":
        return []
    import winreg

    found = []
    for hive, key in (
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    ):
        try:
            root = winreg.OpenKey(hive, key)
        except OSError:
            continue
        with root:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(root, name) as program:
                        display = str(winreg.QueryValueEx(program, "DisplayName")[0])
                        location = str(winreg.QueryValueEx(program, "InstallLocation")[0])
                except OSError:
                    continue
                if display.startswith(GAME_FOLDER) and location:
                    found.append(Path(location))
    return found


def _usual_candidates() -> list[Path]:
    if sys.platform != "win32":
        return []
    folders = []
    for letter in string.ascii_uppercase:
        drive = Path(f"{letter}:\\")
        if not drive.exists():
            continue
        folders += [
            drive / "Games" / GAME_FOLDER,
            drive / "GOG Games" / GAME_FOLDER,
            drive / "SteamLibrary" / "steamapps" / "common" / GAME_FOLDER,
            drive / "Program Files (x86)" / "Steam" / "steamapps" / "common" / GAME_FOLDER,
            drive / "Program Files" / "Steam" / "steamapps" / "common" / GAME_FOLDER,
        ]
    return folders


def _documents_candidates() -> list[Path]:
    folders = []
    if sys.platform == "win32":
        known = _windows_documents()
        if known:
            folders.append(known)
    elif sys.platform.startswith("linux"):
        folders.append(Path.home() / ".local" / "share")
    folders.append(Path.home() / "Documents")
    return folders


def _windows_documents() -> Path | None:
    """The real Documents folder, wherever it was redirected (SHGetKnownFolderPath)."""
    import ctypes
    from ctypes import wintypes

    class Guid(ctypes.Structure):
        _fields_ = [
            ("data1", wintypes.DWORD),
            ("data2", wintypes.WORD),
            ("data3", wintypes.WORD),
            ("data4", ctypes.c_ubyte * 8),
        ]

    # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
    folder_id = Guid(
        0xFDD39AD0,
        0x238F,
        0x46AF,
        (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
    )
    pointer = ctypes.c_wchar_p()
    shell32 = ctypes.WinDLL("shell32")
    ole32 = ctypes.WinDLL("ole32")
    result = shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(pointer))
    try:
        return Path(pointer.value) if result == 0 and pointer.value else None
    finally:
        ole32.CoTaskMemFree(pointer)


def _registry_value(hive: str, key: str, value: str) -> str | None:
    import winreg

    try:
        with winreg.OpenKey(getattr(winreg, hive), key) as handle:
            return str(winreg.QueryValueEx(handle, value)[0])
    except OSError:
        return None

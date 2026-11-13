"""Watch the save folder and report when the game has finished writing a new save.

The desktop panel (UI_DESIGN, build order step 2) refreshes itself when the player
saves. EU4 writes saves incrementally (an autosave is ~45 MB of text), so a change is
reported only once the save has looked the same on two consecutive checks; reading it
earlier could catch a half-written file.

The current save is the one :func:`chancellor.save.loader.find_current_save` picks
(``continue_game.json`` first, then the newest file), the same rule every query uses.
:meth:`SaveWatcher.check` does one poll and is what the tests drive; :meth:`start` runs
it on a background thread.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from chancellor.save.loader import find_current_save

DEFAULT_INTERVAL = 2.0  # seconds between checks


@dataclass(frozen=True)
class SaveSignature:
    """What identifies one written state of a save file."""

    path: Path
    mtime_ns: int
    size: int


def current_signature(save_dir: Path) -> SaveSignature | None:
    """The current save and its size and modification time, or ``None`` if there is none."""
    try:
        path = find_current_save(save_dir)
        stat = path.stat()
    except (FileNotFoundError, OSError):
        return None
    return SaveSignature(path, stat.st_mtime_ns, stat.st_size)


class SaveWatcher:
    """Polls the save folder and calls back once per finished new save."""

    def __init__(
        self,
        save_dir: Path,
        on_new_save: Callable[[Path], None],
        interval: float = DEFAULT_INTERVAL,
    ) -> None:
        """Create a watcher; nothing runs until :meth:`check` or :meth:`start`.

        Args:
            save_dir: The ``save games`` folder.
            on_new_save: Called with the save's path when a new save has settled.
            interval: Seconds between checks when running on a thread.
        """
        self.save_dir = save_dir
        self.on_new_save = on_new_save
        self.interval = interval
        self._seen: SaveSignature | None = None
        self._pending: SaveSignature | None = None
        self._started = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def check(self) -> bool:
        """Poll once. The first poll only records the current save.

        Returns:
            Whether ``on_new_save`` was called.
        """
        signature = current_signature(self.save_dir)
        if not self._started:
            self._started = True
            self._seen = signature
            return False
        if signature is None or signature == self._seen:
            self._pending = None
            return False
        if signature != self._pending:  # still being written, or just appeared
            self._pending = signature
            return False
        self._seen, self._pending = signature, None
        self.on_new_save(signature.path)
        return True

    def start(self) -> None:
        """Check on a daemon thread every ``interval`` seconds until :meth:`stop`."""
        if self._thread is not None:
            return
        self.check()  # record the save that is current now
        self._thread = threading.Thread(target=self._run, name="save-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread, if it runs."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 1)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.check()
            except Exception:  # noqa: BLE001 - a failing callback must not kill the watcher
                continue

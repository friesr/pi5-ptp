import os
import json
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Any, Iterable


class Spooler:
    """
    Disk-backed FIFO spool for GNSS/PTP metrics.

    - Stores line-delimited JSON records.
    - Enforces a max size in bytes (SPOOL_MAX_BYTES).
    - Oldest files are deleted first when over limit.
    - Supports background draining while live data continues.
    """

    def __init__(self, spool_dir: str, max_bytes: int = 20_000_000_000):
        self.spool_dir = Path(spool_dir)
        self.max_bytes = max_bytes
        self.spool_dir.mkdir(parents=True, exist_ok=True)

        # Files are named with a monotonic timestamp and sequence
        self._lock = threading.Lock()
        self._current_file = None
        self._current_file_path = None
        self._current_size = 0
        self._sequence = int(time.time())

        self._open_new_file()

    def _open_new_file(self):
        if self._current_file:
            self._current_file.close()

        timestamp = int(time.time())
        self._sequence += 1
        filename = f"spool_{timestamp}_{self._sequence}.log"
        self._current_file_path = self.spool_dir / filename
        self._current_file = self._current_file_path.open("a", buffering=1)
        self._current_size = 0

    def _rotate_if_needed(self):
        if self._current_size > 10_000_000:  # ~10MB per file
            self._open_new_file()

    def _enforce_size_limit(self):
        """
        Ensure total spool size <= max_bytes by deleting oldest files first.
        """
        files = sorted(self.spool_dir.glob("spool_*.log"), key=lambda p: p.stat().st_mtime)
        total = sum(f.stat().st_size for f in files)

        while total > self.max_bytes and files:
            oldest = files.pop(0)
            size = oldest.stat().st_size
            try:
                oldest.unlink()
                total -= size
            except FileNotFoundError:
                pass

    def append(self, record: Dict[str, Any]):
        """
        Append a single JSON-serializable record to the spool.
        """
        line = json.dumps(record, separators=(",", ":")) + "\n"
        data = line.encode("utf-8")

        with self._lock:
            self._current_file.write(line)
            self._current_size += len(data)
            self._rotate_if_needed()
            self._enforce_size_limit()

    def iter_files_in_order(self) -> Iterable[Path]:
        """
        Yield spool files in chronological order (oldest first).
        """
        files = sorted(self.spool_dir.glob("spool_*.log"), key=lambda p: p.stat().st_mtime)
        for f in files:
            yield f

    def drain(self, handler, stop_event: Optional[threading.Event] = None, batch_size: int = 1000):
        """
        Drain spooled records using the provided handler(record_list) function.

        - handler is called with a list of records.
        - If handler raises, draining stops and files are left intact.
        - If handler succeeds, processed lines are removed by deleting the file
          once fully consumed.
        - stop_event can be used to gracefully stop draining.
        """
        for path in self.iter_files_in_order():
            if stop_event and stop_event.is_set():
                break

            records = []
            try:
                with path.open("r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                            records.append(rec)
                        except json.JSONDecodeError:
                            # Skip corrupted lines
                            continue

                        if len(records) >= batch_size:
                            handler(records)
                            records = []

                    if records:
                        handler(records)

                # If we got here, handler never raised for this file
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

            except FileNotFoundError:
                continue
            except Exception:
                # Any unexpected error: stop draining to avoid data loss
                break

    # ==================================================================
    #  Compatibility Layer for gps_streamer.py
    # ==================================================================

    def enqueue(self, payload: str):
        """
        Store a raw line payload (string) into the spool.
        Streamer uses this for line-based GNSS JSON.
        """
        with self._lock:
            self._current_file.write(payload + "\n")
            self._current_size += len(payload) + 1
            self._rotate_if_needed()
            self._enforce_size_limit()

    def dequeue(self) -> Optional[str]:
        """
        Return the next raw line from the oldest spool file.
        Deletes the file when empty.
        """
        for path in self.iter_files_in_order():
            try:
                with path.open("r") as f:
                    lines = f.readlines()
                if not lines:
                    path.unlink()
                    continue

                first = lines[0].rstrip("\n")

                # Rewrite file without the first line
                if len(lines) > 1:
                    with path.open("w") as f:
                        f.writelines(lines[1:])
                else:
                    path.unlink()

                return first

            except FileNotFoundError:
                continue

        return None

    def size_bytes(self) -> int:
        """
        Return total spool size in bytes.
        """
        return sum(f.stat().st_size for f in self.spool_dir.glob("spool_*.log"))

import os
import time
import logging
import subprocess
from pathlib import Path


# ======================================================================
#  Logging Helper
# ======================================================================

def setup_logger(name: str, log_dir: str = "/var/log/pi5-ptp-node", level=logging.INFO):
    """
    Creates a rotating logger for streamer/watchdog.
    Ensures:
    - log directory exists
    - no duplicate handlers
    - clean timestamped formatting
    """
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir) / f"{name}.log"

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if reloaded
    if logger.handlers:
        return logger

    handler = logging.FileHandler(log_path)

    # Python 3.13-safe logging format
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        "%Y-%m-%d %H:%M:%S"
    )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


# ======================================================================
#  Retry Helper
# ======================================================================

def retry(operation, attempts=3, delay=0.5, exceptions=(Exception,)):
    """
    Simple retry wrapper for small operations.

    Example:
        result = retry(lambda: do_something(), attempts=5, delay=1.0)

    If all attempts fail, the last exception is raised.
    """
    for i in range(attempts):
        try:
            return operation()
        except exceptions:
            if i == attempts - 1:
                raise
            time.sleep(delay)


# ======================================================================
#  Command Helper (required by streamer + watchdog)
# ======================================================================

def run_cmd(cmd: str) -> str:
    """
    Executes a shell command and returns stdout as UTF-8 text.
    Returns an empty string on failure.

    This is intentionally simple and resilient because the streamer
    and watchdog rely on it for gpspipe, chronyc, pgrep, etc.
    """
    try:
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
        return out.decode("utf-8", errors="ignore")
    except Exception:
        return ""

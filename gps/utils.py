import os
import time
import logging
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
    formatter = logging.Formatter(
        "%Y-%m-%d %H:%M:%S [%(levelname)s] %(name)s: %(message)s"
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

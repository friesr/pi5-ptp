import os
import time
import logging
from pathlib import Path


# ----------------------------------------------------------------------
#  Logging Helper
# ----------------------------------------------------------------------
def setup_logger(name: str, log_dir: str = "/var/log/pi5-ptp-node", level=logging.INFO):
    """
    Creates a rotating logger for streamer/watchdog.
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
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


# ----------------------------------------------------------------------
#  Retry Helper
# ----------------------------------------------------------------------
def retry(operation, attempts=3, delay=0.5, exceptions=(Exception,)):
    """
    Simple retry wrapper for small operations.
    """
    for i in range(attempts):
        try:
            return operation()
        except exceptions:
            if i == attempts - 1:
                raise
            time.sleep(delay)

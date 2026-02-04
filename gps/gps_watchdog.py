import time
from utils import setup_logger, run_cmd
from spooler import Spooler

logger = setup_logger("gps_watchdog")

class Watchdog:
    def __init__(self):
        self.spool = Spooler("/var/spool/pi5-ptp-node")

    def gpsd_ok(self):
        out = run_cmd("pgrep gpsd")
        return bool(out.strip())

    def chrony_ok(self):
        out = run_cmd("chronyc tracking")
        return "Leap status     : Normal" in out

    def influx_ok(self):
        # Simple check: if spool is growing, Influx is unreachable
        return self.spool.size_bytes() < 50000000

    def start(self):
        logger.info("gps_watchdog started")
        while True:
            gpsd_ok = self.gpsd_ok()
            chrony_ok = self.chrony_ok()
            influx_ok = self.influx_ok()
            spool_bytes = self.spool.size_bytes()

            logger.info(
                f"gpsd_ok={gpsd_ok} chrony_ok={chrony_ok} "
                f"influx_ok={influx_ok} spool={spool_bytes}"
            )

            if not gpsd_ok:
                run_cmd("systemctl restart gpsd")

            if not chrony_ok:
                run_cmd("systemctl restart chrony")

            if not influx_ok:
                run_cmd("systemctl restart gps-streamer")

            time.sleep(10)


if __name__ == "__main__":
    Watchdog().start()

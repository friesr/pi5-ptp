import time
import json
import requests
from utils import setup_logger
from spooler import Spooler
from utils import run_cmd

logger = setup_logger("gps_streamer")

class GNSSStreamer:
    def __init__(self, influx_url, influx_token, influx_org, influx_bucket):
        self.influx_url = influx_url
        self.influx_token = influx_token
        self.influx_org = influx_org
        self.influx_bucket = influx_bucket
        self.spool = Spooler("/var/spool/pi5-ptp-node")

    def _write_to_influx(self, payload):
        headers = {
            "Authorization": f"Token {self.influx_token}",
            "Content-Type": "text/plain"
        }
        url = f"{self.influx_url}/api/v2/write?org={self.influx_org}&bucket={self.influx_bucket}&precision=ns"
        try:
            r = requests.post(url, data=payload, headers=headers, timeout=2)
            if r.status_code != 204:
                raise Exception(f"Influx write failed: {r.status_code}")
            return True
        except Exception as e:
            logger.error(f"Influx write error: {e}")
            return False

    def _handle_record(self, record):
        payload = record.strip()
        if not self._write_to_influx(payload):
            self.spool.enqueue(payload)

    def start(self):
        logger.info("gps_streamer started")
        while True:
            # Drain spool first
            backlog = self.spool.dequeue()
            if backlog:
                self._write_to_influx(backlog)

            # Read GNSS data from gpsd
            out = run_cmd("gpspipe -w -n 10")
            for line in out.splitlines():
                if line.strip():
                    self._handle_record(line)

            time.sleep(1)


if __name__ == "__main__":
    import os
    influx_url = os.getenv("INFLUX_URL")
    influx_token = os.getenv("INFLUX_TOKEN")
    influx_org = os.getenv("INFLUX_ORG")
    influx_bucket = os.getenv("INFLUX_BUCKET")

    streamer = GNSSStreamer(influx_url, influx_token, influx_org, influx_bucket)
    streamer.start()

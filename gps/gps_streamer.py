#!/usr/bin/env python3
import os
import json
import time
import logging
import datetime
import subprocess
import requests

from spooler import Spooler


# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------
logging.basicConfig(
    filename="/var/log/pi5-ptp-node/gps_streamer.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("gps_streamer")


# ------------------------------------------------------------
# Helper: run a shell command and capture output
# ------------------------------------------------------------
def run_cmd(cmd):
    try:
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
        return out.decode("utf-8", errors="ignore")
    except Exception as e:
        log.error(f"Command failed: {cmd} -> {e}")
        return ""


# ------------------------------------------------------------
# Main Streamer
# ------------------------------------------------------------
class GNSSStreamer:
    def __init__(self):
        self.influx_url = os.getenv("INFLUX_URL")
        self.influx_token = os.getenv("INFLUX_TOKEN")
        self.influx_org = os.getenv("INFLUX_ORG")
        self.influx_bucket = os.getenv("INFLUX_BUCKET")

        self.spool = Spooler("/var/spool/pi5-ptp-node")

        if not all([self.influx_url, self.influx_token, self.influx_org, self.influx_bucket]):
            log.error("Missing one or more required InfluxDB environment variables")
            raise SystemExit(1)

        self.write_url = (
            f"{self.influx_url}/api/v2/write"
            f"?org={self.influx_org}&bucket={self.influx_bucket}&precision=ns"
        )

        log.info("GNSSStreamer initialized")

    # --------------------------------------------------------
    # Convert gpspipe JSON → Line Protocol
    # --------------------------------------------------------
    def _convert_to_line_protocol(self, record):
        try:
            obj = json.loads(record)
        except json.JSONDecodeError:
            return None

        if obj.get("class") != "TPV":
            return None

        lat = obj.get("lat")
        lon = obj.get("lon")
        alt = obj.get("alt")
        speed = obj.get("speed")
        climb = obj.get("climb")
        track = obj.get("track")
        mode = obj.get("mode")
        timestamp = obj.get("time")

        if lat is None or lon is None:
            return None

        fields = [f"lat={lat}", f"lon={lon}"]
        if alt is not None:
            fields.append(f"alt={alt}")
        if speed is not None:
            fields.append(f"speed={speed}")
        if climb is not None:
            fields.append(f"climb={climb}")
        if track is not None:
            fields.append(f"track={track}")

        tag_str = f"mode={mode if mode is not None else 0}"
        field_str = ",".join(fields)

        if timestamp:
            try:
                dt = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                ts = int(dt.timestamp() * 1_000_000_000)
                return f"gnss,{tag_str} {field_str} {ts}"
            except Exception:
                pass

        return f"gnss,{tag_str} {field_str}"

    # --------------------------------------------------------
    # Write to InfluxDB (with spool fallback)
    # --------------------------------------------------------
    def _write_to_influx(self, payload):
        headers = {
            "Authorization": f"Token {self.influx_token}",
            "Content-Type": "text/plain; charset=utf-8"
        }

        try:
            r = requests.post(self.write_url, data=payload, headers=headers, timeout=3)
            if r.status_code == 204:
                return True

            log.error(f"Influx write error: {r.status_code} -> {r.text}")
            return False

        except Exception as e:
            log.error(f"Influx write exception: {e}")
            return False

    # --------------------------------------------------------
    # Main loop
    # --------------------------------------------------------
    def start(self):
        log.info("GNSSStreamer starting")

        # Drain backlog first
        backlog = self.spool.dequeue()
        if backlog:
            log.info(f"Draining backlog: {len(backlog)} records")
            for payload in backlog:
                if not self._write_to_influx(payload):
                    self.spool.enqueue(payload)
                    break

        # Live streaming loop
        while True:
            out = run_cmd("gpspipe -w -n 10")
            for line in out.splitlines():
                lp = self._convert_to_line_protocol(line)
                if not lp:
                    continue

                if not self._write_to_influx(lp):
                    self.spool.enqueue(lp)

            time.sleep(1)


# ------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------
if __name__ == "__main__":
    streamer = GNSSStreamer()
    streamer.start()

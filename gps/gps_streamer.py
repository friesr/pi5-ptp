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

        log.info("GNSSStreamer initialized (SKY-only)")

    # --------------------------------------------------------
    # Convert gpspipe JSON → Line Protocol (SKY only)
    # --------------------------------------------------------
    def _convert_to_line_protocol(self, record):
        try:
            obj = json.loads(record)
        except json.JSONDecodeError:
            return []

        if obj.get("class") != "SKY":
            return []

        # Timestamp for the whole SKY block
        timestamp = obj.get("time")
        if timestamp:
            try:
                dt = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                ts = int(dt.timestamp() * 1_000_000_000)
            except Exception:
                ts = None
        else:
            ts = None

        sats = obj.get("satellites", [])
        lines = []

        for sat in sats:
            prn = sat.get("PRN")
            snr = sat.get("ss")
            el = sat.get("el")
            az = sat.get("az")
            used = sat.get("used")
            doppler = sat.get("doppler")

            if prn is None:
                continue

            # Tags
            tags = [f"prn={prn}"]

            # Fields
            fields = []
            if snr is not None:
                fields.append(f"snr={snr}")
            if el is not None:
                fields.append(f"elevation_deg={el}")
            if az is not None:
                fields.append(f"azimuth_deg={az}")
            if doppler is not None:
                fields.append(f"doppler_hz={doppler}")
            if used is not None:
                fields.append(f"used={1 if used else 0}")

            if not fields:
                continue

            tag_str = ",".join(tags)
            field_str = ",".join(fields)

            if ts is not None:
                line = f"gnss_sky,{tag_str} {field_str} {ts}"
            else:
                line = f"gnss_sky,{tag_str} {field_str}"

            lines.append(line)

        return lines

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
        log.info("GNSSStreamer starting (SKY-only)")

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
            batch = []

            for line in out.splitlines():
                lp_lines = self._convert_to_line_protocol(line)
                if not lp_lines:
                    continue
                batch.extend(lp_lines)

            if batch:
                payload = "\n".join(batch)
                if not self._write_to_influx(payload):
                    self.spool.enqueue(payload)

            time.sleep(1)


# ------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------
if __name__ == "__main__":
    streamer = GNSSStreamer()

import json
import time
import socket
import threading
import requests
from typing import Dict, Any, List, Optional

from spooler import Spooler


class GPSDClient:
    """
    Minimal GPSD JSON interface using the 'WATCH' and streaming protocol.
    """

    def __init__(self, host="127.0.0.1", port=2947):
        self.host = host
        self.port = port
        self.sock = None
        self.buffer = b""

    def connect(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect((self.host, self.port))

        # Enable JSON streaming
        self.sock.sendall(b'?WATCH={"enable":true,"json":true}\n')

    def read(self) -> Optional[Dict[str, Any]]:
        """
        Reads a single JSON object from gpsd.
        Returns None if no complete JSON object is available yet.
        """
        try:
            chunk = self.sock.recv(4096)
            if not chunk:
                return None
            self.buffer += chunk
        except socket.timeout:
            return None
        except Exception:
            return None

        # gpsd sends newline-delimited JSON
        if b"\n" not in self.buffer:
            return None

        line, self.buffer = self.buffer.split(b"\n", 1)
        line = line.strip()
        if not line:
            return None

        try:
            return json.loads(line.decode("utf-8"))
        except Exception:
            return None


class GNSSParser:
    """
    Converts raw gpsd JSON messages into structured per-satellite and per-epoch records.
    """

    @staticmethod
    def parse_sky(msg: Dict[str, Any], node_id: str) -> List[Dict[str, Any]]:
        """
        SKY messages contain per-satellite data.
        """
        sats = msg.get("satellites", [])
        out = []

        for s in sats:
            rec = {
                "measurement": "gnss_satellite",
                "tags": {
                    "node_id": node_id,
                    "sat_id": s.get("PRN"),
                    "constellation": GNSSParser._constellation_from_prn(s.get("PRN")),
                    "used_in_fix": bool(s.get("used", False)),
                },
                "fields": {
                    "snr": s.get("ss"),
                    "elevation_deg": s.get("el"),
                    "azimuth_deg": s.get("az"),
                    "health": s.get("health"),
                    "signal": s.get("signal"),
                },
                "timestamp": time.time(),
            }
            out.append(rec)

        return out

    @staticmethod
    def parse_tpv(msg: Dict[str, Any], node_id: str) -> Optional[Dict[str, Any]]:
        """
        TPV messages contain fix-level data.
        """
        if msg.get("class") != "TPV":
            return None

        return {
            "measurement": "gnss_epoch",
            "tags": {
                "node_id": node_id,
            },
            "fields": {
                "fix_type": msg.get("mode"),
                "lat": msg.get("lat"),
                "lon": msg.get("lon"),
                "alt": msg.get("alt"),
                "speed": msg.get("speed"),
                "track": msg.get("track"),
                "climb": msg.get("climb"),
                "epx": msg.get("epx"),
                "epy": msg.get("epy"),
                "epv": msg.get("epv"),
                "ept": msg.get("ept"),
                "eps": msg.get("eps"),
                "epc": msg.get("epc"),
            },
            "timestamp": time.time(),
        }

    @staticmethod
    def _constellation_from_prn(prn: Any) -> str:
        """
        Rough PRN → constellation mapping.
        """
        if prn is None:
            return "UNKNOWN"
        try:
            prn = int(prn)
        except Exception:
            return "UNKNOWN"

        if 1 <= prn <= 32:
            return "GPS"
        if 65 <= prn <= 96:
            return "GLONASS"
        if 120 <= prn <= 158:
            return "GALILEO"
        if 201 <= prn <= 237:
            return "BEIDOU"

        return "UNKNOWN"


class GNSSStreamer:
    """
    Main streamer class:
    - Connects to gpsd
    - Parses GNSS messages
    - Shapes per-satellite + per-epoch records
    - Sends to InfluxDB (Part 2)
    - Spools on failure
    """

    def __init__(self, env: Dict[str, str]):
        self.node_id = env["NODE_ID"]
        self.influx_url = env["INFLUX_URL"]
        self.influx_org = env["INFLUX_ORG"]
        self.influx_bucket = env["INFLUX_BUCKET"]
        self.influx_token = env["INFLUX_TOKEN"]

        self.spool = Spooler(
            spool_dir=env["SPOOL_DIR"],
            max_bytes=int(env["SPOOL_MAX_BYTES"])
        )

        self.gpsd = GPSDClient()
        self.stop_event = threading.Event()

    def start(self):
        """
        Main loop: read gpsd messages, parse, and forward.
        """
        self.gpsd.connect()

        while not self.stop_event.is_set():
            msg = self.gpsd.read()
            if not msg:
                continue

            cls = msg.get("class")

            # SKY → per-satellite
            if cls == "SKY":
                sats = GNSSParser.parse_sky(msg, self.node_id)
                for rec in sats:
                    self._handle_record(rec)

            # TPV → per-epoch
            elif cls == "TPV":
                epoch = GNSSParser.parse_tpv(msg, self.node_id)
                if epoch:
                    self._handle_record(epoch)

        # ----------------------------------------------------------------------
    #  InfluxDB Write Path
    # ----------------------------------------------------------------------
    def _write_to_influx(self, records: List[Dict[str, Any]]) -> bool:
        """
        Writes a batch of records to InfluxDB.
        Returns True on success, False on failure.
        """

        if not records:
            return True

        lines = []
        for rec in records:
            measurement = rec["measurement"]
            tags = rec["tags"]
            fields = rec["fields"]
            ts = rec["timestamp"]

            # Build InfluxDB line protocol
            tag_str = ",".join(f"{k}={v}" for k, v in tags.items() if v is not None)
            field_str = ",".join(
                f"{k}={json.dumps(v)}" for k, v in fields.items() if v is not None
            )

            line = f"{measurement},{tag_str} {field_str} {int(ts * 1e9)}"
            lines.append(line)

        payload = "\n".join(lines)

        url = f"{self.influx_url}/api/v2/write"
        params = {
            "org": self.influx_org,
            "bucket": self.influx_bucket,
            "precision": "ns",
        }
        headers = {
            "Authorization": f"Token {self.influx_token}",
            "Content-Type": "text/plain; charset=utf-8",
        }

        try:
            r = requests.post(url, params=params, data=payload, headers=headers, timeout=2)
            return r.status_code == 204
        except Exception:
            return False

    # ----------------------------------------------------------------------
    #  Record Handler (Live + Spool)
    # ----------------------------------------------------------------------
    def _handle_record(self, record: Dict[str, Any]):
        """
        Handles a single GNSS/PTP record:
        - Try to send to InfluxDB immediately
        - If fails, spool to disk
        """
        if self._write_to_influx([record]):
            return

        # Influx unreachable → spool
        self.spool.append(record)

    # ----------------------------------------------------------------------
    #  Background Spool Replay Thread
    # ----------------------------------------------------------------------
    def start_replay_thread(self):
        """
        Starts a background thread that drains the spool slowly
        while live data continues to stream.
        """
        t = threading.Thread(target=self._replay_loop, daemon=True)
        t.start()

    def _replay_loop(self):
        """
        Hybrid replay model:
        - Live data is always prioritized
        - Spool drains slowly in background
        - Stops if streamer stops
        """
        while not self.stop_event.is_set():
            time.sleep(2)

            def handler(batch):
                # Try to write batch
                ok = self._write_to_influx(batch)
                if not ok:
                    raise RuntimeError("Influx still unreachable")

            try:
                self.spool.drain(handler, stop_event=self.stop_event, batch_size=500)
            except Exception:
                # Influx still down → wait and retry later
                time.sleep(5)
                continue
    # ----------------------------------------------------------------------
    #  Chrony + PPS Metrics
    # ----------------------------------------------------------------------
    def _read_chrony_tracking(self) -> Dict[str, Any]:
        """
        Reads chrony tracking output and extracts timing metrics.
        """
        try:
            out = subprocess.check_output(["chronyc", "tracking"], timeout=2).decode()
        except Exception:
            return {}

        metrics = {}

        for line in out.splitlines():
            if ":" not in line:
                continue
            key, val = [x.strip() for x in line.split(":", 1)]

            if key == "Reference ID":
                metrics["reference_id"] = val
            elif key == "Stratum":
                metrics["stratum"] = int(val)
            elif key == "Ref time (UTC)":
                metrics["ref_time"] = val
            elif key == "System time":
                # Example: "0.000000123 seconds fast"
                parts = val.split()
                if len(parts) >= 2:
                    try:
                        metrics["system_time_offset_s"] = float(parts[0])
                    except Exception:
                        pass
            elif key == "Last offset":
                try:
                    metrics["last_offset_s"] = float(val.split()[0])
                except Exception:
                    pass
            elif key == "RMS offset":
                try:
                    metrics["rms_offset_s"] = float(val.split()[0])
                except Exception:
                    pass
            elif key == "Frequency":
                try:
                    metrics["frequency_ppm"] = float(val.split()[0])
                except Exception:
                    pass
            elif key == "Residual freq":
                try:
                    metrics["residual_freq_ppm"] = float(val.split()[0])
                except Exception:
                    pass
            elif key == "Skew":
                try:
                    metrics["skew_ppm"] = float(val.split()[0])
                except Exception:
                    pass
            elif key == "Root delay":
                try:
                    metrics["root_delay_s"] = float(val.split()[0])
                except Exception:
                    pass
            elif key == "Root dispersion":
                try:
                    metrics["root_dispersion_s"] = float(val.split()[0])
                except Exception:
                    pass
            elif key == "Leap status":
                metrics["leap_status"] = val

        return metrics

    def _emit_chrony_record(self):
        """
        Converts chrony tracking metrics into an InfluxDB record.
        """
        m = self._read_chrony_tracking()
        if not m:
            return None

        return {
            "measurement": "chrony_tracking",
            "tags": {
                "node_id": self.node_id,
                "reference_id": m.get("reference_id"),
                "leap_status": m.get("leap_status"),
            },
            "fields": {
                "stratum": m.get("stratum"),
                "system_time_offset_s": m.get("system_time_offset_s"),
                "last_offset_s": m.get("last_offset_s"),
                "rms_offset_s": m.get("rms_offset_s"),
                "frequency_ppm": m.get("frequency_ppm"),
                "residual_freq_ppm": m.get("residual_freq_ppm"),
                "skew_ppm": m.get("skew_ppm"),
                "root_delay_s": m.get("root_delay_s"),
                "root_dispersion_s": m.get("root_dispersion_s"),
            },
            "timestamp": time.time(),
        }
    
            # Additional gpsd classes (GST, ATT, etc.) can be added later

    def _handle_record(self, record: Dict[str, Any]):
        """
        Part 2 will add:
        - Influx write
        - spool-on-failure
        - replay logic
        """
        # Placeholder for now — just spool everything
        self.spool.append(record)

    def stop(self):
        self.stop_event.set()

import os
import time
import json
import socket
import subprocess
from pathlib import Path
from typing import Dict, Any


class Watchdog:
    """
    Lightweight watchdog for:
    - gpsd health
    - chrony sync state
    - spool depth
    - Influx reachability
    - service restarts
    - optional reboot on unrecoverable failure
    """

    def __init__(self, env: Dict[str, str]):
        self.influx_url = env["INFLUX_URL"]
        self.spool_dir = Path(env["SPOOL_DIR"])
        self.max_spool_bytes = int(env["SPOOL_MAX_BYTES"])

        self.gpsd_host = "127.0.0.1"
        self.gpsd_port = 2947

        self.unhealthy_since = None
        self.reboot_threshold_seconds = 900  # 15 minutes of continuous bad state

    # ------------------------------------------------------------------
    #  Health checks
    # ------------------------------------------------------------------
    def check_gpsd(self) -> bool:
        """
        Try to connect to gpsd and issue a VERSION command.
        """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect((self.gpsd_host, self.gpsd_port))
            s.sendall(b'?VERSION;\n')
            data = s.recv(1024)
            s.close()
            return bool(data)
        except Exception:
            return False

    def check_chrony(self) -> bool:
        """
        Use chronyc tracking to see if chrony is synced.
        """
        try:
            out = subprocess.check_output(["chronyc", "tracking"], timeout=3).decode()
        except Exception:
            return False

        # Simple heuristic: look for "Leap status     : Normal"
        # and "System time     : X seconds fast/slow"
        if "Leap status     : Normal" not in out:
            return False

        return True

    def check_influx(self) -> bool:
        """
        Simple TCP reachability check to Influx host:port.
        """
        try:
            # Extract host from URL like http://192.168.1.106:8086
            host_port = self.influx_url.replace("http://", "").replace("https://", "")
            if "/" in host_port:
                host_port = host_port.split("/", 1)[0]

            if ":" in host_port:
                host, port = host_port.split(":", 1)
                port = int(port)
            else:
                host, port = host_port, 80

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect((host, port))
            s.close()
            return True
        except Exception:
            return False

    def get_spool_usage(self) -> int:
        """
        Returns total spool size in bytes.
        """
        total = 0
        if not self.spool_dir.exists():
            return 0

        for p in self.spool_dir.glob("spool_*.log"):
            try:
                total += p.stat().st_size
            except FileNotFoundError:
                continue
        return total

    # ------------------------------------------------------------------
    #  Actions
    # ------------------------------------------------------------------
    def restart_service(self, name: str):
        try:
            subprocess.run(["systemctl", "restart", name], check=False)
        except Exception:
            pass

    def reboot_system(self):
        try:
            subprocess.run(["shutdown", "-r", "now"], check=False)
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  Main loop
    # ------------------------------------------------------------------
    def run(self):
        """
        Periodic health loop.
        """
        while True:
            gpsd_ok = self.check_gpsd()
            chrony_ok = self.check_chrony()
            influx_ok = self.check_influx()
            spool_bytes = self.get_spool_usage()

            unhealthy = False

            if not gpsd_ok:
                unhealthy = True
                self.restart_service("gpsd")

            if not chrony_ok:
                unhealthy = True
                self.restart_service("chrony")

            if not influx_ok:
                # Not necessarily unhealthy, but worth noting
                pass

            if spool_bytes > self.max_spool_bytes * 0.9:
                # Spool is >90% full → treat as unhealthy
                unhealthy = True

            # Track continuous unhealthy duration
            now = time.time()
            if unhealthy:
                if self.unhealthy_since is None:
                    self.unhealthy_since = now
                elif now - self.unhealthy_since > self.reboot_threshold_seconds:
                    # Last resort: reboot
                    self.reboot_system()
                    return
            else:
                self.unhealthy_since = None

            time.sleep(10)


def load_env(path: str = "/etc/pi5-ptp-node/streamer.env") -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not os.path.exists(path):
        return env

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def main():
    env = load_env()
    if not env:
        # No env → nothing to do
        return

    wd = Watchdog(env)
    wd.run()


if __name__ == "__main__":
    main()

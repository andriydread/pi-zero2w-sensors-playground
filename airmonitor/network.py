"""Wi-Fi / internet connectivity probe.

Reads interface state from /sys and /proc and tries to open a TCP
connection to a known host (default: Cloudflare DNS on port 53).
"""

import logging
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

LOGGER = logging.getLogger("airmonitor")


def _read_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _read_signal_dbm(interface: str) -> Optional[float]:
    """Parse the signal level for `interface` from /proc/net/wireless."""
    content = _read_file(Path("/proc/net/wireless"))
    if content is None:
        return None
    for line in content.splitlines()[2:]:
        fields = line.strip().split()
        if len(fields) >= 4 and fields[0] == f"{interface}:":
            try:
                return float(fields[3].rstrip("."))
            except ValueError:
                return None
    return None


def probe_network(config) -> Dict[str, Any]:
    """Return a status dict describing the current network health."""
    interface_dir = Path("/sys/class/net") / config.wifi_interface
    interface_exists = interface_dir.exists()

    reachable = False
    latency_ms = None
    error = None
    try:
        started = time.monotonic()
        with socket.create_connection(
            (config.connectivity_host, config.connectivity_port),
            timeout=config.connectivity_timeout,
        ):
            latency_ms = round((time.monotonic() - started) * 1000, 1)
        reachable = True
    except OSError as exc:
        error = f"{exc.__class__.__name__}: {exc}"

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "interface": config.wifi_interface,
        "available": interface_exists,
        "operstate": _read_file(interface_dir / "operstate") if interface_exists else None,
        "carrier": _read_file(interface_dir / "carrier") if interface_exists else None,
        "signal_level_dbm": _read_signal_dbm(config.wifi_interface),
        "target_host": config.connectivity_host,
        "target_port": config.connectivity_port,
        "healthy": reachable,
        "latency_ms": latency_ms,
        "error": error,
    }

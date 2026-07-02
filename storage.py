import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


METRIC_FIELDS = ("co2", "temp", "humid", "pm1", "pm25", "pm4", "pm10", "tps")
COMMAND_STATUSES = {"pending", "running", "succeeded", "failed"}


class AirMonitorDatabase:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at INTEGER NOT NULL,
                    co2 INTEGER,
                    temp REAL,
                    humid REAL,
                    pm1 REAL,
                    pm25 REAL,
                    pm4 REAL,
                    pm10 REAL,
                    tps REAL
                );
                CREATE INDEX IF NOT EXISTS idx_measurements_recorded_at
                    ON measurements(recorded_at);

                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command TEXT NOT NULL,
                    payload TEXT,
                    status TEXT NOT NULL,
                    result TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_commands_status_created_at
                    ON commands(status, created_at);
                """
            )
            connection.execute(
                "UPDATE commands SET status = 'failed', result = 'Collector restarted before completing command', updated_at = ? WHERE status = 'running'",
                (self._now_ts(),),
            )

    @staticmethod
    def _now_ts() -> int:
        return int(time.time())

    @staticmethod
    def _to_iso(timestamp: Optional[int]) -> Optional[str]:
        if timestamp is None:
            return None
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _decode_json(text: Optional[str], fallback: Any = None) -> Any:
        if text is None:
            return fallback
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return fallback

    def insert_measurement(self, values: Dict[str, Optional[float]]) -> None:
        timestamp = self._now_ts()
        payload = {field: values.get(field) for field in METRIC_FIELDS}
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO measurements (
                    recorded_at, co2, temp, humid, pm1, pm25, pm4, pm10, tps
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    payload["co2"],
                    payload["temp"],
                    payload["humid"],
                    payload["pm1"],
                    payload["pm25"],
                    payload["pm4"],
                    payload["pm10"],
                    payload["tps"],
                ),
            )

    def set_state(self, key: str, value: Any) -> None:
        timestamp = self._now_ts()
        encoded = json.dumps(value)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO state(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, encoded, timestamp),
            )

    def get_state(self, key: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value, updated_at FROM state WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "value": self._decode_json(row["value"]),
            "updated_at": self._to_iso(row["updated_at"]),
            "updated_at_ts": row["updated_at"],
        }

    def queue_command(self, command: str, payload: Optional[Dict[str, Any]] = None) -> int:
        timestamp = self._now_ts()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO commands(command, payload, status, result, created_at, updated_at) VALUES (?, ?, 'pending', NULL, ?, ?)",
                (command, json.dumps(payload or {}), timestamp, timestamp),
            )
            return int(cursor.lastrowid)

    def claim_pending_commands(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id, command, payload, created_at FROM commands WHERE status = 'pending' ORDER BY created_at ASC, id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                params = [self._now_ts(), *ids]
                connection.execute(
                    f"UPDATE commands SET status = 'running', updated_at = ? WHERE id IN ({placeholders})",
                    params,
                )
            connection.commit()
        claimed = []
        for row in rows:
            claimed.append(
                {
                    "id": row["id"],
                    "command": row["command"],
                    "payload": self._decode_json(row["payload"], {}),
                    "created_at": self._to_iso(row["created_at"]),
                    "created_at_ts": row["created_at"],
                }
            )
        return claimed

    def complete_command(self, command_id: int, success: bool, result: Any) -> None:
        status = "succeeded" if success else "failed"
        if status not in COMMAND_STATUSES:
            raise ValueError("invalid command status")
        timestamp = self._now_ts()
        with self._connect() as connection:
            connection.execute(
                "UPDATE commands SET status = ?, result = ?, updated_at = ? WHERE id = ?",
                (status, json.dumps(result), timestamp, command_id),
            )

    def get_recent_commands(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, command, payload, status, result, created_at, updated_at FROM commands ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        commands: List[Dict[str, Any]] = []
        for row in rows:
            commands.append(
                {
                    "id": row["id"],
                    "command": row["command"],
                    "payload": self._decode_json(row["payload"], {}),
                    "status": row["status"],
                    "result": self._decode_json(row["result"]),
                    "created_at": self._to_iso(row["created_at"]),
                    "updated_at": self._to_iso(row["updated_at"]),
                }
            )
        return commands

    def get_latest_measurement(self) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT recorded_at, co2, temp, humid, pm1, pm25, pm4, pm10, tps FROM measurements ORDER BY recorded_at DESC, id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self._measurement_row_to_dict(row)

    def query_history(self, hours: int, bucket_seconds: int) -> List[Dict[str, Any]]:
        cutoff = self._now_ts() - max(hours, 1) * 3600
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    (recorded_at / ?) * ? AS bucket_ts,
                    AVG(co2) AS co2,
                    AVG(temp) AS temp,
                    AVG(humid) AS humid,
                    AVG(pm1) AS pm1,
                    AVG(pm25) AS pm25,
                    AVG(pm4) AS pm4,
                    AVG(pm10) AS pm10,
                    AVG(tps) AS tps
                FROM measurements
                WHERE recorded_at >= ?
                GROUP BY bucket_ts
                ORDER BY bucket_ts ASC
                """,
                (bucket_seconds, bucket_seconds, cutoff),
            ).fetchall()
        history: List[Dict[str, Any]] = []
        for row in rows:
            history.append(
                {
                    "timestamp": self._to_iso(row["bucket_ts"]),
                    "timestamp_ts": row["bucket_ts"],
                    "co2": int(round(row["co2"])) if row["co2"] is not None else None,
                    "temp": round(row["temp"], 2) if row["temp"] is not None else None,
                    "humid": round(row["humid"], 2) if row["humid"] is not None else None,
                    "pm1": round(row["pm1"], 2) if row["pm1"] is not None else None,
                    "pm25": round(row["pm25"], 2) if row["pm25"] is not None else None,
                    "pm4": round(row["pm4"], 2) if row["pm4"] is not None else None,
                    "pm10": round(row["pm10"], 2) if row["pm10"] is not None else None,
                    "tps": round(row["tps"], 2) if row["tps"] is not None else None,
                }
            )
        return history


    def delete_history(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM measurements")
            deleted_rows = int(cursor.rowcount if cursor.rowcount is not None else 0)
            connection.execute("VACUUM")
        return deleted_rows

    def get_dashboard_summary(self) -> Dict[str, Any]:
        return {
            "latest_measurement": self.get_latest_measurement(),
            "latest_weather": self.get_state("latest_weather"),
            "latest_display_snapshot": self.get_state("latest_display_snapshot"),
            "collector_status": self.get_state("collector_status"),
            "recent_commands": self.get_recent_commands(),
        }

    def _measurement_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "timestamp": self._to_iso(row["recorded_at"]),
            "timestamp_ts": row["recorded_at"],
            "co2": row["co2"],
            "temp": row["temp"],
            "humid": row["humid"],
            "pm1": row["pm1"],
            "pm25": row["pm25"],
            "pm4": row["pm4"],
            "pm10": row["pm10"],
            "tps": row["tps"],
        }

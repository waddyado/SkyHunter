"""
Read-only lookup against Kinetic BaseStation-style SQLite (e.g. data/basestation.sqb).
Primary table: Aircraft (ModeS = ICAO hex, Registration, Interested flag, metadata).
"""
import logging
import os
import re
import sqlite3
import threading
import urllib.parse
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("skyhunter.basestation")

# Columns selected for analyst-facing alerts (actual DB names)
_AIRCRAFT_SELECT = """
SELECT AircraftID, ModeS, Registration, ModeSCountry, Country, Status,
       Manufacturer, ICAOTypeCode, Type, SerialNo, PopularName, GenericName,
       AircraftClass, RegisteredOwners, OperatorFlagCode, UserNotes, Interested,
       UserTag, UserString1, UserString2, UserString3, InfoURL,
       FirstCreated, LastModified
FROM Aircraft
"""

_match_any_env = os.environ.get("SKYHUNTER_BASESTATION_MATCH_ANY", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _norm_modes(icao: str) -> str:
    if not icao:
        return ""
    s = str(icao).strip().upper()
    s = re.sub(r"[^0-9A-F]", "", s)
    return s[:6] if len(s) >= 6 else s


def _norm_registration(reg: str) -> str:
    if not reg:
        return ""
    s = str(reg).strip().upper().replace("-", "").replace(" ", "")
    return s


class BasestationWatchlist:
    """Thread-safe read-only lookups; lazy-open on first use."""

    def __init__(self, sqb_path: str):
        self._path = sqb_path
        self._conn = None  # type: Optional[sqlite3.Connection]
        self._lock = threading.Lock()
        self._available = False
        self._match_any = _match_any_env
        self._logged_schema = False

    @property
    def available(self) -> bool:
        return self._available

    @property
    def match_any_row(self) -> bool:
        return self._match_any

    def ensure_loaded(self) -> bool:
        """Open DB if present; idempotent. Call once at server startup."""
        return self._open()

    def _open(self) -> bool:
        if self._conn is not None:
            return self._available
        if not self._path or not os.path.isfile(self._path):
            logger.info("Basestation DB not found at %s (ADS-B watchlist disabled).", self._path)
            self._available = False
            return False
        try:
            abs_path = os.path.abspath(self._path)
            uri = "file:" + urllib.parse.quote(abs_path) + "?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._available = True
            logger.info("Opened Basestation DB (read-only): %s", abs_path)
            self._log_schema_once()
        except Exception as e:
            logger.warning("Could not open Basestation DB %s: %s", self._path, e)
            self._conn = None
            self._available = False
        return self._available

    def _log_schema_once(self) -> None:
        if self._logged_schema or not self._conn:
            return
        self._logged_schema = True
        try:
            cur = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [r[0] for r in cur.fetchall()]
            logger.info("Basestation tables: %s", ", ".join(tables))
            if "Aircraft" not in tables:
                logger.warning("Basestation DB has no Aircraft table; watchlist matching disabled.")
                self._available = False
                return
            cur = self._conn.execute("PRAGMA table_info(Aircraft)")
            cols = [r[1] for r in cur.fetchall()]
            logger.info("Aircraft column count=%d (includes ModeS, Registration, Interested, …)", len(cols))
            mode = "all rows" if self._match_any else "Interested!=0 only"
            cur = self._conn.execute("SELECT COUNT(*) FROM Aircraft")
            total = cur.fetchone()[0]
            if self._match_any:
                interested = total
            else:
                cur = self._conn.execute(
                    "SELECT COUNT(*) FROM Aircraft WHERE Interested IS NOT NULL AND Interested != 0"
                )
                interested = cur.fetchone()[0]
            logger.info(
                "Basestation watchlist mode=%s | Aircraft rows=%d | qualifying (Interested) rows=%d",
                mode,
                total,
                interested,
            )
            if interested == 0 and not self._match_any:
                logger.warning(
                    "No rows with Interested=1; mark aircraft in BaseStation or set "
                    "SKYHUNTER_BASESTATION_MATCH_ANY=1 to match any DB row (noisy on large DBs)."
                )
        except Exception as e:
            logger.warning("Basestation schema inspection failed: %s", e)

    def _interested_sql(self) -> str:
        if self._match_any:
            return ""
        return " AND (Interested IS NOT NULL AND Interested != 0)"

    def lookup_by_modes(self, modes_hex: str) -> Optional[sqlite3.Row]:
        if not self._open() or not self._available:
            return None
        m = _norm_modes(modes_hex)
        if not m:
            return None
        sql = _AIRCRAFT_SELECT + " WHERE ModeS = ?" + self._interested_sql() + " LIMIT 1"
        with self._lock:
            try:
                cur = self._conn.execute(sql, (m,))
                return cur.fetchone()
            except Exception as e:
                logger.warning("Basestation lookup_by_modes failed: %s", e)
                return None

    def lookup_by_registration(self, registration: str) -> Optional[sqlite3.Row]:
        if not self._open() or not self._available:
            return None
        r = _norm_registration(registration)
        if len(r) < 3:
            return None
        # Match normalized tail (strip punctuation in DB similarly)
        sql = (
            _AIRCRAFT_SELECT
            + " WHERE REPLACE(REPLACE(UPPER(TRIM(Registration)), '-', ''), ' ', '') = ?"
            + self._interested_sql()
            + " LIMIT 1"
        )
        with self._lock:
            try:
                cur = self._conn.execute(sql, (r,))
                return cur.fetchone()
            except Exception as e:
                logger.warning("Basestation lookup_by_registration failed: %s", e)
                return None

    def lookup_for_plane(self, icao: str, registration: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Try ModeS (ICAO) first, then registration/tail.
        Returns (db_record_dict, match_reason) or (None, None).
        """
        if not self._open() or not self._available:
            return None, None
        icao_n = _norm_modes(icao)
        row = self.lookup_by_modes(icao_n)
        if row:
            logger.info(
                "Basestation MATCH by ModeS=%s (Interested=%s)",
                icao_n,
                row["Interested"],
            )
            return _row_to_dict(row), "ModeS"
        reg = registration or ""
        if reg:
            row = self.lookup_by_registration(reg)
            if row:
                logger.info(
                    "Basestation MATCH by Registration=%s -> ModeS=%s (Interested=%s)",
                    reg,
                    row["ModeS"],
                    row["Interested"],
                )
                return _row_to_dict(row), "Registration"
        return None, None


def _row_to_dict(row: sqlite3.Row) -> dict:
    out = {}
    for k in row.keys():
        v = row[k]
        if isinstance(v, bytes):
            v = v.decode("utf-8", errors="replace")
        out[k] = v
    return out

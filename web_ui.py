#!/usr/bin/env python3
"""
Skyhunter V2 — Web UI server.
Runs the existing Skyhunter detector in a background thread and serves a web dashboard.
HackRF status, detections (FPV/DJI/UNKNOWN) as colored icon notifications, and ADS-B pipe.

Skyhunter (and libhackrf) are imported only inside the detector thread so the server
starts even when HackRF is not connected or libhackrf is not installed.
"""
import os
import sys

# Ensure venv site-packages is on path (WSL/venv can miss it).
_exe = os.path.abspath(sys.executable)
if ".venv" in _exe or "venv" in _exe:
    _base = os.path.dirname(os.path.dirname(_exe))
    _py = "python{}.{}".format(sys.version_info.major, sys.version_info.minor)
    for _sub in ("lib", "Lib"):
        _site = os.path.join(_base, _sub, _py, "site-packages")
        if os.path.isdir(_site) and _site not in sys.path:
            sys.path.insert(0, _site)
            break

import argparse
import atexit
import json
import re
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

# Band constants (match skyhunter.py) so we can choose mode without importing skyhunter
FPV_58_WIDE_MHZ = (5650, 5920)
DJI_24_MHZ = (2400, 2483)
DJI_58_MHZ = (5725, 5850)
DJI_BANDS_MHZ = [DJI_24_MHZ, DJI_58_MHZ]

from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = "skyhunter-v2"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Shared state (updated by Skyhunter thread, read by routes/socketio)
live_status = {}
detections = []  # list of {label, center_mhz, width_mhz, message, ts}; keep last N (drone)
plane_detections = []  # list of {lat, lon, altitude?, icao?, flight?, ts}; for map
adsb_lines = []  # last N lines from ADS-B pipe
MAX_DETECTIONS = 200
MAX_PLANES = 500
MAX_ADSB_LINES = 500
skyhunter_thread = None
skyhunter_started = False
skyhunter_start_lock = threading.Lock()
skyhunter_args = None
skyhunter_bands = None
data_lock = threading.Lock()

# Project root: directory containing this file (web_ui.py). All paths are relative to it.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
MAP_TILES_DIR = os.path.join(PROJECT_ROOT, "static", "map-tiles")
# OSM tile policy: cache on disk; identify app (https://operations.osmfoundation.org/policies/tiles/)
OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
MAP_TILE_USER_AGENT = "SkyhunterV2/1.0 (local map cache)"
MAP_TILE_MAX_ZOOM = 19
_map_tile_write_lock = threading.Lock()
SAVES_DIR = os.path.join(PROJECT_ROOT, "saves")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
FAA_MASTER_PATH = os.path.join(DATA_DIR, "MASTER.txt")
FAA_ACFTREF_PATH = os.path.join(DATA_DIR, "ACFTREF.txt")

# FAA aircraft lookup: MASTER keyed by Mode S hex; ACFTREF keyed by MFR MDL CODE
_faa_master = {}  # icao_hex -> {registration, operator, mfr_mdl_code}
_faa_acftref = {}  # code -> {manufacturer, model, type}
_faa_loaded = False


def _load_faa_data():
    """Load FAA MASTER.txt and ACFTREF.txt for offline aircraft lookup. Idempotent."""
    global _faa_master, _faa_acftref, _faa_loaded
    if _faa_loaded:
        return
    _faa_loaded = True
    import csv
    # MASTER.txt: N-NUMBER, SERIAL NUMBER, MFR MDL CODE, ..., NAME, ..., MODE S CODE HEX
    if os.path.isfile(FAA_MASTER_PATH):
        try:
            with open(FAA_MASTER_PATH, "r", encoding="utf-8-sig", newline="") as f:
                r = csv.reader(f)
                headers = next(r, None)
                if headers:
                    h = [c.strip() for c in headers]
                    try:
                        idx_n = h.index("N-NUMBER")
                        idx_name = h.index("NAME")
                        idx_mfr = h.index("MFR MDL CODE")
                        idx_mode_s_hex = h.index("MODE S CODE HEX")
                    except ValueError:
                        idx_n, idx_name, idx_mfr, idx_mode_s_hex = 0, 6, 2, 33
                    for row in r:
                        if len(row) <= max(idx_n, idx_name, idx_mfr, idx_mode_s_hex):
                            continue
                        mode_s_hex = (row[idx_mode_s_hex] or "").strip().upper()
                        if not mode_s_hex:
                            continue
                        _faa_master[mode_s_hex] = {
                            "registration": (row[idx_n] or "").strip(),
                            "operator": (row[idx_name] or "").strip(),
                            "mfr_mdl_code": (row[idx_mfr] or "").strip(),
                        }
        except Exception:
            pass
    # ACFTREF.txt: CODE, MFR, MODEL, TYPE-ACFT, ...
    if os.path.isfile(FAA_ACFTREF_PATH):
        try:
            with open(FAA_ACFTREF_PATH, "r", encoding="utf-8-sig", newline="") as f:
                r = csv.reader(f)
                headers = next(r, None)
                if headers:
                    h = [c.strip() for c in headers]
                    try:
                        idx_code = h.index("CODE")
                        idx_mfr = h.index("MFR")
                        idx_model = h.index("MODEL")
                        idx_type = h.index("TYPE-ACFT")
                    except ValueError:
                        idx_code, idx_mfr, idx_model, idx_type = 0, 1, 2, 3
                    for row in r:
                        if len(row) <= max(idx_code, idx_mfr, idx_model, idx_type):
                            continue
                        code = (row[idx_code] or "").strip()
                        if not code:
                            continue
                        _faa_acftref[code] = {
                            "manufacturer": (row[idx_mfr] or "").strip(),
                            "model": (row[idx_model] or "").strip(),
                            "type": (row[idx_type] or "").strip(),
                        }
        except Exception:
            pass


def _norm_icao(icao):
    """Normalize ICAO for lookup: uppercase, trimmed."""
    if icao is None:
        return ""
    s = str(icao).strip()
    return s.upper() if s else ""


def _enrich_plane(plane):
    """Enrich plane from FAA MASTER + ACFTREF by Mode S (ICAO) hex. Prefer live callsign."""
    _load_faa_data()
    icao = _norm_icao(plane.get("icao"))
    if not icao or icao not in _faa_master:
        return
    master_row = _faa_master[icao]
    reg = (master_row.get("registration") or "").strip()
    operator = (master_row.get("operator") or "").strip()
    mfr_code = (master_row.get("mfr_mdl_code") or "").strip()
    if reg:
        plane["registration"] = reg
    if operator:
        plane["operator"] = operator
    if mfr_code and mfr_code in _faa_acftref:
        ref = _faa_acftref[mfr_code]
        if ref.get("manufacturer"):
            plane["manufacturer"] = ref["manufacturer"]
        if ref.get("model"):
            plane["model"] = ref["model"]
        if ref.get("type"):
            plane["type"] = ref["type"]
    has_live_callsign = (plane.get("flight") or "").strip() != ""
    if has_live_callsign:
        plane["identity_source"] = "live"
    else:
        if reg:
            plane["flight"] = reg
        plane["identity_source"] = "offline"

# dump1090: start if not running, stop on exit; capture exit cause for status
DUMP1090_PORT = 30003  # SBS decoded output (lat/lon); 30002 is raw hex
_dump1090_proc = None
_dump1090_start_time = None
_dump1090_exit_info = None  # {"code": int, "stderr": str, "stdout": str} when process we started has exited


def _port_open(host="127.0.0.1", port=DUMP1090_PORT, timeout=0.5):
    """Return True if something is listening on the given host:port."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def _wait_for_port_and_process(proc, host="127.0.0.1", port=DUMP1090_PORT, timeout_sec=20, poll_interval=0.5):
    """
    Wait until port is open or process exits. Returns True if port became open.
    If process exits first, reads stderr from temp file into _dump1090_exit_info and returns False.
    """
    global _dump1090_proc, _dump1090_exit_info
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if proc is None:
            break
        ret = proc.poll()
        if ret is not None:
            stderr_s = ""
            try:
                path = getattr(proc, "_stderr_path", None)
                if path and os.path.isfile(path):
                    with open(path, "r", errors="replace") as f:
                        stderr_s = f.read().strip()
                    try:
                        os.remove(path)
                    except Exception:
                        pass
            except Exception:
                pass
            _dump1090_exit_info = {"code": ret, "stdout": "", "stderr": stderr_s}
            _dump1090_proc = None
            return False
        if _port_open(host, port):
            return True
        time.sleep(poll_interval)
    return False


def _start_dump1090_if_needed():
    """If nothing is listening on port 30003 (SBS), start dump1090 (must run from dump1090 source dir). Return True if we started it."""
    global _dump1090_proc, _dump1090_exit_info, _dump1090_start_time
    if _port_open():
        return False
    _dump1090_exit_info = None
    dump1090_dir = os.path.join(PROJECT_ROOT, "dump1090")
    dump1090_path = os.path.join(dump1090_dir, "dump1090")
    if not os.path.isfile(dump1090_path):
        return False
    cmd = [dump1090_path, "--net", "--raw"]
    try:
        # Use temp file for stderr so we can read it if process exits without blocking a pipe
        stderr_file = tempfile.NamedTemporaryFile(mode="w+", suffix=".dump1090.stderr", delete=False)
        stderr_path = stderr_file.name
        stderr_file.close()
        _dump1090_proc = subprocess.Popen(
            cmd,
            cwd=dump1090_dir,
            stdout=subprocess.DEVNULL,
            stderr=open(stderr_path, "w"),
        )
        _dump1090_start_time = time.time()
        # Store stderr path for reading on exit (same process reference holds the open file; we re-open to read)
        _dump1090_proc._stderr_path = stderr_path
        print("[Server] Started dump1090:", " ".join(cmd), flush=True)
        print("[Server]   cwd={}  pid={}".format(dump1090_dir, _dump1090_proc.pid), flush=True)
        return True
    except Exception as e:
        _dump1090_proc = None
        _dump1090_exit_info = {"code": -1, "stdout": "", "stderr": str(e)}
        print("[Server] Failed to start dump1090: {}".format(e), flush=True)
        return False


def _stop_dump1090():
    """Terminate dump1090 if we started it; remove stderr temp file."""
    global _dump1090_proc
    if _dump1090_proc is None:
        return
    try:
        path = getattr(_dump1090_proc, "_stderr_path", None)
        _dump1090_proc.terminate()
        _dump1090_proc.wait(timeout=3)
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except Exception:
                pass
    except subprocess.TimeoutExpired:
        try:
            _dump1090_proc.kill()
        except Exception:
            pass
    except Exception:
        try:
            _dump1090_proc.kill()
        except Exception:
            pass
    _dump1090_proc = None


def _safe_filename(name):
    """Allow only alphanumeric, dash, underscore."""
    return re.sub(r"[^\w\-]", "", name).strip() or "unnamed"


def get_adsb_status():
    """
    ADS-B status: process-exited (if we started dump1090 and it died), running_waiting_for_port,
    or delegate to adsb_listener (starting, not_running, connected_no_data, receiving_data, error).
    """
    global _dump1090_proc, _dump1090_exit_info
    # If we have captured exit info from a previous run, surface it
    if _dump1090_exit_info is not None:
        ei = _dump1090_exit_info
        msg = "dump1090 exited with code {}".format(ei.get("code", "?"))
        if ei.get("stderr"):
            msg += ". " + (ei.get("stderr") or "").strip()
        return {"device": "process_exited", "count": 0, "error": msg}
    # If we started dump1090 and it has since exited, capture stderr and surface
    if _dump1090_proc is not None:
        ret = _dump1090_proc.poll()
        if ret is not None:
            stderr_s = ""
            try:
                path = getattr(_dump1090_proc, "_stderr_path", None)
                if path and os.path.isfile(path):
                    with open(path, "r", errors="replace") as f:
                        stderr_s = f.read().strip()
                    try:
                        os.remove(path)
                    except Exception:
                        pass
            except Exception:
                pass
            _dump1090_exit_info = {"code": ret, "stdout": "", "stderr": stderr_s}
            _dump1090_proc = None
            msg = "dump1090 exited with code {}".format(ret)
            if stderr_s:
                msg += ". " + stderr_s
            return {"device": "process_exited", "count": 0, "error": msg}
        # Process still running but port not open yet (within startup window)
        if _dump1090_start_time and not _port_open():
            if (time.time() - _dump1090_start_time) < 30:
                return {"device": "running_waiting_for_port", "count": 0, "error": "dump1090 started; waiting for port {}...".format(DUMP1090_PORT)}
    from adsb_listener import get_status as _get
    out = _get()
    # Count = unique aircraft (ICAOs), not total message count
    out["count"] = len(plane_detections)
    # Clear stale exit info once we're connected (e.g. user started dump1090 manually)
    if out.get("device") in ("connected_no_data", "receiving_data"):
        _dump1090_exit_info = None
    return out


def on_alert(data):
    """Called from Skyhunter when an alert fires; log to terminal and emit to web clients."""
    import time
    data["ts"] = time.time()
    detections.append(data)
    if len(detections) > MAX_DETECTIONS:
        detections.pop(0)
    # Terminal output when something is detected
    label = data.get("label", "Signal")
    freq = data.get("center_mhz")
    width = data.get("width_mhz") or 0
    freq_str = f" @ {freq:.3f} MHz" if freq is not None else ""
    print(f"[DETECT] {label}{freq_str}  ~{width:.1f} MHz", flush=True)
    socketio.emit("alert", data)


def run_skyhunter():
    global live_status
    try:
        import skyhunter
        skyhunter.HAVE_CURSES = False
        skyhunter.run(
            skyhunter_args,
            skyhunter_bands,
            live_status=live_status,
            on_alert=on_alert,
        )
    except Exception as e:
        err_msg = str(e)
        live_status["error"] = err_msg
        live_status["device"] = "error"
        socketio.emit("status", live_status)
        print(f"[ERROR] HackRF/Skyhunter: {err_msg}", flush=True)
        if "libhackrf" in err_msg.lower() or "hackrf" in err_msg.lower():
            print("  → Install: sudo apt install hackrf libhackrf0 libhackrf-dev", flush=True)
            print("  → If using WSL, attach the device: usbipd wsl attach --busid <BUSID>", flush=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/map-tile/<int:z>/<int:x>/<int:y>.png")
def api_map_tile(z, x, y):
    """
    Serve a map tile from static/map-tiles. If missing, fetch from OpenStreetMap, save, then serve.
    Populates the same tree as download_map_tiles.py so offline use works for viewed areas.
    """
    if z < 0 or z > MAP_TILE_MAX_ZOOM:
        return "", 404
    n = 1 << z
    if x < 0 or x >= n or y < 0 or y >= n:
        return "", 404
    rel = os.path.join(str(z), str(x), f"{y}.png")
    path = os.path.join(MAP_TILES_DIR, rel)
    if os.path.isfile(path):
        return send_file(path, mimetype="image/png")
    with _map_tile_write_lock:
        if os.path.isfile(path):
            return send_file(path, mimetype="image/png")
        url = OSM_TILE_URL.format(z=z, x=x, y=y)
        req = urllib.request.Request(url, headers={"User-Agent": MAP_TILE_USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
        except (urllib.error.URLError, OSError):
            return "", 502
        if not data or not data.startswith(b"\x89PNG"):
            return "", 502
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            return "", 500
        return send_file(path, mimetype="image/png")


@app.route("/api/status")
def api_status():
    out = dict(live_status)
    out["rtl_status"] = get_adsb_status()
    return jsonify(out)


@app.route("/api/detections")
def api_detections():
    return jsonify(detections)


@app.route("/api/planes")
def api_planes():
    return jsonify(plane_detections)


@app.route("/api/saves", methods=["GET", "POST"])
def api_saves():
    global detections, plane_detections
    os.makedirs(SAVES_DIR, exist_ok=True)
    if request.method == "GET":
        out = []
        for f in os.listdir(SAVES_DIR):
            if f.endswith(".json"):
                path = os.path.join(SAVES_DIR, f)
                try:
                    mtime = os.path.getmtime(path)
                    out.append({"name": f[:-5], "saved_at": mtime})
                except Exception:
                    pass
        out.sort(key=lambda x: -x["saved_at"])
        return jsonify(out)
    # POST: save current data
    name = (request.get_json() or {}).get("name") or request.form.get("name") or "scan"
    name = _safe_filename(name)
    if not name:
        return jsonify({"error": "invalid name"}), 400
    with data_lock:
        snap = {
            "detections": list(detections),
            "plane_detections": list(plane_detections),
            "saved_at": time.time(),
            "name": name,
        }
    path = os.path.join(SAVES_DIR, name + ".json")
    try:
        with open(path, "w") as f:
            json.dump(snap, f, indent=0)
        return jsonify({"ok": True, "name": name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/saves/load", methods=["POST"])
def api_saves_load():
    global detections, plane_detections
    name = (request.get_json() or {}).get("name") or request.form.get("name")
    if not name:
        return jsonify({"error": "name required"}), 400
    name = _safe_filename(name)
    path = os.path.join(SAVES_DIR, name + ".json")
    if not os.path.isfile(path):
        return jsonify({"error": "save not found"}), 404
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    merge = (request.get_json() or {}).get("merge", True)
    with data_lock:
        if merge:
            detections = (data.get("detections") or []) + detections
            plane_detections = (data.get("plane_detections") or []) + plane_detections
            if len(detections) > MAX_DETECTIONS:
                detections = detections[-MAX_DETECTIONS:]
            if len(plane_detections) > MAX_PLANES:
                plane_detections = plane_detections[-MAX_PLANES:]
        else:
            detections = list(data.get("detections") or [])
            plane_detections = list(data.get("plane_detections") or [])
    socketio.emit("detections_snapshot", detections[-50:])
    socketio.emit("planes_snapshot", plane_detections[-100:])
    return jsonify({"ok": True, "name": name, "merge": merge})


@app.route("/api/saves/delete", methods=["POST"])
def api_saves_delete():
    name = (request.get_json() or {}).get("name") or request.form.get("name")
    if not name:
        return jsonify({"error": "name required"}), 400
    name = _safe_filename(name)
    path = os.path.join(SAVES_DIR, name + ".json")
    if not os.path.isfile(path):
        return jsonify({"error": "save not found"}), 404
    try:
        os.remove(path)
        return jsonify({"ok": True, "name": name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _parse_adsb_plane(line):
    """If line is JSON with lat/lon, return dict for plane_detections else None. Normalized fields for list and popup."""
    try:
        o = json.loads(line)
        if not isinstance(o, dict):
            return None
        lat = o.get("lat")
        lon = o.get("lon")
        if lat is None or lon is None:
            return None
        alt = o.get("altitude")
        if alt is not None and not isinstance(alt, (int, float)):
            try:
                alt = int(alt)
            except (TypeError, ValueError):
                alt = None
        return {
            "lat": float(lat),
            "lon": float(lon),
            "altitude": alt,
            "icao": o.get("hex") or o.get("icao") or "",
            "flight": o.get("flight") or o.get("callsign") or "",
            "groundspeed": o.get("groundspeed") or o.get("speed"),
            "track": o.get("track") or o.get("heading"),
            "ts": time.time(),
        }
    except Exception:
        return None


def _parse_sbs_plane(line):
    """
    Parse dump1090 SBS/BaseStation line (port 30003). CSV: 4=icao, 10=callsign, 11=alt, 12=groundspeed, 13=track, 14=lat, 15=lon.
    Returns plane dict with lat/lon and all available metadata for list and popup.
    """
    if not line.strip().startswith("MSG,"):
        return None
    try:
        parts = line.strip().split(",")
        if len(parts) < 16:
            return None
        icao = (parts[4] or "").strip()
        if not icao:
            return None
        lat_s = (parts[14] or "").strip()
        lon_s = (parts[15] or "").strip()
        if not lat_s or not lon_s:
            return None
        lat = float(lat_s)
        lon = float(lon_s)
        alt_s = (parts[11] or "").strip()
        altitude = int(alt_s) if alt_s.isdigit() else None
        callsign = (parts[10] or "").strip() if len(parts) > 10 else ""
        gs_s = (parts[12] or "").strip() if len(parts) > 12 else ""
        groundspeed = int(gs_s) if gs_s.isdigit() else (float(gs_s) if gs_s else None)
        try:
            track_s = (parts[13] or "").strip() if len(parts) > 13 else ""
            track = float(track_s) if track_s else None
        except ValueError:
            track = None
        return {
            "lat": lat,
            "lon": lon,
            "altitude": altitude,
            "icao": icao,
            "flight": callsign or "",
            "groundspeed": groundspeed,
            "track": track,
            "ts": time.time(),
        }
    except (ValueError, IndexError):
        return None


def _ingest_adsb_lines(lines):
    """Ingest ADS-B lines (dump1090 SBS or POST /api/adsb). Updates adsb_lines, plane_detections by ICAO, emits to clients."""
    global adsb_lines, plane_detections
    if not lines:
        return
    with data_lock:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            adsb_lines.append(line)
            plane = _parse_sbs_plane(line) or _parse_adsb_plane(line)
            if plane:
                icao = plane.get("icao")
                found = next((i for i, p in enumerate(plane_detections) if p.get("icao") == icao), None)
                if found is not None:
                    # Merge so we keep e.g. callsign from earlier message when this one only has position
                    existing = plane_detections[found]
                    merged = dict(existing)
                    for k, v in plane.items():
                        if v is not None and v != "":
                            merged[k] = v
                    plane_detections[found] = merged
                    plane = merged
                else:
                    plane_detections.append(plane)
                    if len(plane_detections) > MAX_PLANES:
                        plane_detections.pop(0)
                _enrich_plane(plane)
                socketio.emit("plane", plane)
                socketio.emit("planes_snapshot", plane_detections[-100:])
        if len(adsb_lines) > MAX_ADSB_LINES:
            adsb_lines = adsb_lines[-MAX_ADSB_LINES:]
    socketio.emit("adsb_update", {"lines": list(adsb_lines)})


@app.route("/api/adsb", methods=["GET", "POST"])
def api_adsb():
    global adsb_lines, plane_detections
    if request.method == "POST":
        data = request.get_data(as_text=True) or request.form.get("data", "")
        lines = [ln.strip() for ln in data.strip().splitlines() if ln.strip()]
        _ingest_adsb_lines(lines)
        return jsonify({"ok": True, "lines": len(adsb_lines), "planes": len(plane_detections)})
    return jsonify({"lines": adsb_lines})


@socketio.on("connect")
def handle_connect():
    """Send current status and snapshots to newly connected client. Detection runs independently of UI."""
    status = dict(live_status)
    status["rtl_status"] = get_adsb_status()
    socketio.emit("status", status)
    socketio.emit("detections_snapshot", detections[-50:])
    socketio.emit("planes_snapshot", plane_detections[-100:])
    socketio.emit("adsb_update", {"lines": list(adsb_lines)})


def main():
    global skyhunter_args, skyhunter_bands, skyhunter_thread, skyhunter_started, live_status

    ap = argparse.ArgumentParser(description="Skyhunter V2 Web UI")
    ap.add_argument("--host", default="0.0.0.0", help="Bind host")
    ap.add_argument("--port", type=int, default=5050, help="Bind port")
    ap.add_argument("--device-index", type=int, default=0)
    ap.add_argument("--amp", action="store_true")
    ap.add_argument("--lna", type=int, default=32)
    ap.add_argument("--vga", type=int, default=30)
    ap.add_argument("--sample-rate", type=float, default=20e6)
    ap.add_argument("--frame-ms", type=int, default=100)
    ap.add_argument("--nfft", type=int, default=4096)
    ap.add_argument("--overlap", type=float, default=0.5)
    ap.add_argument("--avg-frames", type=int, default=2)
    ap.add_argument("--delta-db", type=float, default=6.0)
    ap.add_argument("--mean-excess-db", type=float, default=8.0)
    ap.add_argument("--nbins-baseline", type=int, default=5)
    ap.add_argument("--persist-hits", type=int, default=2)
    ap.add_argument("--persist-window", type=int, default=5)
    ap.add_argument("--minwidth-mhz", type=float, default=10.0)
    ap.add_argument("--maxwidth-mhz", type=float, default=40.0)
    ap.add_argument("--floor-alert-rise-db", type=float, default=10.0)
    ap.add_argument("--floor-persist-hits", type=int, default=2)
    ap.add_argument("--no-floor-alert", dest="floor_alert_enable", action="store_false")
    ap.add_argument("--dwell", type=float, default=0.4)
    ap.add_argument("--center-overlap", type=float, default=0.75)
    ap.add_argument("--auto", choices=["fpv", "dji", "all"], default="all")
    ap.set_defaults(floor_alert_enable=True)
    args = ap.parse_args()

    if args.auto == "fpv":
        args.mode_name, bands = "FPV 5.8", [FPV_58_WIDE_MHZ]
    elif args.auto == "dji":
        args.mode_name, bands = "DJI 2.4+5.8", DJI_BANDS_MHZ
    else:
        args.mode_name, bands = "All", [FPV_58_WIDE_MHZ] + DJI_BANDS_MHZ

    skyhunter_args = args
    skyhunter_bands = [(int(a), int(b)) for a, b in bands if int(b) > int(a)]
    if not skyhunter_bands:
        print("No valid bands.")
        sys.exit(1)

    live_status["mode"] = args.mode_name
    live_status["bands"] = skyhunter_bands

    # Start HackRF detector at server startup so detections log continuously regardless of UI/tab
    skyhunter_started = True
    skyhunter_thread = threading.Thread(target=run_skyhunter, daemon=True)
    skyhunter_thread.start()
    print("[Server] HackRF detector started (continuous detection).", flush=True)

    # Start dump1090 if port 30003 (SBS) is not open; wait for port or capture exit cause
    atexit.register(_stop_dump1090)
    if _start_dump1090_if_needed():
        if _wait_for_port_and_process(_dump1090_proc, timeout_sec=25):
            print("[Server] dump1090 port {} open.".format(DUMP1090_PORT), flush=True)
        else:
            if _dump1090_exit_info:
                ei = _dump1090_exit_info
                print("[Server] dump1090 exited with code {}.".format(ei.get("code")), flush=True)
                if ei.get("stderr"):
                    print("[Server] dump1090 stderr:", ei.get("stderr"), flush=True)
                if ei.get("stdout"):
                    print("[Server] dump1090 stdout:", ei.get("stdout"), flush=True)
            else:
                print("[Server] dump1090 port {} not ready in time; listener will retry.".format(DUMP1090_PORT), flush=True)
    elif not _port_open():
        print("[Server] dump1090 not running (port {} closed). Start manually from dump1090 dir: ./dump1090 --net --raw".format(DUMP1090_PORT), flush=True)

    from adsb_listener import start as start_adsb_listener
    start_adsb_listener(lambda line: _ingest_adsb_lines([line]))
    print("[Server] ADS-B listener started (localhost:{}).".format(DUMP1090_PORT), flush=True)

    print("---")
    print(f"Server listening on http://{args.host}:{args.port}")
    print("Detections will appear below. Ctrl+C to stop.")
    print("---", flush=True)

    def _shutdown():
        print("\nShutting down...", flush=True)
        _stop_dump1090()

    def _on_sigint(signum, frame):
        _shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_sigint)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_sigint)

    try:
        socketio.run(app, host=args.host, port=args.port, allow_unsafe_werkzeug=True)
    finally:
        _stop_dump1090()


if __name__ == "__main__":
    main()

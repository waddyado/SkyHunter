"""
ADS-B listener for Skyhunter V2.
Connects to dump1090 SBS/BaseStation stream (localhost:30003) for decoded
aircraft with lat/lon. Calls the provided callback for each SBS line. Reconnects on disconnect.
Status is dump1090-based with distinct states: starting, not_running, port_closed,
connected_no_data, receiving_data, error.
"""
import socket
import threading
import time

DUMP1090_HOST = "127.0.0.1"
DUMP1090_SBS_PORT = 30003  # SBS format: decoded lat/lon, altitude, icao, callsign
RECONNECT_INTERVAL = 5
STARTING_WINDOW_SEC = 3  # show "starting" for this long after listener start

_lock = threading.Lock()
_connected = False
_received_data = False
_lines_received = 0
_last_error = ""
_thread = None
_start_time = None


def _run(callback):
    global _connected, _received_data, _lines_received, _last_error
    while True:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10.0)
            sock.connect((DUMP1090_HOST, DUMP1090_SBS_PORT))
            with _lock:
                _connected = True
                _received_data = False
                _last_error = ""
            buf = sock.makefile(mode="r", encoding="utf-8", errors="replace")
            while True:
                line = buf.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                # SBS format: MSG,type,...
                if line.startswith("MSG,"):
                    with _lock:
                        _lines_received += 1
                        _received_data = True
                    try:
                        callback(line)
                    except Exception:
                        pass
        except Exception as e:
            with _lock:
                _connected = False
                _last_error = str(e)
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        time.sleep(RECONNECT_INTERVAL)


def start(on_line_callback):
    """Start the listener in a daemon thread. Call once at server startup."""
    global _thread, _start_time
    if _thread is not None:
        return
    _start_time = time.time()
    _thread = threading.Thread(target=_run, args=(on_line_callback,), daemon=True)
    _thread.start()


def get_status():
    """
    Return status for the ADS-B panel (dump1090 stream only).
    device: starting | not_running | port_closed | connected_no_data | receiving_data | error
    Error text reflects actual condition (no pkg_resources/setuptools).
    """
    with _lock:
        connected = _connected
        received = _received_data
        count = _lines_received
        raw_err = _last_error
    start_time = _start_time or 0
    now = time.time()

    # User-facing error message (no pkg_resources / setuptools)
    err = raw_err or ""
    if "connection refused" in err.lower() or "errno 111" in err or "111" in err:
        err = "dump1090 not running or port {} not open. Start: ./dump1090/dump1090 --net --raw".format(DUMP1090_SBS_PORT)
    elif "pkg_resources" in err or "setuptools" in err or "ModuleNotFoundError" in err:
        err = "Cannot connect to dump1090 on localhost:{}".format(DUMP1090_SBS_PORT)

    if connected:
        if received:
            return {"device": "receiving_data", "count": count, "error": ""}
        return {"device": "connected_no_data", "count": count, "error": "Connected; waiting for ADS-B frames."}

    # Not connected: pick state from raw error and time since start
    if start_time and (now - start_time) < STARTING_WINDOW_SEC:
        return {"device": "starting", "count": 0, "error": "Connecting to dump1090..."}
    if "connection refused" in (raw_err or "").lower() or "111" in (raw_err or ""):
        return {"device": "not_running", "count": 0, "error": err or "Port {} closed.".format(DUMP1090_SBS_PORT)}
    if raw_err and "timed out" in raw_err.lower():
        return {"device": "port_closed", "count": 0, "error": "Port {} not responding.".format(DUMP1090_SBS_PORT)}
    if raw_err:
        return {"device": "error", "count": 0, "error": err or raw_err}
    return {"device": "not_running", "count": 0, "error": err or "Cannot connect to localhost:{}.".format(DUMP1090_SBS_PORT)}

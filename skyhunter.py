#!/usr/bin/env python3
# SKYHUNTER — DRONE RF DETECTOR (TUI, libhackrf.py wrapper on Ubuntu/WSL/Windows via WSL)
# - Streams IQ via your local libhackrf.py (ctypes wrapper) — READING PATH UNCHANGED.
# - Welch PSD + robust baseline to detect DJI (10–40 MHz plateau) and FPV analog (4–12 MHz).
# - Floor-based alert DEFAULT ON at +10 dB over session minimum, ~7s full-band scan by default.
# - FIX: Band-aware alerts now classify by the SIGNAL ITSELF (width + frequency), not by the band being swept.
#   • Analog-width (≤12 MHz) around peak → "FPV Detected" (when in 5.65–5.92 GHz)
#   • Wide plateau (≥10 MHz) in DJI bands (2.4 or 5.8) → "DJI Detected"

import argparse, sys, time
from collections import deque, defaultdict

# -------- Optional curses UI --------
try:
    import curses
    HAVE_CURSES = True
except Exception:
    HAVE_CURSES = False

import numpy as np
from scipy.signal import welch

# -------- Your local wrapper (must be in same folder) --------
from libhackrf import HackRF

TITLE_ASCII = r"""
     _______. __  ___ ____    ____     __    __   __    __  .__   __. .___________. _______ .______      
    /       ||  |/  / \   \  /   /    |  |  |  | |  |  |  | |  \ |  | |           ||   ____||   _  \     
   |   (----`|  '  /   \   \/   /     |  |__|  | |  |  |  | |   \|  | `---|  |----`|  |__   |  |_)  |    
    \   \    |    <     \_    _/      |   __   | |  |  |  | |  . `  |     |  |     |   __|  |      /     
.----)   |   |  .  \      |  |        |  |  |  | |  `--'  | |  |\   |     |  |     |  |____ |  |\  \----.
|_______/    |__|\__\     |__|        |__|  |__|  \______/  |__| \__|     |__|     |_______|| _| `._____|
"""

# -------------------- Frequency bands (MHz) --------------------
FPV_58_WIDE_MHZ = (5650, 5920)
DJI_24_MHZ      = (2400, 2483)
DJI_58_MHZ      = (5725, 5850)
DJI_BANDS_MHZ   = [DJI_24_MHZ, DJI_58_MHZ]

# ============================ Helpers ============================

def in_band(freq_mhz: float, band_mhz: tuple[int,int]) -> bool:
    return (band_mhz[0] <= freq_mhz <= band_mhz[1])

def _rolling_percentile(x: np.ndarray, k: int, q: float) -> np.ndarray:
    """Rolling percentile baseline (q in [0,100]), window = ±k bins."""
    n = x.size
    out = np.empty_like(x)
    for i in range(n):
        lo = max(0, i-k); hi = min(n, i+k+1)
        out[i] = np.percentile(x[lo:hi], q)
    return out

def _smooth_ma(x: np.ndarray, taps: int = 3) -> np.ndarray:
    """Tiny moving-average smoother (odd taps: 3 or 5)."""
    if taps <= 1: return x
    k = np.ones(taps, dtype=np.float32)/taps
    return np.convolve(x, k, mode="same")

def estimate_region_at_peak(freqs_hz: np.ndarray,
                            psd_db: np.ndarray,
                            nbins_baseline: int,
                            hot_delta_db: float):
    """
    Around the global-peak bin, estimate the contiguous 'hot' region width where
    (psd - baseline) >= hot_delta_db. Returns (pk_freq_mhz, peak_db, width_mhz).
    If estimation fails, width_mhz = 0.
    """
    if freqs_hz is None or psd_db is None or psd_db.size < 3:
        return None, None, 0.0
    psd_db_s = _smooth_ma(psd_db, taps=3)
    base = _rolling_percentile(psd_db_s, nbins_baseline, q=20.0)
    excess = psd_db_s - base
    pk = int(np.argmax(psd_db_s))
    thr = hot_delta_db

    # Expand left/right while excess >= thr
    L = pk
    while L - 1 >= 0 and excess[L-1] >= thr:
        L -= 1
    R = pk
    N = excess.size
    while R + 1 < N and excess[R+1] >= thr:
        R += 1

    low_hz  = freqs_hz[L]
    high_hz = freqs_hz[R]
    width_mhz = max(0.0, float(high_hz - low_hz) / 1e6)
    pk_freq_mhz = float(freqs_hz[pk]/1e6)
    peak_db = float(psd_db_s[pk])
    return pk_freq_mhz, peak_db, width_mhz

def classify_signal(pk_freq_mhz: float, est_width_mhz: float) -> str:
    """
    Classify by *signal* shape + location, not current sweep band:
      - Analog FPV: width ≤ 12 MHz AND in FPV 5.8 window → "FPV Detected"
      - DJI OFDM:   width ≥ 10 MHz AND in 2.4/5.8 DJI windows → "DJI Detected"
      - Else: "Signal Detected"
    """
    if pk_freq_mhz is None:
        return "Signal Detected"
    if est_width_mhz <= 10.0 and in_band(pk_freq_mhz, FPV_58_WIDE_MHZ):
        return "FPV Detected"
    if est_width_mhz >= 10.0 and (in_band(pk_freq_mhz, DJI_24_MHZ) or in_band(pk_freq_mhz, DJI_58_MHZ)):
        return "DJI Detected"
    return "Signal Detected"

# ============================ Detector ============================

class MultiBandDetector:
    """
    Robust wide (DJI) + narrower (FPV analog) detection on averaged PSD.
    Uses baseline/excess and region grouping; results further labeled by width+freq.
    """
    def __init__(self,
                 nbins_baseline=5,
                 hot_delta_db=6.0,
                 dji_mean_ex_db=8.0,
                 fpv_mean_ex_db=6.0,
                 fpv_peak_ex_db=12.0,
                 persist_hits=2,
                 persist_window=5):
        self.nbins_baseline = int(nbins_baseline)
        self.hot_delta_db = float(hot_delta_db)
        self.dji_mean_ex_db = float(dji_mean_ex_db)
        self.fpv_mean_ex_db = float(fpv_mean_ex_db)
        self.fpv_peak_ex_db = float(fpv_peak_ex_db)
        self.persist_hits = int(persist_hits)
        self.persist_window = int(persist_window)
        self.history = defaultdict(lambda: deque(maxlen=self.persist_window))

    @staticmethod
    def _contiguous(mask: np.ndarray):
        regions, s = [], None
        for i, h in enumerate(mask):
            if h and s is None: s = i
            elif (not h) and s is not None: regions.append((s, i)); s = None
        if s is not None: regions.append((s, len(mask)))
        return regions

    @staticmethod
    def _overlap_frac(a_low, a_high, b_low, b_high):
        lo = max(a_low, b_low); hi = min(a_high, b_high)
        if hi <= lo: return 0.0
        sl = min(a_high - a_low, b_high - b_low)
        return (hi - lo)/sl if sl>0 else 0.0

    def process_psd(self, key, freqs_hz: np.ndarray, psd_db: np.ndarray):
        psd_db_s = _smooth_ma(psd_db, taps=3)
        base = _rolling_percentile(psd_db_s, self.nbins_baseline, q=20.0)
        excess = psd_db_s - base

        hot = excess >= self.hot_delta_db
        regions = []
        for a, b in self._contiguous(hot):
            low_hz  = freqs_hz[a]
            high_hz = freqs_hz[b-1]
            width_mhz = (high_hz - low_hz) / 1e6
            mean_ex = float(np.mean(excess[a:b]))
            peak_ex = float(np.max(excess[a:b]))
            cf_hz = 0.5*(low_hz + high_hz)
            regions.append((cf_hz/1e6, width_mhz, mean_ex, peak_ex, (low_hz/1e6, high_hz/1e6)))

        # Acceptance rules (width + excess)
        accepted = []
        for cf_mhz, w_mhz, mex, pex, (lo, hi) in regions:
            # DJI-style plateau
            if (10.0 <= w_mhz <= 40.0) and (mex >= self.dji_mean_ex_db):
                accepted.append((cf_mhz, w_mhz, mex, pex, lo, hi))
            # FPV analog
            elif (4.0 <= w_mhz <= 12.0) and ((pex >= self.fpv_peak_ex_db) or (mex >= self.fpv_mean_ex_db)):
                accepted.append((cf_mhz, w_mhz, mex, pex, lo, hi))

        # Persistence (overlap ≥50% in ≥persist_hits of last persist_window)
        alerts = []
        if accepted:
            hist = self.history[key]
            for cf_mhz, w_mhz, mex, pex, lo, hi in accepted:
                hits = 1
                for past in hist:
                    for (pl, ph) in past:
                        if self._overlap_frac(lo, hi, pl, ph) >= 0.5:
                            hits += 1; break
                if hits >= self.persist_hits:
                    alerts.append({
                        "center_mhz": cf_mhz,
                        "width_mhz": w_mhz,
                        "excess_db_mean": mex,
                        "excess_db_peak": pex,
                    })
            hist.append([(lo, hi) for (_cf,_w,_mex,_pex,lo,hi) in accepted])
        else:
            self.history[key].append([])

        return alerts

# =============================== UI ===============================

class UI:
    def __init__(self, stdscr, args, bands):
        self.stdscr = stdscr
        self.args = args
        self.bands = bands
        self.current_band = bands[0]
        self.current_center_mhz = None
        self.last_floor = None
        self.last_peak  = None
        self.last_slice = None
        self.min_floor_db_seen = None
        self.alerts = deque(maxlen=30)
        self.scan_pos = 0
        if HAVE_CURSES:
            curses.curs_set(0)
            stdscr.nodelay(True)
            curses.start_color(); curses.use_default_colors()
            self._layout()

    def _layout(self):
        self.stdscr.erase()
        maxy, maxx = self.stdscr.getmaxyx()
        y = 0
        h = min(7, maxy); self.win_header = curses.newwin(h, maxx, y, 0); y += h
        self.win_status = curses.newwin(7, maxx, y, 0); y += 7
        self.win_bar    = curses.newwin(2, maxx, y, 0); y += 2
        self.win_slice  = curses.newwin(2, maxx, y, 0); y += 2
        h_alerts = max(3, (maxy - y - 1))
        self.win_alerts = curses.newwin(h_alerts, maxx, y, 0); y += h_alerts
        self.win_footer = curses.newwin(1, maxx, y-1, 0)

    def _clrline(self, win, row, text):
        maxy, maxx = win.getmaxyx()
        win.move(row, 0); win.clrtoeol(); win.addstr(row, 0, text[:maxx-1])

    def draw(self):
        if not HAVE_CURSES:
            min_floor_txt = f"{self.min_floor_db_seen:5.1f} dB" if self.min_floor_db_seen is not None else "n/a"
            sys.stdout.write(
                f"\r{time.strftime('%H:%M:%S')}  Band {self.current_band[0]}-{self.current_band[1]} MHz  "
                f"Center {self.current_center_mhz or 0:.3f}  "
                f"Floor {self.last_floor or 0:5.1f} dB  Peak {self.last_peak or 0:5.1f} dB  "
                f"MinFloor {min_floor_txt}    "
            ); sys.stdout.flush(); return

        maxy, maxx = self.stdscr.getmaxyx()
        self.win_header.erase()
        lines = (TITLE_ASCII.strip("\n") + "\nSKYHUNTER — DRONE RF DETECTOR\n" + "-"*min(maxx, 90)).splitlines()
        for i, s in enumerate(lines[:self.win_header.getmaxyx()[0]]):
            self._clrline(self.win_header, i, s)
        self.win_header.noutrefresh()

        self.win_status.erase()
        self._clrline(self.win_status, 0, f"Mode: {self.args.mode_name}")
        self._clrline(self.win_status, 1, "Bands (MHz): " + ", ".join(f"{a}-{b}" for a,b in self.bands))
        self._clrline(self.win_status, 2, f"Gains: LNA={self.args.lna} dB  VGA={self.args.vga} dB  SR={self.args.sample_rate/1e6:.1f} MS/s")
        dtxt = (f"ΔdB≥{self.args.delta_db}  mean_ex≥{self.args.mean_excess_db}  "
                f"width {self.args.minwidth_mhz}-{self.args.maxwidth_mhz} MHz  "
                f"persist {self.args.persist_hits}/{self.args.persist_window}  "
                f"avg {self.args.avg_frames}x")
        self._clrline(self.win_status, 3, dtxt)
        rule = f"floor alert: +{self.args.floor_alert_rise_db:.1f} dB over min"
        self._clrline(self.win_status, 4, rule + (" (ENABLED)" if self.args.floor_alert_enable else " (disabled)"))
        if self.last_floor is None:
            self._clrline(self.win_status, 5, "Live: waiting for data…")
        else:
            minf = f"{self.min_floor_db_seen:5.1f} dB" if self.min_floor_db_seen is not None else "n/a"
            self._clrline(self.win_status, 5, f"Live: Floor {self.last_floor:5.1f} dB   Peak {self.last_peak:5.1f} dB   MinFloor {minf}")
        if self.current_center_mhz and self.last_slice:
            self._clrline(self.win_status, 6, f"Center: {self.current_center_mhz:.3f} MHz   Slice: {self.last_slice[0]:.3f}..{self.last_slice[1]:.3f} MHz")
        self.win_status.noutrefresh()

        self.win_bar.erase()
        bar_w = maxx - 10; bar_w = max(10, bar_w)
        pos = self.scan_pos % bar_w
        bar = ["-"] * bar_w; bar[pos] = "#"
        self._clrline(self.win_bar, 0, "Scan: [" + "".join(bar) + "]")
        bmin, bmax = self.current_band
        self._clrline(self.win_bar, 1, f"Sweeping band: {bmin} .. {bmax} MHz")
        self.win_bar.noutrefresh()

        self.win_slice.erase()
        if self.last_slice:
            self._clrline(self.win_slice, 0, f"Slice: {self.last_slice[0]:.3f} .. {self.last_slice[1]:.3f} MHz")
            self._clrline(self.win_slice, 1, f"(center {self.current_center_mhz:.3f} MHz)")
        else:
            self._clrline(self.win_slice, 0, "Slice: (n/a)")
            self._clrline(self.win_slice, 1, "")
        self.win_slice.noutrefresh()

        self.win_alerts.erase()
        self._clrline(self.win_alerts, 0, "Recent Events:")
        row = 1
        for ts, txt in list(self.alerts)[-(self.win_alerts.getmaxyx()[0]-1):]:
            tstr = time.strftime("%H:%M:%S", time.localtime(ts))
            if row >= self.win_alerts.getmaxyx()[0]: break
            self._clrline(self.win_alerts, row, f"{tstr}  {txt}")
            row += 1
        self.win_alerts.noutrefresh()

        self.win_footer.erase()
        self._clrline(self.win_footer, 0, "Ctrl+C to quit")
        self.win_footer.noutrefresh()
        curses.doupdate()

    def push_event(self, txt):
        self.alerts.append((time.time(), txt))

# ========================= HackRF streamer (UNCHANGED) =========================

class RFStreamer:
    """
    Streams IQ via your libhackrf.py wrapper.
    Uses read_samples(N) to pull complex IQ. (Do not modify this path.)
    """
    def __init__(self, sample_rate, lna_db, vga_db, device_index=0, enable_amp=False):
        self.sr = int(sample_rate)
        self.dev = HackRF(device_index=device_index)
        self.dev.sample_rate = float(self.sr)
        if enable_amp:
            try: self.dev.enable_amp()
            except Exception: pass
        else:
            try: self.dev.disable_amp()
            except Exception: pass
        self.dev.set_lna_gain(int(lna_db))
        self.dev.set_vga_gain(int(vga_db))

    def tune(self, center_hz: int):
        self.dev.center_freq = int(center_hz)

    def _to_complex64(self, iq):
        # NumPy 2.0: np.array(..., copy=False) may raise. Use asarray to allow a copy if needed.
        try:
            return np.asarray(iq, dtype=np.complex64)
        except TypeError:
            return np.asarray(iq, dtype=np.complex64)

    def capture_psd(self, center_hz, frame_ms=100, nfft=4096, overlap=0.5):
        self.tune(center_hz)
        n_samps = max(4096, int(self.sr * (frame_ms/1000.0)))
        iq = self.dev.read_samples(n_samps)
        if iq is None:
            return None, None, None

        sig = self._to_complex64(iq)
        if sig.size < nfft:
            return None, None, None

        freqs, pxx = welch(sig, fs=self.sr, nperseg=nfft,
                           noverlap=int(nfft*overlap), return_onesided=False,
                           detrend=False, scaling='density', window='hann')
        pxx = np.fft.fftshift(pxx); freqs = np.fft.fftshift(freqs)
        freqs_hz = freqs + center_hz
        psd_db = 10.0*np.log10(pxx + 1e-15)
        return freqs_hz, psd_db, (center_hz - self.sr//2, center_hz + self.sr//2)

# ============================ Sweep logic ============================

def centers_for_band(band_mhz, sample_rate_hz, step_overlap=0.75):
    low_hz = int(band_mhz[0]*1e6); high_hz = int(band_mhz[1]*1e6)
    span = int(sample_rate_hz)
    if span <= 0 or (high_hz - low_hz) <= 0: return []
    if span >= (high_hz - low_hz): return [ (low_hz + high_hz)//2 ]
    step = max(1, int(span * step_overlap))
    starts = list(range(low_hz, high_hz - span + 1, step))
    centers = [s + span//2 for s in starts]
    if centers and (centers[-1] + span//2) < high_hz:
        centers.append(high_hz - span//2)
    return centers

def choose_mode_cli():
    print(TITLE_ASCII)
    print("Choose a sweep mode:")
    print("  [1] FPV 5.8 GHz (common analog)")
    print("  [2] DJI (2.4 + 5.8)")
    print("  [3] All")
    print("  [4] Custom (MHz like 5738:5758,5645:5900)")
    print("  [q] Quit\n")
    sel = input("Selection: ").strip().lower()
    if sel == "1":  return "FPV 5.8", [FPV_58_WIDE_MHZ]
    if sel == "2":  return "DJI 2.4+5.8", DJI_BANDS_MHZ
    if sel == "3":  return "All", [FPV_58_WIDE_MHZ] + DJI_BANDS_MHZ
    if sel == "4":
        txt = input("Enter ranges (MHz), comma-separated: ").strip()
        bands=[]
        for chunk in txt.split(","):
            if ":" not in chunk: continue
            a,b = chunk.split(":")
            try:
                a=int(float(a)); b=int(float(b))
                if a<b: bands.append((a,b))
            except: pass
        if not bands:
            print("No valid ranges."); sys.exit(1)
        return "Custom", bands
    sys.exit(0)

# =============================== Main ===============================

def run(args, bands):
    if HAVE_CURSES:
        stdscr = curses.initscr()
        curses.noecho(); curses.cbreak(); stdscr.nodelay(True)
        ui = UI(stdscr, args, bands)
    else:
        ui = UI(None, args, bands)

    det = MultiBandDetector(
        nbins_baseline=args.nbins_baseline,
        hot_delta_db=args.delta_db,
        dji_mean_ex_db=args.mean_excess_db,
        fpv_mean_ex_db=max(6.0, args.mean_excess_db - 2.0),
        fpv_peak_ex_db=12.0,
        persist_hits=args.persist_hits,
        persist_window=args.persist_window,
    )

    rf = RFStreamer(sample_rate=args.sample_rate, lna_db=args.lna, vga_db=args.vga,
                    device_index=args.device_index, enable_amp=args.amp)

    min_floor_db_seen = None
    floor_hits_window = deque(maxlen=5)

    try:
        dwell = args.dwell
        avg_frames = args.avg_frames
        nfft = args.nfft
        overlap = args.overlap

        band_centers = []
        for b in bands:
            cs = centers_for_band(b, args.sample_rate, step_overlap=args.center_overlap)
            if not cs: cs = [ int(((b[0]+b[1])/2)*1e6) ]
            band_centers.append(cs)

        band_idx = 0
        center_idx = 0
        psd_avg_buf = deque(maxlen=avg_frames)

        while True:
            band = bands[band_idx % len(bands)]
            centers = band_centers[band_idx % len(bands)]
            center = centers[center_idx % len(centers)]
            ui.current_band = band
            ui.current_center_mhz = center/1e6

            t0 = time.time()
            while (time.time() - t0) < dwell:
                out = rf.capture_psd(center, frame_ms=args.frame_ms, nfft=nfft, overlap=overlap)
                if out is None:
                    ui.draw(); continue
                freqs_hz, psd_db, sp = out
                if freqs_hz is None:
                    ui.draw(); continue
                slice_lo, slice_hi = sp

                cur_floor = float(np.median(psd_db))
                cur_peak  = float(np.max(psd_db))
                ui.last_slice = (slice_lo/1e6, slice_hi/1e6)
                ui.last_floor = cur_floor
                ui.last_peak  = cur_peak
                ui.scan_pos  += 1

                if min_floor_db_seen is None or cur_floor < min_floor_db_seen:
                    min_floor_db_seen = cur_floor
                ui.min_floor_db_seen = min_floor_db_seen

                # ---------- PSD-based (plateau/analog) detector ----------
                psd_avg_buf.append(psd_db)
                if len(psd_avg_buf) >= avg_frames:
                    psd_mean = np.mean(psd_avg_buf, axis=0)
                    key = (tuple(band), center)
                    for a in det.process_psd(key, freqs_hz, psd_mean):
                        cf = a["center_mhz"]; w = a["width_mhz"]
                        mex = a["excess_db_mean"]; pex = a["excess_db_peak"]
                        label = classify_signal(cf, w)
                        ui.push_event(f"[ALERT] {label} @ {cf:.3f} MHz  ~{w:.1f} MHz  (mean +{mex:.1f} dB, peak +{pex:.1f} dB)")

                # ---------- Floor-based alert (default ON, +10 dB) ----------
                if args.floor_alert_enable and (min_floor_db_seen is not None):
                    if cur_floor >= (min_floor_db_seen + args.floor_alert_rise_db):
                        floor_hits_window.append(1)
                    else:
                        floor_hits_window.append(0)

                    if sum(floor_hits_window) >= args.floor_persist_hits:
                        # Estimate width around peak for proper classification
                        pk_freq_mhz, pk_db, est_w = estimate_region_at_peak(
                            freqs_hz, psd_db,
                            nbins_baseline=args.nbins_baseline,
                            hot_delta_db=args.delta_db
                        )
                        label = classify_signal(pk_freq_mhz, est_w)
                        if pk_freq_mhz is None:
                            # Fallback: just print floor alert if estimation fails
                            ui.push_event(f"[ALERT] {label}: floor {cur_floor:.1f} dB (+{cur_floor - min_floor_db_seen:.1f} dB)")
                        else:
                            ui.push_event(f"[ALERT] {label} @ {pk_freq_mhz:.3f} MHz  Peak {pk_db:.1f} dB  ~{est_w:.1f} MHz")
                        floor_hits_window.clear()

                ui.draw()

                if HAVE_CURSES:
                    try:
                        ch = ui.stdscr.getch()
                        if ch == 3:
                            raise KeyboardInterrupt
                    except curses.error:
                        pass

            center_idx += 1
            if (center_idx % len(centers)) == 0:
                band_idx += 1
                psd_avg_buf.clear()

    except KeyboardInterrupt:
        pass
    finally:
        try: rf.dev.close()
        except Exception: pass
        if HAVE_CURSES:
            curses.nocbreak(); ui.stdscr.nodelay(False); curses.echo(); curses.endwin()

def main():
    ap = argparse.ArgumentParser(description="SKYHUNTER TUI (libhackrf.py, Ubuntu/WSL)")
    ap.add_argument("--device-index", type=int, default=0, help="HackRF device index (default 0)")
    ap.add_argument("--amp", action="store_true", help="Enable 14 dB RF amp (off by default)")

    # Gains
    ap.add_argument("--lna", type=int, default=32, help="LNA gain (0..40 step 8)")
    ap.add_argument("--vga", type=int, default=30, help="VGA gain (0..62 step 2)")

    # Streaming & PSD (faster frames)
    ap.add_argument("--sample-rate", type=float, default=20e6, help="Samples/sec (Hz)")
    ap.add_argument("--frame-ms", type=int, default=100, help="Capture duration per PSD frame (ms)")
    ap.add_argument("--nfft", type=int, default=4096)
    ap.add_argument("--overlap", type=float, default=0.5)
    ap.add_argument("--avg-frames", type=int, default=2, help="Average N PSD frames before detect")

    # Detection thresholds (plateau detector)
    ap.add_argument("--delta-db", type=float, default=6.0, help="Hot-bin threshold over baseline")
    ap.add_argument("--mean-excess-db", type=float, default=8.0, help="DJI mean excess gate")
    ap.add_argument("--nbins-baseline", type=int, default=5)
    ap.add_argument("--persist-hits", type=int, default=2)
    ap.add_argument("--persist-window", type=int, default=5)

    # Width window (status display)
    ap.add_argument("--minwidth-mhz", type=float, default=10.0)
    ap.add_argument("--maxwidth-mhz", type=float, default=40.0)

    # FLOOR ALERT: default ON at +10 dB; use --no-floor-alert to disable
    ap.add_argument("--floor-alert-rise-db", type=float, default=10.0,
                    help="Trigger if live floor rises by >= this many dB over minimum (default 10)")
    ap.add_argument("--floor-persist-hits", type=int, default=2,
                    help="Require this many hits in last 5 checks before alerting")
    ap.add_argument("--no-floor-alert", dest="floor_alert_enable", action="store_false",
                    help="Disable the simple floor-based alert (enabled by default)")
    ap.set_defaults(floor_alert_enable=True)

    # Faster sweep defaults (~7s per band with 20 MS/s, overlap 0.75, dwell 0.4s)
    ap.add_argument("--dwell", type=float, default=0.4, help="Seconds per center before stepping")
    ap.add_argument("--center-overlap", type=float, default=0.75, help="Center step = span*overlap (0.6–0.9)")

    # Modes
    ap.add_argument("--auto", choices=["fpv","dji","all"])
    args = ap.parse_args()

    if args.auto == "fpv":
        args.mode_name, bands = "FPV 5.8", [FPV_58_WIDE_MHZ]
    elif args.auto == "dji":
        args.mode_name, bands = "DJI 2.4+5.8", DJI_BANDS_MHZ
    elif args.auto == "all":
        args.mode_name, bands = "All", [FPV_58_WIDE_MHZ] + DJI_BANDS_MHZ
    else:
        args.mode_name, bands = choose_mode_cli()

    fb = []
    for a,b in bands:
        a=int(a); b=int(b)
        if b>a: fb.append((a,b))
    if not fb:
        print("No valid bands."); sys.exit(1)

    run(args, fb)

if __name__ == "__main__":
    main()

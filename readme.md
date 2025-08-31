# SKYHUNTER — Drone RF Detector (HackRF, Python TUI)

A fast, live drone RF detector for DJI (OFDM) and analog FPV signals using HackRF.  
It streams IQ via a lightweight `libhackrf.py` wrapper, computes PSD (Welch), and raises alerts in a terminal UI.

- **DJI detection:** 10–40 MHz “plateau” with persistence filtering  
- **FPV detection:** 4–12 MHz analog spike (plus a simple floor-rise rule)  
- **Fast sweep:** ~7 s per 5.8 GHz band by default (20 MS/s, overlap 0.75, dwell 0.4 s)  
- **TUI:** curses interface (or a simple status line if curses isn’t available)  

---

## Contents

- [Prerequisites](#prerequisites)
  - [Hardware](#hardware)
  - [OS & drivers](#os--drivers)
  - [Python](#python)
- [Install](#install)
  - [Ubuntu / Debian (native Linux)](#ubuntu--debian-native-linux)
  - [Windows using WSL 2 (recommended for Windows)](#windows-using-wsl-2-recommended-for-windows)
  - [Python env & packages](#python-env--packages)
  - [Verify HackRF](#verify-hackrf)
- [Run SKYHUNTER](#run-skyhunter)
  - [Quick starts](#quick-starts)
  - [All CLI options](#all-cli-options)
- [How it works](#how-it-works)
- [Troubleshooting](#troubleshooting)
- [Tips](#tips)
- [Acknowledgements](#acknowledgements)

---

## Prerequisites

### Hardware
- HackRF One (or compatible) with USB cable.  
- An antenna suitable for 2.4 GHz and/or 5.8 GHz.  

### OS & drivers
- Linux (Ubuntu 22.04+ recommended) **OR** Windows 10/11 with WSL 2.  
- HackRF tools & `libhackrf` installed on the environment where Python runs.  

### Python
- Python 3.10+ recommended.  
- Packages: `numpy`, `scipy`, and on Windows terminals `windows-curses`.  

---

## Install

### Ubuntu / Debian (native Linux)

```bash
sudo apt update
sudo apt install -y hackrf libhackrf0 libhackrf-dev python3 python3-venv python3-pip
# Optional but useful:
sudo apt install -y usbutils
```

#### Udev rules (native Linux only) to avoid `sudo` for device access:
```bash
sudo bash -c 'groupadd -f plugdev && usermod -aG plugdev $SUDO_USER && printf "%s\n" \'SUBSYSTEM=="usb", ATTR{idVendor}=="1d50", ATTR{idProduct}=="6089", MODE="0666", GROUP="plugdev"\' > /etc/udev/rules.d/52-hackrf.rules && udevadm control --reload-rules && udevadm trigger'
```
*Log out/in so your group membership updates.*

---

### Windows using WSL 2 (recommended for Windows)

1. Install WSL (if not already) and Ubuntu from MS Store:
   ```bash
   wsl --install -d Ubuntu
   ```

2. Install `usbipd-win` (share USB devices to WSL):  
   - Download & install from Microsoft (search “usbipd-win GitHub”).  

3. In **PowerShell (Admin):**
   ```powershell
   usbipd wsl list
   usbipd wsl attach --busid <BUSID>   # pick the line that shows HackRF
   ```

4. Inside Ubuntu/WSL, install packages:
   ```bash
   sudo apt update
   sudo apt install -y hackrf libhackrf0 libhackrf-dev python3 python3-venv python3-pip
   ```

*Note: Udev rules aren’t strictly needed for WSL with usbipd, but they don’t hurt.*

---

### Python env & packages

From your project folder (where `skyhunter.py` will live):

```bash
python3 -m venv drone-env
source drone-env/bin/activate    # (on Windows/WSL bash)
pip install --upgrade pip
pip install numpy scipy
```

On Windows terminal (PowerShell/CMD), if you want curses TUI:
```powershell
pip install windows-curses
```

**Important:** This project uses a local file `libhackrf.py` as a Python wrapper for `libhackrf`.  
Place `libhackrf.py` in the same directory as `skyhunter.py`.

---

### Verify HackRF

Make sure your system sees the HackRF and the library works.

```bash
# Hardware visibility
lsusb | grep -E '1d50:6089|HackRF' || echo "No HackRF found"

# Library & firmware check
hackrf_info
```

You should see **"Found HackRF"** and device details.  
If not, see [Troubleshooting](#troubleshooting).

---

## Run SKYHUNTER

### Files
- `skyhunter.py` — the main program  
- `libhackrf.py` — the local Python wrapper (must be in the same folder)  

---

### Quick starts

FPV 5.8 GHz sweep (floor alert ON by default at +10 dB):
```bash
python skyhunter.py --auto fpv
```

DJI (2.4 GHz + 5.8 GHz) sweep:
```bash
python skyhunter.py --auto dji
```

All bands (FPV 5.8 + DJI 2.4/5.8):
```bash
python skyhunter.py --auto all
```

Speed up or slow down sweep (default ~7 s per full 5.8 band):
```bash
python skyhunter.py --auto fpv --dwell 0.3 --center-overlap 0.75
```

Disable floor alert:
```bash
python skyhunter.py --no-floor-alert
```

Adjust gains:
```bash
python skyhunter.py --lna 32 --vga 30
```

Enable RF front-end amp (≈14 dB) on HackRF:
```bash
python skyhunter.py --amp
```

When an RF signal is detected, the Recent Events pane shows:
```
[ALERT] DJI Detected @ <freq> MHz ~<width> MHz (mean +X dB, peak +Y dB)
[ALERT] FPV Detected @ <freq> MHz Peak <dB> ~<width> MHz (from floor rule or analog detector)
```

---

### All CLI options

```text
usage: skyhunter.py [-h] [--device-index DEVICE_INDEX] [--amp] [--lna LNA] [--vga VGA]
                    [--sample-rate SAMPLE_RATE] [--frame-ms FRAME_MS] [--nfft NFFT]
                    [--overlap OVERLAP] [--avg-frames AVG_FRAMES] [--delta-db DELTA_DB]
                    [--mean-excess-db MEAN_EXCESS_DB] [--nbins-baseline NBINS_BASELINE]
                    [--persist-hits PERSIST_HITS] [--persist-window PERSIST_WINDOW]
                    [--minwidth-mhz MINWIDTH_MHZ] [--maxwidth-mhz MAXWIDTH_MHZ]
                    [--floor-alert-rise-db FLOOR_ALERT_RISE_DB]
                    [--floor-persist-hits FLOOR_PERSIST_HITS] [--no-floor-alert]
                    [--dwell DWELL] [--center-overlap CENTER_OVERLAP]
                    [--auto {fpv,dji,all}]
```

**Key defaults:**
- Sweep: `--sample-rate 20e6`, `--dwell 0.4`, `--center-overlap 0.75`  
- Floor rule: enabled, `--floor-alert-rise-db 10`, `--floor-persist-hits 2`  
- DJI detector: width 10–40 MHz, mean excess ≥ 8 dB  
- FPV detector: width 4–12 MHz, peak excess ≥ 12 dB or mean excess ≥ 6 dB  

---

## How it works

1. **Streaming:** HackRF IQ → `read_samples(N)` via `libhackrf.py` wrapper.  
2. **PSD:** Welch periodogram (Hann, nperseg=4096) → dB scale.  
3. **Baseline/excess:** Rolling 20th percentile baseline; “hot” bins exceed by ΔdB.  
4. **Grouping:** Contiguous hot regions → bandwidth, mean/peak excess.  
5. **Classification:**
   - **DJI:** width ≥ 10 MHz in DJI bands (2.4 or 5.8), persistent across frames.  
   - **FPV:** width ≤ 12 MHz in FPV band (5.65–5.92 GHz), or floor rise alert (+10 dB).  
6. **UI:** Curses TUI with event log & stats; fallback to status line if curses missing.  

---

## Troubleshooting

**“Error code -1000 when opening HackRF”**  
- Another program may be using the device (close SDR apps).  
- On WSL: ensure device is attached via `usbipd`.  
- On Linux: confirm udev rules, replug USB, check `groups | grep plugdev`.  

**`hackrf_info` not found / returns no device**  
- Install HackRF packages (`hackrf`, `libhackrf0`, `libhackrf-dev`).  
- On WSL, re-run `usbipd wsl list / attach`.  

**`ModuleNotFoundError: windows-curses`**  
- Only needed for Windows terminals. Install via:  
  ```bash
  pip install windows-curses
  ```

**“Could not find module 'libhackrf.so'”**  
- You’re likely on native Windows. Use **WSL** as described above.  

**No alerts / misclassification**  
- Adjust gains: `--amp`, `--lna`, `--vga`.  
- FPV analog: use `--auto fpv`.  
- DJI: ensure video link is active.  
- Thresholds: tweak `--delta-db`, `--mean-excess-db`.  
- Sweep speed: increase dwell for stability (`--dwell 0.6`).  

---

## Tips

- Antenna proximity matters. Move a few meters away to reduce overload.  
- **Sample rate trade-off:** 20 MS/s spans ~20 MHz; higher = wider but heavier CPU.  
- **Overlap & dwell:** `--center-overlap 0.75` balances coverage vs speed.  
- Logging:  
  ```bash
  python skyhunter.py --auto dji | tee run.log
  ```


Happy hunting.  
If you want a packaged release (`pip install skyhunter-rf`) with prebuilt wheels later, say the word and I’ll prep the packaging scaffolding (setup, entry points, and CI).

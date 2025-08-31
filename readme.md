# SKYHUNTER — Drone RF Detector (HackRF, Python TUI)

**SKYHUNTER** is a fast, live drone RF detector designed for detecting DJI (OFDM) and analog FPV signals using HackRF.  
It streams IQ data via a lightweight `libhackrf.py` wrapper, computes Power Spectral Density (Welch method), and raises alerts in a terminal UI.

---

## ✨ Features

- **DJI Detection**: Identifies 10–40 MHz “plateaus” with persistence filtering.  
- **FPV Detection**: Detects 4–12 MHz analog spikes with a floor-rise rule.  
- **Fast Sweeping**: ~7 seconds per full 5.8 GHz band at default settings (20 MS/s, overlap 0.75, dwell 0.4 s).  
- **Terminal UI**: Interactive curses-based UI with fallback to a simple status line.  

---

## 📖 Table of Contents

1. [Prerequisites](#-prerequisites)  
   - [Hardware](#hardware)  
   - [OS & Drivers](#os--drivers)  
   - [Python](#python)  
2. [Install](#-install)  
   - [Ubuntu / Debian (native Linux)](#ubuntu--debian-native-linux)  
   - [Windows using WSL 2](#windows-using-wsl-2-recommended-for-windows)  
   - [Python Environment & Packages](#python-env--packages)  
   - [Verify HackRF](#verify-hackrf)  
3. [Running SKYHUNTER](#-run-skyhunter)  
   - [Quick Starts](#quick-starts)  
   - [All CLI Options](#all-cli-options)  
4. [How It Works](#-how-it-works)  
5. [Troubleshooting](#-troubleshooting)  
6. [Tips](#-tips)  
7. [Acknowledgements](#-acknowledgements)  

---

## 🔧 Prerequisites

### Hardware
- HackRF One (or compatible SDR).  
- USB cable.  
- Antenna suitable for **2.4 GHz** and/or **5.8 GHz**.  

### OS & Drivers
- **Linux:** Ubuntu 22.04+ recommended.  
- **Windows:** Windows 10/11 with WSL 2.  
- HackRF tools and `libhackrf` must be installed in the same environment where Python runs.  

### Python
- Python **3.10+** recommended.  
- Required packages:  
  - `numpy`  
  - `scipy`  
  - `windows-curses` (Windows only, for TUI support)  

---

## 💻 Install

### Ubuntu / Debian (Native Linux)

```bash
sudo apt update
sudo apt install -y hackrf libhackrf0 libhackrf-dev python3 python3-venv python3-pip
# Optional but useful:
sudo apt install -y usbutils
```

#### Udev Rules (to avoid `sudo` for device access)
```bash
sudo bash -c 'groupadd -f plugdev && usermod -aG plugdev $SUDO_USER && printf "%s\n" \'SUBSYSTEM=="usb", ATTR{idVendor}=="1d50", ATTR{idProduct}=="6089", MODE="0666", GROUP="plugdev"\' > /etc/udev/rules.d/52-hackrf.rules && udevadm control --reload-rules && udevadm trigger'
```
👉 *Log out and back in to refresh group membership.*

---

### Windows using WSL 2 (Recommended)

1. Install WSL & Ubuntu:  
   ```bash
   wsl --install -d Ubuntu
   ```

2. Install `usbipd-win` (for USB passthrough). Download from Microsoft’s GitHub.  

3. In **PowerShell (Admin)**:  
   ```powershell
   usbipd wsl list
   usbipd wsl attach --busid <BUSID>
   ```

4. Inside WSL/Ubuntu:  
   ```bash
   sudo apt update
   sudo apt install -y hackrf libhackrf0 libhackrf-dev python3 python3-venv python3-pip
   ```

---

### Python Environment & Packages

From your project folder:

```bash
python3 -m venv drone-env
source drone-env/bin/activate   # On Windows: use WSL bash
pip install --upgrade pip
pip install numpy scipy
```

For Windows TUI support:
```powershell
pip install windows-curses
```

⚠️ **Important:** Place `libhackrf.py` in the same directory as `skyhunter.py`.

---

### Verify HackRF

Check that your HackRF is visible:

```bash
# Hardware visibility
lsusb | grep -E '1d50:6089|HackRF' || echo "No HackRF found"

# Library & firmware check
hackrf_info
```

You should see **“Found HackRF”** and device details.  

---

## 🚀 Run SKYHUNTER

### Files
- `skyhunter.py` → Main program.  
- `libhackrf.py` → Local Python wrapper (must be in the same folder).  

---

### Quick Starts

- **FPV 5.8 GHz sweep** (default +10 dB floor alert):  
  ```bash
  python skyhunter.py --auto fpv
  ```

- **DJI 2.4 + 5.8 GHz sweep**:  
  ```bash
  python skyhunter.py --auto dji
  ```

- **All bands (FPV + DJI)**:  
  ```bash
  python skyhunter.py --auto all
  ```

- **Faster sweep**:  
  ```bash
  python skyhunter.py --auto fpv --dwell 0.3 --center-overlap 0.75
  ```

- **Disable floor alert**:  
  ```bash
  python skyhunter.py --no-floor-alert
  ```

- **Adjust gains**:  
  ```bash
  python skyhunter.py --lna 32 --vga 30
  ```

- **Enable HackRF RF amp (≈14 dB)**:  
  ```bash
  python skyhunter.py --amp
  ```

When an RF signal is detected, you’ll see logs such as:
```
[ALERT] DJI Detected @ 2435 MHz ~18 MHz (mean +9 dB, peak +15 dB)
[ALERT] FPV Detected @ 5800 MHz Peak +14 dB ~8 MHz
```

---

### All CLI Options

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

**Defaults:**
- Sweep: `--sample-rate 20e6`, `--dwell 0.4`, `--center-overlap 0.75`  
- Floor rule: `--floor-alert-rise-db 10`, `--floor-persist-hits 2`  
- DJI detector: width 10–40 MHz, mean ≥ 8 dB  
- FPV detector: width 4–12 MHz, peak ≥ 12 dB OR mean ≥ 6 dB  

---

## ⚙️ How It Works

1. **Streaming** → HackRF IQ samples read via `libhackrf.py`.  
2. **PSD** → Welch periodogram with Hann window.  
3. **Baseline** → Rolling 20th percentile baseline, detect bins above ΔdB.  
4. **Grouping** → Hot bins grouped into contiguous regions → bandwidth + stats.  
5. **Classification**:  
   - DJI: 10–40 MHz wide plateau, persistent across frames.  
   - FPV: 4–12 MHz spikes or floor-rise +10 dB.  
6. **UI** → Curses TUI event log + live stats (fallback: single status line).  

---

## 🛠 Troubleshooting

- **Error -1000 opening HackRF** → Device busy. Close SDR apps or reattach with `usbipd`.  
- **`hackrf_info` shows no device** → Install HackRF packages, replug device.  
- **`ModuleNotFoundError: windows-curses`** → Only required for Windows. Install with:  
  ```bash
  pip install windows-curses
  ```  
- **“Could not find module 'libhackrf.so'”** → Use WSL, not native Windows.  
- **No alerts / wrong classification**:  
  - Adjust `--amp`, `--lna`, `--vga`.  
  - Ensure DJI link is active.  
  - Loosen thresholds (`--delta-db 5`).  
  - Increase `--dwell 0.6` for stability.  

---

## 💡 Tips

- Don’t hold antenna too close — distance improves accuracy.  
- Higher sample rates widen capture but require more CPU.  
- Adjust overlap & dwell to balance **speed vs accuracy**.  
- Log runs with:  
  ```bash
  python skyhunter.py --auto dji | tee run.log
  ```

---

Happy hunting 🚁  


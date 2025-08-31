SKYHUNTER — Drone RF Detector (HackRF, Python TUI)

A fast, live drone RF detector for DJI (OFDM) and analog FPV signals using HackRF.
It streams IQ via a lightweight libhackrf.py wrapper, computes PSD (Welch), and raises alerts in a terminal UI.

DJI detection: 10–40 MHz “plateau” with persistence filtering

FPV detection: 4–12 MHz analog spike (plus a simple floor-rise rule)

Fast sweep: ~7 s per 5.8 GHz band by default (20 MS/s, overlap 0.75, dwell 0.4 s)

TUI: curses interface (or a simple status line if curses isn’t available)

Contents

Prerequisites

Hardware

OS & drivers

Python

Install

Ubuntu / Debian (native Linux)

Windows using WSL 2 (recommended for Windows)

Python env & packages

Verify HackRF

Run SKYHUNTER

Quick starts

All CLI options

How it works

Troubleshooting

Tips

Acknowledgements

Prerequisites
Hardware

HackRF One (or compatible) with USB cable.

An antenna suitable for 2.4 GHz and/or 5.8 GHz.

OS & drivers

Linux (Ubuntu 22.04+ recommended) OR Windows 10/11 with WSL 2.

HackRF tools & libhackrf installed on the environment where Python runs.

Python

Python 3.10+ recommended.

Packages: numpy, scipy, and on Windows terminals windows-curses.

Install
Ubuntu / Debian (native Linux)
sudo apt update
sudo apt install -y hackrf libhackrf0 libhackrf-dev python3 python3-venv python3-pip
# Optional but useful:
sudo apt install -y usbutils


Udev rules (native Linux only) to avoid sudo for device access:

# One-liner
sudo bash -c 'groupadd -f plugdev && usermod -aG plugdev $SUDO_USER && \
printf "%s\n" \
  \'SUBSYSTEM=="usb", ATTR{idVendor}=="1d50", ATTR{idProduct}=="6089", MODE="0666", GROUP="plugdev"\' \
  > /etc/udev/rules.d/52-hackrf.rules && \
udevadm control --reload-rules && udevadm trigger'
# log out/in so your group membership updates

Windows using WSL 2 (recommended for Windows)

Install WSL (if not already) and Ubuntu from MS Store:

wsl --install -d Ubuntu


Install usbipd-win (share USB devices to WSL):

Download & install from Microsoft (Search “usbipd-win GitHub”).

In PowerShell (Admin):

usbipd wsl list
usbipd wsl attach --busid <BUSID>  # pick the line that shows HackRF


Inside Ubuntu/WSL, install packages:

sudo apt update
sudo apt install -y hackrf libhackrf0 libhackrf-dev python3 python3-venv python3-pip


Note: Udev rules aren’t strictly needed for WSL with usbipd, but they don’t hurt.

Python env & packages

From your project folder (where skyhunter.py will live):

python3 -m venv drone-env
source drone-env/bin/activate   # (on Windows/WSL bash)
pip install --upgrade pip
pip install numpy scipy
# On Windows terminal (PowerShell/CMD), if you want curses TUI:
# pip install windows-curses


Important: This project uses a local file libhackrf.py as a Python wrapper for libhackrf.
Place libhackrf.py in the same directory as skyhunter.py.

Verify HackRF

Make sure your system sees the HackRF and the library works.

# Hardware visibility
lsusb | grep -E '1d50:6089|HackRF' || echo "No HackRF found"

# Library & firmware check
hackrf_info
# Should print "Found HackRF" and device details


If OK: proceed.
If not, see Troubleshooting
.

Run SKYHUNTER
Files

skyhunter.py — the main program (the full file you’ve been using).

libhackrf.py — the local Python wrapper (must be in the same folder).

Quick starts

FPV 5.8 GHz sweep (floor alert ON by default at +10 dB):

python skyhunter.py --auto fpv


DJI (2.4 GHz + 5.8 GHz) sweep:

python skyhunter.py --auto dji


All bands (FPV 5.8 + DJI 2.4/5.8):

python skyhunter.py --auto all


Speed up or slow down sweep (default ~7 s per full 5.8 band):

# Faster centers (less dwell) or different overlap
python skyhunter.py --auto fpv --dwell 0.3 --center-overlap 0.75


Disable floor alert (plateau/analog detector still active):

python skyhunter.py --no-floor-alert


Adjust gains:

python skyhunter.py --lna 32 --vga 30


Enable RF front-end amp (≈14 dB) on HackRF:

python skyhunter.py --amp


When an RF signal is detected, the Recent Events pane shows:

[ALERT] DJI Detected @ <freq> MHz ~<width> MHz (mean +X dB, peak +Y dB)

[ALERT] FPV Detected @ <freq> MHz Peak <dB> ~<width> MHz (from floor rule or analog detector)

All CLI options
usage: skyhunter.py [-h] [--device-index DEVICE_INDEX] [--amp]
                    [--lna LNA] [--vga VGA]
                    [--sample-rate SAMPLE_RATE] [--frame-ms FRAME_MS]
                    [--nfft NFFT] [--overlap OVERLAP] [--avg-frames AVG_FRAMES]
                    [--delta-db DELTA_DB] [--mean-excess-db MEAN_EXCESS_DB]
                    [--nbins-baseline NBINS_BASELINE]
                    [--persist-hits PERSIST_HITS] [--persist-window PERSIST_WINDOW]
                    [--minwidth-mhz MINWIDTH_MHZ] [--maxwidth-mhz MAXWIDTH_MHZ]
                    [--floor-alert-rise-db FLOOR_ALERT_RISE_DB]
                    [--floor-persist-hits FLOOR_PERSIST_HITS]
                    [--no-floor-alert]
                    [--dwell DWELL] [--center-overlap CENTER_OVERLAP]
                    [--auto {fpv,dji,all}]


Key defaults:

Sweep: --sample-rate 20e6, --dwell 0.4, --center-overlap 0.75

Floor rule: enabled, --floor-alert-rise-db 10, --floor-persist-hits 2

DJI detector: width 10–40 MHz, mean excess ≥ 8 dB

FPV detector: width 4–12 MHz, peak excess ≥ 12 dB or mean excess ≥ 6 dB

How it works

Streaming: HackRF IQ → read_samples(N) via libhackrf.py wrapper (unchanged path).

PSD: Welch periodogram (Hann, nperseg=4096 by default) → dB scale.

Baseline/excess: Rolling 20th percentile creates local baseline; “hot” bins exceed by ΔdB.

Grouping: Contiguous hot regions → bandwidth, mean/peak excess.

Classification:

DJI: width ≥ 10 MHz in DJI bands (2.4 or 5.8), persistence across frames.

FPV: width ≤ 12 MHz in FPV band (5.65–5.92 GHz), or floor rise alert (+10 dB) with peak-estimated width.

UI: Curses TUI with recent event log and live stats; falls back to a single-line status if curses isn’t present.

Troubleshooting
“Error code -1000 when opening HackRF”

Another program may be using the device: close SDR apps (gqrx, hackrf_sweep, etc.).

On WSL: ensure the device is attached:

usbipd wsl list
usbipd wsl attach --busid <BUSID>


On Linux: confirm permissions and udev rules, then re-plug the USB cable and/or log out/in:

groups | grep plugdev
hackrf_info


Try a different USB port/cable, avoid low-power hubs.

hackrf_info not found / returns no device

Install packages (hackrf, libhackrf0, libhackrf-dev) and replug the device.

On WSL, run usbipd wsl list / attach again after re-plug.

ModuleNotFoundError: windows-curses

Only needed for Windows terminals. On Ubuntu/WSL, TUI works with system curses.

Install on Windows:

pip install windows-curses

“Could not find module 'libhackrf.so'”

You’re likely on native Windows (not WSL) with a Linux wrapper/package.
This project targets Ubuntu/WSL where libhackrf is available from apt.
Use WSL as described above.

No alerts / misclassification

Gains: Try --amp and adjust --lna/--vga (too high can compress; too low misses signals).

FPV analog: Use --auto fpv. Analog spikes are narrower; floor-rise rule helps catch it.

DJI: Ensure video link is active (controller+drone powered and transmitting).

Thresholds: Loosen --delta-db (e.g., 5) or --mean-excess-db (e.g., 7) for noisy environments.

Sweep speed: If you’re missing bursts, increase dwell: --dwell 0.6 (slower but stickier).

Tips

Antenna proximity matters. A few meters away reduces overload/clipping and improves shape estimation.

Sample rate trade-off: 20 MS/s spans ±10 MHz around center (≈20 MHz span). Higher SR = wider slice but heavier CPU.

Overlap & dwell: --center-overlap near 0.75 gives decent coverage with fewer centers. Increase --dwell to improve averaging.

Logging: Pipe output to a file to keep a record:

python skyhunter.py --auto dji | tee run.log

Acknowledgements

Great Scott Gadgets for HackRF hardware + libhackrf.

The community projects that inspired the approach (OFDM plateau detection, Welch PSD pipelines).

Your provided libhackrf.py wrapper (ctypes) that makes direct streaming dead simple here.

Happy hunting. If you want a packaged release (pip install skyhunter-rf) with prebuilt wheels later, say the word and I’ll prep the packaging scaffolding (setup, entry points, and CI).
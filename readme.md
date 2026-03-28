# SkyHunter V2

<p align="center">
  <img src="static/hackrf.PNG" width="700"/>
</p>

<p align="center">
  <b>RF airspace awareness in one dashboard</b><br>
  Live drone RF detection (HackRF) + ADS-B aircraft tracking + offline intelligence
</p>

---

**SkyHunter V2** combines **software-defined radio (SDR)** drone detection with **real-time aircraft tracking** into a single unified interface.

- Detect **DJI + FPV drone signals** in 2.4 / 5.8 GHz  
- Track aircraft via **ADS-B (1090 MHz)**  
- Enrich aircraft with **FAA registry data (offline)**  
- Trigger alerts using **watchlist databases (basestation.sqb)**  
- Run fully **local-first — no cloud required**

> 🔥 **Why this is different:**  
> Most tools only do SDR *or* flight tracking. SkyHunter correlates both — letting you **see what’s in the air and what’s in the spectrum at the same time.**

---

## 📸 Screenshots

### HackRF Spectrum + Detection Engine
<p align="center">
  <img src="static/hackrf.PNG" width="700"/>
</p>

### Detection + Map View
<p align="center">
  <img src="static/detections.PNG" width="700"/>
</p>

---

## ⚡ Key Capabilities

| Feature | Description |
|--------|------------|
| **HackRF Detection** | Wideband sweeps with PSD + heuristics for DJI / FPV signals |
| **ADS-B Integration** | Live aircraft tracking via dump1090 (port 30003) |
| **Unified UI** | Drones + aircraft on one map with real-time updates |
| **FAA Enrichment** | Aircraft identity pulled from FAA registry (offline) |
| **Watchlist Alerts** | Detect flagged aircraft via `basestation.sqb` |
| **Offline Mode** | Map tiles + FAA data cached locally |
| **Local-First** | No accounts, no cloud, no external dependencies |

---

## 🚀 Quick Start

```bash
chmod +x setup.sh run.sh
./setup.sh
./run.sh
```

Then open:

```
http://localhost:5050
```

---

## 🛠 Prerequisites

- Linux / WSL2 (Ubuntu recommended)
- Python 3.10+
- HackRF One (required for RF detection)
- RTL-SDR (optional for ADS-B)

---

## 🛰 FAA Aircraft Data

Automatically downloaded during setup:

https://registry.faa.gov/database/ReleasableAircraft.zip

Manual refresh:

```bash
.venv/bin/python scripts/fetch_faa_registry.py --force
```

---

## 🗺 Offline Map Support

```bash
python scripts/download_map_tiles.py
```

---

## ✈️ ADS-B Integration

- Uses dump1090
- Reads from localhost:30003
- Auto-starts if not running

---

## 📡 HackRF Workflow

1. Plug in HackRF  
2. Run `./run.sh`  
3. View detections live  

---

## 🚨 Watchlist Alerts

Place:

```
basestation.sqb
```

in root to enable aircraft alerts.

---

## 📁 Project Layout

- web_ui.py → Flask server  
- skyhunter.py → RF engine  
- adsb_listener.py → ADS-B parser  
- scripts/ → utilities  
- data/ → FAA data  
- static/ → UI + images  

---

## 📜 License & Credits

SkyHunter V2 — Speer Cyber Defense

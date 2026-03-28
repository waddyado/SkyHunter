
# Skyhunter V2 — Changelog

This document summarizes **major functional changes and capabilities introduced in Skyhunter V2 compared to V1**.  
UI-only cosmetic tweaks are intentionally excluded unless they enable new functionality.

---

# Skyhunter V2 Functional Changes

## 1. HackRF RF Detection System
Skyhunter V2 introduces full **HackRF-based RF detection**.

### New capabilities
- Continuous HackRF RF scanning
- Detection across multiple frequency bands
- Live RF power spectrum visualization
- HackRF device telemetry reporting

### HackRF telemetry includes
- Device status
- Mode
- Active frequency bands
- Center frequency
- Noise floor / peak signal
- Minimum floor tracking
- Current slice view

### Raw spectral visualization
A new **HackRF tab** provides a real-time spectrum graph showing:

- Frequency (MHz)
- Signal power (dB)
- Downsampled spectrum slices

This enables visual monitoring of RF activity across monitored bands.

---

# 2. ADS‑B Aircraft Detection System

Skyhunter V2 introduces **full ADS‑B aircraft detection using RTL‑SDR and dump1090**.

### New ADS‑B pipeline

RTL‑SDR → dump1090 → SBS messages → Skyhunter parser → map visualization

### Capabilities

- Automatic detection of RTL‑SDR ADS‑B device
- Integration with dump1090 raw output
- SBS message parsing
- Aircraft position extraction
- Aircraft telemetry extraction

### Aircraft telemetry captured

For each aircraft:

- ICAO identifier
- Latitude
- Longitude
- Altitude
- Ground speed
- Track
- Timestamp

### ADS‑B system monitoring

The dashboard now includes **ADS‑B device status** showing:

- Device detection status
- Aircraft count (unique ICAOs)
- Error state reporting

---

# 3. Real‑Time Aircraft Map

Skyhunter V2 adds a **live aircraft map visualization**.

### Map features

- OpenStreetMap integration
- Live aircraft positions
- Map tile loading for offline operation
- Zoom and pan controls

### Aircraft rendering

Each aircraft is rendered as a **plane icon on the map** with:

- ICAO identification
- Current position

---

# 4. Aircraft Trajectory Tracking

Skyhunter V2 introduces **flight path visualization**.

### Features

- Historical position tracking per aircraft
- Up to **50 previous positions stored**
- Live trajectory line rendered behind aircraft
- Dynamic updates as new ADS‑B messages arrive

This allows visualizing aircraft movement over time.

---

# 5. Aircraft Heading Calculation

Aircraft orientation is now calculated dynamically.

Instead of relying solely on raw ADS‑B track values, Skyhunter:

1. Tracks previous aircraft positions
2. Computes the heading based on the most recent trajectory segment
3. Rotates the aircraft icon to match the real direction of travel

This ensures aircraft icons face their **actual direction of movement**.

---

# 6. Ground Speed Estimation

Skyhunter V2 introduces **computed ground speed**.

The system calculates aircraft ground speed by:

1. Tracking the last **10 seconds of aircraft position data**
2. Measuring the distance traveled
3. Dividing by elapsed time

This provides a calculated speed even when ADS‑B speed fields are missing.

---

# 7. Aircraft Detail Popups

Clicking an aircraft on the map now opens a **telemetry popup** displaying:

- ICAO identifier
- Callsign
- Altitude
- Ground speed
- Heading
- Latitude / Longitude
- Last seen timestamp

This allows rapid inspection of aircraft state directly from the map.

---

# 8. Local Callsign Database (Offline Mode)

Skyhunter V2 supports **offline aircraft callsign resolution**.

### Functionality

- Local ICAO → callsign lookup database
- Works completely offline
- Automatically resolves airline identifiers

This removes dependence on internet APIs for callsign lookup.

---

# 9. Unique Aircraft Tracking

Skyhunter V2 now maintains a **unique aircraft registry**.

### Improvements

- Aircraft tracked by ICAO identifier
- Duplicate detections eliminated
- Map entries update instead of duplicating
- Detection list shows **one entry per aircraft**

This greatly improves system clarity and stability.

---

# 10. Detection List Improvements

The aircraft detection panel now:

- Displays **unique aircraft only**
- Sorts aircraft by **most recent detection**
- Limits display to recent entries
- Updates aircraft information live

---

# 11. Settings System

Skyhunter V2 introduces a **persistent settings system**.

### Features

- Settings modal interface
- Local storage persistence
- Save / Reset functionality
- Theme control

### Settings architecture

Settings are stored in:

```
localStorage → skyhunter_settings
```

Settings persist across sessions.

---

# 12. Dark / Light Theme Engine

Skyhunter V2 introduces a **theme engine**.

### Capabilities

- Dark theme (default)
- Light theme toggle
- Dynamic theme switching
- Theme persistence between sessions

Themes are applied via:

```
html[data-theme="dark"]
html[data-theme="light"]
```

---

# 13. Improved Hardware Detection

Skyhunter V2 includes improved device detection logic for:

### HackRF
- Device presence detection
- Error reporting
- Telemetry reporting

### RTL‑SDR
- Device detection validation
- dump1090 integration checks
- ADS‑B port monitoring

---

# 14. dump1090 Integration

Skyhunter V2 now automatically launches and manages **dump1090**.

Capabilities include:

- Automatic dump1090 startup
- Monitoring of port 30002
- SBS message ingestion
- Error reporting if ADS‑B service fails

---

# 15. Live System Status API

The backend now exposes live telemetry endpoints:

```
/api/status
/api/adsb
/api/planes
```

These APIs provide:

- HackRF telemetry
- ADS‑B device state
- Aircraft data

---

# Summary

Skyhunter V2 transforms the platform from a basic RF monitor into a **fully integrated RF + aviation situational awareness system** with:

- HackRF spectrum monitoring
- RTL‑SDR ADS‑B aircraft detection
- Real‑time aircraft map
- Flight trajectory tracking
- Aircraft heading and speed estimation
- Offline callsign resolution
- Persistent system settings
- Hardware health monitoring

Skyhunter V2 represents a major functional expansion of the Skyhunter platform.

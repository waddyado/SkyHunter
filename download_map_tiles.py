#!/usr/bin/env python3
"""
Download map tiles for offline use. Saves to static/map-tiles/{z}/{x}/{y}.png.
Run once to populate the map. Uses zoom levels 0-4 (world view, ~1000 tiles).
"""
import os
import sys
import time
import urllib.request

# Project root: directory containing this file. Tiles go under static/map-tiles.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(PROJECT_ROOT, "static", "map-tiles")
# Use OpenStreetMap; respect their tile usage policy (cache, don't hammer)
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
ZOOM_LEVELS = list(range(5))  # 0-4
USER_AGENT = "SkyhunterV2/1.0 (local map cache)"


def num_tiles(z):
    n = 2 ** z
    return n * n


def download():
    os.makedirs(BASE, exist_ok=True)
    total = sum(num_tiles(z) for z in ZOOM_LEVELS)
    done = 0
    for z in ZOOM_LEVELS:
        n = 2 ** z
        for x in range(n):
            for y in range(n):
                path = os.path.join(BASE, str(z), str(x), f"{y}.png")
                if os.path.isfile(path):
                    done += 1
                    continue
                os.makedirs(os.path.dirname(path), exist_ok=True)
                url = TILE_URL.format(z=z, x=x, y=y)
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                try:
                    with urllib.request.urlopen(req, timeout=15) as r:
                        with open(path, "wb") as f:
                            f.write(r.read())
                except Exception as e:
                    print(f"Skip {z}/{x}/{y}: {e}", file=sys.stderr)
                done += 1
                if done % 50 == 0:
                    print(f"  {done}/{total} tiles ...")
                time.sleep(0.05)
    print(f"Done. Tiles in {BASE}")


if __name__ == "__main__":
    download()

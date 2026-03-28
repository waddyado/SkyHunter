#!/bin/bash
# Skyhunter V2 — install everything (venv + Python deps, dump1090 for ADS-B).
# Run once. For HackRF hardware: sudo apt install hackrf libhackrf0 libhackrf-dev
# For dump1090 build: sudo apt install build-essential librtlsdr-dev pkg-config
#
# IMPORTANT: All dependencies MUST be listed in requirements.txt.
# When you add a new dependency, add it to requirements.txt — this script
# installs from that file. Do not add deps only to run.sh or elsewhere.

set -e
cd "$(dirname "$0")"

VENV_DIR=".venv"
DUMP1090_REPO="https://github.com/antirez/dump1090"
DUMP1090_DIR="dump1090"

echo "Creating virtual environment in $VENV_DIR ..."
python3 -m venv "$VENV_DIR"

echo "Installing Python dependencies (from requirements.txt) ..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
# Bootstrap: setuptools first (provides pkg_resources needed by pyrtlsdr etc.)
"$VENV_DIR/bin/pip" install -q setuptools>=65.0.0
"$VENV_DIR/bin/pip" install -r requirements.txt

# Optional bundled FAA / registry text files: extract data/data.zip into data/
DATA_DIR="data"
mkdir -p "$DATA_DIR"
if [ -f "$DATA_DIR/data.zip" ]; then
  if ! command -v unzip >/dev/null 2>&1; then
    echo "Error: unzip is required to extract $DATA_DIR/data.zip (e.g. sudo apt install unzip)"
    exit 1
  fi
  echo "Extracting $DATA_DIR/data.zip into $DATA_DIR/ ..."
  unzip -o -q "$DATA_DIR/data.zip" -d "$DATA_DIR"
  echo "data.zip extracted."
fi

# Clone dump1090 into project root if not already present, then build
if [ ! -d "$DUMP1090_DIR/.git" ]; then
  echo "Cloning dump1090 into $DUMP1090_DIR/ ..."
  git clone "$DUMP1090_REPO" "$DUMP1090_DIR"
else
  echo "dump1090 directory already present, skipping clone."
fi
if [ -f "$DUMP1090_DIR/Makefile" ]; then
  echo "Building dump1090 ..."
  (cd "$DUMP1090_DIR" && make)
  echo "dump1090 build complete."
else
  echo "Warning: $DUMP1090_DIR/Makefile not found; skipping dump1090 build."
fi

echo ""
echo "Setup complete. Run ./run.sh to start the server."

#!/usr/bin/env bash
# Load all .stdf files in data/ into the DB.
# Run from project root after: pip install -r requirements.txt  (or: pip3 install -r requirements.txt)
set -e
cd "$(dirname "$0")"
PYTHON=${PYTHON:-python3}
echo "Using: $PYTHON"

$PYTHON stdf_loader.py data/demofile.stdf
echo "Loaded: data/demofile.stdf"

$PYTHON stdf_loader.py data/lot2.stdf
echo "Loaded: data/lot2.stdf"

$PYTHON stdf_loader.py data/lot3.stdf
echo "Loaded: data/lot3.stdf"

$PYTHON stdf_loader.py data/ROOS_20140728_131230.stdf
echo "Loaded: data/ROOS_20140728_131230.stdf"

echo "All STDF files loaded."

#!/bin/sh
# ============================================================================
# fetch-liberty.sh - download the sky130 standard-cell liberty files.
#
# The synthesis targets need one: Yosys's `stat -liberty` maps the synthesised
# netlist onto a cell library before it can report an area, and there is no
# area without one.  `make asic-check` and `make area` both refuse to run
# until this has been run once.
#
# The files come from the OpenROAD-flow-scripts sky130 platform, which
# distributes the *built* sky130_fd_sc_hd liberty set.  (The upstream
# skywater-pdk repository ships only the .json timing data; the .lib files are
# generated from it, so there is nothing to download from there.)
#
# Destination: third_party/, which is gitignored -- 12.8 MB per corner does not
# belong in this repository's history.
#
# Usage:  scripts/fetch-liberty.sh
#         LIBERTY=other.lib scripts/fetch-liberty.sh   (override the file name)
# ============================================================================
set -eu

LIB_DIR=third_party
LIB_NAME="${LIBERTY:-sky130_fd_sc_hd__tt_025C_1v80.lib}"
BASE_URL="https://raw.githubusercontent.com/The-OpenROAD-Project/OpenROAD-flow-scripts/master/flow/platforms/sky130hd/lib"

if [ ! -f "$LIB_DIR/$LIB_NAME" ]; then
  echo "fetching $LIB_NAME into $LIB_DIR/ ..."
  mkdir -p "$LIB_DIR"
  # Download to a temporary name and rename only on success, so an interrupted
  # download cannot leave a truncated .lib that Yosys will half-parse later.
  curl -fL --progress-bar "$BASE_URL/$LIB_NAME" -o "$LIB_DIR/$LIB_NAME.part"
  mv "$LIB_DIR/$LIB_NAME.part" "$LIB_DIR/$LIB_NAME"
fi

# A sky130 liberty file is ~12.8 MB and opens with `library (`. Anything
# smaller is an error page that curl happily wrote to disk with a 200 status.
size=$(wc -c < "$LIB_DIR/$LIB_NAME")
if [ "$size" -lt 1000000 ]; then
  echo "fetch-liberty.sh: $LIB_DIR/$LIB_NAME is only $size bytes; that is not a liberty file." >&2
  echo "                 Delete it and re-run, or check your network." >&2
  exit 1
fi
if ! grep -q '^library (' "$LIB_DIR/$LIB_NAME"; then
  echo "fetch-liberty.sh: $LIB_DIR/$LIB_NAME has no 'library (' header; it is not a liberty file." >&2
  exit 1
fi

echo "$LIB_DIR/$LIB_NAME is present ($size bytes)."
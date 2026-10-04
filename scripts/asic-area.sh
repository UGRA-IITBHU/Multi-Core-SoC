#!/bin/sh
# ============================================================================
# asic-area.sh - print a module -> cell-area table for the whole design.
#
# Synthesises every module in rtl/ on its own and reports the area Yosys maps
# it onto, so "which module costs the most silicon" is a measurement rather
# than a guess.  Every module is synthesised as its own top, which is only
# meaningful because the drop-in rule guarantees each one is self-contained.
#
# The module list is enumerated with `find` at ONE level.  Never use '**':
# /bin/sh has no globstar, so '**' matches nothing and this script would
# report an empty table and exit 0.
#
# Environment:
#   LIBERTY        liberty file for `stat -liberty`
#                  (default third_party/sky130_fd_sc_hd__tt_025C_1v80.lib)
#   CORE_CHILDREN  the twelve module names `core` may instantiate, space
#                  separated.  Supplied by the Makefile so this list lives in
#                  exactly one place.  When `core` is synthesised it needs
#                  those twelve on the command line as well as itself.
#
# Yosys cannot parse the immediate-assertion form the modules use, so each
# module is prepared by scripts/yosys-prep.sh first.  See that script.
#
# Usage:  scripts/asic-area.sh        (or: make area)
# ============================================================================
set -eu

LIBERTY="${LIBERTY:-third_party/sky130_fd_sc_hd__tt_025C_1v80.lib}"
CORE_CHILDREN="${CORE_CHILDREN:-}"
RTL_DIR=rtl

if [ ! -f "$LIBERTY" ]; then
  echo "asic-area.sh: liberty file $LIBERTY is missing." >&2
  echo "              run: scripts/fetch-liberty.sh" >&2
  exit 1
fi

printf '%-16s %12s %8s %12s\n' MODULE AREA_um2 CELLS SEQ_um2
printf '%-16s %12s %8s %12s\n' ---------------- ------------ -------- ------------

failed=0
for path in $(find "$RTL_DIR" -name '*.v' | sort); do
  module=$(basename "$path" .v)

  sources=$(CORE_CHILDREN="$CORE_CHILDREN" \
            scripts/yosys-prep.sh "$module" "build/yosys/$module" "$path" 2>/dev/null)

  # hierarchy -check elaborates for real and is what catches an inconsistent
  # port list; a green lint does not (see the Makefile for why).  dfflibmap +
  # abc then map onto the liberty cells, without which stat reports
  # "Area for cell type ... is unknown!" instead of a number.
  log=$(yosys -p "read_verilog -sv -I rtl/core -I rtl/common $sources; \
                  hierarchy -check -top $module; \
                  synth -flatten -top $module; \
                  dfflibmap -liberty $LIBERTY; \
                  abc -liberty $LIBERTY; \
                  stat -liberty $LIBERTY" 2>&1) || {
    echo "asic-area.sh: $module failed to synthesise" >&2
    echo "$log" | grep -iE 'error|hierarch' >&2 || true
    failed=$((failed + 1))
    continue
  }

  # `stat -liberty` prints, among other lines:
  #     "  2   50.048 cells"
  #     "Chip area for module `\top': 50.048000"
  #     "  of which used for sequential elements: 50.048000 (100.00%)"
  # Take the LAST match of each: synth runs `stat` more than once, and only
  # the final, liberty-mapped one carries the mapped numbers.
  area=$(echo "$log" | sed -n "s/.*Chip area for module .*: *\([0-9.]*\).*/\1/p" | tail -1)
  cells=$(echo "$log" | sed -n 's/^ *\([0-9][0-9]*\) *[0-9.]* *cells *$/\1/p' | tail -1)
  seq=$(echo "$log" | sed -n 's/.*sequential elements: *\([0-9.]*\).*/\1/p' | tail -1)
  [ -n "$area" ] || area=0
  [ -n "$cells" ] || cells=0
  [ -n "$seq" ] || seq=0

  printf '%-16s %12s %8s %12s\n' "$module" "$area" "$cells" "$seq"
done

printf '%-16s %12s %8s %12s\n' ---------------- ------------ -------- ------------
printf 'liberty: %s\n' "$LIBERTY"

if [ "$failed" -ne 0 ]; then
  echo "asic-area.sh: $failed module(s) failed to synthesise." >&2
  exit 1
fi
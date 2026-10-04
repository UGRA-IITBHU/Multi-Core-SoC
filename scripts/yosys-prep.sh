#!/bin/sh
# ============================================================================
# yosys-prep.sh - hand Yosys a copy of the RTL that its parser can read.
#
# WHY THIS EXISTS
#
# Every module in rtl/ carries immediate assertions of the frozen form
#
#     assert (1'b0) else $error("not implemented: <module>.<signal>");
#
# Verilator and Icarus both accept that.  Yosys's built-in Verilog frontend
# does not: its grammar accepts only `assert (<expr>);` with no action clause,
# and it rejects both `else ...` and a bare `$error(...)`:
#
#     rtl/core/alu.v:52: ERROR: syntax error, unexpected TOK_ELSE, expecting ';'
#
# `read_verilog -noassert` does not help -- the parse error happens in the
# lexer/parser before -noassert takes effect.  The Homebrew Yosys build has no
# slang or Verific frontend, so there is no parser flag that fixes this.
#
# Assertions are not hardware: every synthesis flow ignores them.  So this
# script copies the sources to a scratch directory with exactly those assertion
# LINES deleted, and prints the resulting file list for Yosys.
#
# WHAT IT WILL NOT DO
#
# The deletion pattern is anchored to the WHOLE line and matches only a complete
# immediate assertion with an $error action.  It cannot swallow logic: if a line
# holds an assertion plus anything else, or is split across lines, the pattern
# does not match, the line is passed through unchanged, and Yosys fails loudly.
# Refusing to read a file is always the safe outcome for a gate.
#
# Usage:
#   scripts/yosys-prep.sh <module> <scratch-dir> <source.v> ...
#   -> prints the scratch-copy paths on stdout, SPACE separated on ONE line.
#      One line matters: the caller interpolates the result straight into a
#      `yosys -p "..."` script, and Yosys treats a newline as a command
#      separator, so a newline-terminated list would silently turn the
#      remaining paths into (nonexistent) Yosys commands.
#
# CORE_CHILDREN may be set in the environment; when <module> is `core`, the
# twelve modules core may instantiate are appended.  (The Makefile owns that
# name list; this script only honours it.)
# ============================================================================
set -eu

if [ "$#" -lt 2 ]; then
  echo "usage: $0 <module> <scratch-dir> <source.v>..." >&2
  exit 2
fi

module="$1"
outdir="$2"
shift 2

# The one line pattern this script is allowed to delete.  Keep it narrow.
assert_line='^[[:space:]]*assert[[:space:]]*(.*)[[:space:]]*else[[:space:]]*\$error[[:space:]]*(.*);[[:space:]]*$'

mkdir -p "$outdir"

for src in "$@"; do
  if [ ! -f "$src" ]; then
    echo "yosys-prep.sh: $src does not exist" >&2
    exit 1
  fi
  base=$(basename "$src" .v)
  dest="$outdir/$base.v"
  sed -E "/$assert_line/d" "$src" > "$dest"
done

# core is the one module allowed to instantiate the other twelve, so Yosys has
# to be given those too or `hierarchy -check` will (correctly) complain that
# they are missing.  The Makefile is the single owner of this name list.
if [ "$module" = "core" ]; then
  for child in $CORE_CHILDREN; do
    src="rtl/core/$child.v"
    if [ -f "$src" ]; then
      sed -E "/$assert_line/d" "$src" > "$outdir/$child.v"
    fi
  done
fi

echo "yosys-prep.sh: removed whole-line immediate assertions from the Yosys" \
     "view of $module (Yosys cannot parse them; assertions are not hardware)." >&2

# Space separated, on one line -- see the "Usage" note above.
for f in "$outdir"/*.v; do
  printf '%s ' "$f"
done
printf '\n'
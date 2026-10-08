#!/bin/bash
# Windows shell-layer wrapper: OSS CAD Suite tools + MSYS2 perl/g++/sh.
export PATH="/c/oss-cad-suite/bin:/c/oss-cad-suite/lib:/c/msys64/usr/bin:$PATH"
# yosys/abc pick a temp dir from TMPDIR; unset it resolves to C:\Windows, which
# abc cannot write its stdcells.genlib scratch file into.
export TMPDIR="${TMPDIR:-/c/Users/devra/AppData/Local/Temp}"
cd /e/Multicore_soc/Multi-Core-SoC-main || exit 1
exec "$@"
#!/bin/sh
# ============================================================================
# build-sw.sh - build the bare-metal ISA test into a flat binary.
#
# The flags are the point of this script and are not to be relaxed:
#
#   -march=rv32imac_zicsr   exactly the ISA the spec froze. No 'g', no 'zicsr2',
#                           no compressed-relaxed variants. If this changes, the
#                           binary is no longer evidence about this core.
#   -mabi=ilp32             matching, and required by the linker.
#   -march=__riscv_... is NOT used; letting the compiler target the host would
#                           silently produce AArch64 code.
#
# -O1 with no -march relaxation keeps the instruction mix honest: at -Os the
# compiler deletes much of the arithmetic these tests exist to observe. -O0 is
# too far the other way and barely resembles compiler output.
#
# Also: no builtin memset/memcpy expectations. crt0 provides the data-segment
# setup and `-nostdlib` removes libc, so if the compiler ever emits a call to a
# memcpy we want a link error, not a silent trap at run time.
#
# Usage:  scripts/build-sw.sh [output-dir]
# ============================================================================
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="${1:-$ROOT/build/sw}"
SW="$ROOT/sw"

# Pick a toolchain. Prefer an explicitly-requested one, then whatever is on PATH.
CC="${RISCV_CC:-}"
if [ -z "$CC" ]; then
    for candidate in riscv64-elf-gcc riscv64-unknown-elf-gcc riscv32-unknown-elf-gcc; do
        if command -v "$candidate" >/dev/null 2>&1; then
            CC="$candidate"
            break
        fi
    done
fi
[ -n "$CC" ] || {
    echo "build-sw.sh: no RISC-V compiler found." >&2
    echo "             install one, or set RISCV_CC=/path/to/riscv-gcc" >&2
    exit 1
}

OBJCOPY="${RISCV_OBJCOPY:-}"
if [ -z "$OBJCOPY" ]; then
    OBJCOPY=$(printf '%s' "$CC" | sed 's/gcc$/objcopy/')
    command -v "$OBJCOPY" >/dev/null 2>&1 || OBJCOPY=riscv64-unknown-elf-objcopy
fi

mkdir -p "$OUT"

ARCH_FLAGS="-march=rv32imac_zicsr -mabi=ilp32"
COMMON="-nostdlib -nostartfiles -ffreestanding -fno-builtin -fno-pic -fno-common"

echo "build-sw.sh: $CC $ARCH_FLAGS"

# shellcheck disable=SC2086
"$CC" $ARCH_FLAGS $COMMON -O1 -Wall -Wextra \
     -T "$SW/rv32.ld" "$SW/src/crt0.S" "$SW/src/main.c" \
     -o "$OUT/isa_test.elf"

# A flat binary is what the testbench loads, but keep the ELF too: it carries
# the symbol table, which is what makes a failure debuggable.
"$OBJCOPY" -O binary "$OUT/isa_test.elf" "$OUT/isa_test.bin"

if command -v riscv64-elf-objdump >/dev/null 2>&1; then
    riscv64-elf-objdump -d "$OUT/isa_test.elf" > "$OUT/isa_test.dis"
fi

# Refuse to ship a binary for the wrong architecture. A host-targeted build
# would still link and still run - in the simulator, as garbage.
if command -v riscv64-elf-objdump >/dev/null 2>&1; then
    arch=$(riscv64-elf-objdump -f "$OUT/isa_test.elf" | sed -n 's/.*architecture: *//p')
    case "$arch" in
        riscv:rv32*) ;;
        *) echo "build-sw.sh: ELF architecture is '$arch', expected riscv:rv32." >&2
           exit 1 ;;
    esac
fi

printf 'build-sw.sh: wrote %s (%s bytes)\n' \
    "$OUT/isa_test.bin" "$(wc -c < "$OUT/isa_test.bin" | tr -d ' ')"
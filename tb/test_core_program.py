"""Run a real compiled program on the core.

This is the first check that the core executes code it did not help write.
Everything in `test_core.py` is hand-assembled by the same person who wrote
the decoder, so a misreading of the ISA in the decoder is reproduced in the
test and both agree. A program built by GCC carries encodings chosen by a
compiler that knows the specification, which is the only way the two
disagreements can be found.

Termination is the program's own `tohost` write, per `sw/rv32.ld` and crt0.
There is no trap support in phase 1, so nothing else can end a run, and the
testbench cannot simply compare registers afterwards without the program
telling it when it is done.
"""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from conftest import CLOCK_PERIOD_NS, RESET_NAMES, cycles
from test_core import Memory, TOHOST, stop_background

# Absolute, because the simulator runs with the working directory somewhere
# other than the repository root. A relative path here fails only once the
# binary is missing, and then fails as a confusing FileNotFoundError.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINARY = os.path.join(REPO, "build", "sw", "isa_test.bin")

# Generous, but finite: a mis-executed program that never writes `tohost` must
# fail the test rather than hang the regression.
MAX_CYCLES = 400000


def describe(result):
    """Name the failing check group, so a failure says what broke."""
    names = {
        1: "lui/auipc",
        2: "op-imm",
        3: "op",
        4: "x0",
        5: "calls/loops/stack frame",
        6: "32-bit constants",
        7: "rv32m multiply and divide",
        8: "rv32a loads and stores",
        9: "branches",
        10: "jumps",
    }
    return names.get(result, "check %d" % result)


@cocotb.test()
async def test_compiled_program_runs_to_completion(dut):
    """A GCC-built bare-metal program must run and report success."""
    await stop_background()
    for name in ("if_rsp_valid", "mem_rsp_valid"):
        getattr(dut, name).value = 0
    cocotb.start_soon(Clock(dut.clk, units="ns", period=CLOCK_PERIOD_NS).start())

    mem = Memory(dut)
    held = [n for n in RESET_NAMES if hasattr(dut, n)]
    for n in held:
        getattr(dut, n).value = 0
    await cycles(dut, 10)

    # Loaded while reset is still asserted, so the core cannot fetch the
    # default NOP before the real first instruction is in memory.
    mem.load_binary(BINARY)
    cocotb.start_soon(mem.serve())

    for n in held:
        getattr(dut, n).value = 1
    await cycles(dut, 1)

    for _ in range(MAX_CYCLES):
        await RisingEdge(dut.clk)
        if mem.tohost is not None:
            break
    else:
        raise AssertionError(
            "program did not write to tohost (0x%08x) within %d cycles; "
            "it never finished" % (TOHOST, MAX_CYCLES)
        )

    passed, value = mem.result
    assert passed, (
        "ISA test reported failure in group %s (check value %d)"
        % (describe(value), value)
    )

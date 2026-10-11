"""Integration tests for `core` -- the whole 5-stage pipeline wired together.

Each block already has its own unit test. This file tests the things that only
exist once the blocks are connected, and which no per-module test can catch:

* **Wiring.** Every stage bundle is packed at the right offset and unpacked by
  the right consumer. A single misplaced bit here silently corrupts programs
  that every unit test passes.
* **Reset.** No stage may come up holding a valid bit. Verilator is 2-state and
  reads X as 0, so an uncleared valid bit passes every functional test here and
  then boots nondeterministically on silicon. `stage_valid` exists so this can
  be observed without hierarchical references.
* **The pipeline's own behaviour**, end to end: forwarding across stage
  boundaries, the load-use interlock, branch flush, and the x0 discard.

The memory model is a plain dictionary driven off the two real memory port
pairs, so the testbench never reaches inside the DUT. Both pairs respond in the
cycle they are asked, which keeps expectations easy to state in cycles.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

from conftest import CLOCK_PERIOD_NS, RESET_NAMES, cycles, reset

# --------------------------------------------------------------------------
# Instruction encoders. Written out rather than pasted as hex so a reader can
# check the test against the ISA rather than trusting a magic number.
# Field order is the RISC-V one: imm | rs1 | funct3 | rd | opcode
# --------------------------------------------------------------------------


def _r(opcode, rd, funct3, rs1, rs2, funct7):
    return (
        (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode
    )


def _i(opcode, rd, funct3, rs1, imm):
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def _s(opcode, funct3, rs1, rs2, imm):
    imm &= 0xFFF
    return (
        ((imm >> 5) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (funct3 << 12)
        | ((imm & 0x1F) << 7)
        | opcode
    )


def _b(opcode, funct3, rs1, rs2, imm):
    """Branch: imm is a byte offset and bits [0] is always zero."""
    imm &= 0x1FFF
    b12 = (imm >> 12) & 1
    b10_5 = (imm >> 5) & 0x3F
    b4_1 = (imm >> 1) & 0xF
    b11 = (imm >> 11) & 1
    return (
        (b12 << 31)
        | (b10_5 << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (funct3 << 12)
        | (b4_1 << 8)
        | (b11 << 7)
        | opcode
    )


def _u(opcode, rd, imm):
    return (imm & 0xFFFFF000) | (rd << 7) | opcode


OP_IMM = 0x13
OP = 0x33
LOAD = 0x03
STORE = 0x23
BRANCH = 0x63
LUI = 0x37
AUIPC = 0x17

X0 = 0


def addi(rd, rs1, imm):
    return _i(OP_IMM, rd, 0x0, rs1, imm)


def add(rd, rs1, rs2):
    return _r(OP, rd, 0x0, rs1, rs2, 0x00)


def sw(rs2, rs1, imm):
    return _s(STORE, 0x2, rs1, rs2, imm)


def lw(rd, rs1, imm):
    # funct3 010 under opcode 0x03. Using OP_IMM here is the easy mistake:
    # funct3 010 is not a valid OP-IMM funct3, so the word decodes as an
    # illegal instruction and the load-use interlock this test exists to prove
    # is never reached at all.
    return _i(LOAD, rd, 0x2, rs1, imm)


def beq(rs1, rs2, imm):
    return _b(BRANCH, 0x0, rs1, rs2, imm)


def lui(rd, imm20):
    return _u(LUI, rd, imm20)


# --------------------------------------------------------------------------
# A dictionary-backed memory on both real port pairs.
# --------------------------------------------------------------------------

MEM_WORDS = 512  # 2 KB of 32-bit words

# What an unmapped address reads as. 0x00000013 is `addi x0, x0, 0` - the
# canonical RISC-V NOP. It matters that it is not 0x00000000: zero is not a
# valid encoding, and `if_stage` asserts that an instruction it holds is never
# zero, which is the right thing for it to assert. A program that runs off the
# end therefore walks through NOPs rather than fetching an illegal word.
NOP = 0x00000013


class Memory:
    def __init__(self, dut):
        self.dut = dut
        self.cells = {}

    def load(self, addr, *words):
        # Byte-addressed, to match `read` and `write` and the address the
        # fetch port actually carries. Indexing by `i` here instead of `4*i`
        # silently agrees only for a program at 0, which is exactly why it
        # looks right until the second word goes missing.
        for i, w in enumerate(words):
            self.cells[addr + 4 * i] = w & 0xFFFFFFFF

    def read(self, addr):
        return self.cells.get(addr, NOP)

    def write(self, addr, data):
        self.cells[addr] = data & 0xFFFFFFFF

    async def serve(self):
        """Answer the fetch pair and the load/store pair with one cycle of latency.

        The latency is not decoration. `lsu` retires a request on
        `resp_done = mem_rsp_valid`, and it deliberately does *not* latch
        `req_pending` when memory answers in the very same cycle the request is
        presented - its own comment calls out that a zero-latency memory "would
        see every access issued twice" unless `core` does something about it.
        Nothing can: the access is still sitting in EX/MEM at that moment, so
        the moment `req_pending` stays 0 and `req_eligible` is still true, the
        very same access goes out again on the next cycle, with whatever the
        bundle has become by then. A store then writes its data and overwrites
        it with the next instruction's - which is a silent, extremely expensive
        bug that looks like a memory-model problem and is actually a handshake
        one.

        A synchronous memory answers a cycle after the request, which is also
        what the SRAM this design will eventually sit next to actually does.
        With that latency `req_pending` latches, `core` holds EX/MEM for exactly
        the outstanding window (see `pipe_busy`), and the access retires once.
        Both ports share one response slot because the two never collide: only
        one of them is ever outstanding.
        """
        d = self.dut
        d.if_rsp_valid.value = 0
        d.mem_rsp_valid.value = 0
        pending = None
        await FallingEdge(d.clk)
        while True:
            # Latch this cycle's request *before* driving any response.
            # `mem_req_wdata` is gated on `mem_req_valid`, so answering a
            # request can change it combinationally; read after driving and a
            # store latches its own strobe with a zero data field.
            #
            # Only while nothing is outstanding. Both ports hold `*_req_valid`
            # high across several cycles for one logical request - `if_stage`
            # presents the same address in ST_IDLE and again in ST_REQ - so
            # capturing on every cycle counts one request twice and answers it
            # twice. The second answer is the dangerous one: a redirect squashes
            # the first, and the leftover then arrives at a freshly redirected
            # `if_stage` and is taken as the instruction at the target. Nothing
            # reports it; the wrong instruction simply executes.
            queued = None
            if pending is None:
                if d.mem_req_valid.value:
                    queued = ("mem", int(d.mem_req_addr.value),
                              int(d.mem_req_wdata.value), int(d.mem_req_we.value))
                elif d.if_req_valid.value:
                    queued = ("fetch", self.read(int(d.if_req_addr.value)))

            # Answer whatever was latched on the previous edge.
            if pending is None:
                d.if_rsp_valid.value = 0
                d.mem_rsp_valid.value = 0
            elif pending[0] == "fetch":
                d.if_rsp_rdata.value = pending[1]
                d.if_rsp_valid.value = 1
                d.mem_rsp_valid.value = 0
            else:
                _, addr, data, we = pending
                if we:
                    self.write(addr, data)
                else:
                    d.mem_rsp_rdata.value = self.read(addr)
                d.mem_rsp_valid.value = 1
                d.if_rsp_valid.value = 0

            pending = queued
            await FallingEdge(d.clk)


_BACKGROUND = []


async def stop_background():
    """Tear down every coroutine this module started for the previous test."""
    for task in _BACKGROUND:
        task.kill()
    _BACKGROUND.clear()


async def start(dut, program=(), data=None):
    """Hold reset, load `program`, release reset, and return a memory model.

    The program, and any `data` the program will read back, are written while
    reset is still asserted. That ordering is the
    whole point of this function and it is not cosmetic: the fetch port is live
    the instant reset releases, and an empty memory reads back NOP, so a core
    that is allowed to run before its program is loaded captures a NOP as the
    first instruction in IF/ID. The real first instruction is then never
    executed at all -- the program silently starts at its second word, and the
    failure lands far away from its cause.

    Whatever this starts is also torn down before the next test starts its own.
    Every test in a regression shares one simulation, so a second clock and a
    second memory model left running would fight over the same DUT: one clears
    `if_rsp_valid` in the same cycle the other sets it, and `if_stage` captures
    whatever `if_rsp_rdata` happens to be lying there.
    """
    await stop_background()

    # Leave the response channels defined rather than holding whatever the last
    # test's model was driving.
    dut.if_rsp_valid.value = 0
    dut.mem_rsp_valid.value = 0

    _BACKGROUND.append(
        cocotb.start_soon(Clock(dut.clk, units="ns", period=CLOCK_PERIOD_NS).start())
    )
    mem = Memory(dut)

    held = [n for n in RESET_NAMES if hasattr(dut, n)]
    for name in held:
        getattr(dut, name).value = 0
    await cycles(dut, 10)

    for addr, value in (data or {}).items():
        mem.write(addr, value)
    mem.load(0x0, *program)
    _BACKGROUND.append(cocotb.start_soon(mem.serve()))

    for name in held:
        getattr(dut, name).value = 1
    await cycles(dut, 1)
    return mem


def stage_bits(dut):
    return int(dut.stage_valid.value)


# --------------------------------------------------------------------------
# Reset behaviour
# --------------------------------------------------------------------------


@cocotb.test()
async def test_no_stage_is_valid_after_reset(dut):
    """Review-focus item: nothing may come up holding a valid bit.

    This is the check Verilator cannot make for us. It is 2-state and reads an
    uninitialised flop as 0, so a valid bit that reset fails to clear looks
    exactly like a cleared one here and boots nondeterministically on silicon.
    `stage_valid` is the observability path that makes it checkable at all.
    """
    # This test deliberately starts the clock itself rather than going through
    # `start`, because it needs reset with nothing resident in memory. The
    # clock still goes into `_BACKGROUND` so it is torn down with the rest --
    # an unregistered clock keeps running into the next test in the same
    # simulation and drives a second, unreset design underneath it.
    await stop_background()
    dut.if_rsp_valid.value = 0
    dut.mem_rsp_valid.value = 0
    _BACKGROUND.append(
        cocotb.start_soon(Clock(dut.clk, units="ns", period=CLOCK_PERIOD_NS).start())
    )

    await reset(dut)
    assert stage_bits(dut) == 0, (
        "stage_valid=%#x straight after reset; a stage came up valid" % stage_bits(dut)
    )

    # And it must stay zero while nothing is being fetched.
    await cycles(dut, 5)
    assert stage_bits(dut) == 0, (
        "stage_valid=%#x five idle cycles after reset" % stage_bits(dut)
    )


@cocotb.test()
async def test_stage_valid_advances_once_instructions_flow(dut):
    """With instructions resident, valid must eventually be high.

    The companion to the test above: it proves the reset check is not passing
    simply because the valid bits are permanently dead.
    """
    mem = await start(dut, [addi(1, X0, 5) ^ 0x00000000, addi(2, X0, 7)])
    await cycles(dut, 12)
    assert stage_bits(dut) != 0, (
        "stage_valid never asserted; valid bits look permanently tied low"
    )


# --------------------------------------------------------------------------
# End-to-end behaviour. Register values are read back through the memory the
# program itself stored them to, so the test needs no peeking at internals.
# --------------------------------------------------------------------------


async def run_and_check(dut, mem, expect, budget=40):
    """Let the loaded program run, then check what it left in memory."""
    await cycles(dut, budget)
    for addr, want in expect.items():
        got = mem.read(addr)
        assert got == want, (
            "memory[%#x] = %#x, expected %#x" % (addr, got, want)
        )


@cocotb.test()
async def test_single_addi_reaches_memory(dut):
    """addi x1, x0, 5 then sw it out: the whole path IF->WB must work."""
    program = [
        addi(1, X0, 5),
        sw(1, X0, 0x40),
    ]
    mem = await start(dut, program)
    await run_and_check(dut, mem, {0x40: 5})


@cocotb.test()
async def test_back_to_back_dependent_addis(dut):
    """Two instructions where the second reads what the first writes.

    The second must not read a stale value, which means EX->EX and MEM->EX
    forwarding are both doing their job.
    """
    program = [
        addi(1, X0, 5),
        addi(2, 1, 3),   # 8, one instruction after its dependency
        addi(3, 2, 1),   # 9
        sw(3, X0, 0x40),
    ]
    mem = await start(dut, program)
    await run_and_check(dut, mem, {0x40: 9})


@cocotb.test()
async def test_load_then_use_of_the_loaded_value(dut):
    """lw followed immediately by a use of the loaded register.

    This is the load-use interlock: the loaded value is not available a cycle
    later, so exactly one bubble must be injected and the add must still see
    the loaded data rather than whatever the register file happened to hold.
    """
    mem = await start(
        dut,
        [
            lw(4, X0, 0x80),   # x4 = 0x2A
            addi(5, 4, 1),     # x5 = 0x2B, immediately dependent
            sw(5, X0, 0x40),
        ],
        data={0x80: 0x2A},
    )
    await run_and_check(dut, mem, {0x40: 0x2B})


@cocotb.test()
async def test_taken_branch_redirects_to_its_target(dut):
    """A taken branch must reach its target and skip what lies between.

    The instruction after the branch is deliberately wrong: if the flush is
    short by even one instruction the stored value is wrong, so this catches a
    one-cycle flush as well as a two-cycle one.
    """
    program = [
        beq(X0, X0, 0x8),        # taken, to 0xC
        addi(6, X0, 0xBAD),      # must be squashed
        lui(7, 0x12345 << 12),   # must execute
        sw(7, X0, 0x40),
    ]
    # Nothing is loaded on top of the program after `start`. An earlier version
    # dropped a marker store at 0xC "to catch running off the end" - but 0xC is
    # where the program's own `sw` lives, so the marker overwrote the very
    # instruction the assertion below is waiting for. Nothing was ever stored to
    # 0x40, and the test failed while looking exactly like a redirect that never
    # happened.
    mem = await start(dut, program)
    await run_and_check(dut, mem, {0x40: (0x12345 << 12)}, budget=30)


@cocotb.test()
async def test_untaken_branch_falls_through(dut):
    """An untaken branch must not disturb the fall-through path."""
    program = [
        addi(8, X0, 1),
        beq(8, X0, 0x8),         # 1 != 0, so not taken
        addi(9, X0, 0x22),
        sw(9, X0, 0x40),
    ]
    mem = await start(dut, program)
    await run_and_check(dut, mem, {0x40: 0x22})


@cocotb.test()
async def test_x0_write_is_discarded_end_to_end(dut):
    """`addi x0, x0, 1` must leave x0 at zero, and the program must show it.

    The discard is enforced twice -- at the register file and at writeback --
    so this checks the end-to-end effect rather than either gate in isolation.
    """
    program = [
        addi(0, X0, 1),   # must be discarded
        addi(10, X0, 0),
        sw(10, X0, 0x40),  # x0 again: if the discard leaked, this is non-zero
    ]
    mem = await start(dut, program)
    await run_and_check(dut, mem, {0x40: 0})
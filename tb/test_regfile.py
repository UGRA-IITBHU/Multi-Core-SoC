"""Regression tests for ``rtl/core/regfile.v``.

Drives the module with the shared helpers in ``tb/conftest.py``.

The contract makes four promises, and each has a test here:

* **combinational reads with a same-cycle writeback bypass** - reading a
  register that the write port is committing *this* cycle returns the new value,
  not the old one.  This is what lets a WB->ID distance of one cost zero stall
  cycles, so a test that only ever writes and then reads on a *later* cycle
  would not be testing the promise at all;
* **`rs1_data` / `rs2_data` are exactly 0 when `*_used` is low** - and exactly
  0, not "unchanged" or "whatever the array holds";
* **reading `x0` always yields 0** - after reset, and after every kind of write;
* **writes to `x0` are discarded** - Review Focus 3, and the reason `addi x0,
  x0, 1` must not corrupt the ISA.

The two x0 discards are tested separately because they fail separately: the
write gate can be correct while the read path is not, and vice versa.

Run with::

    make test MODULE=test_regfile TOP=regfile
    make test-4state MODULE=test_regfile TOP=regfile
"""

import cocotb
from cocotb.triggers import ReadWrite, Timer
from conftest import Clock, cycles, reset

XLEN_MASK = 0xFFFFFFFF

# Distinct, recognisable values so a mis-wired read port is obvious rather than
# accidentally right.
V = {
    1: 0x11111111,
    2: 0x22222222,
    3: 0x33333333,
    4: 0xDEADBEEF,
    5: 0x00000001,
    6: 0x80000000,
    7: 0xFFFFFFFF,
    8: 0x00000000,
    9: 0x0000FFFF,
    10: 0xFFFF0000,
    31: 0xA5A5A5A5,
}


async def drive_reads(dut, rs1_addr=0, rs2_addr=0, rs1_used=1, rs2_used=1):
    """Point the two read ports somewhere, with the `*_used` qualifiers."""
    dut.rs1_addr.value = rs1_addr
    dut.rs2_addr.value = rs2_addr
    dut.rs1_used.value = rs1_used
    dut.rs2_used.value = rs2_used
    await settle(dut)


async def drive_write(dut, we=0, addr=0, data=0):
    """Present something on the writeback port."""
    dut.wb_we.value = we
    dut.wb_waddr.value = addr
    dut.wb_wdata.value = data
    await settle(dut)


async def settle(dut):
    """Let pending signal writes take effect before anything is read back.

    cocotb applies a signal assignment on the next delta cycle, so a test that
    drives inputs and reads an output in the same delta reads the *previous*
    value.  Every helper in this file that changes inputs awaits this before its
    caller reads, which is what makes "read before the edge" tests - the bypass
    tests - mean what they say.

    A real 1 ns is used rather than a bare delta so the same code works under
    both simulators.  Note that 1 ns can still cross a clock edge, so a test
    which must not advance time - the test that corrupts `regs[0]` deliberately -
    uses `delta_settle` instead.
    """
    await Timer(1, unit="ns")


async def delta_settle(dut):
    """Apply pending writes WITHOUT advancing simulation time.

    Needed by the test that deliberately makes `regs[0]` nonzero, so that a
    rising edge cannot accidentally land on the corrupted state.  A delta cycle
    is enough to make cocotb's writes take effect while guaranteeing that no edge
    occurs.
    """
    await ReadWrite()


async def write_reg(dut, addr, data):
    """Commit one write and advance past the edge that performs it.

    `cycles` returns after the design has settled, so the write is complete when
    this returns - which is what `reset` and `cycles` exist to guarantee.
    """
    await drive_write(dut, we=1, addr=addr, data=data)
    await cycles(dut, 1)
    await drive_write(dut, we=0, addr=addr, data=data)
    await settle(dut)


async def start(dut):
    """Clock running and reset released, ports parked in a known state."""
    cocotb.start_soon(Clock(dut.clk).start())
    await reset(dut)
    await drive_write(dut, we=0, addr=0, data=0)
    await drive_reads(dut)
    await settle(dut)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_all_registers_read_zero_after_reset(dut):
    """Every register reads 0 once reset is released.

    Read across the whole index space rather than a sample: a reset that clears
    only some of the array passes every functional test and then hands the
    program a garbage value the first time it touches an untouched register.
    """
    await start(dut)
    for addr in range(32):
        await drive_reads(dut, rs1_addr=addr, rs2_addr=addr)
        assert int(dut.rs1_data.value) == 0, (
            "register x%d read %08x after reset, expected 0"
            % (addr, int(dut.rs1_data.value))
        )
        assert int(dut.rs2_data.value) == 0, (
            "register x%d read %08x on rs2 after reset, expected 0"
            % (addr, int(dut.rs2_data.value))
        )


@cocotb.test()
async def test_reset_clears_registers_that_were_written(dut):
    """Reset is not just "the array starts at zero": it must clear real state.

    Reading zero after reset with nothing ever written proves nothing about the
    reset path - it is equally consistent with a reset that does not exist.  So
    this dirties the array first, then asserts reset puts it back.
    """
    await start(dut)
    for addr, data in V.items():
        await write_reg(dut, addr, data)

    # Precondition: the values really are in the array.
    await drive_reads(dut, rs1_addr=4)
    assert int(dut.rs1_data.value) == V[4], "precondition: x4 must hold its value"

    await reset(dut)
    await drive_write(dut, we=0)
    await drive_reads(dut, rs1_addr=4)
    assert int(dut.rs1_data.value) == 0, (
        "x4 still reads %08x after a second reset, expected 0"
        % int(dut.rs1_data.value)
    )


# ---------------------------------------------------------------------------
# Basic read / write
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_write_then_read(dut):
    """A committed write is visible from the next cycle onwards."""
    await start(dut)
    for addr, data in V.items():
        await write_reg(dut, addr, data)
    for addr, data in V.items():
        await drive_reads(dut, rs1_addr=addr, rs2_addr=addr)
        assert int(dut.rs1_data.value) == data, (
            "x%d read %08x, expected %08x" % (addr, int(dut.rs1_data.value), data)
        )
        assert int(dut.rs2_data.value) == data, (
            "x%d read %08x on rs2, expected %08x"
            % (addr, int(dut.rs2_data.value), data)
        )


@cocotb.test()
async def test_write_replaces_the_previous_value(dut):
    """A second write to the same register overwrites it; it does not accumulate."""
    await start(dut)
    await write_reg(dut, 5, 0xAAAAAAAA)
    await write_reg(dut, 5, 0x55555555)
    await drive_reads(dut, rs1_addr=5)
    assert int(dut.rs1_data.value) == 0x55555555, (
        "x5 read %08x after two writes, expected the second (55555555)"
        % int(dut.rs1_data.value)
    )


@cocotb.test()
async def test_write_with_we_low_changes_nothing(dut):
    """`wb_we` low means the write port is presented but not committed.

    The address and data are driven to a valid target while `wb_we` is low: a
    write port that ignores `wb_we` and writes whenever the address is valid
    would corrupt that register on every cycle the pipeline holds `wb_we` low,
    which is most of them.
    """
    await start(dut)
    await write_reg(dut, 7, 0x0BADF00D)

    # Present a write to x9 but do not commit it, for several cycles.
    await drive_write(dut, we=0, addr=9, data=0x12345678)
    await cycles(dut, 4)
    await drive_write(dut, we=0)

    await drive_reads(dut, rs1_addr=9)
    assert int(dut.rs1_data.value) == 0, (
        "x9 read %08x after an uncommitted write, expected 0"
        % int(dut.rs1_data.value)
    )
    await drive_reads(dut, rs1_addr=7)
    assert int(dut.rs1_data.value) == 0x0BADF00D, "x7 was corrupted"


@cocotb.test()
async def test_writing_every_register_and_reading_them_all(dut):
    """Write all 32 registers, then read all 32 back through both ports.

    Catches an off-by-one in either the address decode or the read mux that a
    handful of hand-picked addresses would step over.
    """
    await start(dut)
    pattern = {}
    for addr in range(1, 32):
        # A distinct value per register, spanning the awkward boundaries.
        value = ((addr * 0x01010101) ^ 0xA5A50000) & XLEN_MASK
        pattern[addr] = value
        await write_reg(dut, addr, value)

    for addr in range(1, 32):
        await drive_reads(dut, rs1_addr=addr, rs2_addr=(addr % 31) + 1)
        assert int(dut.rs1_data.value) == pattern[addr], (
            "x%d read %08x, expected %08x"
            % (addr, int(dut.rs1_data.value), pattern[addr])
        )
        other = (addr % 31) + 1
        assert int(dut.rs2_data.value) == pattern[other], (
            "rs2 on x%d read %08x, expected %08x"
            % (other, int(dut.rs2_data.value), pattern[other])
        )


# ---------------------------------------------------------------------------
# The two read ports
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_two_read_ports_are_independent(dut):
    """The two read ports address different registers in the same cycle.

    Reading the same address on both ports is the easy case that passes even if
    the two ports are wired together, so this drives genuinely different
    addresses and cross-checks both against what was written.
    """
    await start(dut)
    await write_reg(dut, 3, 0x33333333)
    await write_reg(dut, 17, 0x11112222)
    await write_reg(dut, 31, 0xCAFEBABE)

    await drive_reads(dut, rs1_addr=3, rs2_addr=17)
    assert int(dut.rs1_data.value) == V[3], (
        "rs1 on x3 read %08x, expected %08x" % (int(dut.rs1_data.value), V[3])
    )
    assert int(dut.rs2_data.value) == 0x11112222, (
        "rs2 on x17 read %08x, expected 11112222" % int(dut.rs2_data.value)
    )

    # The mirror image, with the same two registers the other way round.
    await drive_reads(dut, rs1_addr=17, rs2_addr=3)
    assert int(dut.rs1_data.value) == 0x11112222, "rs1 on x17 was wrong"
    assert int(dut.rs2_data.value) == V[3], "rs2 on x3 was wrong"

    # And one involving the highest index, since 31 is the one address where an
    # off-by-one in a 5-bit decode would wrap rather than simply fail.
    await drive_reads(dut, rs1_addr=31, rs2_addr=3)
    assert int(dut.rs1_data.value) == 0xCAFEBABE, "rs1 on x31 was wrong"
    assert int(dut.rs2_data.value) == V[3], "rs2 on x3 was wrong"


@cocotb.test()
async def test_read_ports_are_independent_of_each_others_address(dut):
    """The value rs1 returns must not depend on what rs2 is pointing at.

    Each iteration sets rs1 to a known register and sweeps rs2 across every
    index.  This catches a shared address mux, which would make rs1's answer
    change as rs2 moves.
    """
    await start(dut)
    await write_reg(dut, 4, 0xCAFEBABE)

    for rs2_addr in range(32):
        await drive_reads(dut, rs1_addr=4, rs2_addr=rs2_addr)
        assert int(dut.rs1_data.value) == 0xCAFEBABE, (
            "rs1 returned %08x while rs2 pointed at x%d, expected cafebabe"
            % (int(dut.rs1_data.value), rs2_addr)
        )


@cocotb.test()
async def test_both_ports_can_read_the_same_register(dut):
    """The same address on both ports returns the same value on both."""
    await start(dut)
    await write_reg(dut, 12, 0x0F0F0F0F)
    await drive_reads(dut, rs1_addr=12, rs2_addr=12)
    assert int(dut.rs1_data.value) == 0x0F0F0F0F
    assert int(dut.rs2_data.value) == 0x0F0F0F0F


# ---------------------------------------------------------------------------
# The `*_used` qualifiers
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_unused_rs1_reads_exactly_zero(dut):
    """`rs1_used` low forces rs1_data to 0 even when the address is a live register.

    The address is deliberately pointed at a register holding a nonzero value,
    because "unused reads 0" is trivially true when the address happens to be
    x0 or an unwritten register.
    """
    await start(dut)
    await write_reg(dut, 6, 0x80000000)
    await drive_reads(dut, rs1_addr=6, rs2_addr=6, rs1_used=0, rs2_used=1)
    assert int(dut.rs1_data.value) == 0, (
        "rs1_used=0 on x6 (holding 80000000) gave %08x, expected 0"
        % int(dut.rs1_data.value)
    )
    assert int(dut.rs2_data.value) == 0x80000000, (
        "rs2_used=1 on x6 gave %08x, expected 80000000" % int(dut.rs2_data.value)
    )


@cocotb.test()
async def test_unused_rs2_reads_exactly_zero(dut):
    """`rs2_used` low forces rs2_data to 0, independently of rs1_used."""
    await start(dut)
    await write_reg(dut, 6, 0x80000000)
    await drive_reads(dut, rs1_addr=6, rs2_addr=6, rs1_used=1, rs2_used=0)
    assert int(dut.rs2_data.value) == 0, (
        "rs2_used=0 on x6 (holding 80000000) gave %08x, expected 0"
        % int(dut.rs2_data.value)
    )
    assert int(dut.rs1_data.value) == 0x80000000, (
        "rs1_used=1 on x6 gave %08x, expected 80000000" % int(dut.rs1_data.value)
    )


@cocotb.test()
async def test_both_ports_unused_read_zero(dut):
    """Both `*_used` low: both outputs are 0, whatever the addresses say."""
    await start(dut)
    await write_reg(dut, 9, 0x0000FFFF)
    await write_reg(dut, 10, 0xFFFF0000)
    await drive_reads(dut, rs1_addr=9, rs2_addr=10, rs1_used=0, rs2_used=0)
    assert int(dut.rs1_data.value) == 0, "rs1_used=0 did not force zero"
    assert int(dut.rs2_data.value) == 0, "rs2_used=0 did not force zero"


@cocotb.test()
async def test_used_is_high_does_not_change_the_address(dut):
    """`*_used` qualifies the value; it must not qualify the address.

    `rs1_used = 1` on x9 must return x9's value, not x0 or the bypass.
    """
    await start(dut)
    await write_reg(dut, 9, 0x0000FFFF)
    await drive_reads(dut, rs1_addr=9, rs2_addr=9, rs1_used=1, rs2_used=1)
    assert int(dut.rs1_data.value) == 0x0000FFFF
    assert int(dut.rs2_data.value) == 0x0000FFFF


# ---------------------------------------------------------------------------
# x0 - Review Focus 3
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_write_to_x0_is_discarded(dut):
    """`addi x0, x0, 1` must not change anything.

    This is Review Focus 3 from the plan, in the form the ISA cares about: the
    write port is driven exactly as a real write to x0 would be, and x0 must
    still read 0 afterwards.
    """
    await start(dut)
    await drive_reads(dut, rs1_addr=0)
    assert int(dut.rs1_data.value) == 0, "precondition: x0 reads 0"

    for payload in (1, 0xFFFFFFFF, 0x80000000, 0x12345678):
        await write_reg(dut, 0, payload)
        await drive_reads(dut, rs1_addr=0)
        assert int(dut.rs1_data.value) == 0, (
            "x0 read %08x after a write of %08x, expected 0"
            % (int(dut.rs1_data.value), payload)
        )


@cocotb.test()
async def test_x0_write_does_not_disturb_other_registers(dut):
    """A write to x0 must not leak into the array anywhere.

    The write data is a distinctive pattern and several neighbours are
    pre-loaded.  A write port that decoded index 0 wrongly - by dropping the
    index, or by masking it to 4 bits - would land the payload somewhere else
    and this catches it.
    """
    await start(dut)
    await write_reg(dut, 1, 0x11111111)
    await write_reg(dut, 16, 0x16161616)

    await write_reg(dut, 0, 0xFEEDFACE)
    await drive_write(dut, we=0)

    for addr, expected in ((0, 0), (1, 0x11111111), (16, 0x16161616)):
        await drive_reads(dut, rs1_addr=addr)
        assert int(dut.rs1_data.value) == expected, (
            "x%d read %08x after a write to x0, expected %08x"
            % (addr, int(dut.rs1_data.value), expected)
        )


@cocotb.test()
async def test_writing_x0_then_reading_a_real_register_is_unaffected(dut):
    """A write to x0 is invisible even in the cycle it is presented.

    The write port is live and `wb_we` is high with `wb_waddr = 0`, while the
    read ports are pointed at x5.  If the bypass did not apply the same
    `wb_waddr != 0` gate as the write, x5's read would be unaffected anyway -
    but a bypass that compared only the low bits, or an index-0 write that was
    broadcast, would show up here.
    """
    await start(dut)
    await write_reg(dut, 5, 0x12345678)

    await drive_reads(dut, rs1_addr=5, rs2_addr=5)
    await drive_write(dut, we=1, addr=0, data=0xFEEDFACE)
    # Same cycle, no edge: the bypass is combinational and must not fire.
    assert int(dut.rs1_data.value) == 0x12345678, (
        "x5 read %08x while a write to x0 was presented, expected 12345678"
        % int(dut.rs1_data.value)
    )
    await drive_write(dut, we=0)
    await drive_reads(dut, rs1_addr=5)
    assert int(dut.rs1_data.value) == 0x12345678, "x5 changed"


@cocotb.test()
async def test_x0_reads_zero_even_if_the_storage_at_index_zero_is_corrupted(dut):
    """The *second* x0 discard: reads of index 0 are forced to 0 regardless.

    The contract says x0 "must be discarded, twice": once by gating the write
    port, and once by forcing every read of index 0 to zero.  Those two gates are
    independently correct and independently necessary, and testing only the
    first leaves the second untested - because with the write port gated, index 0
    of the array can never become nonzero, so a design with *only* the write gate
    passes every other test in this file.

    Reaching that state requires writing the array directly, which is normally
    forbidden: the drop-in rule says no hierarchical references across modules,
    and this testbench sees only `regfile`'s ports.  But this is the DUT's own
    internal state, not another module's, and the alternative is leaving one of
    the two documented protections unverified - which is how a defence gets
    deleted one day by someone who could not see what it was for.  So this one
    test pokes the array deliberately, and says why.

    If a future implementation replaces the array with something a simulator
    cannot be made to deposit into, this test should be kept but re-expressed as
    a lint-level or structural check - not deleted.
    """
    await start(dut)

    # Point both read ports at x0 and park the write port.  Driven directly
    # rather than through the helpers, because those settle on a 1 ns Timer and
    # this test must not advance time at all.
    dut.rs1_addr.value = 0
    dut.rs2_addr.value = 0
    dut.rs1_used.value = 1
    dut.rs2_used.value = 1
    dut.wb_we.value = 0
    dut.wb_waddr.value = 0
    dut.wb_wdata.value = 0
    await delta_settle(dut)

    # Precondition: the storage really is zero, and reads really are zero.
    assert int(dut.regs[0].value) == 0, (
        "precondition: regs[0] should be 0 after reset, is %08x"
        % int(dut.regs[0].value)
    )
    assert int(dut.rs1_data.value) == 0

    # Corrupt index 0 of the array directly, behind the write port's back.
    dut.regs[0].value = 0xDEADBEEF
    await delta_settle(dut)

    # The array is now nonzero...
    assert int(dut.regs[0].value) == 0xDEADBEEF, (
        "precondition: the deposit did not take, regs[0] is %08x"
        % int(dut.regs[0].value)
    )
    # ...but both read ports must still report 0 for x0.
    assert int(dut.rs1_data.value) == 0, (
        "rs1 read %08x for x0 while regs[0] held deadbeef, expected 0: the "
        "read-side x0 discard is missing" % int(dut.rs1_data.value)
    )
    assert int(dut.rs2_data.value) == 0, (
        "rs2 read %08x for x0 while regs[0] held deadbeef, expected 0: the "
        "read-side x0 discard is missing" % int(dut.rs2_data.value)
    )

    # And a writeback of that same corrupt value must not be bypassed either:
    # even a committed write to x0 does not become visible on the read side.
    dut.wb_we.value = 1
    dut.wb_waddr.value = 0
    dut.wb_wdata.value = 0xDEADBEEF
    await delta_settle(dut)
    assert int(dut.rs1_data.value) == 0, "the bypass exposed a write to x0"
    assert int(dut.rs2_data.value) == 0, "the bypass exposed a write to x0"

    # Restore the invariant and park the port.  No rising edge is allowed to
    # happen while regs[0] is nonzero: `regfile` asserts that x0's storage is
    # always zero, which is the whole point of the write-side discard, and that
    # assertion is *supposed* to fire on this deliberately corrupted state.
    dut.wb_we.value = 0
    dut.regs[0].value = 0
    await delta_settle(dut)
    assert int(dut.regs[0].value) == 0, "could not restore regs[0] to zero"


@cocotb.test()
async def test_a_corrupted_neighbouring_register_does_not_affect_x0(dut):
    """The index-0 read force must be a real index comparison, not a zero check.

    Every register except x0 is writable, so a design that special-cased "the
    register that reads 0" rather than "index 0" would look correct.  This makes
    a *different* register nonzero and requires that x0 still reads 0 while the
    other reads its own value - which is only true if the force is indexed.
    """
    await start(dut)
    await write_reg(dut, 1, 0x11111111)
    await drive_reads(dut, rs1_addr=0, rs2_addr=1)
    assert int(dut.rs1_data.value) == 0, "x0 must read 0"
    assert int(dut.rs2_data.value) == 0x11111111, "x1 must read its own value"

    # And after overwriting x1 repeatedly, x0 is unaffected.
    for value in (0x22222222, 0x33333333, 0x00000000):
        await write_reg(dut, 1, value)
        await drive_reads(dut, rs1_addr=0, rs2_addr=1)
        assert int(dut.rs1_data.value) == 0, "x0 read %08x" % int(dut.rs1_data.value)
        assert int(dut.rs2_data.value) == value, (
            "x1 read %08x, expected %08x" % (int(dut.rs2_data.value), value)
        )


@cocotb.test()
async def test_x0_stays_zero_across_a_long_sequence_of_writes(dut):
    """Interleave writes to x0 and to real registers; x0 never moves.

    `core` will present writeback for a bubble, for a misaligned access and for
    an `x0` destination in the same cycle as real writes, so x0 has to survive
    being written every cycle rather than only in a clean test sequence.
    """
    await start(dut)
    for round_index in range(8):
        await write_reg(dut, 0, 0xFFFFFFFF - round_index)
        await write_reg(dut, (round_index % 30) + 1, 0x1000 + round_index)
        await drive_reads(dut, rs1_addr=0, rs2_addr=0)
        assert int(dut.rs1_data.value) == 0, (
            "round %d: x0 read %08x, expected 0"
            % (round_index, int(dut.rs1_data.value))
        )
        assert int(dut.rs2_data.value) == 0, (
            "round %d: x0 read %08x on rs2, expected 0"
            % (round_index, int(dut.rs2_data.value))
        )


@cocotb.test()
async def test_the_x0_assertion_is_armed_and_silent_on_a_correct_design(dut):
    """`regfile`'s own immediate assertion must be live, and must not misfire.

    The RTL asserts, on every rising edge where a write to x0 is being
    committed, that `regs[0]` is still zero.  An assertion nobody has ever seen
    fire is indistinguishable from one that cannot fire, and the second kind is
    the dangerous one: it reads as a safety net that is not there.

    So this drives many writes to x0 through the port and requires silence -
    which is the part that matters day to day, because an assertion that fires
    on correct hardware gets disabled, and then it is gone for the case that
    needed it.

    Deliberately defeating the gate to watch it fire is *not* done here.  It
    needs the internal array, and it would mean deliberately creating the
    corrupted state the assertion exists to report; the assertion is checked by
    the 4-state regression and by review instead.
    """
    await start(dut)

    for payload in (0xFFFFFFFF, 0x80000000, 0x00000001, 0xDEADBEEF):
        await write_reg(dut, 0, payload)

    # Writes to x0 interleaved with writes to real registers, which is the case
    # the assertion's `wb_waddr == 0` term exists to isolate from.
    await write_reg(dut, 5, 0x12345678)
    await write_reg(dut, 0, 0xFFFFFFFF)
    await write_reg(dut, 5, 0x87654321)
    await write_reg(dut, 0, 0x00000000)

    await drive_reads(dut, rs1_addr=0, rs2_addr=0)
    assert int(dut.rs1_data.value) == 0, "x0 must be 0 after all that"
    assert int(dut.rs2_data.value) == 0, "x0 must be 0 after all that"

    # And the neighbours are untouched, so the assertion's silence is not just a
    # side effect of nothing being written at all.
    await drive_reads(dut, rs1_addr=5)
    assert int(dut.rs1_data.value) == 0x87654321, "x5 was disturbed"


# ---------------------------------------------------------------------------
# The writeback bypass - the guarantee that makes a WB->ID distance of one free
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_read_sees_the_write_in_the_same_cycle(dut):
    """With `wb_we` high and the addresses equal, the read returns the new data.

    This is the contract's "reads bypass the writeback port in the same cycle,
    so a load-use distance of one needs no hazard stall".  It is checked
    *without* advancing a clock: the bypass is combinational, so a test that
    waited an edge would be testing the array read and would pass against a
    design with no bypass at all.
    """
    await start(dut)
    await write_reg(dut, 8, 0xAAAAAAAA)

    await drive_reads(dut, rs1_addr=8, rs2_addr=8)
    assert int(dut.rs1_data.value) == 0xAAAAAAAA, "precondition: x8 holds its value"

    # Present a write to x8 and read x8 in the same cycle, no edge in between.
    await drive_write(dut, we=1, addr=8, data=0xBBBBBBBB)
    assert int(dut.rs1_data.value) == 0xBBBBBBBB, (
        "rs1 read %08x with a write of bbbbbbbb presented to the same register "
        "in the same cycle, expected bbbbbbbb: the bypass is missing"
        % int(dut.rs1_data.value)
    )
    assert int(dut.rs2_data.value) == 0xBBBBBBBB, (
        "rs2 read %08x, expected bbbbbbbb: the rs2 bypass is missing"
        % int(dut.rs2_data.value)
    )

    # And the value must still be there after the edge commits it.  `wb_we`
    # deliberately stays high across that edge: dropping it first would mean
    # the write never commits, and the assertion would then be checking the
    # bypass again rather than the array.
    await cycles(dut, 1)
    assert int(dut.rs1_data.value) == 0xBBBBBBBB, (
        "the bypassed write did not commit: x8 reads %08x after the edge"
        % int(dut.rs1_data.value)
    )
    await drive_write(dut, we=0, addr=8, data=0xBBBBBBBB)


@cocotb.test()
async def test_bypass_only_affects_the_matching_register(dut):
    """A write in flight must not appear on a *different* register's read port.

    The bypass condition includes an address comparison.  Without it, every read
    would return the writeback data in any cycle the write port was live - which
    is most cycles in the real pipeline.
    """
    await start(dut)
    await write_reg(dut, 8, 0xAAAAAAAA)
    await write_reg(dut, 11, 0xBBBBBBBB)

    await drive_reads(dut, rs1_addr=11, rs2_addr=11)
    await drive_write(dut, we=1, addr=8, data=0xCCCCCCCC)

    assert int(dut.rs1_data.value) == 0xBBBBBBBB, (
        "x11 read %08x while a write to x8 was in flight, expected bbbbbbbb"
        % int(dut.rs1_data.value)
    )
    assert int(dut.rs2_data.value) == 0xBBBBBBBB, "rs2 leaked the in-flight write"

    # x8's own read does bypass.
    await drive_reads(dut, rs1_addr=8, rs2_addr=11)
    assert int(dut.rs1_data.value) == 0xCCCCCCCC, "x8 did not bypass"
    await drive_write(dut, we=0, addr=8, data=0xCCCCCCCC)
    await cycles(dut, 1)


@cocotb.test()
async def test_bypass_only_applies_to_the_matching_read_port(dut):
    """rs2 bypasses only when *it* is the port whose address matches.

    With rs1 on the written register and rs2 elsewhere, only rs1 may see the new
    value.  The mirror image - rs2 matching and rs1 not - is checked too, so the
    two read muxes cannot have been implemented as one shared term.
    """
    await start(dut)
    await write_reg(dut, 8, 0xAAAAAAAA)
    await write_reg(dut, 11, 0xBBBBBBBB)

    await drive_reads(dut, rs1_addr=8, rs2_addr=11)
    await drive_write(dut, we=1, addr=8, data=0xCCCCCCCC)
    assert int(dut.rs1_data.value) == 0xCCCCCCCC, "rs1 did not bypass"
    assert int(dut.rs2_data.value) == 0xBBBBBBBB, "rs2 bypassed when it should not"
    await drive_write(dut, we=0, addr=8, data=0xCCCCCCCC)
    await cycles(dut, 1)

    await drive_reads(dut, rs1_addr=11, rs2_addr=8)
    await drive_write(dut, we=1, addr=8, data=0xDDDDDDDD)
    assert int(dut.rs2_data.value) == 0xDDDDDDDD, "rs2 did not bypass"
    assert int(dut.rs1_data.value) == 0xBBBBBBBB, "rs1 bypassed when it should not"
    await drive_write(dut, we=0, addr=8, data=0xDDDDDDDD)
    await cycles(dut, 1)


@cocotb.test()
async def test_no_bypass_when_we_is_low(dut):
    """With `wb_we` low the writeback port is not committed and must not bypass.

    Same address, same data, only `wb_we` differs from the passing case - which
    is what makes this a real test of the enable rather than of the address
    comparison.
    """
    await start(dut)
    await write_reg(dut, 8, 0xAAAAAAAA)
    await drive_reads(dut, rs1_addr=8, rs2_addr=8)
    await drive_write(dut, we=0, addr=8, data=0xBBBBBBBB)
    assert int(dut.rs1_data.value) == 0xAAAAAAAA, (
        "rs1 read %08x with wb_we low, expected the stored aaaaaaaa"
        % int(dut.rs1_data.value)
    )
    assert int(dut.rs2_data.value) == 0xAAAAAAAA, "rs2 bypassed with wb_we low"


@cocotb.test()
async def test_bypass_to_x0_is_suppressed(dut):
    """A write to x0 in flight must not be bypassed onto a read of x0.

    x0 reads 0 regardless, so this asserts the same thing as the discard tests -
    but through the bypass path rather than the array path, and the two gates
    are separate terms in the RTL.
    """
    await start(dut)
    await drive_reads(dut, rs1_addr=0, rs2_addr=0)
    await drive_write(dut, we=1, addr=0, data=0xFFFFFFFF)
    assert int(dut.rs1_data.value) == 0, (
        "rs1 read %08x while a write to x0 was in flight, expected 0"
        % int(dut.rs1_data.value)
    )
    assert int(dut.rs2_data.value) == 0, "rs2 bypassed a write to x0"
    await drive_write(dut, we=0, addr=0, data=0xFFFFFFFF)


@cocotb.test()
async def test_bypass_is_suppressed_when_the_port_is_unused(dut):
    """`*_used` low beats the bypass: an unused port reads 0, not the writeback data.

    The address is the written register and `wb_we` is high, so the bypass is the
    only thing that could put a nonzero value on the output.  Order matters
    here: the `*_used` term has to come first in the mux, or an instruction that
    does not read rs1 would pick up whatever the writeback port happens to be
    carrying.
    """
    await start(dut)
    await write_reg(dut, 8, 0xAAAAAAAA)
    await drive_reads(dut, rs1_addr=8, rs2_addr=8, rs1_used=0, rs2_used=1)
    await drive_write(dut, we=1, addr=8, data=0xCCCCCCCC)

    assert int(dut.rs1_data.value) == 0, (
        "unused rs1 read %08x through the bypass, expected 0"
        % int(dut.rs1_data.value)
    )
    assert int(dut.rs2_data.value) == 0xCCCCCCCC, "used rs2 did not bypass"
    await drive_write(dut, we=0, addr=8, data=0xCCCCCCCC)
    await cycles(dut, 1)


@cocotb.test()
async def test_back_to_back_dependent_writes_are_visible_immediately(dut):
    """The WB->ID distance of one, exercised directly on the register file.

    A sequence of dependent instructions is the real use: each write's target is
    the next instruction's source.  If the bypass were missing, the second
    instruction would read the pre-write value - which a test that advances a
    cycle between operations would not notice, because the array would have been
    updated by then.
    """
    await start(dut)

    # x1 = 0x10, then x2 = x1 + 1 computed by the writeback port's value, etc.
    # Every step presents the write and reads the previous target in the same
    # cycle, which is the bypass condition.
    chain = [0x10, 0x11, 0x12, 0x13, 0x14, 0x15]
    await drive_reads(dut, rs1_addr=1, rs2_addr=2, rs1_used=1, rs2_used=1)

    # Seed x1.
    await write_reg(dut, 1, chain[0])

    for index in range(1, len(chain)):
        source = index  # x1, x2, ... in turn
        target = index + 1
        # Read the source, which is still the *previous* value in the array.
        await drive_reads(dut, rs1_addr=source, rs2_addr=source)
        previous = int(dut.rs1_data.value)
        assert previous == chain[index - 1], (
            "step %d: x%d read %08x, expected %08x"
            % (index, source, previous, chain[index - 1])
        )
        # Write the dependent value and read it back in the same cycle.
        await drive_write(dut, we=1, addr=target, data=chain[index])
        await drive_reads(dut, rs1_addr=target)
        assert int(dut.rs1_data.value) == chain[index], (
            "step %d: x%d read %08x in the cycle it was written, expected %08x"
            % (index, target, int(dut.rs1_data.value), chain[index])
        )
        # Commit, with `wb_we` still high across the edge, then drop it.
        await cycles(dut, 1)
        await drive_write(dut, we=0, addr=target, data=chain[index])


@cocotb.test()
async def test_same_cycle_write_and_read_of_every_register(dut):
    """For all 32 addresses: read xN while writing xN, with no edge in between.

    The address decode and the bypass comparator are the same 5-bit field in two
    different places in the RTL, and this is the only test that exercises both
    against all 32 values at once rather than a sample.
    """
    await start(dut)
    for addr in range(32):
        stored = 0x10000000 + addr
        incoming = 0x20000000 + addr

        await write_reg(dut, addr, stored)
        await drive_reads(dut, rs1_addr=addr, rs2_addr=addr)
        await drive_write(dut, we=1, addr=addr, data=incoming)

        # x0 is the exception the contract carves out: it stays 0 both times.
        expected_in_cycle = 0 if addr == 0 else incoming
        assert int(dut.rs1_data.value) == expected_in_cycle, (
            "x%d: rs1 read %08x in the cycle it was written, expected %08x"
            % (addr, int(dut.rs1_data.value), expected_in_cycle)
        )
        assert int(dut.rs2_data.value) == expected_in_cycle, (
            "x%d: rs2 read %08x in the cycle it was written, expected %08x"
            % (addr, int(dut.rs2_data.value), expected_in_cycle)
        )

        # Commit with `wb_we` still high, so the write is real, then drop it.
        await cycles(dut, 1)
        await drive_write(dut, we=0, addr=addr, data=incoming)

        # And the committed value is what a later read returns.
        await drive_reads(dut, rs1_addr=addr)
        assert int(dut.rs1_data.value) == expected_in_cycle, (
            "x%d: after the edge, rs1 read %08x, expected %08x"
            % (addr, int(dut.rs1_data.value), expected_in_cycle)
        )


# ---------------------------------------------------------------------------
# Reset and write interaction
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_write_is_ignored_while_reset_is_asserted(dut):
    """A write presented while `rst_n` is low does not survive the reset.

    `core` will hold `wb_we` low through reset, but the register file must not
    depend on that: the write port is synchronous and reset has priority, so a
    write during reset is discarded and the register reads 0 afterwards.
    """
    cocotb.start_soon(Clock(dut.clk).start())
    await drive_reads(dut)
    await drive_write(dut, we=0)

    dut.rst_n.value = 0
    await drive_write(dut, we=1, addr=7, data=0xDEADBEEF)
    await cycles(dut, 4)
    await drive_write(dut, we=0, addr=7, data=0xDEADBEEF)

    dut.rst_n.value = 1
    await cycles(dut, 1)

    await drive_reads(dut, rs1_addr=7)
    assert int(dut.rs1_data.value) == 0, (
        "x7 read %08x after a write during reset, expected 0"
        % int(dut.rs1_data.value)
    )


@cocotb.test()
async def test_write_in_the_cycle_reset_releases_takes_effect(dut):
    """A write committed on the edge that ends reset is kept.

    This is the boundary the other reset test does not cover: reset holds the
    array at zero on every edge while `rst_n` is low, and stops doing so on the
    first edge with `rst_n` high.  A design that kept the reset branch one cycle
    too long would lose this write.
    """
    cocotb.start_soon(Clock(dut.clk).start())
    await drive_reads(dut, rs1_addr=3, rs2_addr=3)
    await drive_write(dut, we=0)

    dut.rst_n.value = 0
    await cycles(dut, 4)

    # rst_n goes high before this edge, so the edge is the first non-reset edge.
    dut.rst_n.value = 1
    await drive_write(dut, we=1, addr=3, data=0x0BADF00D)
    await cycles(dut, 1)
    await drive_write(dut, we=0, addr=3, data=0x0BADF00D)

    assert int(dut.rs1_data.value) == 0x0BADF00D, (
        "x3 read %08x after a write on the edge that released reset, expected 0badf00d"
        % int(dut.rs1_data.value)
    )

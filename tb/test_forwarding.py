"""Regression tests for ``rtl/core/forwarding.v``.

``forwarding`` supplies each execute-stage operand with the newest value written
to it by an earlier instruction.  It is purely combinational -- no clock, no
reset, no state -- so these tests drive inputs and read the outputs after a
settle delay, which is also what lets one file run unchanged under Verilator
(2-state) and Icarus (4-state).

WHICH FORWARDING DISTANCE LIVES WHERE
======================================

A five-stage pipeline has three distances a consumer can need a value over.  This
module's interface exposes exactly two producer registers, so the distances map
onto them like this, and it is worth being explicit because the naming in the
five-stage literature is not consistent:

* **EX-to-EX.**  The producer was in execute last cycle; its result is now held
  in the EX/MEM register.  This is the back-to-back ALU case (``add`` then
  ``sub`` using the same register) and it arrives on the ``mem_rd_*`` inputs.
  Tested by :func:`test_ex_to_ex_forwarding_into_rs1` and its rs2 twin.

* **MEM-to-EX.**  The producer was in memory; its result is now held in the
  MEM/WB register.  It arrives on the ``fwd_rd_*`` inputs.  Tested by
  :func:`test_mem_to_ex_forwarding`.

* **WB-to-EX.**  The producer has already reached writeback and written the
  register file, so the consumer is served by ``regfile``'s writeback bypass
  (regfile.v, "WRITE-BACK BYPASS") at zero stall.  That path is **not** in this
  module and cannot be reached from these inputs -- what *is* testable here is
  that the network correctly declines to forward, because with neither producer
  register targeting the operand there is nothing to forward.  Tested by
  :func:`test_wb_to_ex_leaves_the_operand_to_regfile`, which is a negative test
  and would fail if this module invented a forward the register file has to
  override.

The load-use distance is deliberately absent: a load's data is not in either
producer register in time, which is why :mod:`hazard_unit` holds decode for that
cycle.  ``mem_reg_write`` is defined by the contract as "the MEM-stage value is
valid", so this module trusts its producers and asserts nothing about what kind
of instruction produced the value.

WHY THE X0 AND id_uses_* CASES ARE THE INTERESTING ONES
========================================================

Both producers are gated on the destination not being x0, and both matches are
gated on the consumer actually reading that register.  Neither gate is optional:

* an x0 destination means the producer wrote no register at all, so no consumer
  can be depending on it -- forwarding a value into an instruction that reads x0
  would corrupt it;
* ``ex_rs1_addr`` / ``ex_rs2_addr`` carry whatever bits the encoding put in that
  field whether or not the instruction reads the register, because for ``lui``
  and ``addi`` those bits are part of the immediate.  An address match on an
  unread source is not a dependency, and reporting one would hand ``ex_stage`` a
  forward for an operand it never consumes.

Expected values come from two independent sources: hand-written constants for
the canonical cases, and a reference function derived from the contract prose.  A
test that only compares the RTL against a second implementation of the same idea
can agree with a shared misreading, whereas a constant cannot.

Run with::

    make test TOP=forwarding
    make test-4state TOP=forwarding
"""

import cocotb
from cocotb.triggers import Timer

# `p_REG_ADDR_W` is 5, so every architectural register index is 0..31.
NREGS = 32

X0 = 0
T1, T2, T3 = 5, 9, 17

# Deliberately different and complementary patterns for the two producers, so a
# swapped data mux or a wrong priority shows up as the wrong value rather than
# passing because both producers happened to agree.
MEM_DATA = 0xAAAA_AAAA
WB_DATA = 0x5555_5555

MASK32 = 0xFFFF_FFFF


async def settle(dut):
    """Let the combinational block re-evaluate.

    ``forwarding`` has no clock, so there is no edge to wait for.  A Timer of a
    real duration rather than a bare delta is used so the same code works under
    both Verilator and Icarus.
    """
    await Timer(1, unit="ns")


def reference(use, ex_addr, mem_addr, mem_data, mem_we,
              wb_addr, wb_data, wb_we):
    """The (valid, data) pair this module owes one source operand.

    Written from the contract prose rather than from the RTL's expression of it:
    forward when one of the two producer registers targets the operand the
    instruction actually reads, with the younger register (the one named ``mem``
    here) taking priority.
    """
    mem_hit = bool(use) and bool(mem_we) and mem_addr != X0 and mem_addr == ex_addr
    wb_hit = bool(use) and bool(wb_we) and wb_addr != X0 and wb_addr == ex_addr
    if mem_hit:
        return 1, mem_data
    if wb_hit:
        return 1, wb_data
    return 0, None


async def check(dut, **drive):
    """Drive one combination and compare all four outputs against the reference.

    ``fwd_*_data`` is only checked where the matching ``fwd_*_valid`` is high.
    When valid is low the data output is a don't-care -- the contract drives it
    unconditionally so ``ex_stage`` need not gate its read -- so asserting on it
    would be asserting on unspecified behaviour.
    """
    inputs = {
        "ex_rs1_addr": X0,
        "ex_rs2_addr": X0,
        "id_uses_rs1": 0,
        "id_uses_rs2": 0,
        "mem_rd_addr": X0,
        "mem_rd_data": MEM_DATA,
        "mem_reg_write": 0,
        "fwd_rd_addr": X0,
        "fwd_rd_data": WB_DATA,
        "fwd_reg_write": 0,
    }
    inputs.update(drive)
    for name, value in inputs.items():
        getattr(dut, name).value = value
    await settle(dut)

    got1, got2 = int(dut.fwd_rs1_valid.value), int(dut.fwd_rs2_valid.value)
    exp1, exp2 = reference(
        inputs["id_uses_rs1"], inputs["ex_rs1_addr"],
        inputs["mem_rd_addr"], inputs["mem_rd_data"], inputs["mem_reg_write"],
        inputs["fwd_rd_addr"], inputs["fwd_rd_data"], inputs["fwd_reg_write"],
    ), reference(
        inputs["id_uses_rs2"], inputs["ex_rs2_addr"],
        inputs["mem_rd_addr"], inputs["mem_rd_data"], inputs["mem_reg_write"],
        inputs["fwd_rd_addr"], inputs["fwd_rd_data"], inputs["fwd_reg_write"],
    )
    where = " ".join("%s=%d" % (k, v) for k, v in sorted(inputs.items()))
    assert got1 == exp1[0], "fwd_rs1_valid=%d, expected %d for %s" % (got1, exp1[0], where)
    assert got2 == exp2[0], "fwd_rs2_valid=%d, expected %d for %s" % (got2, exp2[0], where)
    if exp1[0]:
        d1 = int(dut.fwd_rs1_data.value)
        assert d1 == exp1[1], "fwd_rs1_data=%08x, expected %08x for %s" % (d1, exp1[1], where)
    if exp2[0]:
        d2 = int(dut.fwd_rs2_data.value)
        assert d2 == exp2[1], "fwd_rs2_data=%08x, expected %08x for %s" % (d2, exp2[1], where)
    return got1, got2


# ---------------------------------------------------------------------------
# EX-to-EX: the EX/MEM register holding what execute produced last cycle.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_ex_to_ex_forwarding_into_rs1(dut):
    """An ALU result feeding rs1, with hand-written expectations."""
    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=T1,
        mem_rd_addr=T1, mem_rd_data=MEM_DATA, mem_reg_write=1,
    ) == (1, 0), "an EX result feeding rs1 must forward into rs1 only"

    # Control: the same producer, but the consumer reads a different register.
    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=T2,
        mem_rd_addr=T1, mem_rd_data=MEM_DATA, mem_reg_write=1,
    ) == (0, 0), "an EX result must not forward to an unrelated register"


@cocotb.test()
async def test_ex_to_ex_forwarding_into_rs2(dut):
    """An ALU result feeding rs2, with hand-written expectations."""
    assert await check(
        dut,
        id_uses_rs2=1, ex_rs2_addr=T2,
        mem_rd_addr=T2, mem_rd_data=MEM_DATA, mem_reg_write=1,
    ) == (0, 1), "an EX result feeding rs2 must forward into rs2 only"

    assert await check(
        dut,
        id_uses_rs2=1, ex_rs2_addr=T3,
        mem_rd_addr=T2, mem_rd_data=MEM_DATA, mem_reg_write=1,
    ) == (0, 0), "an EX result must not forward to an unrelated rs2"


@cocotb.test()
async def test_ex_to_ex_into_both_sources_when_they_are_the_same_register(dut):
    """rs1 and rs2 may be the same register; both must be fed."""
    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=T1,
        id_uses_rs2=1, ex_rs2_addr=T1,
        mem_rd_addr=T1, mem_rd_data=MEM_DATA, mem_reg_write=1,
    ) == (1, 1), "a producer matching both sources must forward to both"


# ---------------------------------------------------------------------------
# MEM-to-EX: the MEM/WB register holding what memory passed on.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_mem_to_ex_forwarding(dut):
    """The MEM/WB register supplies the operand when the EX/MEM one does not."""
    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=T1,
        fwd_rd_addr=T1, fwd_rd_data=WB_DATA, fwd_reg_write=1,
    ) == (1, 0), "a MEM/WB value feeding rs1 must forward into rs1"

    assert await check(
        dut,
        id_uses_rs2=1, ex_rs2_addr=T2,
        fwd_rd_addr=T2, fwd_rd_data=WB_DATA, fwd_reg_write=1,
    ) == (0, 1), "a MEM/WB value feeding rs2 must forward into rs2"

    # The producer must be asserted as writing a register; `fwd_reg_write` low
    # means the register holds something that is not a new value.
    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=T1,
        fwd_rd_addr=T1, fwd_rd_data=WB_DATA, fwd_reg_write=0,
    ) == (0, 0), "a non-writing producer must not forward"

    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=T1,
        mem_rd_addr=T1, mem_rd_data=MEM_DATA, mem_reg_write=0,
    ) == (0, 0), "a non-writing EX/MEM producer must not forward"


# ---------------------------------------------------------------------------
# WB-to-EX: served by regfile's writeback bypass, not by this module.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_wb_to_ex_leaves_the_operand_to_regfile(dut):
    """With no producer targeting the operand, this module must not forward.

    A value that has already reached writeback is bypassed into decode by
    ``regfile``, which costs no stall and needs nothing from this network.  The
    observable requirement here is the negative one: forwarding must not fire,
    or it would be overriding the register file's own copy of the newest value
    with a stale one.  The bypass itself is `regfile`'s to test, and
    tb/test_regfile.py does.
    """
    # Producers present and writing, but neither targeting the operand.
    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=T1,
        mem_rd_addr=T2, mem_rd_data=MEM_DATA, mem_reg_write=1,
        fwd_rd_addr=T3, fwd_rd_data=WB_DATA, fwd_reg_write=1,
    ) == (0, 0), "no producer targeting the operand means no forward"

    # Both registers idle, which is the steady state between hazards.
    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=T1,
        id_uses_rs2=1, ex_rs2_addr=T2,
    ) == (0, 0), "an idle network must forward nothing"


# ---------------------------------------------------------------------------
# MEM over WB priority.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_mem_over_wb_priority_rs1(dut):
    """Both producers targeting rs1: the MEM one wins, and its data is used."""
    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=T1,
        mem_rd_addr=T1, mem_rd_data=MEM_DATA, mem_reg_write=1,
        fwd_rd_addr=T1, fwd_rd_data=WB_DATA, fwd_reg_write=1,
    ) == (1, 0), "both producers matching must still forward exactly once"

    # The data must be MEM's.  `check` compares against the reference, which
    # selects MEM, so this also pins the payload rather than just the flag.
    # Written out here as well because it is the single most important value in
    # the module.
    await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=T1,
        mem_rd_addr=T1, mem_rd_data=MEM_DATA, mem_reg_write=1,
        fwd_rd_addr=T1, fwd_rd_data=WB_DATA, fwd_reg_write=1,
    )
    assert int(dut.fwd_rs1_data.value) == MEM_DATA, (
        "the younger MEM value must win; got %08x, MEM is %08x and WB is %08x"
        % (int(dut.fwd_rs1_data.value), MEM_DATA, WB_DATA)
    )


@cocotb.test()
async def test_mem_over_wb_priority_rs2(dut):
    """Both producers targeting rs2: the MEM one wins."""
    assert await check(
        dut,
        id_uses_rs2=1, ex_rs2_addr=T2,
        mem_rd_addr=T2, mem_rd_data=MEM_DATA, mem_reg_write=1,
        fwd_rd_addr=T2, fwd_rd_data=WB_DATA, fwd_reg_write=1,
    ) == (0, 1), "both producers matching must still forward exactly once"

    await check(
        dut,
        id_uses_rs2=1, ex_rs2_addr=T2,
        mem_rd_addr=T2, mem_rd_data=MEM_DATA, mem_reg_write=1,
        fwd_rd_addr=T2, fwd_rd_data=WB_DATA, fwd_reg_write=1,
    )
    assert int(dut.fwd_rs2_data.value) == MEM_DATA, (
        "the younger MEM value must win; got %08x" % int(dut.fwd_rs2_data.value)
    )


@cocotb.test()
async def test_mem_over_wb_priority_is_not_checked_only_on_sampled_destinations(dut):
    """Priority must hold for every destination, not just the sampled ones.

    The two priority tests above pin the payload at one register, which is where
    a hand-written constant is most convincing.  This one repeats the same
    demand across the whole address space so a priority term that were somehow
    address-dependent could not hide, and it re-checks the payload rather than
    only the flag.  A pure-Python sweep of the reference would have been cheaper,
    but it would have been checking the reference against itself; going through
    the simulator is what makes it a test of the RTL.
    """
    for rd in range(NREGS):
        for src in range(NREGS):
            await check(
                dut,
                id_uses_rs1=1, ex_rs1_addr=src,
                id_uses_rs2=0, ex_rs2_addr=X0,
                mem_rd_addr=rd, mem_rd_data=MEM_DATA, mem_reg_write=1,
                fwd_rd_addr=rd, fwd_rd_data=WB_DATA, fwd_reg_write=1,
            )
            # The flag alone cannot distinguish a right mux from a wrong one, so
            # the payload is compared directly whenever a forward is claimed.
            if int(dut.fwd_rs1_valid.value):
                assert int(dut.fwd_rs1_data.value) == MEM_DATA, (
                    "rd=%d src=%d: MEM must win" % (rd, src)
                )


# ---------------------------------------------------------------------------
# x0 exclusion.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_x0_producer_never_forwards(dut):
    """A producer targeting x0 forwards nothing, however the consumer reads it.

    ``rd == 0`` means the producer wrote no register, so there is nothing to
    forward even when the consumer's address field also reads 0.
    """
    for uses1 in (0, 1):
        for uses2 in (0, 1):
            for we in (0, 1):
                # EX/MEM producer targeting x0, and the consumer reads x0.
                assert await check(
                    dut,
                    id_uses_rs1=uses1, ex_rs1_addr=X0,
                    id_uses_rs2=uses2, ex_rs2_addr=X0,
                    mem_rd_addr=X0, mem_rd_data=MEM_DATA, mem_reg_write=we,
                ) == (0, 0), "an x0 destination must not forward into rs1"
                # MEM/WB producer targeting x0, same expectation.
                assert await check(
                    dut,
                    id_uses_rs1=uses1, ex_rs1_addr=X0,
                    id_uses_rs2=uses2, ex_rs2_addr=X0,
                    fwd_rd_addr=X0, fwd_rd_data=WB_DATA, fwd_reg_write=we,
                ) == (0, 0), "an x0 destination must not forward into rs1"


@cocotb.test()
async def test_x0_producer_loses_to_a_real_one(dut):
    """x0 exclusion must not suppress a genuine producer on the same operand."""
    # The producer targets a real register and the consumer reads it.
    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=T1,
        mem_rd_addr=T1, mem_rd_data=MEM_DATA, mem_reg_write=1,
    ) == (1, 0), "a non-x0 destination must still forward"

    # The other producer sits on x0 while the real one matches: the x0 producer
    # contributes nothing, and the real one still wins.
    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=T1,
        mem_rd_addr=T1, mem_rd_data=MEM_DATA, mem_reg_write=1,
        fwd_rd_addr=X0, fwd_rd_data=WB_DATA, fwd_reg_write=1,
    ) == (1, 0), "an x0 producer must be ignored, not suppress the real one"


@cocotb.test()
async def test_x0_consumer_reads_x0_from_no_producer(dut):
    """Reading x0 must not create a match against an x0 producer."""
    # Both producers idle, consumer reads x0.
    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=X0,
        id_uses_rs2=1, ex_rs2_addr=X0,
    ) == (0, 0), "reading x0 with idle producers must not forward"

    # A real producer on a different register, consumer reads x0.
    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=X0,
        mem_rd_addr=T1, mem_rd_data=MEM_DATA, mem_reg_write=1,
    ) == (0, 0), "a producer on another register must not forward into x0"


# ---------------------------------------------------------------------------
# id_uses_* gating.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_unread_source_is_never_forwarded(dut):
    """A matching address on an unread source must not raise a forward.

    ``ex_rs1_addr`` carries immediate bits for ``lui`` / ``addi``, so a match
    there means nothing unless the instruction reads rs1.
    """
    # rs1 unread but its address field matches the producer.
    assert await check(
        dut,
        id_uses_rs1=0, ex_rs1_addr=T1,
        mem_rd_addr=T1, mem_rd_data=MEM_DATA, mem_reg_write=1,
    ) == (0, 0), "an unread rs1 must not be forwarded into"

    # rs2 unread, rs1 read and matching -- only rs1 forwards.
    assert await check(
        dut,
        id_uses_rs1=1, ex_rs1_addr=T1,
        id_uses_rs2=0, ex_rs2_addr=T1,
        mem_rd_addr=T1, mem_rd_data=MEM_DATA, mem_reg_write=1,
    ) == (1, 0), "only the read source may forward"

    # Neither source read, both address fields matching the producer.
    assert await check(
        dut,
        id_uses_rs1=0, ex_rs1_addr=T1,
        id_uses_rs2=0, ex_rs2_addr=T1,
        mem_rd_addr=T1, mem_rd_data=MEM_DATA, mem_reg_write=1,
    ) == (0, 0), "an instruction reading no register must forward nothing"


# ---------------------------------------------------------------------------
# Exhaustive address sweeps through the simulator.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_exhaustive_ex_rs1_against_each_producer(dut):
    """Every consumer rs1 against every destination of each producer."""
    for rd in range(NREGS):
        for rs1 in range(NREGS):
            await check(
                dut,
                id_uses_rs1=1, ex_rs1_addr=rs1,
                id_uses_rs2=0, ex_rs2_addr=X0,
                mem_rd_addr=rd, mem_reg_write=1,
                fwd_rd_addr=rd, fwd_reg_write=1,
            )
    # Both producers are on the same destination here, so this sweep also
    # re-checks MEM-over-WB priority across the whole address space.


@cocotb.test()
async def test_exhaustive_ex_rs2_against_each_producer(dut):
    """Every consumer rs2 against every destination of each producer."""
    for rd in range(NREGS):
        for rs2 in range(NREGS):
            await check(
                dut,
                id_uses_rs1=0, ex_rs1_addr=X0,
                id_uses_rs2=1, ex_rs2_addr=rs2,
                mem_rd_addr=rd, mem_reg_write=1,
                fwd_rd_addr=rd, fwd_reg_write=1,
            )


@cocotb.test()
async def test_exhaustive_producers_on_different_destinations(dut):
    """MEM and WB on different destinations, across the address space.

    The two producers must be able to serve the same source or different ones
    without either contaminating the other.
    """
    for rd_mem in range(NREGS):
        for rd_wb in range(NREGS):
            await check(
                dut,
                id_uses_rs1=1, ex_rs1_addr=rd_wb,
                id_uses_rs2=1, ex_rs2_addr=rd_mem,
                mem_rd_addr=rd_mem, mem_rd_data=MEM_DATA, mem_reg_write=1,
                fwd_rd_addr=rd_wb, fwd_rd_data=WB_DATA, fwd_reg_write=1,
            )


@cocotb.test()
async def test_all_reg_write_and_use_combinations(dut):
    """Every producer-enable and use-bit combination, over a matching address."""
    for mem_we in (0, 1):
        for wb_we in (0, 1):
            for uses1 in (0, 1):
                for uses2 in (0, 1):
                    await check(
                        dut,
                        id_uses_rs1=uses1, ex_rs1_addr=T1,
                        id_uses_rs2=uses2, ex_rs2_addr=T2,
                        mem_rd_addr=T1, mem_reg_write=mem_we,
                        fwd_rd_addr=T2, fwd_reg_write=wb_we,
                    )
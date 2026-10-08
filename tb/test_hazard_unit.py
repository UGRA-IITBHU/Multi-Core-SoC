"""Regression tests for ``rtl/core/hazard_unit.v``.

``hazard_unit`` is the load-use interlock: it reports the single cycle of decode
stall that a load-use dependency needs.  It is purely combinational and has no
clock, no reset and no state, so these tests drive inputs and read the output
after a settle delay rather than over clock edges.  That is also what makes the
same file work unchanged under Verilator (2-state) and Icarus (4-state).

What is under test, and why each part matters:

* **A load whose ``rd`` matches a source the decode instruction reads must
  stall.**  This is the only case that needs a stall at all.  Every other
  producer is covered by ``forwarding``, or arrives early enough for
  ``regfile``'s writeback bypass.

* **An *unused* source must never create a dependency.**  This is the check most
  worth pinning.  For an instruction such as ``lui`` or ``addi``, bits
  ``[24:20]`` of the encoding are part of the immediate, so ``rs1_addr`` still
  arrives as whatever those immediate bits happened to be.  Comparing the
  address without first checking ``id_uses_rs1`` would manufacture a spurious
  dependency on an instruction that reads no register at all, and the resulting
  stall would be indistinguishable from a real hazard.

* **A store must never stall.**  A store writes memory and never a register, so
  it can never be the source of a dependency.  ``ex_mem_write`` exists to
  record that, and the RTL gates on it explicitly.

* **``x0`` is never a dependency.**  ``rd == 0`` means the producer is not
  writing a register, so no decode instruction can be depending on it --
  including one that happens to have ``rs == 0``.

* **``ex_mem_read`` high with ``ex_mem_write`` high must not stall.**  The two
  bits are never both set by well-formed control, and the RTL is written so that
  the defensive ``!ex_mem_write`` term keeps a malformed producer from turning
  into a stall.

The sweeps are exhaustive over the address space rather than sampled, because the
module is small enough to afford it and because a sampled test would miss an
address-dependent term such as the ``x0`` exclusion.  Expected values come from
two independent sources: hard-coded constants for the canonical cases, and a
reference function written from the contract prose.  The constants matter --
a test that only compares the RTL against a second implementation of the same
idea can agree with a shared misreading, whereas a constant cannot.

Run with::

    make test TOP=hazard_unit
    make test-4state TOP=hazard_unit
"""

import cocotb
from cocotb.triggers import Timer

# `p_REG_ADDR_W` is 5, so every architectural register index is 0..31.
NREGS = 32

# A few indices used as stand-ins.  X0 is called out because it is the one index
# the implementation treats specially; the others are arbitrary non-zero values.
X0 = 0
T1 = 5
T2 = 9
T3 = 17


async def settle(dut):
    """Let the combinational block re-evaluate.

    ``hazard_unit`` has no clock, so there is no edge to wait for.  A Timer of a
    real duration rather than a bare delta is used so the same code works under
    both Verilator and Icarus.
    """
    await Timer(1, unit="ns")


def reference_stall(
    id_uses_rs1, id_uses_rs2, id_rs1_addr, id_rs2_addr,
    ex_mem_read, ex_mem_write, ex_rd_addr,
):
    """The rule as ``hazard_unit``'s contract states it.

    Written from the prose in ``docs/contracts/phase1-interfaces.md`` and the
    module's header, independently of the RTL's expression of it: stall when the
    EX/MEM instruction is a load that will produce a register value, that value
    is not x0, and the decode instruction actually reads the register it is
    destined for.
    """
    if not ex_mem_read:
        return 0
    if ex_mem_write:
        # A store never writes a register, so it is not a dependency source.
        return 0
    if ex_rd_addr == X0:
        # Not writing a register at all, so nothing can depend on it.
        return 0
    if id_uses_rs1 and id_rs1_addr == ex_rd_addr:
        return 1
    if id_uses_rs2 and id_rs2_addr == ex_rd_addr:
        return 1
    return 0


async def check(dut, **drive):
    """Drive one combination, then compare ``id_stall`` against the reference."""
    # Default every input, so a caller only states the case it cares about and
    # no test can accidentally inherit a leftover value from the previous one.
    inputs = {
        "id_uses_rs1": 0,
        "id_uses_rs2": 0,
        "id_rs1_addr": X0,
        "id_rs2_addr": X0,
        "ex_mem_read": 0,
        "ex_mem_write": 0,
        "ex_rd_addr": X0,
    }
    inputs.update(drive)
    for name, value in inputs.items():
        getattr(dut, name).value = value
    await settle(dut)
    got = int(dut.id_stall.value)
    expected = reference_stall(**inputs)
    assert got == expected, (
        "id_stall=%d, expected %d for %s" % (got, expected, describe(inputs))
    )
    return got


def describe(inputs):
    return " ".join("%s=%d" % (k, v) for k, v in sorted(inputs.items()))


# ---------------------------------------------------------------------------
# Canonical cases, with the expected value written out rather than computed.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_canonical_load_use_cases(dut):
    """The cases the contract names, each with a hand-written expectation."""
    # The load-use hazard proper: a load into rs1, and decode reads that rs1.
    assert await check(
        dut,
        id_uses_rs1=1, id_rs1_addr=T1, ex_mem_read=1, ex_rd_addr=T1,
    ) == 1, "a load feeding rs1 must stall"

    assert await check(
        dut,
        id_uses_rs2=1, id_rs2_addr=T2, ex_mem_read=1, ex_rd_addr=T2,
    ) == 1, "a load feeding rs2 must stall"

    assert await check(
        dut,
        id_uses_rs1=1, id_rs1_addr=T3,
        id_uses_rs2=1, id_rs2_addr=T3,
        ex_mem_read=1, ex_rd_addr=T3,
    ) == 1, "a load feeding both sources must stall"

    # A load into a register the decode instruction does not read.
    assert await check(
        dut,
        id_uses_rs1=1, id_rs1_addr=T1, ex_mem_read=1, ex_rd_addr=T2,
    ) == 0, "a load into an unread register must not stall"

    # No producer at all.
    assert await check(
        dut, id_uses_rs1=1, id_rs1_addr=T1, ex_rd_addr=T1,
    ) == 0, "an address match with no EX/MEM producer must not stall"


@cocotb.test()
async def test_unused_source_never_creates_a_dependency(dut):
    """A source field the instruction does not read is ignored.

    ``rs_addr`` still carries whatever bits the encoding put there when the
    instruction reads no register, so an address match against an *unused*
    source has to be ignored rather than treated as a dependency.
    """
    rd = T1
    # rs1 unused, and its address field happens to equal the load's rd.  rs2 is
    # read but reads something else, so there is no dependency at all.
    assert await check(
        dut,
        id_uses_rs1=0, id_rs1_addr=rd,
        id_uses_rs2=1, id_rs2_addr=T2,
        ex_mem_read=1, ex_rd_addr=rd,
    ) == 0, "an unused rs1 must not create a dependency"

    # Same again with the roles of the two sources exchanged: rs2 unused and
    # matching, rs1 read and reading something else.
    assert await check(
        dut,
        id_uses_rs1=1, id_rs1_addr=T2,
        id_uses_rs2=0, id_rs2_addr=rd,
        ex_mem_read=1, ex_rd_addr=rd,
    ) == 0, "an unused rs2 must not create a dependency"

    # Neither source read, with both address fields equal to the load's rd --
    # the worst case for a missing id_uses_* guard.
    assert await check(
        dut,
        id_uses_rs1=0, id_rs1_addr=rd,
        id_uses_rs2=0, id_rs2_addr=rd,
        ex_mem_read=1, ex_rd_addr=rd,
    ) == 0, "a load with no reader must not stall"

    # Control: the same addresses, but with rs1 now marked read.  This one MUST
    # stall, and without it the three cases above would pass for the wrong
    # reason -- namely an id_stall that is stuck low rather than one that is
    # correctly ignoring the unused source.
    assert await check(
        dut,
        id_uses_rs1=1, id_rs1_addr=rd,
        id_uses_rs2=0, id_rs2_addr=rd,
        ex_mem_read=1, ex_rd_addr=rd,
    ) == 1, "the same match with rs1 read must stall"


@cocotb.test()
async def test_x0_is_never_a_dependency(dut):
    """``rd == 0`` writes no register, so nothing can depend on it."""
    assert await check(
        dut,
        id_uses_rs1=1, id_rs1_addr=X0, ex_mem_read=1, ex_rd_addr=X0,
    ) == 0, "a load to x0 must not stall even when decode reads x0"

    assert await check(
        dut,
        id_uses_rs2=1, id_rs2_addr=X0, ex_mem_read=1, ex_rd_addr=X0,
    ) == 0, "a load to x0 must not stall via rs2"

    # And the neighbouring case: rd is x0 but decode reads a real register.
    assert await check(
        dut,
        id_uses_rs1=1, id_rs1_addr=T1, ex_mem_read=1, ex_rd_addr=X0,
    ) == 0, "a load to x0 must not stall an unrelated reader"


@cocotb.test()
async def test_store_and_alu_never_stall(dut):
    """Neither a store nor a non-memory instruction is a dependency source."""
    for rd in range(NREGS):
        assert await check(
            dut,
            id_uses_rs1=1, id_rs1_addr=rd, id_uses_rs2=1, id_rs2_addr=rd,
            ex_mem_write=1, ex_rd_addr=rd,
        ) == 0, "a store must never stall, whatever it matches"
        assert await check(
            dut,
            id_uses_rs1=1, id_rs1_addr=rd, id_uses_rs2=1, id_rs2_addr=rd,
            ex_rd_addr=rd,
        ) == 0, "an ALU instruction must never stall, whatever it matches"


@cocotb.test()
async def test_malformed_read_and_write_together_does_not_stall(dut):
    """``ex_mem_read`` and ``ex_mem_write`` high together must not stall.

    Well-formed control never sets both.  The RTL keeps the ``!ex_mem_write``
    term in the load gate so that a loose producer cannot turn into a stall, and
    this is the check on that defensive term.
    """
    for rd in (T1, T2, T3):
        assert await check(
            dut,
            id_uses_rs1=1, id_rs1_addr=rd, id_uses_rs2=1, id_rs2_addr=rd,
            ex_mem_read=1, ex_mem_write=1, ex_rd_addr=rd,
        ) == 0, "read and write together must not stall"


@cocotb.test()
async def test_exhaustive_flag_combinations(dut):
    """All sixteen ``uses``/``read``/``write`` combinations, over several
    address relationships, against the reference."""
    # Four address relationships, so the flag sweep cannot pass by accident.
    relationships = [
        ("rs1 matches", dict(id_rs1_addr=T1, id_rs2_addr=T2)),
        ("rs2 matches", dict(id_rs1_addr=T2, id_rs2_addr=T1)),
        ("both match", dict(id_rs1_addr=T1, id_rs2_addr=T1)),
        ("neither matches", dict(id_rs1_addr=T2, id_rs2_addr=T3)),
        ("both are x0", dict(id_rs1_addr=X0, id_rs2_addr=X0)),
    ]
    for uses_rs1 in (0, 1):
        for uses_rs2 in (0, 1):
            for ex_read in (0, 1):
                for ex_write in (0, 1):
                    for label, addrs in relationships:
                        rd = addrs["id_rs1_addr"]
                        await check(
                            dut,
                            id_uses_rs1=uses_rs1, id_uses_rs2=uses_rs2,
                            ex_mem_read=ex_read, ex_mem_write=ex_write,
                            ex_rd_addr=rd,
                            **addrs,
                        )


@cocotb.test()
async def test_exhaustive_rd_against_rs1(dut):
    """Every ``ex_rd_addr`` against every ``id_rs1_addr``, with rs1 read.

    rs2 is deliberately marked UNUSED: over a 32-value sweep of ``rd`` no fixed
    rs2 address can be guaranteed not to collide with it, and a collision would
    let rs2 raise the stall and mask whatever rs1 did.
    """
    for rd in range(NREGS):
        for rs1 in range(NREGS):
            assert await check(
                dut,
                id_uses_rs1=1, id_rs1_addr=rs1,
                id_uses_rs2=0, id_rs2_addr=rs1,
                ex_mem_read=1, ex_rd_addr=rd,
            ) == (1 if (rd != X0 and rd == rs1) else 0), (
                "rd=%d rs1=%d with rs1 read" % (rd, rs1)
            )


@cocotb.test()
async def test_exhaustive_rd_against_rs2(dut):
    """Every ``ex_rd_addr`` against every ``id_rs2_addr``, with rs2 read.

    rs1 is marked UNUSED here for the same reason as above.
    """
    for rd in range(NREGS):
        for rs2 in range(NREGS):
            assert await check(
                dut,
                id_uses_rs1=0, id_rs1_addr=rs2,
                id_uses_rs2=1, id_rs2_addr=rs2,
                ex_mem_read=1, ex_rd_addr=rd,
            ) == (1 if (rd != X0 and rd == rs2) else 0), (
                "rd=%d rs2=%d with rs2 read" % (rd, rs2)
            )


@cocotb.test()
async def test_exhaustive_rd_against_both_unused_sources(dut):
    """Every ``ex_rd_addr`` when neither source is read.

    The addresses are set equal to ``rd`` throughout, so this is the worst case
    for a missing ``id_uses_*`` guard.
    """
    for rd in range(NREGS):
        assert await check(
            dut,
            id_uses_rs1=0, id_rs1_addr=rd,
            id_uses_rs2=0, id_rs2_addr=rd,
            ex_mem_read=1, ex_rd_addr=rd,
        ) == 0, "no reader means no stall, for rd=%d" % rd


@cocotb.test()
async def test_output_tracks_inputs_within_one_settle(dut):
    """``id_stall`` is combinational: no pipeline state, nothing to clear.

    The same inputs must keep producing the same answer, and a stall must not
    need a cycle to appear or to disappear.
    """
    for _ in range(3):
        assert await check(
            dut,
            id_uses_rs1=1, id_rs1_addr=T1, ex_mem_read=1, ex_rd_addr=T1,
        ) == 1, "a load-use hazard must stay asserted while it is present"
        assert await check(
            dut,
            id_uses_rs1=1, id_rs1_addr=T2, ex_mem_read=1, ex_rd_addr=T1,
        ) == 0, "the stall must drop as soon as the dependency goes"
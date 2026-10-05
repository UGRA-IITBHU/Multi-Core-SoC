"""Regression tests for ``rtl/core/mem_stage.v``.

Drives the module with the shared helpers in ``tb/conftest.py``.

This module owns the MEM/WB register, so almost every test here is about *when*
a value appears rather than *what* it is.  The contract makes four promises, and
each has a test:

* **three writeback sources, not two** - ``wb_sel`` 0 is the ALU result, 1 is the
  returned word, and 2 is ``pc + 4``.  The third is the one that distinguishes
  this design from a textbook two-way load mux: a ``JAL`` writes its link
  register from the PC, not from the ALU and not from memory, and a mux that
  cannot express it turns every taken jump into a jump into garbage;
* **the selection is registered, so the word memory returns is captured** -
  ``mem_rsp_rdata`` is sampled on the edge that ends the access, which is exactly
  what ``mem_rsp_valid`` promises;
* **a stall holds the stage** - the value, and the misalignment verdict that
  belongs with it, must not move while the stage is held, or ``core``'s
  suppression would land on the wrong instruction;
* **a write to ``x0`` is discarded** - Review Focus 3, enforced here, again at
  ``wb_stage`` and again at ``regfile``.

Because the outputs are registered, every test drives an input, takes an edge and
*then* reads - which is what ``conftest.cycles`` exists to make safe.

Run with::

    make test MODULE=test_mem_stage TOP=mem_stage
    make test-4state MODULE=test_mem_stage TOP=mem_stage
"""

import cocotb
from conftest import Clock, cycles, reset

XLEN_MASK = 0xFFFFFFFF

# `wb_sel`, frozen by docs/contracts/phase1-interfaces.md.
WB_SEL_ALU = 0
WB_SEL_MEM = 1
WB_SEL_PC4 = 2

# Distinct values, so a source that is wrong is obvious rather than accidentally
# right - in particular the ALU result and the returned word must never coincide.
V = {
    "alu": 0x11111111,
    "mem": 0xCAFEF00D,
    "pc": 0x0000BEE0,
    "data": 0xDEADBEEF,
    "other": 0xA5A5A5A5,
}


async def settle(dut):
    """Let pending signal writes take effect before anything is read back.

    cocotb applies a signal assignment on the next delta cycle, so a test that
    drives inputs and reads an output in the same delta reads the *previous*
    value.  A real 1 ns is used rather than a bare delta so the same code works
    under both simulators.
    """
    from cocotb.triggers import Timer

    await Timer(1, unit="ns")


async def drive(
    dut,
    alu_result=V["alu"],
    pc=V["pc"],
    rsp_rdata=V["mem"],
    rd_addr=5,
    reg_write=1,
    wb_sel=WB_SEL_ALU,
    misaligned=0,
    stall=0,
):
    """Present an access as EX/MEM would, with the stage released."""
    dut.mem_alu_result.value = alu_result
    dut.mem_pc.value = pc
    dut.mem_rsp_rdata.value = rsp_rdata
    dut.mem_rd_addr.value = rd_addr
    dut.mem_reg_write.value = reg_write
    dut.mem_wb_sel.value = wb_sel
    dut.lsu_data_misaligned.value = misaligned
    dut.stall.value = stall
    await settle(dut)


async def start(dut):
    """Clock running, reset released, every input parked.

    The inputs are parked *before* the reset as well as after it, and that order
    matters: `conftest.reset` holds the reset across ten edges and then takes one
    more edge with it released, and on that last edge this module captures
    whatever is on its inputs.  Parking them only afterwards therefore leaves the
    stage holding the last value the *previous* test happened to leave behind -
    which is invisible in a suite where every test ends on the same value and
    breaks the first time one does not.
    """
    cocotb.start_soon(Clock(dut.clk).start())
    await drive(dut, alu_result=0, pc=0, rsp_rdata=0, rd_addr=0,
                reg_write=0, wb_sel=WB_SEL_ALU, misaligned=0, stall=0)
    await reset(dut)
    await drive(dut, alu_result=0, pc=0, rsp_rdata=0, rd_addr=0,
                reg_write=0, wb_sel=WB_SEL_ALU, misaligned=0, stall=0)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_writeback_value_is_zero_after_reset(dut):
    """Both outputs read zero once reset is released.

    Not a formality: a writeback value that is not reset to something defined is
    whatever the flops powered up with, and Verilator's two-state model reports
    that as 0 and so hides the difference.  That is what `make test-4state` is
    for, and it is why this assertion is checked rather than assumed.
    """
    await start(dut)
    assert int(dut.mem_rd_data.value) == 0, (
        "mem_rd_data is %08x after reset, expected 0" % int(dut.mem_rd_data.value)
    )
    assert int(dut.data_misaligned.value) == 0, (
        "data_misaligned is %d after reset, expected 0"
        % int(dut.data_misaligned.value)
    )


@cocotb.test()
async def test_reset_clears_a_writeback_that_was_staged(dut):
    """Reset clears real state, not just the power-up value.

    Staging a value and then reading zero proves nothing about the reset path: it
    is equally consistent with a reset that does not exist.  So this dirties the
    stage first and asserts reset puts it back.

    The stage is *held* across the reset (`stall` stays high), which is what makes
    the check conclusive: with the hold in place nothing else can change the
    register, so the zero can only have come from the reset.  Without it the
    register would simply re-capture whatever the inputs say on the first edge
    after reset is released, and the test would pass on a module with no reset at
    all.
    """
    await start(dut)
    await drive(dut, alu_result=V["data"], wb_sel=WB_SEL_ALU, rd_addr=9,
                reg_write=1, misaligned=1, stall=0)
    await cycles(dut, 1)
    assert int(dut.mem_rd_data.value) == V["data"], "precondition: the value must stage"
    assert int(dut.data_misaligned.value) == 1, "precondition: the verdict must stage"

    await drive(dut, alu_result=V["data"], wb_sel=WB_SEL_ALU, rd_addr=9,
                reg_write=1, misaligned=1, stall=1)
    await reset(dut)
    assert int(dut.mem_rd_data.value) == 0, (
        "mem_rd_data still reads %08x after a second reset, expected 0"
        % int(dut.mem_rd_data.value)
    )
    assert int(dut.data_misaligned.value) == 0, (
        "a misalignment verdict survived reset"
    )


# ---------------------------------------------------------------------------
# The three writeback sources
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_alu_result_is_selected(dut):
    """`wb_sel` 0 is the ALU result - the common case, and the one that decides
    whether an ordinary add or a branch works at all."""
    await start(dut)
    for value in (0x00000000, 0x00000001, V["data"], 0x80000000, 0xFFFFFFFF):
        await drive(dut, alu_result=value, wb_sel=WB_SEL_ALU)
        await cycles(dut, 1)
        assert int(dut.mem_rd_data.value) == value, (
            "wb_sel=0 gave %08x, expected the ALU result %08x"
            % (int(dut.mem_rd_data.value), value)
        )


@cocotb.test()
async def test_load_data_is_selected(dut):
    """`wb_sel` 1 is the word memory returned.

    Checked at every lane position and for a word that is all ones and all
    zeros, because the returned word is the one value this stage cannot compute
    itself and so cannot accidentally get right.
    """
    await start(dut)
    for value in (0x00000000, 0x00000001, V["mem"], 0x80000000, 0xFFFFFFFF):
        for rd_addr in (1, 5, 31):
            await drive(dut, rsp_rdata=value, wb_sel=WB_SEL_MEM, rd_addr=rd_addr)
            await cycles(dut, 1)
            assert int(dut.mem_rd_data.value) == value, (
                "wb_sel=1 gave %08x, expected the returned word %08x"
                % (int(dut.mem_rd_data.value), value)
            )


@cocotb.test()
async def test_pc_plus_four_is_selected(dut):
    """`wb_sel` 2 is `pc + 4` - the JAL/JALR link register.

    This is the source a two-source mux cannot express, so it gets its own test
    rather than being folded into the other two.
    """
    await start(dut)
    cases = (
        (0x00000000, 0x00000004),
        (0x00000004, 0x00000008),
        (V["pc"], V["pc"] + 4),
        (0xFFFFFFFC, 0x00000000),   # wraps, see the next test
        (0x0000FFF8, 0x0000FFFC),
    )
    for pc, expected in cases:
        await drive(dut, pc=pc, wb_sel=WB_SEL_PC4)
        await cycles(dut, 1)
        assert int(dut.mem_rd_data.value) == expected, (
            "wb_sel=2 at pc=%08x gave %08x, expected %08x"
            % (pc, int(dut.mem_rd_data.value), expected)
        )


@cocotb.test()
async def test_pc_plus_four_wraps_at_the_top_of_the_address_space(dut):
    """A jump from the last word links to 0, not to 33 bits.

    RV32 addresses are 32 bits, so the addition wraps.  Stated as a test because
    the alternative - a 33-bit adder - would be a real bug that every other
    `pc + 4` test would pass.
    """
    await start(dut)
    for pc, expected in (
        (0xFFFFFFFC, 0x00000000),
        (0xFFFFFFF8, 0xFFFFFFFC),
    ):
        await drive(dut, pc=pc, wb_sel=WB_SEL_PC4)
        await cycles(dut, 1)
        assert int(dut.mem_rd_data.value) == expected, (
            "pc+4 at pc=%08x gave %08x, expected %08x (32-bit wrap)"
            % (pc, int(dut.mem_rd_data.value), expected)
        )


@cocotb.test()
async def test_the_source_selects_and_nothing_else_does(dut):
    """With a source selected, changing any *other* input must not move the value.

    The point of a multiplexer with three inputs is that exactly one of them
    chooses the output.  An implementation that ORed the sources together, or that
    reached for `mem_rsp_rdata` unconditionally, passes every "is this source
    selected" test above and fails this one - so for each selection, each of the
    *other* fields is replaced with junk in turn and the value must not move.
    """
    await start(dut)
    reference = dict(
        alu_result=V["alu"], pc=V["pc"], rsp_rdata=V["mem"],
        rd_addr=5, reg_write=1, misaligned=0, stall=0,
    )
    junk = {
        "alu_result": V["other"],
        "pc": 0x00001234,
        "rsp_rdata": 0x00005678,
        "rd_addr": 17,
        "reg_write": 0,
        "misaligned": 1,
    }
    for wb_sel, (selected, want) in enumerate(
        (("alu_result", V["alu"]), ("rsp_rdata", V["mem"]), ("pc", V["pc"] + 4))
    ):
        base = dict(reference)
        base["wb_sel"] = wb_sel
        await drive(dut, **base)
        await cycles(dut, 1)
        assert int(dut.mem_rd_data.value) == want, (
            "wb_sel=%d did not select %s: value is %08x, expected %08x"
            % (wb_sel, selected, int(dut.mem_rd_data.value), want)
        )
        for field, value in junk.items():
            if field == selected:
                continue
            moved = dict(base)
            moved[field] = value
            await drive(dut, **moved)
            await cycles(dut, 1)
            assert int(dut.mem_rd_data.value) == want, (
                "with wb_sel=%d, changing %s to %08x moved the value to %08x; "
                "only %s may select it"
                % (wb_sel, field, value, int(dut.mem_rd_data.value), selected)
            )


@cocotb.test()
async def test_an_unused_wb_sel_falls_back_to_the_alu_result(dut):
    """`wb_sel` of 3 is not an encoding, and lands on the ALU value.

    Chosen over driving zero, because a decoder that leaves the mux input at
    whatever it happens to be would put an undefined word into a register.
    """
    await start(dut)
    await drive(dut, alu_result=V["data"], pc=V["pc"], rsp_rdata=V["mem"],
                wb_sel=3)
    await cycles(dut, 1)
    assert int(dut.mem_rd_data.value) == V["data"], (
        "wb_sel=3 gave %08x, expected the ALU result %08x as the fallback"
        % (int(dut.mem_rd_data.value), V["data"])
    )


# ---------------------------------------------------------------------------
# The stall
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_a_held_stage_holds_its_writeback_value(dut):
    """While `stall` is high the stage keeps the instruction it already has.

    Not "keeps a value that happens to be the same": the inputs are moved to
    completely different ones while the stage is held, so a stage that
    recomputed while held would show the new value.
    """
    await start(dut)
    await drive(dut, alu_result=V["data"], wb_sel=WB_SEL_ALU, rd_addr=5,
                reg_write=1, stall=0)
    await cycles(dut, 1)
    assert int(dut.mem_rd_data.value) == V["data"], "precondition: the stage holds V[data]"

    await drive(dut, alu_result=V["other"], pc=0x0000FFFF, rsp_rdata=V["mem"],
                wb_sel=WB_SEL_MEM, rd_addr=17, reg_write=0, stall=1)
    for _ in range(8):
        assert int(dut.mem_rd_data.value) == V["data"], (
            "a held stage changed its writeback value to %08x"
            % int(dut.mem_rd_data.value)
        )
        await cycles(dut, 1)

    # Releasing the hold admits the access that was waiting.
    await drive(dut, alu_result=V["other"], pc=0x0000FFFF, rsp_rdata=V["mem"],
                wb_sel=WB_SEL_MEM, rd_addr=17, reg_write=0, stall=0)
    await cycles(dut, 1)
    assert int(dut.mem_rd_data.value) == V["mem"], (
        "the released stage did not admit the waiting access, value is %08x"
        % int(dut.mem_rd_data.value)
    )


@cocotb.test()
async def test_a_held_stage_holds_its_misalignment_verdict(dut):
    """The verdict travels with the instruction it belongs to.

    This is the reason the verdict is registered rather than passed straight
    through: a combinational pass-through would let a *later* access's verdict
    reach `wb_stage` for the instruction currently in MEM/WB, and `core` would
    then suppress the wrong instruction's register write.  So while the stage is
    held, a fresh misalignment on the input must not appear on the output.
    """
    await start(dut)
    await drive(dut, misaligned=1, alu_result=V["data"], wb_sel=WB_SEL_ALU)
    await cycles(dut, 1)
    assert int(dut.data_misaligned.value) == 1, "precondition: verdict staged"
    assert int(dut.mem_rd_data.value) == V["data"], "precondition"

    await drive(dut, misaligned=0, alu_result=V["other"], wb_sel=WB_SEL_MEM,
                rsp_rdata=V["mem"], stall=1)
    for _ in range(6):
        assert int(dut.data_misaligned.value) == 1, (
            "a held stage dropped the misalignment verdict belonging to its "
            "instruction - core would stop suppressing the wrong instruction"
        )
        await cycles(dut, 1)

    await drive(dut, misaligned=0, alu_result=V["other"], wb_sel=WB_SEL_MEM,
                rsp_rdata=V["mem"], stall=0)
    await cycles(dut, 1)
    assert int(dut.data_misaligned.value) == 0, (
        "the released stage did not admit the waiting access's clean verdict"
    )
    assert int(dut.mem_rd_data.value) == V["mem"], (
        "the released stage did not admit the waiting access"
    )


# ---------------------------------------------------------------------------
# Misalignment: reported, never gated
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_the_misalignment_verdict_is_reported(dut):
    """`lsu`'s verdict reaches this stage's output unchanged."""
    await start(dut)
    for misaligned in (0, 1):
        await drive(dut, misaligned=misaligned)
        await cycles(dut, 1)
        assert int(dut.data_misaligned.value) == misaligned, (
            "data_misaligned reported %d, expected %d"
            % (int(dut.data_misaligned.value), misaligned)
        )


@cocotb.test()
async def test_misalignment_does_not_suppress_the_writeback_value(dut):
    """A misaligned access still produces a value - this module reports, not gates.

    The contract is explicit that `core` applies the rule
    (`mem_wb__reg_write = mem_reg_write && !mem_stage.data_misaligned`) because
    `mem_reg_write` is an *input* here and a module cannot gate its own input.
    So this test pins the value that `core` will then suppress, rather than
    pretending the suppression belongs here.
    """
    await start(dut)
    await drive(dut, misaligned=1, alu_result=V["data"], wb_sel=WB_SEL_ALU,
                rd_addr=5, reg_write=1)
    await cycles(dut, 1)
    assert int(dut.data_misaligned.value) == 1, "precondition: verdict reported"
    assert int(dut.mem_rd_data.value) == V["data"], (
        "mem_rd_data stopped producing a value for a misaligned access; the "
        "gate belongs in core, not here"
    )


@cocotb.test()
async def test_the_verdict_and_the_value_come_from_the_same_access(dut):
    """A clean access after a misaligned one must not inherit its verdict.

    The pair (value, verdict) describes one instruction.  If the verdict could
    outlive the access it belonged to, `core`'s suppression would be applied to
    the following instruction - the worst possible place for it, because the
    following instruction is a good one.
    """
    await start(dut)
    for misaligned, value in ((1, V["data"]), (0, V["other"]), (1, V["mem"]),
                              (0, V["alu"])):
        await drive(dut, misaligned=misaligned, alu_result=value,
                    wb_sel=WB_SEL_ALU, rd_addr=5, reg_write=1)
        await cycles(dut, 1)
        assert int(dut.data_misaligned.value) == misaligned, (
            "verdict is %d for an access presented with %d"
            % (int(dut.data_misaligned.value), misaligned)
        )
        assert int(dut.mem_rd_data.value) == value, (
            "value is %08x for an access presented with %08x"
            % (int(dut.mem_rd_data.value), value)
        )


# ---------------------------------------------------------------------------
# Review Focus 3: x0
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_a_write_to_x0_still_produces_a_value_here(dut):
    """`j .` is `jal x0, 0`, and this module still selects its link value.

    The `x0` discard is real - Review Focus 3 - but it is *not observable at these
    ports*: `mem_stage` has no write-enable output, so the gate it applies is
    internal.  The port-visible consequence is only that the value is still
    produced.  `core` applies the gate that stops the commit while packing MEM/WB,
    and `wb_stage` applies it again at the other end of the writeback port, both
    of which are tested there.

    What matters here is the negative: a module that produced *nothing* for `x0`
    would make a legal `j .` indistinguishable from a jump with no link value, and
    `core` could not tell a discarded write from a missing one.
    """
    await start(dut)
    await drive(dut, pc=0x00000100, wb_sel=WB_SEL_PC4, rd_addr=0, reg_write=1)
    await cycles(dut, 1)
    assert int(dut.data_misaligned.value) == 0, "precondition"
    assert int(dut.mem_rd_data.value) == 0x00000104, (
        "mem_rd_data is %08x for `jal x0`, expected the link value 00000104"
        % int(dut.mem_rd_data.value)
    )

    # The other two sources behave the same way for a destination of x0.
    await drive(dut, alu_result=V["data"], wb_sel=WB_SEL_ALU, rd_addr=0,
                reg_write=1)
    await cycles(dut, 1)
    assert int(dut.mem_rd_data.value) == V["data"], "alu source, rd = x0"
    await drive(dut, rsp_rdata=V["mem"], wb_sel=WB_SEL_MEM, rd_addr=0,
                reg_write=1)
    await cycles(dut, 1)
    assert int(dut.mem_rd_data.value) == V["mem"], "mem source, rd = x0"


@cocotb.test()
async def test_every_destination_index_is_accepted(dut):
    """All 31 writable registers, including the two neighbours of x0.

    A gate written as `rd_addr > 0` is right by accident here but wrong for
    `rd_addr` being X; a gate written as `rd_addr != 5'd0` is right.  Sweeping the
    whole index space is what tells the two apart.
    """
    await start(dut)
    for rd_addr in range(32):
        await drive(dut, alu_result=rd_addr + 1, wb_sel=WB_SEL_ALU,
                    rd_addr=rd_addr, reg_write=1)
        await cycles(dut, 1)
        assert int(dut.mem_rd_data.value) == rd_addr + 1, (
            "destination x%d produced the wrong value" % rd_addr
        )


# ---------------------------------------------------------------------------
# Sequencing
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_back_to_back_accesses_each_stage_their_own_value(dut):
    """One value per access, in order, with nothing off by one cycle.

    A pipeline stage that is a cycle early or late produces every value the right
    eventually, so a test that only checks the final result proves very little.
    The check here is the whole sequence.
    """
    await start(dut)
    sequence = [
        (V["alu"], WB_SEL_ALU),
        (V["mem"], WB_SEL_MEM),
        (V["pc"] + 4, WB_SEL_PC4),
        (0x00000000, WB_SEL_ALU),
        (0xFFFFFFFF, WB_SEL_MEM),
        (V["data"], WB_SEL_ALU),
    ]
    for value, wb_sel in sequence:
        await drive(dut, alu_result=V["alu"], pc=V["pc"], rsp_rdata=V["mem"],
                    wb_sel=wb_sel)
        await cycles(dut, 1)
        if wb_sel == WB_SEL_ALU:
            await drive(dut, alu_result=value, wb_sel=WB_SEL_ALU)
        elif wb_sel == WB_SEL_MEM:
            await drive(dut, rsp_rdata=value, wb_sel=WB_SEL_MEM)
        else:
            await drive(dut, pc=value - 4, wb_sel=WB_SEL_PC4)
        await cycles(dut, 1)
        assert int(dut.mem_rd_data.value) == value, (
            "expected %08x at step %d, got %08x"
            % (value, sequence.index((value, wb_sel)), int(dut.mem_rd_data.value))
        )


@cocotb.test()
async def test_the_selection_is_taken_on_the_edge_not_before(dut):
    """The value on the wire is the one from *before* the edge.

    `mem_rd_data` is a register output, so between the edge that captures an
    access and the edge that captures the next one it must show the captured
    one.  A combinational mux - or a register updated on the wrong edge - shows
    the incoming access here, and `core` would pack MEM/WB with the wrong
    instruction's data.
    """
    await start(dut)
    await drive(dut, alu_result=V["data"], wb_sel=WB_SEL_ALU)
    assert int(dut.mem_rd_data.value) == 0, (
        "mem_rd_data showed the incoming access before it was captured"
    )
    await cycles(dut, 1)
    assert int(dut.mem_rd_data.value) == V["data"], (
        "mem_rd_data did not show the captured access after the edge"
    )
    # Now change the input: the output must not move until the next edge.
    await drive(dut, alu_result=V["other"], wb_sel=WB_SEL_MEM,
                rsp_rdata=V["mem"])
    assert int(dut.mem_rd_data.value) == V["data"], (
        "mem_rd_data followed its input instead of waiting for the edge"
    )
    await cycles(dut, 1)
    assert int(dut.mem_rd_data.value) == V["mem"], (
        "mem_rd_data did not capture the new access on the edge"
    )

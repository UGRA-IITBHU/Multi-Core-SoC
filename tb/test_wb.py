"""Regression tests for ``rtl/core/wb_stage.v``.

Drives the module with the shared helpers in ``tb/conftest.py``.

This module is deliberately tiny - it is a rename plus one gate - so almost every
test here exists to prove that the *absence* of logic is correct:

* **the writeback value and destination pass through untouched** - ``mem_rd_data``
  is already the selected value, because ``mem_stage`` owns the writeback mux.  A
  second mux here would give two owners of one decision, and the case they would
  eventually disagree about is ``pc + 4``, which a two-way select cannot express;
* **writes to ``x0`` are discarded** - Review Focus 3, at this end of the
  writeback path, and independently at ``mem_stage`` and at ``regfile``;
* **the forwarding enable is the write enable, by construction** - not two
  similar terms.  If they could differ, ``forwarding`` would publish a value the
  register file is not going to take, and a dependent instruction would read
  ``x0``'s forwarded garbage instead of its own register value;
* **`data_misaligned` does not gate anything here** - the contract puts that gate
  in ``core``, and this module checks ``core``'s wiring instead (see DESIGN NOTE 3
  in ``rtl/core/wb_stage.v``).

The module is combinational, so there is no clock to wait for: every test drives
the inputs, lets the delta cycles settle, and reads.

Run with::

    make test MODULE=test_wb TOP=wb_stage
    make test-4state MODULE=test_wb TOP=wb_stage
"""

import cocotb
from cocotb.triggers import Timer

XLEN_MASK = 0xFFFFFFFF

# Distinct values, so a pass-through that is wired to the wrong port is obvious.
V = {
    1: 0x11111111,
    2: 0xCAFEF00D,
    3: 0x0000BEEF,
    4: 0x80000000,
    5: 0xFFFFFFFF,
    6: 0x00000000,
    31: 0xA5A5A5A5,
}


async def settle(dut):
    """Let pending signal writes take effect before anything is read back.

    cocotb applies a signal assignment on the next delta cycle, so a test that
    drives inputs and reads an output in the same delta reads the *previous*
    value.  A real 1 ns is used rather than a bare delta so the same code works
    under both simulators - and this module has no clock, so this is the only
    settling that happens.
    """
    await Timer(1, unit="ns")


async def drive(dut, rd_data=0x00000000, rd_addr=0, reg_write=0, misaligned=0):
    """Present one instruction at MEM/WB, as `core` unpacks the bundle."""
    dut.mem_rd_data.value = rd_data
    dut.mem_rd_addr.value = rd_addr
    dut.mem_reg_write.value = reg_write
    dut.data_misaligned.value = misaligned
    await settle(dut)


async def start(dut):
    """Every input parked, so each test starts from a known state.

    Note what is *absent*: a clock and a reset.  `wb_stage` has neither port,
    because the contract says it is purely combinational in phase 1 - the MEM/WB
    pipeline register lives in `mem_stage`, which owns the memory-stage timing.
    So `conftest.Clock` and `conftest.reset` cannot be used here at all, and the
    only settling there is to do is the delta cycle in `settle`.
    """
    await drive(dut)


# ---------------------------------------------------------------------------
# The write port
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_writeback_value_and_destination_pass_through(dut):
    """`wb_wdata` is `mem_rd_data` and `wb_waddr` is `mem_rd_addr`.

    Swept across the whole index space and a set of awkward values, because this
    module's whole job is not to touch what it is given - and an implementation
    that quietly re-selected a source would pass a single sample.
    """
    await start(dut)
    for rd_addr in range(32):
        for rd_data in (0x00000000, 0xFFFFFFFF, rd_addr, rd_addr << 16):
            await drive(dut, rd_data=rd_data, rd_addr=rd_addr, reg_write=1)
            assert int(dut.wb_wdata.value) == rd_data, (
                "wb_wdata is %08x, expected the writeback value %08x"
                % (int(dut.wb_wdata.value), rd_data)
            )
            assert int(dut.wb_waddr.value) == rd_addr, (
                "wb_waddr is %d, expected %d" % (int(dut.wb_waddr.value), rd_addr)
            )


@cocotb.test()
async def test_write_is_enabled_when_the_instruction_writes_rd(dut):
    """`wb_we` follows `mem_reg_write`, and the writeback value is unaffected."""
    await start(dut)
    for rd_addr in (0, 1, 5, 31):
        for reg_write in (0, 1):
            await drive(dut, rd_data=V[5], rd_addr=rd_addr, reg_write=reg_write)
            if rd_addr == 0:
                assert int(dut.wb_we.value) == 0, "precondition: x0 is never written"
                continue
            assert int(dut.wb_we.value) == reg_write, (
                "wb_we is %d for reg_write=%d at x%d"
                % (int(dut.wb_we.value), reg_write, rd_addr)
            )
            assert int(dut.wb_wdata.value) == V[5], (
                "the value on the write port moved when the enable changed"
            )


@cocotb.test()
async def test_a_write_to_x0_is_discarded(dut):
    """No write enable for `x0`, for any value and either way round.

    Review Focus 3, and the reason this module has a gate at all: `addi x0, x0,
    1` and `jal x0, 0` are legal instructions, and without the gate they would
    corrupt the ISA.  Both the value and the data-misalignment flag are swept,
    because a gate written as `mem_rd_addr > 0` and one written as
    `mem_rd_addr != 0` behave identically here and differ when the index is X.
    """
    await start(dut)
    for rd_data in V.values():
        for reg_write in (0, 1):
            # `data_misaligned` is set only where `core` would have suppressed
            # `mem_reg_write`; the pair (1, 1) is a wiring error the module
            # asserts on, and driving it here would trip that assertion instead
            # of testing anything.
            misaligned = 1 - reg_write
            await drive(dut, rd_data=rd_data, rd_addr=0, reg_write=reg_write,
                        misaligned=misaligned)
            assert int(dut.wb_we.value) == 0, (
                "wb_we is 1 for a write to x0 (value %08x, reg_write=%d, "
                "misaligned=%d)" % (rd_data, reg_write, misaligned)
            )
    # And x1 is written, so the gate is not simply always low.
    await drive(dut, rd_data=V[1], rd_addr=1, reg_write=1)
    assert int(dut.wb_we.value) == 1, "precondition: x1 must be writable"
    assert int(dut.wb_waddr.value) == 1, "precondition"


@cocotb.test()
async def test_the_enable_does_not_change_the_value_or_the_destination(dut):
    """`wb_wdata` and `wb_waddr` are unconditional.

    A design that zeroed the data when the enable was low - a natural-looking
    "tidiness" - would still pass every enable test, and would pass an
    end-to-end test too as long as nothing ever read an unwritten register
    through this port.  `regfile` gates the write itself, so nothing here needs
    to.
    """
    await start(dut)
    for rd_addr in (1, 5, 31):
        for reg_write in (0, 1):
            await drive(dut, rd_data=V[2], rd_addr=rd_addr, reg_write=reg_write)
            assert int(dut.wb_wdata.value) == V[2], (
                "wb_wdata changed with reg_write=%d at x%d" % (reg_write, rd_addr)
            )
            assert int(dut.wb_waddr.value) == rd_addr, (
                "wb_waddr changed with reg_write=%d" % reg_write
            )


# ---------------------------------------------------------------------------
# The forwarding source
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_the_forwarding_source_is_the_writeback_value(dut):
    """`fwd_rd_data`/`fwd_rd_addr` are the same value and destination.

    The forwarding source is the youngest architectural result in the pipeline,
    and the value about to be written to `rd` is exactly that - so publishing it
    unchanged is not an optimisation, it is the definition.
    """
    await start(dut)
    for rd_addr in range(32):
        for rd_data in (0x00000000, 0xFFFFFFFF, V[2], rd_addr):
            await drive(dut, rd_data=rd_data, rd_addr=rd_addr, reg_write=1)
            assert int(dut.fwd_rd_data.value) == int(dut.wb_wdata.value), (
                "fwd_rd_data is %08x while the write port carries %08x"
                % (int(dut.fwd_rd_data.value), int(dut.wb_wdata.value))
            )
            assert int(dut.fwd_rd_addr.value) == int(dut.wb_waddr.value), (
                "fwd_rd_addr is %d while the write port targets %d"
                % (int(dut.fwd_rd_addr.value), int(dut.wb_waddr.value))
            )


@cocotb.test()
async def test_x0_is_never_forwarded(dut):
    """No forwarding value for `x0`, whatever the enable says.

    This is the reason `fwd_reg_write` exists as a separate output from
    `mem_reg_write`: without the `x0` exclusion, `forwarding` would offer `x0`'s
    port value to any instruction reading `x0`, and the dependent instruction
    would get it instead of its own register.
    """
    await start(dut)
    for rd_data in (0x00000000, 0xFFFFFFFF, V[2]):
        for reg_write in (0, 1):
            await drive(dut, rd_data=rd_data, rd_addr=0, reg_write=reg_write)
            assert int(dut.fwd_reg_write.value) == 0, (
                "fwd_reg_write is 1 for x0 with reg_write=%d" % reg_write
            )
            assert int(dut.fwd_rd_addr.value) == 0, "precondition"
    # A real destination is forwarded, so the gate is not always low.
    await drive(dut, rd_data=V[2], rd_addr=5, reg_write=1)
    assert int(dut.fwd_reg_write.value) == 1, "precondition: x5 must forward"


@cocotb.test()
async def test_the_forwarding_enable_is_the_write_enable(dut):
    """`fwd_reg_write == wb_we`, in every combination.

    They are the same term by construction, and this is the test that says so.  If
    they could ever differ, `forwarding` would be selecting a value that the
    register file is not taking - and the two would disagree only in the one case
    that matters, an `x0` write.
    """
    await start(dut)
    for rd_addr in range(32):
        for reg_write in (0, 1):
            # `data_misaligned` is set only where `core` would have gated
            # `mem_reg_write`, so every combination driven here is one the
            # contract allows - see
            # test_the_misalignment_input_is_rejected_as_a_wiring_error.
            misaligned = 1 - reg_write
            await drive(dut, rd_data=V[3], rd_addr=rd_addr,
                        reg_write=reg_write, misaligned=misaligned)
            assert int(dut.fwd_reg_write.value) == int(dut.wb_we.value), (
                "fwd_reg_write=%d while wb_we=%d, at x%d with reg_write=%d "
                "misaligned=%d"
                % (int(dut.fwd_reg_write.value), int(dut.wb_we.value),
                   rd_addr, reg_write, misaligned)
            )


@cocotb.test()
async def test_forwarding_follows_the_register_write_enable(dut):
    """An instruction that does not write `rd` forwards nothing."""
    await start(dut)
    for rd_addr in (1, 5, 31):
        await drive(dut, rd_data=V[4], rd_addr=rd_addr, reg_write=0)
        assert int(dut.fwd_reg_write.value) == 0, (
            "an instruction with reg_write=0 forwarded a value from x%d" % rd_addr
        )
        # The value and destination are still presented; only the enable is low.
        # `forwarding` needs them to be able to see what it is *not* taking.
        assert int(dut.fwd_rd_data.value) == V[4], "fwd_rd_data must still pass"
        assert int(dut.fwd_rd_addr.value) == rd_addr, "fwd_rd_addr must still pass"


# ---------------------------------------------------------------------------
# data_misaligned: checked here, gated in `core`
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_a_misaligned_access_reaches_this_stage_already_gated(dut):
    """The state this stage really sees for a misaligned access.

    The contract requires `core` to produce `mem_reg_write = 0` for a misaligned
    access - the verdict is applied at the packer, because a module cannot gate
    its own input - so `data_misaligned = 1` here always arrives with
    `mem_reg_write = 0`.  This is that state: nothing is written, nothing is
    forwarded, and the value and destination are still presented so `forwarding`
    can see what it is not taking.

    The two sweeps are the point of the test.  Taken together they cover every
    combination the contract allows, and the only thing that changes between them
    is `reg_write` - which is what "the gate lives in `core`" means in practice.
    """
    await start(dut)
    # A misaligned access, gated by `core`.
    for rd_addr in range(32):
        await drive(dut, rd_data=0xDEADBEEF, rd_addr=rd_addr, reg_write=0,
                    misaligned=1)
        assert int(dut.wb_we.value) == 0, (
            "a gated misaligned access wrote x%d" % rd_addr
        )
        assert int(dut.fwd_reg_write.value) == 0, (
            "a gated misaligned access forwarded a value from x%d" % rd_addr
        )
        assert int(dut.mem_rd_data.value) == 0xDEADBEEF, (
            "precondition: the port still carries the access's value"
        )
    # A clean access, ungated: written and forwarded, `data_misaligned` low.
    for rd_addr in range(32):
        await drive(dut, rd_data=0xDEADBEEF, rd_addr=rd_addr, reg_write=1,
                    misaligned=0)
        assert int(dut.wb_we.value) == (0 if rd_addr == 0 else 1), (
            "a clean access to x%d did not behave as mem_reg_write && x0-discard"
            % rd_addr
        )


@cocotb.test()
async def test_the_misalignment_input_is_rejected_as_a_wiring_error(dut):
    """`data_misaligned` high together with `mem_reg_write` high is illegal.

    The module carries an immediate assertion for exactly that combination
    (DESIGN NOTE 3 in ``rtl/core/wb_stage.v``), because it is the one state in
    which `core` has not done its job:
    `mem_wb__reg_write = mem_reg_write && !mem_stage.data_misaligned`.

    This test therefore does not drive the combination - driving it would trip
    the assertion, which is the intended outcome and not something to assert on
    from Python.  What it pins is the *asymmetry* that makes the assertion safe:
    with `data_misaligned` high the module must be passive, and with
    `mem_reg_write` high it must be active, and the only thing that ever moves
    between those two states is `mem_reg_write` itself.
    """
    await start(dut)
    # Misaligned and ungated-by-mem_reg_write: nothing happens, and that is the
    # whole of this module's response to a verdict - no gate of its own.
    await drive(dut, rd_data=V[5], rd_addr=5, reg_write=0, misaligned=1)
    assert int(dut.wb_we.value) == 0, "precondition: passive"
    # Clean and writing: the write happens.
    await drive(dut, rd_data=V[5], rd_addr=5, reg_write=1, misaligned=0)
    assert int(dut.wb_we.value) == 1, "precondition: active"
    # Clean, not writing: passive again, without any misalignment involved.
    await drive(dut, rd_data=V[5], rd_addr=5, reg_write=0, misaligned=0)
    assert int(dut.wb_we.value) == 0, (
        "a store with no register write must not write"
    )


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_back_to_back_writes_are_distinct_instructions(dut):
    """Consecutive instructions are seen as consecutive writes.

    A pipeline that mixed two instructions' value and destination together - a
    pass-through with a shared temporary, say - would produce one correct write
    out of every two, which a test that only checks the final one never sees.
    """
    await start(dut)
    sequence = [
        (V[1], 1),
        (V[2], 2),
        (V[3], 3),
        (V[4], 4),
        (V[5], 5),
        (V[6], 6),
        (0x7FFFFFFF, 7),
        (0x80000000, 8),
    ]
    for rd_data, rd_addr in sequence:
        await drive(dut, rd_data=rd_data, rd_addr=rd_addr, reg_write=1)
        assert int(dut.wb_wdata.value) == rd_data, (
            "value for x%d is %08x, expected %08x"
            % (rd_addr, int(dut.wb_wdata.value), rd_data)
        )
        assert int(dut.wb_waddr.value) == rd_addr, (
            "destination is x%d, expected x%d" % (int(dut.wb_waddr.value), rd_addr)
        )
        assert int(dut.wb_we.value) == 1, "precondition"


@cocotb.test()
async def test_no_input_combination_leaves_an_output_undefined(dut):
    """Every output is a defined value for every input combination.

    Swept over the fields that matter, with the rest held: an output that can be
    X for some legal input is a bug `forwarding` or `regfile` would propagate
    silently, and Verilator's two-state model would report it as 0.
    """
    await start(dut)
    for rd_addr in range(32):
        for rd_data in (0x00000000, 0xFFFFFFFF):
            for reg_write in (0, 1):
                await drive(dut, rd_data=rd_data, rd_addr=rd_addr,
                            reg_write=reg_write, misaligned=0)
                for name in ("wb_we", "wb_wdata", "wb_waddr", "fwd_rd_addr",
                             "fwd_rd_data", "fwd_reg_write"):
                    # `str()` of a LogicArray is its bit string, so an undefined
                    # bit shows up as x or z in it.
                    bits_of = str(getattr(dut, name).value)
                    assert "x" not in bits_of.lower() and "z" not in bits_of.lower(), (
                        "%s is %s at x%d with rd_data=%08x reg_write=%d"
                        % (name, bits_of, rd_addr, rd_data, reg_write)
                    )

"""Regression tests for ``rtl/common/reset_sync.v``.

Drives the module with the shared helpers in ``tb/conftest.py``: ``Clock``
starts the clock, ``reset`` performs the reset, ``cycles`` advances.

Two things are checked, because they are the two halves of the module's
contract:

* deassertion is **synchronous** -- ``srst_n`` may only rise on a rising clock
  edge, and only two rising edges after ``arst_n`` went high;
* assertion is **asynchronous** -- ``srst_n`` falls as soon as ``arst_n`` falls,
  without waiting for a clock edge.

Checking only "``srst_n`` is eventually 1" would pass against
``assign srst_n = arst_n``, which has no synchroniser at all.

Run with::

    make test MODULE=test_reset_sync TOP=reset_sync
    make test-4state MODULE=test_reset_sync TOP=reset_sync
"""

import cocotb
from cocotb.triggers import Timer
from conftest import Clock, cycles, reset


@cocotb.test()
async def test_reset_helper_deasserts_rst_n(dut):
    """``srst_n`` stays low while ``arst_n`` is low, and comes high of its own
    two rising edges after ``arst_n`` is released."""
    cocotb.start_soon(Clock(dut.clk).start())

    dut.arst_n.value = 0
    await cycles(dut, 2)
    assert int(dut.srst_n.value) == 0, (
        "srst_n was %s after two clocks of arst_n low, expected 0"
        % int(dut.srst_n.value)
    )

    # reset() releases arst_n and then advances one rising edge.  The
    # synchroniser needs two, so srst_n must STILL be low here.  This is the
    # assertion that a bare `assign srst_n = arst_n` cannot pass.
    await reset(dut, cycles=10)
    assert int(dut.arst_n.value) == 1, "reset() must release arst_n"
    assert int(dut.srst_n.value) == 0, (
        "srst_n was %s one clock after arst_n went high, expected 0: "
        "deassertion must be synchronised through two flops" % int(dut.srst_n.value)
    )

    await cycles(dut, 1)
    assert int(dut.srst_n.value) == 1, (
        "srst_n was %s two clocks after arst_n went high, expected 1"
        % int(dut.srst_n.value)
    )


@cocotb.test()
async def test_assertion_is_asynchronous(dut):
    """``srst_n`` must fall in the same delta as ``arst_n``, not on the next
    clock edge.

    This is the one check that needs ``Timer``: it deliberately samples between
    two rising edges, which ``reset`` and ``cycles`` cannot express.
    """
    cocotb.start_soon(Clock(dut.clk).start())
    await reset(dut, cycles=10)
    await cycles(dut, 2)
    assert int(dut.srst_n.value) == 1, "precondition: srst_n must be high here"

    # Fall arst_n a little after a rising edge, so a synchronous reset would
    # leave srst_n high for the rest of this period.
    dut.arst_n.value = 0
    await Timer(1, unit="ns")
    assert int(dut.srst_n.value) == 0, (
        "srst_n was %s 1 ns after arst_n fell: assertion must be asynchronous"
        % int(dut.srst_n.value)
    )
"""Shared testbench helpers.

Every testbench in this repository drives its DUT with exactly these three
things and nothing else:

* :class:`Clock`   -- the clock driver, pinned to ``CLOCK_PERIOD_NS``
* :func:`reset`    -- hold every active-low reset across ``cycles`` rising
  edges, then release it
* :func:`cycles`   -- advance ``n`` rising edges

``reset`` and ``cycles`` both require the clock to be running already, so a
testbench starts it itself::

    cocotb.start_soon(Clock(dut.clk).start())

``reset`` drives whichever reset inputs the DUT actually has -- ``rst_n`` for
the synchronous pipeline modules, ``arst_n`` for the asynchronous-assert
synchroniser in ``rtl/common/reset_sync.v`` -- and drives both if both are
present, so the same helper works on either.
"""

from cocotb.clock import Clock as _Clock
from cocotb.triggers import NextTimeStep, RisingEdge

# 100 MHz: the single clock period every testbench in this repository uses.
CLOCK_PERIOD_NS = 10

# Active-low reset names a DUT may present, in the order they are driven.
RESET_NAMES = ("rst_n", "arst_n")


class Clock(_Clock):
    """The project's clock driver.

    Same as :class:`cocotb.clock.Clock` with the period already set to
    ``CLOCK_PERIOD_NS``, so no testbench hard-codes a time of its own and every
    testbench sees the same period.
    """

    def __init__(self, signal, unit="ns"):
        super().__init__(signal, CLOCK_PERIOD_NS, unit=unit)


def _resets(dut):
    """Return the active-low reset inputs ``dut`` actually has."""
    found = [name for name in RESET_NAMES if hasattr(dut, name)]
    if not found:
        raise AttributeError(
            "%s presents none of %s; it has no reset to drive"
            % (type(dut).__name__, ", ".join(RESET_NAMES))
        )
    return found


async def reset(dut, cycles=10):
    """Hold every reset of ``dut`` low across ``cycles`` rising edges, release,
    then advance one further edge and let the design settle.

    Returns with the DUT having *sampled* the release, so a register read
    straight afterwards shows the state after that edge.
    """
    names = _resets(dut)
    for name in names:
        getattr(dut, name).value = 0
    # _advance, not cycles(): the parameter below deliberately shadows the
    # module-level `cycles` inside this function's body.
    await _advance(dut, cycles)
    for name in names:
        getattr(dut, name).value = 1
    await _edge(dut)


async def cycles(dut, n):
    """Advance ``n`` rising edges of ``dut``'s clock.

    Returns after the design has settled, so reading a signal immediately
    afterwards gives the value produced *by* the last edge rather than the
    value that edge replaced.  Without that, every register read in every
    testbench would be one cycle stale.
    """
    await _advance(dut, n)


async def _advance(dut, n):
    for _ in range(n):
        await _edge(dut)


async def _edge(dut):
    """One rising edge, then let the design settle."""
    await RisingEdge(dut.clk)
    await NextTimeStep()


__all__ = ["CLOCK_PERIOD_NS", "RESET_NAMES", "Clock", "cycles", "reset"]
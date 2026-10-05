"""Tests for `pc_gen` -- the PC register and the single redirect funnel.

What is actually under test, and why each test exists:

* `pc` starts at `p_RESET_VEC` on reset and steps by one instruction (4) per
  cycle otherwise.
* `next_pc` is the *combinational* result of the arbiter
  `redirect_valid` > `pred_taken` > `pc + 4`, and `pc` takes exactly the value
  `next_pc` showed in the cycle before, so the two can never disagree about
  which source won.
* `stall` freezes `pc` without freezing the arbiter.
* A redirect outranks `stall` -- see `rtl/core/pc_gen.v` for why that is the
  only safe reading, and the report to the integrator.

The last test is a differential test against a Python model of the arbiter
driven by a seeded pseudo-random stimulus, which is what actually pins the
priority order down: checking each arm once cannot distinguish
`redirect_valid > pred_taken` from `pred_taken > redirect_valid`, and every
value check alone passes an implementation whose arms are simply wrong.
"""

import random

import cocotb
from cocotb.triggers import Timer

from conftest import Clock, cycles, reset

# rtl/common/defs.vh: `p_RESET_VEC is 32'h0000_0000.
RESET_VEC = 0x0000_0000
PC_STEP = 4
MASK = 0xFFFF_FFFF


async def settle():
    """Let combinational logic settle after inputs were driven."""
    await Timer(1, unit="ns")


async def start(dut, **inputs):
    """Clock the DUT, hold reset, release it, and leave the arbiter idle.

    On return `pc` is `RESET_VEC + PC_STEP`: `reset()` advances one edge past
    the release, and on that edge an idle `pc_gen` takes its sequential step.
    Every test starts from that known state instead of from wherever the
    previous test happened to leave the PC.
    """
    cocotb.start_soon(Clock(dut.clk).start())
    idle(dut, **inputs)
    await reset(dut)


def idle(dut, stall=0, redirect_valid=0, redirect_pc=0, pred_taken=0, pred_pc=0):
    """Drive every control input to a stated value."""
    dut.stall.value = stall
    dut.redirect_valid.value = redirect_valid
    dut.redirect_pc.value = redirect_pc
    dut.pred_taken.value = pred_taken
    dut.pred_pc.value = pred_pc


class PcGenModel:
    """Reference model of `pc_gen`, one instance per test."""

    def __init__(self):
        self.pc = RESET_VEC

    def next_pc(self, redirect_valid, redirect_pc, pred_taken, pred_pc):
        """The combinational arbiter, in the contract's priority order."""
        if redirect_valid:
            return redirect_pc & MASK
        if pred_taken:
            return pred_pc & MASK
        return (self.pc + PC_STEP) & MASK

    def step(self, stall, redirect_valid, redirect_pc, pred_taken, pred_pc):
        """Advance one clock edge and return the value `next_pc` must show."""
        nxt = self.next_pc(redirect_valid, redirect_pc, pred_taken, pred_pc)
        if redirect_valid:
            self.pc = redirect_pc & MASK
        elif not stall:
            self.pc = nxt
        return nxt


@cocotb.test()
async def test_resets_to_reset_vector(dut):
    """Reset must return `pc` to `p_RESET_VEC` from any address.

    The PC is walked away from `p_RESET_VEC` first, because "reset to zero"
    and "registers happen to start at zero" look identical on a two-state
    simulator and this test must not be one that passes by accident.
    """
    await start(dut)
    dut.redirect_valid.value = 1
    dut.redirect_pc.value = 0x0000_1000
    await settle()
    await cycles(dut, 1)
    dut.redirect_valid.value = 0
    assert int(dut.pc.value) == 0x0000_1000, "redirect should have moved the PC"

    dut.rst_n.value = 0
    await cycles(dut, 1)
    assert int(dut.pc.value) == RESET_VEC, (
        "pc is 0x%08x after a reset edge, expected the reset vector 0x%08x"
        % (int(dut.pc.value), RESET_VEC)
    )


@cocotb.test()
async def test_increments_by_four(dut):
    """Free-running, `pc` steps by one instruction per cycle, not by more."""
    await start(dut)
    assert int(dut.pc.value) == RESET_VEC + PC_STEP
    for expected in range(
        RESET_VEC + 2 * PC_STEP, RESET_VEC + 6 * PC_STEP, PC_STEP
    ):
        await settle()
        assert int(dut.next_pc.value) == expected, (
            "next_pc is 0x%08x before the edge, expected 0x%08x"
            % (int(dut.next_pc.value), expected)
        )
        await cycles(dut, 1)
        assert int(dut.pc.value) == expected, (
            "pc is 0x%08x, expected 0x%08x" % (int(dut.pc.value), expected)
        )


@cocotb.test()
async def test_next_pc_falls_through_to_pc_plus_four(dut):
    """With no redirect and no prediction, `next_pc` is the sequential step."""
    await start(dut)
    await settle()
    assert int(dut.next_pc.value) == (int(dut.pc.value) + PC_STEP) & MASK


@cocotb.test()
async def test_redirect_overrides_next_pc(dut):
    """A redirect is visible combinationally and taken on the very next edge."""
    await start(dut)
    target = 0x8000_0100
    dut.redirect_valid.value = 1
    dut.redirect_pc.value = target
    await settle()
    assert int(dut.next_pc.value) == target, (
        "next_pc must show the redirect target in the same cycle it is presented"
    )
    await cycles(dut, 1)
    assert int(dut.pc.value) == target


@cocotb.test()
async def test_redirect_outranks_the_prediction(dut):
    """`redirect_valid` > `pred_taken`, not the other way round.

    Both arms asserted at once is the only stimulus that orders them: a value
    check on either arm alone cannot tell the two priorities apart.
    """
    await start(dut)
    dut.pred_taken.value = 1
    dut.pred_pc.value = 0x0000_0700
    dut.redirect_valid.value = 1
    dut.redirect_pc.value = 0x0000_0F00
    await settle()
    assert int(dut.next_pc.value) == 0x0000_0F00
    await cycles(dut, 1)
    assert int(dut.pc.value) == 0x0000_0F00


@cocotb.test()
async def test_predicted_take_uses_pred_pc(dut):
    """A taken prediction redirects to `pred_pc`, not to `pc + 4`."""
    await start(dut)
    target = 0x0000_004C
    dut.pred_taken.value = 1
    dut.pred_pc.value = target
    await settle()
    assert int(dut.next_pc.value) == target
    await cycles(dut, 1)
    assert int(dut.pc.value) == target


@cocotb.test()
async def test_stall_freezes_pc(dut):
    """`stall` holds `pc` for as long as it is asserted, then one step resumes.

    The interesting half is the resume: a PC that advanced anyway, or that
    caught up by taking several steps at once, passes every "is it frozen?"
    check and only misbehaves later.
    """
    await start(dut)
    held = int(dut.pc.value)
    dut.stall.value = 1
    for _ in range(3):
        await settle()
        # next_pc keeps tracking while the register is held: the arbiter is
        # combinational and the stall is applied at the register, not earlier.
        assert int(dut.next_pc.value) == (held + PC_STEP) & MASK
        await cycles(dut, 1)
        assert int(dut.pc.value) == held, "pc moved while stall was asserted"

    dut.stall.value = 0
    await settle()
    await cycles(dut, 1)
    assert int(dut.pc.value) == (held + PC_STEP) & MASK, (
        "pc took more than one step when the stall was released"
    )


@cocotb.test()
async def test_stall_holds_the_prediction_too(dut):
    """A prediction is not a redirect: it waits for the stall to clear."""
    await start(dut)
    held = int(dut.pc.value)
    dut.stall.value = 1
    dut.pred_taken.value = 1
    dut.pred_pc.value = 0x0000_0200
    await settle()
    assert int(dut.next_pc.value) == 0x0000_0200
    await cycles(dut, 1)
    assert int(dut.pc.value) == held, "a prediction must not outrank stall"
    dut.stall.value = 0
    await cycles(dut, 1)
    assert int(dut.pc.value) == 0x0000_0200


@cocotb.test()
async def test_redirect_is_taken_while_stalled(dut):
    """A redirect outranks `stall`; see the note in `rtl/core/pc_gen.v`.

    A redirect arrives from EX on the very cycles the front end may be stalled
    by a load-use interlock.  If `stall` could swallow it, the wrong path
    would be fetched for a whole stall window and nothing downstream would
    report an error, so this is asserted rather than left to the wiring.
    """
    await start(dut)
    target = 0x0000_0300
    dut.stall.value = 1
    dut.redirect_valid.value = 1
    dut.redirect_pc.value = target
    await settle()
    await cycles(dut, 1)
    assert int(dut.pc.value) == target, (
        "a redirect presented while stalled was dropped"
    )


@cocotb.test()
async def test_redirect_to_the_same_address_is_still_a_redirect(dut):
    """The target, not the change, is what `redirect_valid` means.

    A redirect whose target equals the current `pc` looks like a no-op to an
    implementation that watches for a difference, and it must not be.
    """
    await start(dut)
    here = int(dut.pc.value)
    dut.redirect_valid.value = 1
    dut.redirect_pc.value = here
    await settle()
    assert int(dut.next_pc.value) == here
    await cycles(dut, 1)
    assert int(dut.pc.value) == here


@cocotb.test()
async def test_next_pc_previews_the_pc_that_follows(dut):
    """Differential test against a model of the arbiter.

    Seeded pseudo-random stimulus over all four control combinations, 200
    cycles, checking `next_pc` every cycle and `pc` after every edge.  This is
    the test that pins down the arm priority and the stall rule together: an
    implementation with `pred_taken` above `redirect_valid`, or one that
    advances on `pc + 4` while stalled, disagrees with the model here and
    nowhere else.
    """
    await start(dut)
    model = PcGenModel()
    # `start` leaves the DUT one step past the reset vector; start the model
    # from where the PC actually is rather than from the reset vector.
    model.pc = int(dut.pc.value)
    rng = random.Random(0xC0FFEE)
    interesting = [
        (0, 0, 0, 0),
        (1, 0, 0, 0),
        (0, 1, 0x0000_0400, 0),
        (0, 0, 0, 1),
        (0, 1, 0x0000_0400, 1),
        (1, 1, 0x0000_0400, 1),
        (1, 0, 0, 1),
        (0, 1, 0xFFFF_FFFC, 1),
    ]
    for cycle in range(200):
        if cycle < len(interesting):
            stall, redirect_valid, redirect_pc, pred_taken = interesting[cycle]
            pred_pc = 0x0000_0800
        else:
            stall = rng.randint(0, 1)
            redirect_valid = rng.randint(0, 1)
            pred_taken = rng.randint(0, 1)
            redirect_pc = rng.randrange(0, 1 << 32)
            pred_pc = rng.randrange(0, 1 << 32)
        idle(
            dut,
            stall=stall,
            redirect_valid=redirect_valid,
            redirect_pc=redirect_pc,
            pred_taken=pred_taken,
            pred_pc=pred_pc,
        )
        await settle()
        expected_next = model.next_pc(redirect_valid, redirect_pc, pred_taken, pred_pc)
        assert int(dut.next_pc.value) == expected_next, (
            "cycle %d: next_pc is 0x%08x, model says 0x%08x "
            "(stall=%d redirect_valid=%d redirect_pc=0x%08x pred_taken=%d pred_pc=0x%08x)"
            % (
                cycle,
                int(dut.next_pc.value),
                expected_next,
                stall,
                redirect_valid,
                redirect_pc,
                pred_taken,
                pred_pc,
            )
        )
        await cycles(dut, 1)
        model.step(stall, redirect_valid, redirect_pc, pred_taken, pred_pc)
        assert int(dut.pc.value) == model.pc, (
            "cycle %d: pc is 0x%08x, model says 0x%08x"
            % (cycle, int(dut.pc.value), model.pc)
        )

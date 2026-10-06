"""Tests for `if_stage` -- the instruction fetch stage and its memory handshake.

The module owns the instruction-fetch port pair, so what is under test is a
protocol, not a value: a request must be presented for the address currently
being fetched, it must stay presented with a stable address until the memory
answers, and the answer must reach `instr` exactly once and never late.

The cycle model every test uses is the one `core` is expected to wire:

    pc_gen.stall = if_req_valid || stall

so the PC is frozen while a fetch is in flight and while an instruction is
held, and advances by 4 on the edge that consumes the instruction.  That is
what makes `if_stage`'s contract guarantee -- "`instr` is the instruction at
`pc`" -- true at the IF/ID boundary, and it lets every test assert an
instruction against the `pc` of the cycle it is presented in rather than
against the address it was requested for.

Invariants checked, and why each one exists:

* nothing is presented on `instr` out of reset;
* `if_req_valid` is asserted for the current `pc` as soon as reset is released;
* the address is stable for the whole request window, and a request is never
  abandoned half way -- a memory that has accepted a request always gets its
  response accepted exactly once;
* the response is latched into `instr` on the cycle after it arrives;
* `instr` is held for as long as `stall` is asserted, and no new fetch is
  started meanwhile;
* `flush` squashes the instruction in flight, and a response to a request that
  was already outstanding when the flush arrived is discarded rather than
  mistaken for the instruction at the new `pc`;
* `pred_taken` is low and `pred_pc` is the sequential fall-through, because
  phase 1 has no predictor (spec decision 8);
* `instr`, whenever it is non-zero, is the instruction at the `pc` of the same
  cycle.

The last test is a randomised handshake soak with random memory latency,
random stalls and random flushes, checking all of the above every cycle and
then requiring the fetch stream to resume with consecutive addresses.
"""

import random

import cocotb
from cocotb.triggers import Timer

from conftest import Clock, cycles, reset

# rtl/common/defs.vh
RESET_VEC = 0x0000_0000
PC_STEP = 4
MASK = 0xFFFF_FFFF


def word(addr):
    """The instruction word `addr` maps to.

    Injective in `addr`, so a word presented on `instr` identifies the request
    it came from -- which is how a stale fetch is caught rather than merely
    counted.
    """
    return (addr + 0x1000) & MASK


async def settle():
    """Let combinational logic settle after inputs were driven."""
    await Timer(1, unit="ns")


def idle(dut, stall=0, flush=0, pc=RESET_VEC):
    dut.stall.value = stall
    dut.flush.value = flush
    dut.pc.value = pc
    dut.if_rsp_valid.value = 0
    dut.if_rsp_rdata.value = 0


class FetchMemory:
    """A fetch memory with a fixed or random latency.

    Call :meth:`drive` exactly once per simulated cycle.  It presents this
    cycle's response and accepts a request if one is up, keeping its own cycle
    count so a testbench cannot desynchronise it by forgetting to tick.

    A request is accepted in any cycle where `if_req_valid` is high, no request
    is outstanding, and no response is being delivered this cycle -- the last
    exclusion is what makes a request presented in the same cycle as the
    response to it the tail of that window rather than a new request, which is
    how a `valid`/`ready` pair behaves.
    """

    def __init__(self, dut, rng=None, latency=1, min_latency=1, max_latency=3):
        self.dut = dut
        self.rng = rng
        self.latency = latency
        self.min_latency = min_latency
        self.max_latency = max_latency
        self.pending = None  # [addr, due_cycle, rdata]
        self.accepted = []
        self.delivered = []
        self.cycle = 0

    def _latency(self):
        if self.rng is None:
            return self.latency
        return self.rng.randint(self.min_latency, self.max_latency)

    def drive(self):
        dut = self.dut
        dut.if_rsp_valid.value = 0
        dut.if_rsp_rdata.value = 0
        delivered_now = False
        if self.pending is not None and self.pending[1] <= self.cycle:
            addr, _, rdata = self.pending
            dut.if_rsp_valid.value = 1
            dut.if_rsp_rdata.value = rdata
            self.delivered.append((self.cycle, addr, rdata))
            self.pending = None
            delivered_now = True
        if int(dut.if_req_valid.value) and self.pending is None and not delivered_now:
            addr = int(dut.if_req_addr.value)
            self.pending = [addr, self.cycle + self._latency(), word(addr)]
            self.accepted.append((self.cycle, addr))
        self.cycle += 1


class PcModel:
    """`pc_gen` as `core` is expected to wire it: `pc_gen.stall = if_req_valid || stall`."""

    def __init__(self, start=RESET_VEC):
        self.pc = start

    def step(self, fetch_busy, stalled, flushed, redirect_pc):
        if flushed:
            self.pc = redirect_pc & MASK  # a redirect outranks the stall
        elif not (fetch_busy or stalled):
            self.pc = (self.pc + PC_STEP) & MASK


async def start(dut, **inputs):
    """Clock the DUT, hold reset, release it, leave the fetch inputs idle.

    On return the stage holds the request for `p_RESET_VEC`: the release edge
    advanced it out of its post-reset state into the request window.
    """
    cocotb.start_soon(Clock(dut.clk).start())
    idle(dut, **inputs)
    await reset(dut)


@cocotb.test()
async def test_presents_nothing_out_of_reset(dut):
    """Out of reset no instruction is on `instr` and the prediction is not taken.

    `instr` is the word decode sees, so a power-up value of all-ones or of a
    leftover instruction is a decode-time garbage instruction the moment the
    first valid bit is granted.
    """
    await start(dut)
    assert int(dut.instr.value) == 0, "instr is not zero out of reset"
    assert int(dut.pred_taken.value) == 0, "there is no predictor in phase 1"
    for _ in range(3):
        await cycles(dut, 1)
        assert int(dut.instr.value) == 0, "an instruction appeared with no response"


@cocotb.test()
async def test_issues_a_fetch_request_for_the_reset_vector(dut):
    """The reset vector is requested as soon as reset is released.

    No bubble: a fetch unit that needs a dead cycle before its first request
    costs one cycle of every program, and it is only reachable if the
    behaviour is checked rather than assumed.
    """
    await start(dut)
    assert int(dut.pc.value) == RESET_VEC
    assert int(dut.if_req_valid.value) == 1, "no fetch request after reset"
    assert int(dut.if_req_addr.value) == RESET_VEC


@cocotb.test()
async def test_latches_the_response_into_instr(dut):
    """The response becomes `instr` on the cycle after the memory answers."""
    await start(dut)
    mem = FetchMemory(dut, latency=1)
    mem.drive()
    await cycles(dut, 1)
    assert int(dut.instr.value) == 0, "instr appeared before the response"
    mem.drive()  # the response is delivered in this cycle
    assert int(dut.instr.value) == 0, "instr is combinational off the response"
    await cycles(dut, 1)
    assert int(dut.instr.value) == word(RESET_VEC), (
        "instr is 0x%08x, expected 0x%08x" % (int(dut.instr.value), word(RESET_VEC))
    )
    assert int(dut.if_req_valid.value) == 0, "a request is outstanding again"


@cocotb.test()
async def test_holds_fetch_valid_until_the_response(dut):
    """`if_req_valid` and `if_req_addr` hold for the whole request window.

    A memory that answers after four cycles is the normal case, not an exotic
    one, so a request that is withdrawn early -- or whose address moves while
    it is outstanding -- is exactly the bug this catches.
    """
    await start(dut)
    mem = FetchMemory(dut, latency=4)
    for cycle in range(4):
        assert int(dut.if_req_valid.value) == 1, (
            "if_req_valid dropped %d cycle(s) into the request window" % cycle
        )
        assert int(dut.if_req_addr.value) == RESET_VEC, (
            "if_req_addr moved to 0x%08x while the request was outstanding"
            % int(dut.if_req_addr.value)
        )
        assert int(dut.instr.value) == 0, "instr appeared before the response"
        mem.drive()
        await cycles(dut, 1)
    assert int(dut.if_req_valid.value) == 1
    mem.drive()
    await cycles(dut, 1)
    assert int(dut.instr.value) == word(RESET_VEC)


@cocotb.test()
async def test_accepts_a_response_while_stalled(dut):
    """`stall` holds the *instruction*, not the fetch handshake.

    A response that arrives on a cycle the pipeline happens to be stalled must
    still be taken.  Ignoring it loses the read -- the memory has already spent
    it -- and the stage then waits for a response to a request it has already
    had, which is a deadlock rather than a slow fetch.  This is a realistic
    wiring accident: `core` raises `stall` for the whole front end, and a
    front end that gates its own handshake on it stalls the fetch against
    itself.
    """
    await start(dut)
    mem = FetchMemory(dut, latency=1)
    mem.drive()  # request for the reset vector accepted
    await cycles(dut, 1)

    dut.stall.value = 1
    mem.drive()  # the response arrives on this stalled cycle
    await settle()
    assert int(dut.if_rsp_valid.value) == 1
    await cycles(dut, 1)
    mem.drive()  # and is not answered again
    await cycles(dut, 1)
    assert int(dut.instr.value) == word(RESET_VEC), (
        "the response was dropped on a stalled cycle: instr is 0x%08x"
        % int(dut.instr.value)
    )
    # The stalled instruction is held, not lost.
    for _ in range(3):
        assert int(dut.instr.value) == word(RESET_VEC)
        mem.drive()
        await cycles(dut, 1)


@cocotb.test()
async def test_holds_the_instruction_while_stalled(dut):
    """`stall` holds the fetched instruction and starts no new fetch."""
    await start(dut)
    mem = FetchMemory(dut, latency=1)
    mem.drive()
    await cycles(dut, 1)
    mem.drive()
    await cycles(dut, 1)
    assert int(dut.instr.value) == word(RESET_VEC)

    dut.stall.value = 1
    for _ in range(4):
        assert int(dut.instr.value) == word(RESET_VEC), "stall lost the instruction"
        assert int(dut.if_req_valid.value) == 0, (
            "a fetch was started while the instruction was stalled"
        )
        mem.drive()
        await cycles(dut, 1)

    # `core` releases the PC on the same edge it lets the instruction go.
    dut.stall.value = 0
    dut.pc.value = RESET_VEC + PC_STEP
    await cycles(dut, 1)
    assert int(dut.if_req_valid.value) == 1, "no refetch after the stall released"
    assert int(dut.if_req_addr.value) == RESET_VEC + PC_STEP, (
        "refetched 0x%08x, expected the released pc 0x%08x"
        % (int(dut.if_req_addr.value), RESET_VEC + PC_STEP)
    )


@cocotb.test()
async def test_flush_squashes_the_instruction(dut):
    """`flush` drops the instruction in flight whatever the response said."""
    await start(dut)
    mem = FetchMemory(dut, latency=1)
    mem.drive()
    await cycles(dut, 1)
    mem.drive()
    await cycles(dut, 1)
    assert int(dut.instr.value) == word(RESET_VEC)

    # A redirect, a flush and a response in the same cycle: the response must
    # still not reach decode, whatever it carries.
    dut.flush.value = 1
    dut.if_rsp_valid.value = 1
    dut.if_rsp_rdata.value = 0xFFFF_FFFF
    await cycles(dut, 1)
    dut.flush.value = 0
    dut.if_rsp_valid.value = 0
    dut.if_rsp_rdata.value = 0
    assert int(dut.instr.value) == 0, "flush did not squash the instruction"
    await cycles(dut, 1)
    assert int(dut.instr.value) == 0, "a squashed instruction came back"
    assert int(dut.if_req_valid.value) == 1, "no refetch after the flush"
    assert int(dut.if_req_addr.value) == RESET_VEC


@cocotb.test()
async def test_flush_refetches_from_the_current_pc(dut):
    """After a flush the next request carries the `pc` of the redirect."""
    await start(dut)
    mem = FetchMemory(dut, latency=1)
    mem.drive()
    await cycles(dut, 1)
    mem.drive()
    await cycles(dut, 1)
    assert int(dut.instr.value) == word(RESET_VEC)

    target = 0x0000_0400
    dut.flush.value = 1
    mem.drive()
    await cycles(dut, 1)
    dut.flush.value = 0
    dut.pc.value = target  # `pc_gen` took the redirect on the flush edge
    await settle()
    assert int(dut.instr.value) == 0, "the flushed instruction was still there"
    assert int(dut.if_req_valid.value) == 1, "no fetch after the redirect"
    assert int(dut.if_req_addr.value) == target, (
        "refetched 0x%08x after a redirect to 0x%08x"
        % (int(dut.if_req_addr.value), target)
    )


@cocotb.test()
async def test_flush_discards_an_inflight_response(dut):
    """A response to a request outstanding at the flush is discarded.

    A memory read cannot be withdrawn, so the response arrives after the
    redirect.  Latched, it would be presented as the instruction at the *new*
    `pc` -- a wrong-path word with a right-path address, which no value check
    downstream would catch.  The latency here is long enough that the response
    lands after the flush has already been taken.
    """
    await start(dut)
    mem = FetchMemory(dut, latency=4)
    mem.drive()  # the request for the reset vector is accepted now
    await cycles(dut, 1)
    mem.drive()
    await cycles(dut, 1)
    assert int(dut.if_req_valid.value) == 1
    assert int(dut.if_req_addr.value) == RESET_VEC
    assert mem.pending is not None and mem.pending[0] == RESET_VEC

    target = 0x0000_0400
    dut.flush.value = 1
    mem.drive()
    await cycles(dut, 1)
    dut.flush.value = 0
    dut.pc.value = target

    saw_target_request = False
    for cycle in range(16):
        mem.drive()
        if int(dut.instr.value) != 0:
            assert int(dut.instr.value) == word(int(dut.pc.value)), (
                "cycle %d: instr is 0x%08x at pc 0x%08x -- a stale fetch reached decode"
                % (cycle, int(dut.instr.value), int(dut.pc.value))
            )
        if int(dut.if_req_valid.value) and int(dut.if_req_addr.value) == target:
            saw_target_request = True
        await cycles(dut, 1)
    assert saw_target_request, "the redirect target was never fetched"
    assert mem.pending is None or mem.pending[0] != RESET_VEC, (
        "the pre-flush request was never answered"
    )


@cocotb.test()
async def test_prediction_is_the_sequential_fallthrough(dut):
    """Phase 1 publishes no prediction: `pred_taken` low, `pred_pc` = pc + 4.

    Spec decision 8 stubs the predictor by tying its inputs to constants.
    `pred_pc` still has to be the fall-through address rather than a leftover
    value, because phase 5 plugs a predictor in here and reads this signal.
    """
    await start(dut)
    # Odd addresses as well as even: a `pred_taken` derived from `pc[0]` rather
    # than tied low passes every even address there is.
    for pc in (0x0000_0000, 0x0000_0001, 0x0000_0040, 0x0000_0045, 0xFFFF_FFC0, 0xFFFF_FFC1):
        dut.pc.value = pc
        await settle()
        assert int(dut.pred_taken.value) == 0
        assert int(dut.pred_pc.value) == (pc + PC_STEP) & MASK, (
            "pred_pc is 0x%08x at pc 0x%08x" % (int(dut.pred_pc.value), pc)
        )


@cocotb.test()
async def test_instr_is_the_instruction_at_pc(dut):
    """Scripted walk through a short fetch stream.

    Each word is checked against the address of the *cycle it is presented in*,
    not the address it was requested for -- those are only the same if the PC
    is frozen across the request window, and that is exactly what can silently
    drift.
    """
    await start(dut)
    mem = FetchMemory(dut, latency=1)
    pc = PcModel()
    presented = []
    for cycle in range(24):
        dut.pc.value = pc.pc  # drive the modelled `pc_gen` output into the DUT
        await settle()  # `if_req_addr` is combinational off `pc`
        if int(dut.instr.value) != 0:
            assert int(dut.instr.value) == word(pc.pc), (
                "cycle %d: instr is 0x%08x at pc 0x%08x"
                % (cycle, int(dut.instr.value), pc.pc)
            )
            presented.append(pc.pc)
        busy = int(dut.if_req_valid.value)
        mem.drive()
        await cycles(dut, 1)
        pc.step(fetch_busy=busy, stalled=0, flushed=0, redirect_pc=0)
    assert presented == [RESET_VEC + 4 * n for n in range(len(presented))], (
        "fetch presented %r, expected consecutive addresses from the reset vector"
        % presented
    )
    assert len(presented) >= 4, "only %d instructions in 24 cycles" % len(presented)


@cocotb.test()
async def test_randomised_handshake_never_loses_or_corrupts_a_fetch(dut):
    """Soak the handshake with random latency, random stalls and random flushes.

    Every cycle the request window, the address and the instruction are checked
    against the models; at the end the outstanding requests are drained and the
    fetch stream has to carry on with consecutive addresses.  An implementation
    that duplicated a request, dropped one, moved an address mid-window, or
    presented a stale instruction after a redirect cannot pass this, and none
    of the value checks above would notice.
    """
    await start(dut)
    rng = random.Random(0x5EED)
    mem = FetchMemory(dut, rng=rng, latency=1, min_latency=1, max_latency=4)
    pc = PcModel()
    next_redirect = 0x1000

    for cycle in range(300):
        # --- this cycle's inputs from `pc_gen`, then the settled outputs ---
        dut.pc.value = pc.pc
        await settle()  # `if_req_addr` is combinational off `pc`
        assert int(dut.pred_taken.value) == 0, (
            "cycle %d: pred_taken is high; phase 1 has no predictor" % cycle
        )
        if int(dut.instr.value) != 0:
            assert int(dut.instr.value) == word(pc.pc), (
                "cycle %d: instr is 0x%08x at pc 0x%08x -- stale or wrong instruction"
                % (cycle, int(dut.instr.value), pc.pc)
            )
        if mem.pending is not None:
            # The request is still outstanding: it must still be presented, at
            # the same address, or the memory has been left waiting forever.
            assert int(dut.if_req_valid.value) == 1, (
                "cycle %d: the outstanding request for 0x%08x was abandoned"
                % (cycle, mem.pending[0])
            )
            assert int(dut.if_req_addr.value) == mem.pending[0], (
                "cycle %d: if_req_addr is 0x%08x mid-window, expected 0x%08x"
                % (cycle, int(dut.if_req_addr.value), mem.pending[0])
            )
        busy = int(dut.if_req_valid.value)

        # --- this cycle's inputs ---
        flush = 1 if rng.random() < 0.08 else 0
        stall = 1 if rng.random() < 0.15 else 0
        redirect_pc = 0
        if flush:
            next_redirect += 4 * rng.randint(1, 8)
            redirect_pc = next_redirect
        dut.flush.value = flush
        dut.stall.value = stall
        mem.drive()
        await cycles(dut, 1)
        pc.step(fetch_busy=busy, stalled=stall, flushed=flush, redirect_pc=redirect_pc)

    # --- drain: no stalls, no flushes, and the stream must carry on ---
    dut.stall.value = 0
    dut.flush.value = 0
    seen = []
    for cycle in range(300):
        dut.pc.value = pc.pc
        await settle()  # `if_req_addr` is combinational off `pc`
        if int(dut.instr.value) != 0:
            assert int(dut.instr.value) == word(pc.pc), (
                "drain cycle %d: instr is 0x%08x at pc 0x%08x"
                % (cycle, int(dut.instr.value), pc.pc)
            )
            seen.append(pc.pc)
        busy = int(dut.if_req_valid.value)
        mem.drive()
        await cycles(dut, 1)
        pc.step(fetch_busy=busy, stalled=0, flushed=0, redirect_pc=0)
        if len(seen) >= 6:
            break

    assert len(seen) >= 6, (
        "fetch stalled: only %d instructions after the stimulus stopped (%d "
        "requests accepted, %d responses delivered)"
        % (len(seen), len(mem.accepted), len(mem.delivered))
    )
    assert seen == [seen[0] + 4 * n for n in range(len(seen))], (
        "the fetch stream skipped an address: %r" % seen
    )
    assert len(mem.delivered) == len(mem.accepted), (
        "%d requests accepted but %d responses delivered"
        % (len(mem.accepted), len(mem.delivered))
    )

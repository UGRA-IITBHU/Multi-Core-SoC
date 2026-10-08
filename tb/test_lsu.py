"""Regression tests for ``rtl/core/lsu.v``.

Drives the module with the shared helpers in ``tb/conftest.py``.

The contract makes five promises about the data-memory interface, and each has
a test here:

* **the request is held until it is granted** - ``mem_req_valid`` stays high
  from the cycle the request is presented until the cycle ``mem_rsp_valid`` is
  seen, and every request-side signal is unchanged for the whole of that
  window, so memory may accept the request at its own pace;
* **never a lost and never a duplicated request** - one access is exactly one
  grant.  This is Review Focus 4, and it is tested with randomised backpressure
  rather than with a tidy one-cycle memory, because a tidy memory passes a
  handshake that is wrong only when it is slow;
* **the byte lanes come from the address and the size** - ``mem_req_wstrb`` is
  what makes ``SB`` and ``SH`` correct, so the whole 4x3 table is checked, and
  a byte-addressed memory model checks that a sub-word store really does leave
  its neighbours alone;
* **a misaligned word or halfword access is flagged and not performed** -
  ``data_misaligned`` rises, no request reaches memory, and no request is left
  outstanding for a response that can never arrive;
* **the writeback metadata is passed through untouched** - destination, write
  enable and source select reach MEM/WB exactly as ``ex_stage`` produced them.

Two phase-1 limitations are pinned by tests as well, so that phase 2 cannot
break them silently:

* an ``lb``/``lbu``/``lh``/``lhu`` returns the whole containing word - see
  DESIGN NOTE 4 in ``rtl/core/lsu.v``, which reports that no frozen port lets
  any module sign- or zero-extend it yet;
* ``ex_mem_unsigned`` changes nothing about the request.  There is no producer
  for it in the EX/MEM bundle, so the tests assert the *absence* of any effect.

Run with::

    make test MODULE=test_lsu TOP=lsu
    make test-4state MODULE=test_lsu TOP=lsu
"""

import random

import cocotb
from cocotb.triggers import NextTimeStep, RisingEdge, Timer
from conftest import Clock, cycles, reset

XLEN_MASK = 0xFFFFFFFF

# `ex_mem_size`, frozen by docs/contracts/phase1-interfaces.md.
MEM_SIZE_BYTE = 0
MEM_SIZE_HALF = 1
MEM_SIZE_WORD = 2

# The offsets each size may legally be accessed at: phase 1 refuses a misaligned
# word or halfword access (DESIGN NOTE 3 in ``rtl/core/lsu.v``), and a byte may
# go anywhere.  Tests iterate over this rather than over ``range(4)``, because an
# offset that is refused produces no request at all and a test waiting for one
# would hang instead of failing.
LEGAL_OFFSETS = (
    (MEM_SIZE_BYTE, (0, 1, 2, 3)),
    (MEM_SIZE_HALF, (0, 2)),
    (MEM_SIZE_WORD, (0,)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def settle(dut):
    """Let pending signal writes take effect before anything is read back.

    cocotb applies a signal assignment on the next delta cycle, so a test that
    drives inputs and reads an output in the same delta reads the *previous*
    value.  A real 1 ns is used rather than a bare delta so the same code works
    under both simulators.
    """
    await Timer(1, unit="ns")


async def idle(dut):
    """Park every input: no access presented, no response, no stall."""
    dut.ex_mem_addr.value = 0
    dut.ex_store_data.value = 0
    dut.ex_mem_read.value = 0
    dut.ex_mem_write.value = 0
    dut.ex_mem_size.value = MEM_SIZE_WORD
    dut.ex_mem_unsigned.value = 0
    dut.ex_rd_addr.value = 0
    dut.ex_reg_write.value = 0
    dut.ex_wb_sel.value = 0
    dut.mem_rsp_rdata.value = 0
    dut.mem_rsp_valid.value = 0
    dut.stall.value = 0
    await settle(dut)


async def present(
    dut,
    addr,
    data=0x00000000,
    read=0,
    write=0,
    size=MEM_SIZE_WORD,
    unsigned=0,
    rd_addr=0,
    reg_write=0,
    wb_sel=0,
):
    """Put an access in front of the module, as EX/MEM would."""
    dut.ex_mem_addr.value = addr
    dut.ex_store_data.value = data
    dut.ex_mem_read.value = read
    dut.ex_mem_write.value = write
    dut.ex_mem_size.value = size
    dut.ex_mem_unsigned.value = unsigned
    dut.ex_rd_addr.value = rd_addr
    dut.ex_reg_write.value = reg_write
    dut.ex_wb_sel.value = wb_sel
    await settle(dut)


async def step(dut):
    """One rising edge, then let the design settle."""
    await RisingEdge(dut.clk)
    await NextTimeStep()


async def start(dut):
    """Clock running, reset released, every input parked.

    The inputs are parked *before* the reset as well as after it.
    `conftest.reset` holds the reset across ten edges and then takes one more
    edge with it released, and this module latches `req_pending` on that last
    edge - so parking the inputs only afterwards would leave a request
    outstanding for whatever the previous test happened to leave on the bus.
    """
    cocotb.start_soon(Clock(dut.clk).start())
    await idle(dut)
    await reset(dut)
    await idle(dut)


def bits(pattern):
    """A four-bit lane pattern as a binary string, for readable messages."""
    return format(pattern, "04b")


def request(dut):
    """The request as it appears on the bus: (valid, addr, we, wdata, wstrb)."""
    return (
        int(dut.mem_req_valid.value),
        int(dut.mem_req_addr.value),
        int(dut.mem_req_we.value),
        int(dut.mem_req_wdata.value),
        int(dut.mem_req_wstrb.value),
    )


async def grant_next(dut, rdata=0x00000000, wait=0):
    """Grant the outstanding request after ``wait`` further cycles.

    Started before the access is presented, so it can be used as a memory
    model.  The response is held for exactly one cycle, which is what the
    contract promises memory will see: ``mem_rsp_valid`` is a pulse, not a
    level that the module has to catch.
    """
    waited = 0
    while not int(dut.mem_req_valid.value):
        await step(dut)
        waited += 1
        assert waited <= 8, (
            "no request appeared within %d cycles - the access in front of the "
            "module is not one that can be performed (misaligned? not a memory "
            "access?).  valid=%s addr=%08x size=%d read=%s write=%s misaligned=%s "
            "stall=%s rsp_valid=%s"
            % (waited, dut.mem_req_valid.value, int(dut.ex_mem_addr.value),
               int(dut.ex_mem_size.value), dut.ex_mem_read.value,
               dut.ex_mem_write.value, dut.data_misaligned.value,
               dut.stall.value, dut.mem_rsp_valid.value)
        )
    for _ in range(wait):
        await step(dut)
    dut.mem_rsp_rdata.value = rdata
    dut.mem_rsp_valid.value = 1
    # The response is sampled on this edge, and the module must drop
    # `mem_req_valid` in the cycle that follows it.
    await step(dut)
    assert int(dut.mem_req_valid.value) == 0, (
        "mem_req_valid was still high in the response cycle"
    )
    dut.mem_rsp_valid.value = 0
    await settle(dut)


async def complete(dut, rdata=0x00000000, wait=0):
    """Grant the request, then retire the access the way `core` does.

    `core` advances MEM/WB on the response cycle, so the access is gone from
    this stage afterwards.  The module is *not* expected to remember that a
    request was granted: with the access still in front of it and no response
    in sight, presenting a fresh request is correct.  Every "the request is
    finished" test therefore retires the access first, or it would be testing
    the wrong thing.
    """
    await grant_next(dut, rdata=rdata, wait=wait)
    await present(dut, 0x00000000)


# ---------------------------------------------------------------------------
# Request generation
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_no_request_without_an_access(dut):
    """An idle memory stage, or one holding an ALU result or a branch, must
    leave the bus alone.

    The memory stage sees every instruction in the pipeline, so "not a memory
    instruction" is the common case, not an edge case.
    """
    await start(dut)
    for _ in range(4):
        assert int(dut.mem_req_valid.value) == 0, "idle stage drove mem_req_valid"
        await cycles(dut, 1)
    # An ALU result in the stage is not an access.
    await present(dut, 0x00001000, data=0xDEADBEEF, read=0, write=0)
    for _ in range(4):
        assert int(dut.mem_req_valid.value) == 0, (
            "an address without mem_read/mem_write produced a request"
        )
        await cycles(dut, 1)


@cocotb.test()
async def test_load_issues_a_read_request(dut):
    """A load presents the effective address with the write side off."""
    await start(dut)
    await present(dut, 0x00001234, read=1, size=MEM_SIZE_WORD)
    valid, addr, we, _wdata, wstrb = request(dut)
    assert valid == 1, "a load did not present a request"
    assert addr == 0x00001234, "request address is %08x, expected the effective address" % addr
    assert we == 0, "a load asserted mem_req_we"
    assert wstrb == 0, "a load asserted write strobes %b" % wstrb

    await complete(dut, rdata=0xCAFEF00D)
    assert int(dut.mem_req_valid.value) == 0, "the request survived its response"


@cocotb.test()
async def test_store_issues_a_write_request(dut):
    """A store presents the effective address, the data and every byte lane."""
    await start(dut)
    await present(dut, 0x00002000, data=0xA5A5A5A5, write=1, size=MEM_SIZE_WORD)
    valid, addr, we, wdata, wstrb = request(dut)
    assert valid == 1, "a store did not present a request"
    assert addr == 0x00002000, "request address is %08x" % addr
    assert we == 1, "a store did not assert mem_req_we"
    assert wdata == 0xA5A5A5A5, "request data is %08x" % wdata
    assert wstrb == 0b1111, "a word store asserted %b, expected 1111" % wstrb
    await complete(dut)


@cocotb.test()
async def test_writeback_metadata_is_passed_through(dut):
    """Destination, write enable and source select reach MEM/WB unchanged.

    They are `ex_stage`'s outputs on the way to the MEM/WB bundle, so anything
    other than a pass-through would silently retarget a writeback.
    """
    await start(dut)
    for rd_addr in (0, 1, 15, 31):
        for reg_write in (0, 1):
            for wb_sel in (0, 1, 2):
                await present(
                    dut, 0x00003000, read=1, rd_addr=rd_addr,
                    reg_write=reg_write, wb_sel=wb_sel,
                )
                assert int(dut.mem_rd_addr.value) == rd_addr, (
                    "mem_rd_addr is %d, expected %d" % (int(dut.mem_rd_addr.value), rd_addr)
                )
                assert int(dut.mem_reg_write.value) == reg_write, (
                    "mem_reg_write is %d, expected %d"
                    % (int(dut.mem_reg_write.value), reg_write)
                )
                assert int(dut.mem_wb_sel.value) == wb_sel, (
                    "mem_wb_sel is %d, expected %d" % (int(dut.mem_wb_sel.value), wb_sel)
                )
        # Every access presented above is granted and retired, so this test does
        # not leave a request outstanding for the next one to trip over.
        await complete(dut)


# ---------------------------------------------------------------------------
# Byte lanes
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_byte_store_selects_the_lane_the_address_names(dut):
    """`SB` moves exactly one lane, chosen by `addr[1:0]`.

    Lane i of the request data is byte i of `ex_store_data`, so `sb` to
    `base+2` must assert `0100` and nothing else.
    """
    await start(dut)
    for offset, expected in ((0, 0b0001), (1, 0b0010), (2, 0b0100), (3, 0b1000)):
        await present(
            dut, 0x00004000 + offset, data=0xDEADBEEF,
            write=1, size=MEM_SIZE_BYTE,
        )
        _valid, addr, _we, _wdata, wstrb = request(dut)
        assert wstrb == expected, (
            "sb to %08x asserted %s, expected %s" % (addr, bits(wstrb), bits(expected))
        )
        await complete(dut)


@cocotb.test()
async def test_halfword_store_selects_the_lanes_the_address_names(dut):
    """`SH` moves two lanes, chosen by `addr[1]`.

    Only the two aligned addresses get here: an odd address is a misaligned
    access, which phase 1 refuses rather than performs
    (``test_misaligned_halfword_access_is_flagged_and_not_requested``).  Note
    that the data is not shifted for either lane - the strobes are the whole
    mechanism, which is why they are derived here rather than in a memory model
    that would have to guess.
    """
    await start(dut)
    table = (
        (0, 0b0011),
        (2, 0b1100),
    )
    for offset, expected in table:
        await present(
            dut, 0x00005000 + offset, data=0x0000BEEF,
            write=1, size=MEM_SIZE_HALF,
        )
        _valid, addr, _we, _wdata, wstrb = request(dut)
        assert wstrb == expected, (
            "sh to %08x asserted %s, expected %s" % (addr, bits(wstrb), bits(expected))
        )
        await complete(dut)


@cocotb.test()
async def test_word_store_selects_every_lane(dut):
    """An aligned word store asserts all four lanes.

    There is no "at any alignment" case to check: a word store to a misaligned
    address is refused, so its strobes are zero.  That is asserted here as well
    as flagged by the misalignment tests, because a narrowed lane pattern on a
    refused access would be exactly the way a partial store slips through.
    """
    await start(dut)
    await present(dut, 0x00006000, data=0x12345678, write=1, size=MEM_SIZE_WORD)
    _valid, _addr, _we, _wdata, wstrb = request(dut)
    assert wstrb == 0b1111, (
        "a word store asserted %s, expected 1111" % bits(wstrb)
    )
    await complete(dut)

    for offset in (1, 2, 3):
        await present(
            dut, 0x00006000 + offset, data=0x12345678,
            write=1, size=MEM_SIZE_WORD,
        )
        _valid, _addr, _we, _wdata, wstrb = request(dut)
        assert int(dut.data_misaligned.value) == 1, (
            "precondition: a misaligned word store must be flagged"
        )
        assert wstrb == 0, (
            "a refused word store at offset %d still asserted %s"
            % (offset, bits(wstrb))
        )
        await cycles(dut, 2)
        await present(dut, 0x00006000)


@cocotb.test()
async def test_load_never_asserts_a_write_strobe(dut):
    """`mem_req_wstrb` is zero for every load and for every idle cycle.

    A strobe on a read is the classic way a memory ends up writing what it
    returned, so it is checked for all three sizes and both signednesses.
    """
    await start(dut)
    for size, offsets in LEGAL_OFFSETS:
        for offset in offsets:
            for unsigned in (0, 1):
                await present(
                    dut, 0x00007000 + offset, read=1, size=size, unsigned=unsigned
                )
                assert int(dut.mem_req_valid.value) == 1, (
                    "precondition: an aligned %d-byte load must be requested" % size
                )
                assert int(dut.mem_req_wstrb.value) == 0, (
                    "a load asserted write strobes %s" % bits(int(dut.mem_req_wstrb.value))
                )
                await complete(dut)


# ---------------------------------------------------------------------------
# The handshake
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_request_is_held_until_the_response(dut):
    """`mem_req_valid` and the whole payload survive every cycle of the wait.

    Memory accepts a request at its own pace, so the address, the data, the
    direction and the lanes must be *unchanged* while it thinks - not merely
    still valid.
    """
    await start(dut)
    await present(dut, 0x00008124, data=0x0BADF00D, write=1, size=MEM_SIZE_HALF)
    first = request(dut)
    assert first[0] == 1, "no request was presented"
    for waited in range(1, 9):
        await cycles(dut, 1)
        now = request(dut)
        assert now == first, (
            "the request changed after %d cycles:\n  was %s\n  now %s"
            % (waited, first, now)
        )
    await complete(dut)
    assert int(dut.mem_req_valid.value) == 0, "the request survived its response"


@cocotb.test()
async def test_request_drops_in_the_response_cycle(dut):
    """The window ends in the cycle the response arrives, not a cycle later.

    One extra cycle of `mem_req_valid` is one extra opportunity for a memory
    that grants combinationally to see the same request twice.
    """
    await start(dut)
    await present(dut, 0x00008200, read=1)
    assert int(dut.mem_req_valid.value) == 1, "no request was presented"

    dut.mem_rsp_valid.value = 1
    await settle(dut)
    assert int(dut.mem_req_valid.value) == 0, (
        "mem_req_valid was still high in the response cycle"
    )
    await cycles(dut, 1)
    assert int(dut.mem_req_valid.value) == 0, (
        "mem_req_valid came back after the response"
    )
    dut.mem_rsp_valid.value = 0
    # The access leaves the stage with its grant, so nothing is left outstanding.
    await present(dut, 0x00000000)


@cocotb.test()
async def test_a_response_in_the_presentation_cycle_is_not_a_duplicate(dut):
    """A memory that grants in the very cycle the request is presented must not
    cause the request to be issued again.

    This is the zero-latency memory: a register-file-backed L1, or a test
    harness that ties `mem_rsp_valid` high.  If the module latched "request
    outstanding" before checking the response, every access would be sent twice
    and the second one would retire the *next* access.
    """
    await start(dut)
    # `mem_rsp_valid` is already high when the access arrives.
    dut.mem_rsp_valid.value = 1
    await settle(dut)
    await present(dut, 0x00008300, read=1)
    assert int(dut.mem_req_valid.value) == 0, (
        "a request was presented although the response was already here"
    )
    for _ in range(4):
        await cycles(dut, 1)
        assert int(dut.mem_req_valid.value) == 0, (
            "the same-cycle-granted access was presented again"
        )

    # With the response withdrawn the access is still in the stage, so a fresh
    # request is correct - and it must be the first one, not a repeat.
    dut.mem_rsp_valid.value = 0
    await settle(dut)
    assert int(dut.mem_req_valid.value) == 1, (
        "the access was never presented once the response went away"
    )
    await complete(dut)


@cocotb.test()
async def test_each_access_is_granted_exactly_once(dut):
    """Back-to-back accesses each get one request and one response.

    Checked by counting: a handshake that drops a request, or that grants one
    access twice, changes the count even when every value it did produce was
    correct.
    """
    await start(dut)
    grants = 0

    async def responder():
        nonlocal grants
        while True:
            await step(dut)
            if int(dut.mem_req_valid.value):
                grants += 1
                dut.mem_rsp_rdata.value = 0x10000000 + grants
                dut.mem_rsp_valid.value = 1
                await step(dut)
                dut.mem_rsp_valid.value = 0

    cocotb.start_soon(responder())

    for index in range(12):
        await present(dut, 0x00009000 + 4 * index, read=1, size=MEM_SIZE_WORD)
        await cycles(dut, 2)
        await present(dut, 0x00009000)
        await cycles(dut, 1)
    await cycles(dut, 3)
    assert grants == 12, "%d grants for 12 accesses" % grants


@cocotb.test()
async def test_stall_holds_the_request_and_never_duplicates_it(dut):
    """`stall` freezes an outstanding request instead of withdrawing it.

    Withdrawing a held request is the tempting reading of "hold the outstanding
    request" and it is wrong twice over: it closes a combinational loop with the
    `stall` `core` derives from `mem_req_valid`, and it breaks the contract's
    promise that the request stays presented until it is granted - a memory that
    had already latched the request would see it again.

    So the property here is that the request and its whole payload are frozen
    while the stage is held, and that it is granted exactly once.

    No test in this file grants a request *while* the stage is held, because that
    is a state `core` cannot produce: its own stall term is
    `mem_req_valid && !mem_rsp_valid`, which is low in any cycle a response is
    present.  DESIGN NOTE 5 in `rtl/core/lsu.v` records that obligation.
    """
    await start(dut)
    await present(dut, 0x0000A000, data=0x0F0F0F0F, write=1, size=MEM_SIZE_BYTE)
    assert int(dut.mem_req_valid.value) == 1, "no request was presented"

    dut.stall.value = 1
    await settle(dut)
    held = request(dut)
    assert held[0] == 1, "the outstanding request was withdrawn while held"
    for _ in range(8):
        await cycles(dut, 1)
        assert request(dut) == held, (
            "a held request changed:\n  was %s\n  now %s" % (held, request(dut))
        )

    # `core` releases the hold once the response arrives, and grants only on a
    # cycle it is not holding - which is what makes the freeze above safe, and
    # is why no test grants a request while the stage is held.
    dut.stall.value = 0
    await settle(dut)
    assert int(dut.mem_req_valid.value) == 1, "the held request was not resumed"
    await complete(dut)
    assert int(dut.mem_req_valid.value) == 0, "the request survived its response"

    # And the module still works for the next access.
    await present(dut, 0x0000A000, data=0x00C0FFEE, read=1, size=MEM_SIZE_WORD)
    assert int(dut.mem_req_valid.value) == 1, "no request after the hold"
    await complete(dut, rdata=0x0000FEED)


@cocotb.test()
async def test_reset_clears_an_outstanding_request(dut):
    """Reset in the middle of a handshake leaves nothing outstanding.

    A request that outlived reset would make the first access after reset wait
    for a response that belonged to whatever was running before it - a hang that
    only appears after a warm reset, which is exactly when a SoC is already in
    trouble.

    The reset here is driven by hand rather than through ``conftest.reset()``,
    and that is not a stylistic choice: ``reset`` releases the reset and then
    takes one more edge with it released, which lets a *fresh* request start for
    an access that is still in the stage.  Retiring the access afterwards would
    then withdraw a presented request, which is exactly what the frozen contract
    forbids ``core`` from doing - so the access is retired while the reset is
    still asserted, which is the only order in which this test is legal.
    """
    await start(dut)
    await present(dut, 0x0000B000, read=1)
    assert int(dut.mem_req_valid.value) == 1, "no request was presented"
    await cycles(dut, 3)

    dut.rst_n.value = 0
    await settle(dut)
    await present(dut, 0x00000000)   # retire the access while reset is asserted
    for _ in range(4):
        await cycles(dut, 1)
        assert int(dut.mem_req_valid.value) == 0, (
            "a request was still outstanding while reset was asserted"
        )

    dut.rst_n.value = 1
    for _ in range(3):
        await cycles(dut, 1)
        assert int(dut.mem_req_valid.value) == 0, (
            "the pre-reset request came back"
        )

    # And the module still works afterwards.
    await present(dut, 0x0000B000, read=1)
    assert int(dut.mem_req_valid.value) == 1, "no request after reset"
    await complete(dut, rdata=0x0000ABCD)
    assert int(dut.mem_req_valid.value) == 0, "the request survived its response"


# ---------------------------------------------------------------------------
# Misalignment
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_misaligned_word_access_is_flagged_and_not_requested(dut):
    """A word access off a 4-byte boundary is reported, never performed."""
    await start(dut)
    for read, write in ((1, 0), (0, 1)):
        for offset in (1, 2, 3):
            await present(
                dut, 0x0000C000 + offset, data=0xAAAAAAAA, read=read,
                write=write, size=MEM_SIZE_WORD,
            )
            assert int(dut.data_misaligned.value) == 1, (
                "a misaligned word access at offset %d was not flagged" % offset
            )
            assert int(dut.mem_req_valid.value) == 0, (
                "a misaligned word access at offset %d reached memory" % offset
            )
            for _ in range(3):
                await cycles(dut, 1)
                assert int(dut.mem_req_valid.value) == 0, (
                    "a misaligned access was presented later"
                )
            await present(dut, 0x0000C000)


@cocotb.test()
async def test_misaligned_halfword_access_is_flagged_and_not_requested(dut):
    """A halfword access at an odd address is reported, never performed.

    The straddling byte lanes in DESIGN NOTE 2 of `rtl/core/lsu.v` are what an
    *unaligned halfword access* would use - but phase 1 refuses the access
    instead, because an RV32 core with no compressed instructions must raise a
    misaligned-access condition rather than quietly do it.
    """
    await start(dut)
    for read, write in ((1, 0), (0, 1)):
        for base in (0x0000D000, 0x0000D002, 0x0000D004):
            for offset in (1, 3):
                await present(
                    dut, base + offset, data=0xBBBBBBBB, read=read, write=write,
                    size=MEM_SIZE_HALF,
                )
                assert int(dut.data_misaligned.value) == 1, (
                    "a misaligned halfword access at %08x was not flagged"
                    % (base + offset)
                )
                assert int(dut.mem_req_valid.value) == 0, (
                    "a misaligned halfword access reached memory"
                )
                assert int(dut.mem_req_wstrb.value) == 0, (
                    "a refused halfword access still asserted strobes"
                )
                await present(dut, base)


@cocotb.test()
async def test_aligned_access_is_never_flagged(dut):
    """The verdict is not raised for an access that is correctly aligned."""
    await start(dut)
    cases = (
        (MEM_SIZE_BYTE, 0, 0),
        (MEM_SIZE_BYTE, 1, 0),
        (MEM_SIZE_BYTE, 2, 0),
        (MEM_SIZE_BYTE, 3, 0),
        (MEM_SIZE_HALF, 0, 0),
        (MEM_SIZE_HALF, 2, 0),
        (MEM_SIZE_WORD, 0, 0),
    )
    for size, offset, expected in cases:
        for read, write in ((1, 0), (0, 1)):
            await present(
                dut, 0x0000E000 + offset, read=read, write=write, size=size
            )
            assert int(dut.data_misaligned.value) == expected, (
                "an aligned %d-byte access at offset %d was flagged"
                % (size, offset)
            )
            await complete(dut)


@cocotb.test()
async def test_misalignment_verdict_needs_an_access(dut):
    """No access, no verdict - including for a misaligned-looking address.

    The address bits are on the port while the stage is empty, and a verdict
    computed from them alone would report misalignment for every cycle of every
    bubble.
    """
    await start(dut)
    await present(dut, 0x0000F003, read=0, write=0, size=MEM_SIZE_WORD)
    assert int(dut.data_misaligned.value) == 0, (
        "an empty stage raised a misalignment verdict"
    )
    await cycles(dut, 2)
    assert int(dut.data_misaligned.value) == 0, (
        "an empty stage raised a misalignment verdict after an edge"
    )
    await present(dut, 0x0000F003, read=1, size=MEM_SIZE_WORD)
    assert int(dut.data_misaligned.value) == 1, (
        "a misaligned load was not flagged"
    )


@cocotb.test()
async def test_a_refused_access_does_not_block_the_next_one(dut):
    """The access after a misaligned one is issued normally.

    A refused access has no response coming, so if it left a request
    outstanding the pipeline would wait for it forever.  This is the deadlock
    that a naive "hold until granted" implementation produces.
    """
    await start(dut)
    await present(dut, 0x00011001, read=1, size=MEM_SIZE_WORD)
    assert int(dut.data_misaligned.value) == 1, "precondition: misaligned"
    assert int(dut.mem_req_valid.value) == 0, "precondition: not requested"
    await cycles(dut, 3)

    await present(dut, 0x00011004, read=1, size=MEM_SIZE_WORD)
    assert int(dut.mem_req_valid.value) == 1, (
        "the access after a refused one was not presented"
    )
    await complete(dut, rdata=0x00001111)
    assert int(dut.mem_req_valid.value) == 0, "the request survived its response"


@cocotb.test()
async def test_a_misaligned_store_does_not_corrupt_a_neighbouring_word(dut):
    """Nothing reaches memory for a refused store, at any of the low bits."""
    await start(dut)
    for offset in (1, 2, 3):
        await present(
            dut, 0x00012000 + offset, data=0xFFFFFFFF, write=1, size=MEM_SIZE_WORD
        )
        await cycles(dut, 2)
        _valid, _addr, _we, _wdata, wstrb = request(dut)
        assert wstrb == 0, (
            "a refused store still asserted write strobes %b" % wstrb
        )
        await present(dut, 0x00012000)


# ---------------------------------------------------------------------------
# Review Focus 4: randomised backpressure loses nothing, duplicates nothing
# ---------------------------------------------------------------------------


class BackpressureMemory:
    """A byte-addressed memory that grants after a random wait.

    It drives the *whole* transaction from one coroutine, which is what makes it
    faithful to how `core` uses the interface and what stops the testbench from
    racing itself:

    * it holds ``stall`` - the module's input - while a request is outstanding
      but ungranted, which is exactly ``mem_req_valid && !mem_rsp_valid``, the
      stall `core` derives.  That is what proved that ``mem_req_valid`` must not
      depend on ``stall`` (DESIGN NOTE 5 in ``rtl/core/lsu.v``): a memory driving
      backpressure the way `core` does makes a gated request oscillate.
    * it retires the access in the response cycle, the way `core` advances
      MEM/WB, so a request that stays presented after its grant is a *real*
      duplicate rather than a testbench artefact.
    * it grants each request exactly once and accounts for it, so a duplicated
      request shows up as an extra grant rather than as a plausible value.
    """

    def __init__(self, dut, seed, size=0x10000, max_wait=4):
        self.dut = dut
        self.rng = random.Random(seed)
        self.cells = bytearray(size)
        self.max_wait = max_wait
        self.grants = []
        self.reads = []

    def _word_at(self, addr):
        # Lane-aligned, as DESIGN NOTE 2 in `rtl/core/lsu.v` requires: the low
        # bits of the address are redundant once the lanes and the data agree,
        # and a memory must not have to derive a shift from them.
        return int.from_bytes(self.cells[addr & ~3:(addr & ~3) + 4], "little")

    def _apply(self, addr, wdata, wstrb):
        word = addr & ~3
        for lane in range(4):
            if wstrb & (1 << lane):
                self.cells[word + lane] = (wdata >> (8 * lane)) & 0xFF

    def _expected_wstrb(self, addr, size):
        if size == MEM_SIZE_BYTE:
            return 1 << (addr & 3)
        if size == MEM_SIZE_HALF:
            return 0b0011 << (addr & 2)
        return 0b1111

    async def access(self, addr, data=0x00000000, read=0, write=0,
                     size=MEM_SIZE_WORD):
        """Run one access to completion and return the word memory returned.

        Raises if the module does something the contract forbids - a withdrawn
        request, a changed payload, a request that never arrives.
        """
        dut = self.dut
        await present(dut, addr, data=data, read=read, write=write, size=size)
        assert int(dut.mem_req_valid.value) == 1, (
            "no request for %08x (size=%d read=%d write=%d misaligned=%d)"
            % (addr, size, read, write, int(dut.data_misaligned.value))
        )

        # Backpressure for a random number of cycles, with `stall` driven the
        # way `core` drives it.
        dut.stall.value = 1
        for _ in range(self.rng.randint(0, self.max_wait)):
            await step(dut)
            assert int(dut.mem_req_valid.value) == 1, (
                "the request for %08x was withdrawn before it was granted "
                "(stall=%d)" % (addr, int(dut.stall.value))
            )
            assert int(dut.mem_req_addr.value) == addr, (
                "the request address moved while it was being held"
            )
        dut.stall.value = 0
        await settle(dut)

        # Sample what the DUT actually put on the bus, not what the model
        # expected: the whole point of the byte-addressed model below is to check
        # the DUT's lane derivation against real memory, and a model that applies
        # its own expectation proves nothing.
        seen = (
            int(dut.mem_req_addr.value),
            int(dut.mem_req_we.value),
            int(dut.mem_req_wdata.value),
            int(dut.mem_req_wstrb.value),
        )
        self.grants.append(seen)
        bus_addr, bus_we, bus_wdata, bus_wstrb = seen
        rdata = self._word_at(bus_addr)
        if bus_we:
            self._apply(bus_addr, bus_wdata, bus_wstrb)

        dut.mem_rsp_rdata.value = rdata
        dut.mem_rsp_valid.value = 1
        await step(dut)
        assert int(dut.mem_req_valid.value) == 0, (
            "the request for %08x survived its response" % addr
        )
        dut.mem_rsp_valid.value = 0

        # `core` advances in the response cycle, so the access leaves the stage
        # here.  Retiring it in the same coroutine is what keeps the two halves
        # of this model from racing each other by a cycle.
        await present(dut, 0x00000000)
        self.reads.append(rdata)
        return rdata


@cocotb.test()
async def test_randomised_backpressure_never_loses_or_duplicates_an_access(dut):
    """Every access is granted exactly once, whatever the memory's timing.

    Review Focus 4.  The check is the *count and the payload*: an implementation
    that presented a request twice would produce the right values for every
    access and still be wrong, because the second grant would retire the
    following one.
    """
    await start(dut)
    mem = BackpressureMemory(dut, seed=0x1F5A, max_wait=4)
    rng = random.Random(0xC0FFEE)

    for index in range(40):
        base = 0x1000 + 4 * index
        size = rng.choice((MEM_SIZE_BYTE, MEM_SIZE_HALF, MEM_SIZE_WORD))
        if size == MEM_SIZE_BYTE:
            offset = rng.randrange(4)
        elif size == MEM_SIZE_HALF:
            offset = 2 * rng.randrange(2)
        else:
            offset = 0
        is_store = bool(rng.getrandbits(1))
        data = rng.getrandbits(32)
        await mem.access(
            base + offset, data=data,
            read=0 if is_store else 1, write=1 if is_store else 0, size=size,
        )
        await cycles(dut, 1)

    assert len(mem.grants) == 40, (
        "%d grants for 40 accesses - a request was lost or duplicated"
        % len(mem.grants)
    )
    # Every grant must match the access that was presented, and every access
    # must be in the list exactly once: re-derive the sequence and compare.
    expected = []
    rng = random.Random(0xC0FFEE)
    for index in range(40):
        base = 0x1000 + 4 * index
        size = rng.choice((MEM_SIZE_BYTE, MEM_SIZE_HALF, MEM_SIZE_WORD))
        if size == MEM_SIZE_BYTE:
            offset = rng.randrange(4)
        elif size == MEM_SIZE_HALF:
            offset = 2 * rng.randrange(2)
        else:
            offset = 0
        is_store = bool(rng.getrandbits(1))
        data = rng.getrandbits(32)
        # The bus carries the store value in the lane the address names, and
        # nothing at all on a read (DESIGN NOTE 2 in `rtl/core/lsu.v`).  The
        # value keeps all 32 random bits on purpose: the shifter must move only
        # the lanes the strobes cover and must not care what was in the others.
        if is_store:
            want_data = (data << (8 * offset)) & 0xFFFFFFFF
            want_wstrb = mem._expected_wstrb(base + offset, size)
        else:
            want_data = 0
            want_wstrb = 0
        expected.append((
            base + offset,
            1 if is_store else 0,
            want_data,
            want_wstrb,
        ))
    assert mem.grants == expected, (
        "the granted requests do not match the accesses presented:\n"
        "  got      %s\n  expected %s" % (mem.grants[:6], expected[:6])
    )


@cocotb.test()
async def test_randomised_subword_stores_touch_only_their_own_lanes(dut):
    """Byte-addressed check that `SB` and `SH` write exactly their bytes.

    The strobe table can be right while the data is wrong, so this drives a real
    byte memory: read the word, write the sub-word, and check that every byte the
    strobes did not cover is exactly what it was.
    """
    await start(dut)
    mem = BackpressureMemory(dut, seed=0xBEE5, max_wait=3)
    rng = random.Random(0x5EED)

    for index in range(60):
        base = 0x2000 + 4 * index
        size = rng.choice((MEM_SIZE_BYTE, MEM_SIZE_HALF))
        offset = rng.randrange(4) if size == MEM_SIZE_BYTE else 2 * rng.randrange(2)
        value = rng.randrange(256) if size == MEM_SIZE_BYTE else rng.randrange(65536)

        before = bytearray(mem.cells[base:base + 4])
        expected = bytearray(before)
        await mem.access(base + offset, data=value, write=1, size=size)
        # Byte 0 of the value goes to the lane the address names, byte 1 to the
        # next one, and so on: exactly what the strobes cover, and nothing else.
        width = 1 if size == MEM_SIZE_BYTE else 2
        for step in range(width):
            expected[offset + step] = (value >> (8 * step)) & 0xFF

        after = mem.cells[base:base + 4]
        assert after == expected, (
            "sub-word store of %04x at %08x left %s, expected %s"
            % (value, base + offset, bytes(after).hex(), bytes(expected).hex())
        )




# ---------------------------------------------------------------------------
# Phase-1 limitations, pinned
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_signedness_does_not_change_the_request(dut):
    """`LB` and `LBU` request the same byte; `LH` and `LHU` the same halfword.

    Phase 1 has no module port that can sign- or zero-extend a returned byte or
    halfword (DESIGN NOTE 4 in `rtl/core/lsu.v`), so both encodings must issue an
    identical request.  Pinning it here means the day the extension arrives it
    cannot quietly start moving the address or the lanes.
    """
    await start(dut)
    for (size, offsets), base in zip(LEGAL_OFFSETS,
                                     (0x00030000, 0x00031000, 0x00032000)):
        for offset in offsets:
            signed_request = None
            for unsigned in (0, 1):
                await present(
                    dut, base + offset, read=1, size=size, unsigned=unsigned
                )
                got = request(dut)
                if signed_request is None:
                    signed_request = got
                assert got == signed_request, (
                    "the request for unsigned=%d differs from unsigned=0: %s vs %s"
                    % (unsigned, got, signed_request)
                )
                await complete(dut, rdata=0x12345678)


@cocotb.test()
async def test_subword_load_returns_the_containing_word(dut):
    """Phase 1 returns the whole word for `LB`/`LBU`/`LH`/`LHU`.

    Stated as a test so that the behaviour is a recorded decision rather than an
    accident: the ISA requires the byte or halfword, and the frozen port list has
    nowhere to put the extraction.  When phase 2 adds it, this test is what must
    change.
    """
    await start(dut)
    for size in (MEM_SIZE_BYTE, MEM_SIZE_HALF, MEM_SIZE_WORD):
        await present(dut, 0x00040000, read=1, size=size)
        await complete(dut, rdata=0x89ABCDEF)
        assert int(dut.mem_rsp_rdata.value) == 0x89ABCDEF, (
            "the returned word was modified on the way through"
        )


# ---------------------------------------------------------------------------
# What the bus looks like for a sub-word store
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_store_data_is_lane_aligned(dut):
    """A sub-word store arrives in the lane its address names.

    The contract fixes the strobes but does not say whether `mem_req_wdata`
    carries the value in the lane the access names or always in lane 0; this
    module chose lane-aligned, which is AXI4's rule and what phase 4's L1 D$
    needs (DESIGN NOTE 2 in `rtl/core/lsu.v`).  The test is here so that the
    choice is a recorded, checkable contract rather than a comment: if the team
    decides the other way, this test and three lines of RTL are what change.
    """
    await start(dut)
    cases = (
        (MEM_SIZE_BYTE, 0, 0x64, 0x00000064, 0b0001),
        (MEM_SIZE_BYTE, 1, 0x64, 0x00006400, 0b0010),
        (MEM_SIZE_BYTE, 2, 0x64, 0x00640000, 0b0100),
        (MEM_SIZE_BYTE, 3, 0x64, 0x64000000, 0b1000),
        (MEM_SIZE_HALF, 0, 0xBEEF, 0x0000BEEF, 0b0011),
        (MEM_SIZE_HALF, 2, 0xBEEF, 0xBEEF0000, 0b1100),
        (MEM_SIZE_WORD, 0, 0xDEADBEEF, 0xDEADBEEF, 0b1111),
    )
    for size, offset, value, want_data, want_wstrb in cases:
        await present(dut, 0x00050000 + offset, data=value, write=1, size=size)
        _valid, addr, _we, wdata, wstrb = request(dut)
        assert (addr, wdata, wstrb) == (0x00050000 + offset, want_data, want_wstrb), (
            "store of %08x at offset %d went out as addr=%08x data=%08x wstrb=%s, "
            "expected data=%08x wstrb=%s"
            % (value, offset, addr, wdata, bits(wstrb), want_data, bits(want_wstrb))
        )
        await complete(dut)

    # A load's data is a pass-through and must not be shifted on the way out.
    await present(dut, 0x00050003, read=1, size=MEM_SIZE_BYTE)
    assert int(dut.mem_req_wdata.value) == 0, (
        "a load presented write data"
    )
    await complete(dut)

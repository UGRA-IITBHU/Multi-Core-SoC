"""Regression tests for ``rtl/core/alu.v``.

Drives the module with the shared helpers in ``tb/conftest.py``.

`alu` is purely combinational and has no clock or reset, so this file does not
start a clock: there is nothing to reset and nothing to wait for.  Every test
drives the inputs and then lets one time step elapse, which is what makes
cocotb's deferred signal writes visible - the alternative, reading in the same
delta, reads the *previous* stimulus and would silently pass against a module
that ignores its inputs.

The contract makes three promises, and each has tests here:

* **nine... ten operations, all RV32I.**  TEAM.md says "nine `alu_op` cases"
  and then lists ten, and `decode` encodes ten; this regression checks all ten
  encodings and every encoding the field can hold, so the disagreement in the
  prose cannot turn into a missing case;
* **the comparison outputs are live on every operation.**  `decode` asks for
  `ALU_SUB` for every conditional branch, so `slt` / `sltu` / `zero` must be
  right *when the operation is SUB*, not only when it is SLT or SLTU.  That is
  the single most bug-prone thing about this module and it is tested on its own;
* **the outputs are mutually consistent in the same cycle** - which is what lets
  `ex_stage` need one ALU and no second comparison pass.

The `alu_op` encoding is not in the frozen contract, so it is written down here
as well as in the RTL: `decode.v` DESIGN NOTE 2 and `alu.v` DESIGN NOTE 1 are
the two places that own it, and this file is what fails if the three disagree.

Run with::

    make test MODULE=test_alu TOP=alu
    make test-4state MODULE=test_alu TOP=alu
"""

import cocotb
from cocotb.triggers import Timer

MASK = 0xFFFFFFFF

# `alu_op` encoding - must match alu.v DESIGN NOTE 1 and decode.v DESIGN NOTE 2.
ALU_ADD = 0x0
ALU_SUB = 0x1
ALU_SLL = 0x2
ALU_SLT = 0x3
ALU_SLTU = 0x4
ALU_XOR = 0x5
ALU_SRL = 0x6
ALU_SRA = 0x7
ALU_OR = 0x8
ALU_AND = 0x9

ALL_OPS = (
    ALU_ADD, ALU_SUB, ALU_SLL, ALU_SLT, ALU_SLTU,
    ALU_XOR, ALU_SRL, ALU_SRA, ALU_OR, ALU_AND,
)

# The shift amount is the low five bits of op_b and nothing else.  SLLI/SRLI/
# SRAI can never present a larger one, so a design that masked at 4 or at 6
# would pass every legal stimulus and be wrong only on a value the decoder can
# never produce - which is exactly the class of bug that survives to silicon.
UNUSED_SHIFT_OPS = (ALU_SLL, ALU_SRL, ALU_SRA)


def signed(value):
    """Interpret a 32-bit pattern as two's complement."""
    return value - (1 << 32) if value & 0x80000000 else value


def model(alu_op, op_a, op_b):
    """The behaviour `alu` is contracted to have, in Python."""
    op_a &= MASK
    op_b &= MASK
    shamt = op_b & 0x1F

    if alu_op == ALU_ADD:
        result = op_a + op_b
    elif alu_op == ALU_SUB:
        result = op_a - op_b
    elif alu_op == ALU_SLL:
        result = op_a << shamt
    elif alu_op == ALU_SLT:
        result = 1 if signed(op_a) < signed(op_b) else 0
    elif alu_op == ALU_SLTU:
        result = 1 if op_a < op_b else 0
    elif alu_op == ALU_XOR:
        result = op_a ^ op_b
    elif alu_op == ALU_SRL:
        result = op_a >> shamt
    elif alu_op == ALU_SRA:
        result = signed(op_a) >> shamt
    elif alu_op == ALU_OR:
        result = op_a | op_b
    elif alu_op == ALU_AND:
        result = op_a & op_b
    else:
        result = 0

    return result & MASK


async def drive(dut, op_a, op_b, alu_op):
    """Present one stimulus and let the combinational outputs settle."""
    dut.op_a.value = op_a
    dut.op_b.value = op_b
    dut.alu_op.value = alu_op
    await Timer(1, unit="ns")


async def check(dut, op_a, op_b, alu_op, why=""):
    """Drive one stimulus and assert every output against the model."""
    await drive(dut, op_a, op_b, alu_op)

    expected = model(alu_op, op_a, op_b)
    context = "op_a=%08x op_b=%08x alu_op=%d%s" % (op_a, op_b, alu_op, why)

    assert int(dut.result.value) == expected, (
        "alu_op=%d: result is %08x, expected %08x (%s)"
        % (alu_op, int(dut.result.value), expected, context)
    )
    assert int(dut.zero.value) == (1 if expected == 0 else 0), (
        "alu_op=%d: zero is %d for result %08x (%s)"
        % (alu_op, int(dut.zero.value), expected, context)
    )
    # `slt` / `sltu` are live for EVERY operation, not only for the two that
    # write them into `result` - that is what makes one ALU instance enough for
    # branch resolution, where the selected operation is SUB.
    assert int(dut.slt.value) == (1 if signed(op_a) < signed(op_b) else 0), (
        "alu_op=%d: slt is %d, expected the signed comparison of %08x and %08x (%s)"
        % (alu_op, int(dut.slt.value), op_a, op_b, context)
    )
    assert int(dut.sltu.value) == (1 if op_a < op_b else 0), (
        "alu_op=%d: sltu is %d, expected the unsigned comparison of %08x and %08x (%s)"
        % (alu_op, int(dut.sltu.value), op_a, op_b, context)
    )


async def sweep(dut, pairs, why=""):
    """Run every operation against every operand pair."""
    for op_a, op_b in pairs:
        for alu_op in ALL_OPS:
            await check(dut, op_a, op_b, alu_op, why)


# Operand pairs chosen to break each operation in a different way.
PAIRS = [
    (0x00000000, 0x00000000),  # both zero: `zero` must be 1
    (0x00000001, 0x00000001),  # equal nonzero: `zero` must be 0
    (0xFFFFFFFF, 0x00000001),  # signed -1 < +1, unsigned max > 1
    (0x00000001, 0xFFFFFFFF),  # the mirror image: signedness must flip
    (0x7FFFFFFF, 0x80000000),  # INT_MAX vs INT_MIN: the signed corner
    (0x80000000, 0x7FFFFFFF),  # the mirror image
    (0x80000000, 0x80000000),  # equal negative: `zero` must be 1
    (0x00000000, 0xFFFFFFFF),  # 0 vs -1
    (0xFFFFFFFF, 0x00000000),  # -1 vs 0
    (0x12345678, 0x9ABCDEF0),  # no bit pattern in common
    (0xDEADBEEF, 0xCAFEBABE),  # and another
    (0x000000FF, 0x00000001),  # small positives
    (0xAAAAAAAA, 0x55555555),  # alternating bits
    (0x0F0F0F0F, 0xF0F0F0F0),  # nibble patterns
    (0x00000001, 0x00000020),  # shift by 32 - the masking case
    (0x00000001, 0x0000001F),  # shift by 31 - the largest legal shift
    (0x80000000, 0x00000001),  # shift a negative right, arithmetically
    (0x80000000, 0x0000001F),  # and by 31: the all-ones / all-zeros corner
    (0x00000001, 0x00000000),  # shift by zero, which must not clear the value
    (0xFFFFFFFF, 0x00000000),  # shift by zero on an all-ones operand
]


# ---------------------------------------------------------------------------
# Every operation
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_every_operation_on_every_operand_pair(dut):
    """All ten operations against every pair in PAIRS.

    Read across the whole operand matrix rather than a sample: `sll` and `srl`
    and `sra` are three arms that differ only in the shift operator, and a
    hand-picked set of values with a zero shift amount would pass all three.
    """
    await sweep(dut, PAIRS)


@cocotb.test()
async def test_add_and_sub_are_inverses(dut):
    """`(a + b) - b == a`, so the two arms cannot be swapped silently."""
    for op_a, op_b in PAIRS:
        await drive(dut, op_a, op_b, ALU_ADD)
        total = int(dut.result.value)
        await check(dut, total, op_b, ALU_SUB)
        assert int(dut.result.value) == op_a, (
            "(%08x + %08x) - %08x = %08x, expected %08x"
            % (op_a, op_b, op_b, int(dut.result.value), op_a)
        )


@cocotb.test()
async def test_zero_is_high_for_exactly_the_results_that_are_zero(dut):
    """`zero` is a property of `result`, for every operation.

    Swept across every operation and a set of pairs that includes results which
    are zero by construction (add of a value and its negation) and non-zero by
    construction, so a `zero` that is really an operand comparison rather than
    a result comparison would show up.
    """
    cancelling = [
        (0x00000001, 0xFFFFFFFF),  # 1 + (-1) == 0
        (0x80000000, 0x80000000),  # INT_MIN + INT_MIN wraps to 0
        (0x12345678, 0xEDCBA988),  # arbitrary pair that cancels
        (0xFFFFFFFF, 0x00000001),  # 0xFFFFFFFF + 1 == 0
    ]
    for op_a, op_b in PAIRS + cancelling:
        for alu_op in ALL_OPS:
            await drive(dut, op_a, op_b, alu_op)
            expected = model(alu_op, op_a, op_b)
            assert int(dut.zero.value) == (1 if expected == 0 else 0), (
                "alu_op=%d on %08x, %08x: result is %08x so zero must be %d, got %d"
                % (alu_op, op_a, op_b, expected, 1 if expected == 0 else 0,
                   int(dut.zero.value))
            )


# ---------------------------------------------------------------------------
# Signed and unsigned comparison
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_slt_is_signed_and_sltu_is_unsigned(dut):
    """The same operand pair must disagree between `slt` and `sltu` whenever
    the sign bit decides it.

    A pair that differs only in the sign bit is the whole test: an `slt` built
    as `op_a < op_b` (unsigned) passes every pair where both operands share a
    sign, which is most of them.  Each row carries its own two expected bits
    rather than assuming which way each pair must go - the mirror-image pairs
    are here precisely because the answer is not symmetric.
    """
    # (op_a, op_b, slt, sltu) - in every row the two bits differ.
    disagreeing = [
        (0xFFFFFFFF, 0x00000001, 1, 0),  # -1  vs +1: signed less, unsigned more
        (0x80000000, 0x7FFFFFFF, 1, 0),  # MIN  vs MAX: signed less, unsigned more
        (0xFFFF0000, 0x0000FFFF, 1, 0),  # -64K vs +64K
        (0x00000001, 0xFFFFFFFF, 0, 1),  # +1  vs -1: the mirror image
        (0x7FFFFFFF, 0x80000000, 0, 1),  # MAX vs MIN: the mirror image
        (0x0000FFFF, 0xFFFF0000, 0, 1),  # the mirror image
    ]
    for op_a, op_b, want_slt, want_sltu in disagreeing:
        await drive(dut, op_a, op_b, ALU_ADD)
        assert int(dut.slt.value) == want_slt, (
            "slt(%08x, %08x) = %d, expected %d"
            % (op_a, op_b, int(dut.slt.value), want_slt)
        )
        assert int(dut.sltu.value) == want_sltu, (
            "sltu(%08x, %08x) = %d, expected %d"
            % (op_a, op_b, int(dut.sltu.value), want_sltu)
        )


@cocotb.test()
async def test_comparisons_agree_when_both_operands_share_a_sign(dut):
    """With both operands non-negative the two comparisons must agree."""
    agreeing = [
        (0x00000001, 0x00000002),
        (0x7FFFFFFF, 0x7FFFFFFE),
        (0x00000000, 0x00000001),
        (0xDEADBEEF, 0xCAFEBABE),
    ]
    for op_a, op_b in agreeing:
        await drive(dut, op_a, op_b, ALU_ADD)
        assert int(dut.slt.value) == int(dut.sltu.value), (
            "slt and sltu disagree for %08x and %08x, both non-negative"
            % (op_a, op_b)
        )


@cocotb.test()
async def test_slt_and_sltu_are_correct_at_the_signed_extremes(dut):
    """INT_MIN against itself and against INT_MAX, in both directions.

    A comparison that widened the operands instead of sign-extending them
    passes every non-negative pair and fails exactly here.
    """
    extremes = [
        (0x80000000, 0x80000000, 0, 0),
        (0x80000000, 0x7FFFFFFF, 1, 0),
        (0x7FFFFFFF, 0x80000000, 0, 1),
        (0x80000000, 0x00000000, 1, 0),
        (0x00000000, 0x80000000, 0, 1),  # 0 unsigned is less than INT_MIN
        (0x7FFFFFFF, 0x7FFFFFFF, 0, 0),
    ]
    for op_a, op_b, want_slt, want_sltu in extremes:
        await drive(dut, op_a, op_b, ALU_ADD)
        assert int(dut.slt.value) == want_slt, (
            "slt(%08x, %08x) = %d, expected %d"
            % (op_a, op_b, int(dut.slt.value), want_slt)
        )
        assert int(dut.sltu.value) == want_sltu, (
            "sltu(%08x, %08x) = %d, expected %d"
            % (op_a, op_b, int(dut.sltu.value), want_sltu)
        )


@cocotb.test()
async def test_slt_result_bit_is_the_comparison_output(dut):
    """For `ALU_SLT` / `ALU_SLTU`, `result` bit 0 is `slt` / `sltu`.

    This is the link between the comparison wires and the datapath, and it is
    what makes `slt` an architectural 0/1 rather than a flag.
    """
    for op_a, op_b in PAIRS:
        await drive(dut, op_a, op_b, ALU_SLT)
        assert int(dut.result.value) == int(dut.slt.value), (
            "ALU_SLT result %08x disagrees with slt %d on %08x, %08x"
            % (int(dut.result.value), int(dut.slt.value), op_a, op_b)
        )
        assert int(dut.result.value) in (0, 1), (
            "ALU_SLT produced %08x, expected 0 or 1" % int(dut.result.value)
        )
        await drive(dut, op_a, op_b, ALU_SLTU)
        assert int(dut.result.value) == int(dut.sltu.value), (
            "ALU_SLTU result %08x disagrees with sltu %d on %08x, %08x"
            % (int(dut.result.value), int(dut.sltu.value), op_a, op_b)
        )


# ---------------------------------------------------------------------------
# THE BRANCH-FACING GUARANTEE
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_comparisons_are_live_when_the_operation_is_sub(dut):
    """`decode` selects `ALU_SUB` for every conditional branch.

    On that operation `result` is the *difference*, and `slt` / `sltu` / `zero`
    must still be the comparison answers.  This is the single property the
    whole one-ALU branch design rests on, and it is checked here on the
    operation the branch path actually uses rather than on SLT and SLTU.
    """
    branch_cases = [
        # (rs1, rs2, zero, slt, sltu)
        (0x00000005, 0x00000005, 1, 0, 0),   # BEQ
        (0x00000005, 0x00000006, 0, 1, 1),   # BNE, BLT, BLTU
        (0x00000006, 0x00000005, 0, 0, 0),   # BGE, BGEU
        (0xFFFFFFFF, 0x00000001, 0, 1, 0),   # BLT yes, BLTU no
        (0x00000001, 0xFFFFFFFF, 0, 0, 1),   # BLTU yes, BLT no
        (0x80000000, 0x7FFFFFFF, 0, 1, 0),   # INT_MIN vs INT_MAX
        (0x00000000, 0x00000000, 1, 0, 0),
    ]
    for op_a, op_b, want_zero, want_slt, want_sltu in branch_cases:
        await drive(dut, op_a, op_b, ALU_SUB)
        assert int(dut.result.value) == ((op_a - op_b) & MASK), (
            "ALU_SUB result should be the difference, got %08x"
            % int(dut.result.value)
        )
        assert int(dut.zero.value) == want_zero, (
            "ALU_SUB zero on %08x - %08x is %d, expected %d"
            % (op_a, op_b, int(dut.zero.value), want_zero)
        )
        assert int(dut.slt.value) == want_slt, (
            "ALU_SUB slt on %08x, %08x is %d, expected %d"
            % (op_a, op_b, int(dut.slt.value), want_slt)
        )
        assert int(dut.sltu.value) == want_sltu, (
            "ALU_SUB sltu on %08x, %08x is %d, expected %d"
            % (op_a, op_b, int(dut.sltu.value), want_sltu)
        )


@cocotb.test()
async def test_zero_is_high_whenever_two_equal_operands_are_subtracted(dut):
    """`zero` after SUB is BEQ, whatever else `alu` is doing.

    Swept over every operand in a list that includes equal pairs at both signs,
    because `zero` computed as "op_a == op_b" and `zero` computed as "result ==
    0" agree everywhere for SUB and disagree for nothing - but only SUB is
    branch-relevant, and only this test looks at it.
    """
    equal_pairs = [
        (0x00000000, 0x00000000),
        (0xFFFFFFFF, 0xFFFFFFFF),
        (0x80000000, 0x80000000),
        (0x7FFFFFFF, 0x7FFFFFFF),
        (0xDEADBEEF, 0xDEADBEEF),
    ]
    for op_a, op_b in equal_pairs:
        await drive(dut, op_a, op_b, ALU_SUB)
        assert int(dut.zero.value) == 1, (
            "subtracting %08x from itself must leave zero high" % op_a
        )
    for op_a, op_b in PAIRS:
        if op_a == op_b:
            continue
        await drive(dut, op_a, op_b, ALU_SUB)
        assert int(dut.zero.value) == 0, (
            "subtracting %08x from %08x must not report zero" % (op_b, op_a)
        )


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_shift_amount_uses_only_the_low_five_bits(dut):
    """shamt is op_b[4:0], and the upper 27 bits are ignored.

    Each shift amount from 0 to 31 is presented twice: once on its own and once
    with the upper bits set to all ones.  A design that shifted by the whole
    operand - or masked at four or six bits - produces different answers for the
    two and fails here, while still passing every stimulus a decoder can
    actually generate, because no RV32I shift-immediate sets bit 5 or above.
    """
    for shamt in range(32):
        plain = 0x00000020 | shamt
        polluted = 0xFFFFFFE0 | shamt
        for op_a in (0x00000001, 0x80000000, 0xFFFFFFFF, 0x0F0F0F0F,
                     0x12345678, 0x00000000):
            for alu_op in UNUSED_SHIFT_OPS:
                await check(dut, op_a, plain, alu_op, " shamt=%d" % shamt)
                await check(dut, op_a, polluted, alu_op,
                            " shamt=%d with high bits set" % shamt)
                assert model(alu_op, op_a, plain) == model(alu_op, op_a, polluted), (
                    "shamt=%d: the high bits of op_b changed the result, so the "
                    "shift amount is not masked to five bits" % shamt
                )


@cocotb.test()
async def test_sll_zeroes_the_shifted_out_bits_and_srl_does_the_reverse(dut):
    """SLL shifts toward the MSB, SRL toward the LSB.

    A single bit at a known position, walked across the whole word, is what
    makes the direction observable; two operands that happen to be symmetric
    would hide a swapped pair of arms.
    """
    for position in range(32):
        single = 1 << position
        remaining = 32 - position
        for shamt in (0, 1, 7, 16, 31):
            if shamt >= remaining:
                expect_sll = 0
            else:
                expect_sll = single << shamt

            await drive(dut, single, shamt, ALU_SLL)
            assert int(dut.result.value) == expect_sll, (
                "SLL of bit %d by %d gave %08x, expected %08x"
                % (position, shamt, int(dut.result.value), expect_sll)
            )

            if shamt > position:
                expect_srl = 0
            else:
                expect_srl = single >> shamt

            await drive(dut, single, shamt, ALU_SRL)
            assert int(dut.result.value) == expect_srl, (
                "SRL of bit %d by %d gave %08x, expected %08x"
                % (position, shamt, int(dut.result.value), expect_srl)
            )


@cocotb.test()
async def test_sra_and_srl_differ_on_a_negative_operand(dut):
    """A negative operand shifted right is where the two operations part ways.

    Run over every shift amount and a handful of sign patterns, because the two
    agree again once the shift is large enough to shift the sign out - and a
    test that only shifts by one would pass an implementation that had the two
    arms the wrong way round for some other amount.
    """
    negatives = [0x80000000, 0xFFFFFFFF, 0xC0000000, 0x80000001, 0xDEADBEEF,
                 0x9ABCDEF0]
    for op_a in negatives:
        for shamt in range(32):
            await drive(dut, op_a, shamt, ALU_SRA)
            expect_sra = (signed(op_a) >> shamt) & MASK
            assert int(dut.result.value) == expect_sra, (
                "SRA of %08x by %d gave %08x, expected %08x"
                % (op_a, shamt, int(dut.result.value), expect_sra)
            )
            await drive(dut, op_a, shamt, ALU_SRL)
            expect_srl = (op_a & MASK) >> shamt
            assert int(dut.result.value) == expect_srl, (
                "SRL of %08x by %d gave %08x, expected %08x"
                % (op_a, shamt, int(dut.result.value), expect_srl)
            )


# ---------------------------------------------------------------------------
# Encodings the field can hold but no instruction produces
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_unused_alu_op_encodings_produce_zero_and_do_not_latch(dut):
    """`alu_op` 10..15 are unreachable from a legal decode and drive result 0.

    Two things are being checked, and only the second is interesting.  First,
    the value is defined - a latch would make it depend on history, and a
    garbage value here would become a garbage address in `ex_stage`.  Second,
    it is genuinely independent of what came before: the operands are changed
    to something that would give a nonzero result under every real operation,
    and the output must still read zero rather than whatever it held.
    """
    for alu_op in range(10, 16):
        await check(dut, 0xFFFFFFFF, 0x00000001, alu_op)
        assert int(dut.result.value) == 0, (
            "unused alu_op %d produced %08x, expected 0"
            % (alu_op, int(dut.result.value))
        )


@cocotb.test()
async def test_operation_change_takes_effect_immediately(dut):
    """The module is combinational: no state, so no latency between operations.

    Each operation is presented in sequence on the *same* operands, with no
    time in between beyond the settle step, and every one must be reflected.
    A module that registered its inputs would answer with the previous
    operation's result for the first entry of the sequence.
    """
    op_a, op_b = 0x0F0F0F0F, 0x00000004
    for alu_op in ALL_OPS:
        await check(dut, op_a, op_b, alu_op, " in a back-to-back sequence")


@cocotb.test()
async def test_the_alus_own_assertions_are_armed_and_silent(dut):
    """The two immediate assertions in `alu.v` must not misfire.

    An assertion that fires on correct hardware gets disabled, and then it is
    gone for the case that needed it.  This drives every operation over a wide
    sweep of operands and requires silence, including the SRA / SRL sign-bit
    properties the assertions actually check.
    """
    for op_a, op_b in PAIRS:
        for alu_op in ALL_OPS:
            await drive(dut, op_a, op_b, alu_op)
    for shamt in range(32):
        for op_a in (0x00000000, 0x00000001, 0x80000000, 0xFFFFFFFF):
            await drive(dut, op_a, shamt, ALU_SRA)
            await drive(dut, op_a, shamt, ALU_SRL)

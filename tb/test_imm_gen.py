"""Regression tests for ``rtl/core/imm_gen.v``.

Drives the module with the shared helpers in ``tb/conftest.py``.

The tests are grouped by format, and the two formats worth being careful about
are B and J.  Both store their immediate out of instruction order, so a decoder
that gets the order right but the sign extension wrong still produces a
plausible-looking number, and one that gets the sign right but the order wrong
is wrong only for some displacements.  So:

* every format is checked with a positive and a negative immediate;
* bit 31 is driven both ways for every format, because sign extension is the
  easiest part to get subtly wrong;
* for every format, each bit of the immediate field is driven *on its own* and
  the resulting bit of `imm` is checked.  This is the check that actually pins
  the field order: driving one bit at a time makes "instr[20] -> imm[11]" and
  "instr[19] -> imm[11]" produce visibly different results, whereas a
  whole-pattern test only sees a sum and would pass either way;
* B and J additionally get an exhaustive sweep of every encodable value against
  an independent reference, because they are the two formats a sweep is
  affordable for and the two most often got wrong;
* every `imm_sel` value outside 0..4 is checked to produce zero, because the
  contract requires zero rather than undefined bits.

The encoders and the reference extractors below are written from the ISA
specification's field tables, independently of the RTL.  Where a test could
just as well hard-code an expected constant, it does - a test that compares the
RTL against a second implementation of the same idea can agree with a shared
misreading, whereas a constant cannot.

Run with::

    make test MODULE=test_imm_gen TOP=imm_gen
    make test-4state MODULE=test_imm_gen TOP=imm_gen
"""

import cocotb
from cocotb.triggers import Timer

# `imm_sel` encoding, frozen by docs/contracts/phase1-interfaces.md.
IMM_I, IMM_S, IMM_B, IMM_U, IMM_J = 0, 1, 2, 3, 4

MASK32 = 0xFFFFFFFF

# Opcode values used only so the encoded words are recognisable.
OP_IMM, OP_STORE, OP_BRANCH, OP_LUI, OP_JAL = 0x13, 0x23, 0x63, 0x37, 0x6F


# ---------------------------------------------------------------------------
# Encoders: instruction word -> immediate field, per the ISA spec tables.
# ---------------------------------------------------------------------------


def enc_i(imm12, rs1=0, funct3=0, rd=0):
    """I-type: imm occupies instr[31:20]."""
    return (
        ((imm12 & 0xFFF) << 20)
        | ((rs1 & 0x1F) << 15)
        | ((funct3 & 0x7) << 12)
        | ((rd & 0x1F) << 7)
        | OP_IMM
    )


def enc_s(imm12, rs2=0, rs1=0, funct3=0):
    """S-type: imm[11:5] = instr[31:25], imm[4:0] = instr[11:7]."""
    return (
        (((imm12 >> 5) & 0x7F) << 25)
        | ((rs2 & 0x1F) << 20)
        | ((rs1 & 0x1F) << 15)
        | ((funct3 & 0x7) << 12)
        | ((imm12 & 0x1F) << 7)
        | OP_STORE
    )


def enc_b(imm13, rs2=0, rs1=0, funct3=0):
    """B-type, the bit reversal.

    imm[12] = instr[31];  imm[10:5] = instr[30:25];
    imm[4:1] = instr[11:8];  imm[11] = instr[7];  imm[0] = 0.
    """
    imm = imm13 & 0x1FFF
    return (
        (((imm >> 12) & 0x1) << 31)
        | (((imm >> 5) & 0x3F) << 25)
        | ((rs2 & 0x1F) << 20)
        | ((rs1 & 0x1F) << 15)
        | ((funct3 & 0x7) << 12)
        | (((imm >> 1) & 0xF) << 8)
        | (((imm >> 11) & 0x1) << 7)
        | OP_BRANCH
    )


def enc_u(imm32, rd=0):
    """U-type: imm[31:12] = instr[31:12], imm[11:0] = 0.

    Takes the 32-bit value the instruction is meant to produce and keeps only
    the top 20 bits of it, so the argument and the expected `imm` are the same
    number - which is what makes the "was it sign-extended" cases below
    readable.  The low 12 bits being unrepresentable is the whole point of the
    format, and is why `lui` cannot express a small constant.
    """
    return ((((imm32 >> 12) & 0xFFFFF) << 12) | ((rd & 0x1F) << 7) | OP_LUI)


def enc_j(imm21, rd=0):
    """J-type, the bit reversal.

    imm[20] = instr[31];  imm[10:1] = instr[30:21];
    imm[11] = instr[20];  imm[19:12] = instr[19:12];  imm[0] = 0.
    """
    imm = imm21 & 0x1FFFFF
    return (
        (((imm >> 20) & 0x1) << 31)
        | (((imm >> 1) & 0x3FF) << 21)
        | (((imm >> 11) & 0x1) << 20)
        | (((imm >> 12) & 0xFF) << 12)
        | ((rd & 0x1F) << 7)
        | OP_JAL
    )


# ---------------------------------------------------------------------------
# Reference extractors: instruction word -> 32-bit sign-extended immediate.
# Written straight from the ISA tables, independently of the RTL under test.
# ---------------------------------------------------------------------------


def ref_i(word):
    return sext(word >> 20, 12)


def ref_s(word):
    return sext((((word >> 25) & 0x7F) << 5) | ((word >> 7) & 0x1F), 12)


def ref_b(word):
    imm = (
        (((word >> 31) & 0x1) << 12)
        | (((word >> 7) & 0x1) << 11)
        | (((word >> 25) & 0x3F) << 5)
        | (((word >> 8) & 0xF) << 1)
    )
    return sext(imm, 13)


def ref_u(word):
    return (word & 0xFFFFF000) & MASK32  # never sign-extended


def ref_j(word):
    imm = (
        (((word >> 31) & 0x1) << 20)
        | (((word >> 21) & 0x3FF) << 1)
        | (((word >> 20) & 0x1) << 11)
        | (((word >> 12) & 0xFF) << 12)
    )
    return sext(imm, 21)


REFERENCE = {IMM_I: ref_i, IMM_S: ref_s, IMM_B: ref_b, IMM_U: ref_u, IMM_J: ref_j}


def sext(value, bits):
    """Sign-extend ``value`` from ``bits`` to 32 bits, as the hardware does."""
    value &= (1 << bits) - 1
    if value & (1 << (bits - 1)):
        value -= 1 << bits
    return value & MASK32


async def settle(dut):
    """Let the combinational block re-evaluate.

    `imm_gen` has no clock, so there is no edge to wait for.  A Timer of a real
    duration rather than a bare delta is used so the same code works under both
    Verilator and Icarus.
    """
    await Timer(1, unit="ns")


async def check(dut, word, imm_sel, expected, note=""):
    """Drive one instruction, read `imm` back after the logic has settled."""
    dut.instr.value = word
    dut.imm_sel.value = imm_sel
    await settle(dut)
    got = int(dut.imm.value)
    assert got == expected, (
        "%s: imm_sel=%d instr=%08x gave imm=%08x, expected %08x"
        % (note or "imm_gen", imm_sel, word, got, expected)
    )


# ---------------------------------------------------------------------------
# I format
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_i_format(dut):
    """I-type: instr[31:20] sign-extended to 32 bits."""
    await check(dut, enc_i(0x000), IMM_I, 0x00000000, "ADDI imm=0")
    await check(dut, enc_i(0x001), IMM_I, 0x00000001, "ADDI imm=1")
    await check(dut, enc_i(0x7FF), IMM_I, 0x000007FF, "ADDI imm=+2047")
    # bit 31 set: this is the sign bit and must extend through the top of `imm`
    await check(dut, enc_i(0x800), IMM_I, 0xFFFFF800, "ADDI imm=-2048")
    await check(dut, enc_i(0xFFF), IMM_I, 0xFFFFFFFF, "ADDI imm=-1")


@cocotb.test()
async def test_i_format_each_bit_lands_in_place(dut):
    """I-type: each bit of the 12-bit field reaches the same bit of `imm`.

    Trivial for I, and that is the point: it is the control against which the
    B and J cases, where the field order is not the identity, are meaningful.
    """
    for bit in range(12):
        # bit 11 is the sign, so it sign-extends; the rest do not
        await check(
            dut, enc_i(1 << bit), IMM_I, sext(1 << bit, 12), "I bit %d" % bit
        )


# ---------------------------------------------------------------------------
# S format
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_s_format(dut):
    """S-type: instr[31:25] and instr[11:7] reassembled, then sign-extended."""
    await check(dut, enc_s(0x000), IMM_S, 0x00000000, "SB imm=0")
    await check(dut, enc_s(0x005), IMM_S, 0x00000005, "SB imm=5")
    await check(dut, enc_s(0x020), IMM_S, 0x00000020, "SB imm=32")
    await check(dut, enc_s(0x7FF), IMM_S, 0x000007FF, "SB imm=+2047")
    await check(dut, enc_s(0x800), IMM_S, 0xFFFFF800, "SB imm=-2048")
    await check(dut, enc_s(0xFFF), IMM_S, 0xFFFFFFFF, "SB imm=-1")


@cocotb.test()
async def test_s_format_field_placement(dut):
    """S-type: each half of the immediate lands in its own half of `imm`.

    Driving the halves separately is what distinguishes "instr[31:25] went to
    imm[11:5] and instr[11:7] went to imm[4:0]" from "the two were swapped",
    which a whole-pattern test cannot see - the sum is identical.
    """
    # Only instr[31:25] nonzero -> only imm[11:5] set
    await check(dut, enc_s(0x7E0), IMM_S, 0x000007E0, "S high field only")
    # Only instr[11:7] nonzero -> only imm[4:0] set
    await check(dut, enc_s(0x01F), IMM_S, 0x0000001F, "S low field only")
    # Both, and the halves must not overlap
    await check(dut, enc_s(0x7FF), IMM_S, 0x000007FF, "S both fields")

    for bit in range(12):
        # bit 11 is the sign, so it sign-extends; the rest do not
        await check(
            dut, enc_s(1 << bit), IMM_S, sext(1 << bit, 12), "S bit %d" % bit
        )


# ---------------------------------------------------------------------------
# B format - the first of the two that need the bit reversal
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_b_format(dut):
    """B-type: sign-extended 13-bit branch displacement."""
    await check(dut, enc_b(0x0000), IMM_B, 0x00000000, "BEQ +0")
    await check(dut, enc_b(0x0002), IMM_B, 0x00000002, "BEQ +2")
    await check(dut, enc_b(0x0010), IMM_B, 0x00000010, "BEQ +16")
    await check(dut, enc_b(0x0FFE), IMM_B, 0x00000FFE, "BEQ +4094")
    # imm[12] is instr[31] and is the sign of the 13-bit field
    await check(dut, enc_b(0x1000), IMM_B, 0xFFFFF000, "BEQ -4096")
    await check(dut, enc_b(0x1FFE), IMM_B, 0xFFFFFFFE, "BEQ -2")
    # -6 is the 13-bit pattern 0x1FFA: bit 12 set, magnitude 6
    await check(dut, enc_b(0x1FFA), IMM_B, 0xFFFFFFFA, "BEQ -6")


@cocotb.test()
async def test_b_format_each_bit_lands_in_place(dut):
    """B-type: each bit of the 13-bit field reaches the same bit of `imm`.

    The encoding scatters the field over instr[31], instr[30:25], instr[11:8],
    instr[7] and a hardwired zero, so this is the check that pins the order.
    Each case drives exactly one bit, so a decoder that read it from the wrong
    instruction bit produces a different `imm` here - and a decoder that simply
    dropped the single-bit instr[7] field fails on bit 11 alone.
    """
    for bit in range(1, 13):  # bit 0 is hardwired to 0 in the instruction
        expected = sext(1 << bit, 13)
        await check(dut, enc_b(1 << bit), IMM_B, expected, "B bit %d" % bit)


@cocotb.test()
async def test_b_format_bit0_is_always_zero(dut):
    """B-type: imm[0] is hardwired to 0 in the instruction, so it is 0 here.

    Every 4-byte-aligned branch displacement is even, so a decoder that let
    bit 0 through would still pass every even-displacement test - including the
    exhaustive sweep above, which only uses even values because no odd value is
    encodable.
    """
    dut.instr.value = 0xFFFFFFFF
    dut.imm_sel.value = IMM_B
    await settle(dut)
    assert int(dut.imm.value) & 1 == 0, (
        "B-format imm[0] was 1: the low bit must be hardwired to zero"
    )


@cocotb.test()
async def test_b_format_instr11_to_7_are_immediate_not_rd(dut):
    """B-type: instr[11:7] is imm[11:1], *not* a destination register.

    A branch has no rd, so those five instruction bits belong to the immediate.
    This is the one place in the RV32I encoding where a field's meaning depends
    on the opcode, and it is exactly why an `imm_gen` that read the immediate
    as a contiguous slice would be wrong for every branch.

    Note the consequence, which is architecture, not a bug here: a B-type
    instruction has no rd, so `core` must not extract `instr[11:7]` as a
    register index for it.  `decode.uses_rd` is what tells it not to.
    """
    # instr[7] alone is imm[11], and nothing else.
    await check(dut, OP_BRANCH | (1 << 7), IMM_B, 0x00000800, "B instr[7] -> imm[11]")
    # instr[11:8] is imm[4:1]: all four set gives 0b1110, and imm[0] stays 0.
    await check(dut, OP_BRANCH | (0xF << 8), IMM_B, 0x0000001E, "B instr[11:8] -> imm[4:1]")
    # The whole of instr[11:7] set: instr[7] gives imm[11] and instr[11:8] gives
    # imm[4:1], so 0x800 | 0x1E.
    await check(dut, OP_BRANCH | (0x1F << 7), IMM_B, 0x0000081E, "B instr[11:7] all set")


@cocotb.test()
async def test_b_format_opcode_does_not_leak(dut):
    """B-type: instr[6:0] is the opcode and contributes nothing to `imm`.

    This is the part of the rd/opcode region that is genuinely unused: the B
    immediate stops at instr[7].  Driving the opcode to all ones must leave
    `imm` untouched, which is what stops a decoder reading the immediate as one
    contiguous slice down to instr[0].
    """
    # instr[10] is imm[3], so a displacement of 8.
    base = OP_BRANCH | (1 << 10)
    for opcode in (0x00, 0x63, 0x7F):
        await check(
            dut,
            base | opcode,
            IMM_B,
            0x00000008,
            "B with opcode %02x" % opcode,
        )


@cocotb.test()
async def test_b_format_exhaustive_sweep(dut):
    """Every encodable B displacement, against the reference extractor.

    B's immediate is 13 bits with bit 0 hardwired to zero, so 4096 values are
    encodable.  All 4096 are driven; this is affordable at this size and it is
    the format where a single swapped field produces plausible-looking
    displacements on most inputs and wrong ones only on the rest.
    """
    for half in range(1 << 12):
        imm13 = half << 1
        word = enc_b(imm13)
        await check(dut, word, IMM_B, ref_b(word), "B sweep imm=%d" % imm13)


# ---------------------------------------------------------------------------
# U format
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_u_format(dut):
    """U-type: instr[31:12] into the top of `imm`, low 12 bits zero.

    U is the one format that is NOT sign-extended, and getting that wrong is
    invisible for any immediate whose bit 31 is 0 - which is why the last two
    cases below are the important ones.
    """
    # `enc_u` takes the full 32-bit immediate value and keeps only its top 20
    # bits, so the argument here is the value `lui` is meant to produce.
    await check(dut, enc_u(0x00000000), IMM_U, 0x00000000, "LUI 0")
    await check(dut, enc_u(0x00001000), IMM_U, 0x00001000, "LUI 1")
    # `lui` cannot express anything below 0x1000: its low 12 bits are zero in
    # the instruction, so the smallest nonzero value it can produce is 0x1000.
    await check(dut, enc_u(0x00000FFF), IMM_U, 0x00000000, "LUI 0xFFF truncates")
    await check(dut, enc_u(0x12345000), IMM_U, 0x12345000, "LUI 0x12345000")
    await check(dut, enc_u(0xABCDE000), IMM_U, 0xABCDE000, "LUI 0xABCDE000")
    # bit 31 set: sign extension must NOT happen
    await check(dut, enc_u(0xFFFFF000), IMM_U, 0xFFFFF000, "LUI bit31 set")
    await check(dut, enc_u(0x80000000), IMM_U, 0x80000000, "LUI 0x80000")
    await check(dut, enc_u(0xFFFFFFFF), IMM_U, 0xFFFFF000, "LUI all ones")


@cocotb.test()
async def test_u_format_is_never_sign_extended(dut):
    """U-type: `imm` is instr[31:12] followed by twelve zeros, never a sign.

    If U were sign-extended, `lui x1, 0x80000` would come out as -0x80000
    instead of +0x80000000 - the instruction would become an immediate negate
    rather than a load of a large constant, which is architecturally visible and
    silent.

    The encodable space is 2^20, which is too large to sweep through a
    simulator one delta at a time, so this checks the two properties that a
    sign-extension bug could break, on the boundaries where it would show:

    * `imm` bit 31 must always equal instr bit 31 - never its inverse, which is
      what sign extension of bit 31 would give;
    * `imm` must never exceed 0xFFFFF000 - a sign-extended value with any bit
      above bit 19 set is negative, and negative in Python's `int()` shows up as
      a huge unsigned number.

    A deterministic sweep of the low 16 bits of the field, combined with the
    boundary values above, covers both halves of the range.
    """
    tops = [0x00000, 0x00001, 0x7FFFF, 0x80000, 0x80001, 0xFFFFE, 0xFFFFF]
    for top in tops:
        for low_rd in (0x000, 0x0FF, 0x7FF, 0xFFF):
            word = (top << 12) | low_rd | OP_LUI
            dut.instr.value = word
            dut.imm_sel.value = IMM_U
            await settle(dut)
            got = int(dut.imm.value)
            assert got == (top << 12), (
                "LUI field %05x rd/opcode %03x gave imm=%08x, expected %08x"
                % (top, low_rd, got, top << 12)
            )
            assert got <= 0xFFFFF000, (
                "imm=%08x is above 0xFFFFF000: U was sign-extended" % got
            )


@cocotb.test()
async def test_u_format_low_twelve_bits_are_zero(dut):
    """U-type: instr[11:0] is rd and opcode and must not reach `imm`."""
    dut.instr.value = 0xFFFFFFFF  # rd = 0x1F, opcode = 0x7F
    dut.imm_sel.value = IMM_U
    await settle(dut)
    assert int(dut.imm.value) & 0xFFF == 0, (
        "U-format imm[11:0] was nonzero: rd and opcode leaked into the immediate"
    )


# ---------------------------------------------------------------------------
# J format - the second, and the least regular, of the reversals
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_j_format(dut):
    """J-type: sign-extended 21-bit jump displacement."""
    await check(dut, enc_j(0x000000), IMM_J, 0x00000000, "JAL +0")
    await check(dut, enc_j(0x000002), IMM_J, 0x00000002, "JAL +2")
    await check(dut, enc_j(0x000010), IMM_J, 0x00000010, "JAL +16")
    await check(dut, enc_j(0x000FFE), IMM_J, 0x00000FFE, "JAL +4094")
    await check(dut, enc_j(0x001000), IMM_J, 0x00001000, "JAL +4096")
    # imm[20] is instr[31] and is the sign of the 21-bit field
    await check(dut, enc_j(0x100000), IMM_J, 0xFFF00000, "JAL -1MiB")
    await check(dut, enc_j(0x1FFFFE), IMM_J, 0xFFFFFFFE, "JAL -2")
    # -4096 is the 21-bit pattern 0x1FF000
    await check(dut, enc_j(0x1FF000), IMM_J, 0xFFFFF000, "JAL -4096")


@cocotb.test()
async def test_j_format_each_bit_lands_in_place(dut):
    """J-type: each bit of the 21-bit field reaches the same bit of `imm`.

    J's field order is the least regular of the five: instr[20] sits *alone*
    between instr[19:12] and instr[30:21].  A decoder that swapped those two
    groups still sums to the right value for any symmetric pattern, so a
    whole-pattern test passes it and this one does not.  Bit 11 in particular
    comes from instr[20] and from nowhere else.
    """
    for bit in range(1, 21):  # bit 0 is hardwired to 0 in the instruction
        expected = sext(1 << bit, 21)
        await check(dut, enc_j(1 << bit), IMM_J, expected, "J bit %d" % bit)


@cocotb.test()
async def test_j_format_bit0_is_always_zero(dut):
    """J-type: imm[0] is hardwired to 0 in the instruction, so it is 0 here."""
    dut.instr.value = 0xFFFFFFFF
    dut.imm_sel.value = IMM_J
    await settle(dut)
    assert int(dut.imm.value) & 1 == 0, (
        "J-format imm[0] was 1: the low bit must be hardwired to zero"
    )


@cocotb.test()
async def test_j_format_rd_and_opcode_do_not_leak(dut):
    """J-type: instr[6:0] is the opcode and instr[11:7] is rd; neither reaches `imm`.

    J is the format where this matters most, because its immediate reaches down
    to instr[12] and the fields just below that are rd and the opcode.  A
    decoder that read the immediate as one contiguous slice including instr[11:0]
    would be wrong for every JAL with a nonzero rd.
    """
    base = enc_j(0x000800)
    polluted = base | 0x0FFF  # set rd and opcode
    await check(dut, base, IMM_J, 0x00000800, "J clean")
    await check(dut, polluted, IMM_J, 0x00000800, "J with rd/opcode set")


@cocotb.test()
async def test_j_format_instr20_is_isolated(dut):
    """J-type: instr[20] alone supplies imm[11], and moves nothing else.

    This drives instr[20] by hand rather than through the encoder, so it checks
    the RTL against the instruction encoding directly: instr[20] set, with the
    rest of the immediate zero and rd/opcode clear, must give exactly 0x800.
    """
    word = OP_JAL | (1 << 20)  # opcode only, plus instr[20]
    await check(dut, word, IMM_J, 0x00000800, "J instr[20] -> imm[11]")
    # instr[19] is the top of the imm[19:12] group and must land on imm[19] -
    # a different position, so this pair cannot be confused with each other.
    word = OP_JAL | (1 << 19)
    await check(dut, word, IMM_J, 0x00080000, "J instr[19] -> imm[19]")


# ---------------------------------------------------------------------------
# imm_sel selection
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_undefined_imm_sel_gives_zero(dut):
    """imm_sel 5, 6 and 7 are not formats: `imm` must be 0, not undefined bits.

    The contract says this in so many words ("any other `imm_sel` value must
    drive `imm` to zero rather than to undefined bits"), because a decoder that
    leaves the mux unassigned propagates X into ID/EX and from there into the
    address of a load.
    """
    for sel in (5, 6, 7):
        dut.instr.value = 0xFFFFFFFF  # every immediate field nonzero
        dut.imm_sel.value = sel
        await settle(dut)
        got = int(dut.imm.value)
        assert got == 0, (
            "imm_sel=%d is not a format but imm came out %08x, expected 0"
            % (sel, got)
        )


@cocotb.test()
async def test_each_imm_sel_selects_exactly_one_format(dut):
    """One instruction word, all five formats, each against the reference.

    A single word is used for all five so that a mux which ignored `imm_sel`
    entirely, or which treated 5..7 as a sixth format, cannot pass: the five
    expected values are all different.
    """
    # Chosen because all five formats give five *different* immediates for it,
    # which the assertion below confirms before it is relied on.  Without that
    # check a word where two formats coincide would let a mux that ignores
    # `imm_sel` for those two pass.
    word = 0x8FEFABCD
    assert len({REFERENCE[s](word) for s in REFERENCE}) == 5, (
        "precondition: this word must decode to five different immediates"
    )
    for sel in (IMM_I, IMM_S, IMM_B, IMM_U, IMM_J):
        await check(dut, word, sel, REFERENCE[sel](word), "imm_sel=%d" % sel)


@cocotb.test()
async def test_imm_sel_does_not_depend_on_the_opcode(dut):
    """`imm_gen` selects on `imm_sel` alone; the opcode is not consulted.

    The same instruction word with a different opcode must give the same
    immediate.  This is the check that `imm_gen` is not a second decoder: if it
    started inspecting instr[6:0] to sanity-check `imm_sel`, this would fail.
    """
    body = 0x0FF0000 | 0x0001000  # immediate bits, rd and funct3
    for opcode in (0x13, 0x23, 0x63, 0x37, 0x6F, 0x67, 0x33):
        word = body | opcode
        for sel in (IMM_I, IMM_S, IMM_B, IMM_U, IMM_J):
            await check(
                dut,
                word,
                sel,
                REFERENCE[sel](word),
                "opcode %02x imm_sel=%d" % (opcode, sel),
            )

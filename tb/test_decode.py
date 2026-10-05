"""Regression tests for ``rtl/core/decode.v``.

`decode` is purely combinational: one instruction word in, a control bundle
out, no state.  So the shape of these tests is a table - a word in, every output
field checked - rather than a sequence of clocked operations.

Four properties get most of the attention, because each is a way this block can
be wrong in a way that passes a functional test:

1. **Every output defaults to illegal, not to a working operation.**  This is
   Review Focus 5 from the plan.  `0xFFFF_FFFF` must come out illegal and must
   request no side effect at all, and the illegal arm is checked on *every*
   output, not just `is_illegal` - a decoder that sets `is_illegal` and leaves
   `reg_write` high has not fixed anything.

2. **Unimplemented encodings are illegal, not silently ignored.**  The M
   extension, the C extension, reserved `funct3` values, over-long
   instructions, and the whole SYSTEM opcode.  Each is checked individually,
   because "illegal" here means one specific wrong answer per encoding.

3. **The three control-class signals are mutually exclusive.**  `ex_stage`
   resolves a branch or a jump from them without re-decoding, so two being high
   at once is ambiguous in a way no single-instruction functional test would
   reveal.

4. **`alu_op`, `op1_sel`, `op2_sel` are right per instruction**, including the
   cases that are easy to get backwards: `lui` adds zero to an immediate,
   `auipc` adds the PC to the PC, `jal` adds the PC to an immediate, and
   branches subtract so that `zero` answers BEQ.

The encoders below are written from the RISC-V spec's opcode/funct tables.  The
expected control values are written out as literals rather than as a second
Python decoder, because a test that compares the RTL against another
implementation of the same idea can agree with a shared misreading.

The one thing this file cannot check alone is the `alu_op` *encoding* itself -
the numbers 0..9 - because `alu` is P3's module and is not on this testbench's
source list.  `test_alu_op_encoding_is_the_documented_table` pins the numbers
this file emits so that a change here is caught immediately and visibly to
whoever owns `alu`.

Run with::

    make test MODULE=test_decode TOP=decode
    make test-4state MODULE=test_decode TOP=decode
"""

import cocotb
from cocotb.triggers import Timer

# ---------------------------------------------------------------------------
# Encodings
# ---------------------------------------------------------------------------

OP_LOAD = 0x03
OP_MISC_MEM = 0x0F
OP_OP_IMM = 0x13
OP_AUIPC = 0x17
OP_STORE = 0x23
OP_OP = 0x33
OP_LUI = 0x37
OP_BRANCH = 0x63
OP_JALR = 0x67
OP_JAL = 0x6F
OP_SYSTEM = 0x73

# `alu_op`, as documented in rtl/core/decode.v DESIGN NOTE 2.  P3's `alu` must
# implement exactly this table.
ALU_ADD, ALU_SUB, ALU_SLL, ALU_SLT, ALU_SLTU = 0, 1, 2, 3, 4
ALU_XOR, ALU_SRL, ALU_SRA, ALU_OR, ALU_AND = 5, 6, 7, 8, 9

# `op1_sel`
OP1_RS1, OP1_PC, OP1_ZERO = 0, 1, 2
# `op2_sel` (2 = "4" is enumerated by the contract but selected by no encoding)
OP2_RS2, OP2_IMM, OP2_FOUR, OP2_PC = 0, 1, 2, 3

# `imm_sel`
IMM_I, IMM_S, IMM_B, IMM_U, IMM_J = 0, 1, 2, 3, 4

# `mem_size`
MEM_BYTE, MEM_HALF, MEM_WORD = 0, 1, 2

# `wb_sel`
WB_ALU, WB_MEM, WB_PC4 = 0, 1, 2


def r_type(funct7, rs2, rs1, funct3, rd, opcode):
    return (
        (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode
    )


def i_type(imm12, rs1, funct3, rd, opcode):
    return (((imm12 & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode)


def s_type(imm12, rs2, rs1, funct3, opcode):
    return (
        (((imm12 >> 5) & 0x7F) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (funct3 << 12)
        | ((imm12 & 0x1F) << 7)
        | opcode
    )


def b_type(imm13, rs2, rs1, funct3, opcode=OP_BRANCH):
    imm = imm13 & 0x1FFF
    return (
        (((imm >> 12) & 1) << 31)
        | (((imm >> 5) & 0x3F) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (funct3 << 12)
        | (((imm >> 1) & 0xF) << 8)
        | (((imm >> 11) & 1) << 7)
        | opcode
    )


def u_type(imm32, rd, opcode):
    return (((imm32 >> 12) & 0xFFFFF) << 12) | (rd << 7) | opcode


def j_type(imm21, rd, opcode=OP_JAL):
    imm = imm21 & 0x1FFFFF
    return (
        (((imm >> 20) & 1) << 31)
        | (((imm >> 1) & 0x3FF) << 21)
        | (((imm >> 11) & 1) << 20)
        | (((imm >> 12) & 0xFF) << 12)
        | (rd << 7)
        | opcode
    )


# Instruction words, named after what they are.  rs1 = x5, rs2 = x6, rd = x7
# throughout, so `uses_rs1` / `uses_rs2` / `uses_rd` have something to be true
# about.
RS1, RS2, RD = 5, 6, 7

BEQ = b_type(0x010, RS2, RS1, 0b000)
BNE = b_type(0x010, RS2, RS1, 0b001)
BLT = b_type(0x010, RS2, RS1, 0b100)
BGE = b_type(0x010, RS2, RS1, 0b101)
BLTU = b_type(0x010, RS2, RS1, 0b110)
BGEU = b_type(0x010, RS2, RS1, 0b111)

LB = i_type(0x004, RS1, 0b000, RD, OP_LOAD)
LH = i_type(0x004, RS1, 0b001, RD, OP_LOAD)
LW = i_type(0x004, RS1, 0b010, RD, OP_LOAD)
LBU = i_type(0x004, RS1, 0b100, RD, OP_LOAD)
LHU = i_type(0x004, RS1, 0b101, RD, OP_LOAD)

SB = s_type(0x004, RS2, RS1, 0b000, OP_STORE)
SH = s_type(0x004, RS2, RS1, 0b001, OP_STORE)
SW = s_type(0x004, RS2, RS1, 0b010, OP_STORE)

ADDI = i_type(0x7FF, RS1, 0b000, RD, OP_OP_IMM)
SLLI = i_type(0x01F, RS1, 0b001, RD, OP_OP_IMM)
SLTI = i_type(0x7FF, RS1, 0b010, RD, OP_OP_IMM)
SLTIU = i_type(0x7FF, RS1, 0b011, RD, OP_OP_IMM)
XORI = i_type(0x7FF, RS1, 0b100, RD, OP_OP_IMM)
SRLI = i_type(0x01F, RS1, 0b101, RD, OP_OP_IMM)
SRAI = i_type(0x400 | 0x01F, RS1, 0b101, RD, OP_OP_IMM)
ORI = i_type(0x7FF, RS1, 0b110, RD, OP_OP_IMM)
ANDI = i_type(0x7FF, RS1, 0b111, RD, OP_OP_IMM)

ADD = r_type(0x00, RS2, RS1, 0b000, RD, OP_OP)
SUB = r_type(0x20, RS2, RS1, 0b000, RD, OP_OP)
SLL = r_type(0x00, RS2, RS1, 0b001, RD, OP_OP)
SLT = r_type(0x00, RS2, RS1, 0b010, RD, OP_OP)
SLTU = r_type(0x00, RS2, RS1, 0b011, RD, OP_OP)
XOR = r_type(0x00, RS2, RS1, 0b100, RD, OP_OP)
SRL = r_type(0x00, RS2, RS1, 0b101, RD, OP_OP)
SRA = r_type(0x20, RS2, RS1, 0b101, RD, OP_OP)
OR = r_type(0x00, RS2, RS1, 0b110, RD, OP_OP)
AND = r_type(0x00, RS2, RS1, 0b111, RD, OP_OP)

LUI = u_type(0x12345000, RD, OP_LUI)
AUIPC = u_type(0x12345000, RD, OP_AUIPC)
JAL = j_type(0x010, RD)
JALR = i_type(0x004, RS1, 0b000, RD, OP_JALR)
FENCE = i_type(0x0FF, 0, 0b000, 0, OP_MISC_MEM)
FENCE_I = i_type(0x000, 0, 0b001, 0, OP_MISC_MEM)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


# Every output of `decode`, read back in the order the contract lists them.
OUTPUTS = (
    "alu_op",
    "op1_sel",
    "op2_sel",
    "imm_sel",
    "branch_funct3",
    "is_branch",
    "is_jal",
    "is_jalr",
    "is_illegal",
    "uses_rs1",
    "uses_rs2",
    "uses_rd",
    "mem_read",
    "mem_write",
    "mem_size",
    "mem_unsigned",
    "reg_write",
    "wb_sel",
)

# The fields that are one bit wide, used by the definedness check.
ONE_BIT = frozenset(
    ("is_branch", "is_jal", "is_jalr", "is_illegal", "uses_rs1", "uses_rs2",
     "uses_rd", "mem_read", "mem_write", "mem_unsigned", "reg_write")
)

# The full width of each multi-bit field, so the definedness check can tell an
# X from a legitimate larger value.  `mem_size` is 2 bits and `mem_size = 2`
# (word) is a perfectly good answer, so checking "is it 0 or 1" would be wrong.
WIDTH = {
    "alu_op": 4, "op1_sel": 2, "op2_sel": 3, "imm_sel": 3,
    "branch_funct3": 3, "mem_size": 2, "wb_sel": 2,
}


async def decode(dut, word):
    """Present one instruction word and read the whole control bundle back."""
    dut.instr.value = word
    await Timer(1, unit="ns")
    return {name: int(getattr(dut, name).value) for name in OUTPUTS}


async def expect(dut, word, note, **wanted):
    """Assert the bundle equals `wanted` on *every* output.

    All eighteen are checked, not just the ones named, so a caller that forgets
    a field still gets that field checked against the `bundle()` default rather
    than not checked at all.  That is what lets the RV32I table state only what
    is interesting about each instruction.  Use `expect_fields` when only some
    outputs are of interest.
    """
    got = await decode(dut, word)
    for name in OUTPUTS:
        value = wanted.get(name, 0)
        assert got[name] == value, (
            "%s (instr=%08x): %s is %d, expected %d.  full bundle: %s"
            % (note, word, name, got[name], value, got)
        )


async def expect_fields(dut, word, note, **wanted):
    """Assert only the named outputs, leaving the rest unchecked.

    For tests that are about one specific field and would only be made noisier
    by restating the other seventeen.  `expect` is the stronger check and is
    preferred wherever a whole bundle is known.
    """
    got = await decode(dut, word)
    for name, value in wanted.items():
        assert got[name] == value, (
            "%s (instr=%08x): %s is %d, expected %d.  full bundle: %s"
            % (note, word, name, got[name], value, got)
        )


async def expect_illegal(dut, word, note):
    """Assert the whole bundle is the inert illegal verdict.

    This is stronger than asserting `is_illegal` alone, and deliberately so: the
    contract says an unimplemented encoding "sets `is_illegal` and none of the
    three" control-class signals, and a decoder that raises the flag while still
    asserting `reg_write` would let the instruction write a register - the exact
    failure mode `is_illegal` exists to prevent.
    """
    got = await decode(dut, word)
    assert got["is_illegal"] == 1, (
        "%s (instr=%08x): is_illegal is 0, expected 1.  bundle: %s"
        % (note, word, got)
    )
    for name, value in got.items():
        if name == "is_illegal":
            continue
        assert value == 0, (
            "%s (instr=%08x): illegal instruction still sets %s=%d.  An "
            "unimplemented encoding must have no effect on anything.  "
            "bundle: %s" % (note, word, name, value, got)
        )


# ---------------------------------------------------------------------------
# Every RV32I instruction
# ---------------------------------------------------------------------------

# The bundle an instruction that does *not* write a register, does not access
# memory and is not a branch or jump must produce: everything inert.  Written
# out once so each row below only has to state what is actually *interesting*
# about its instruction, and so that adding a field to the decoder cannot
# silently escape the table.
INERT = dict(
    alu_op=ALU_ADD, op1_sel=OP1_RS1, op2_sel=OP2_RS2, imm_sel=IMM_I,
    branch_funct3=0, is_branch=0, is_jal=0, is_jalr=0, is_illegal=0,
    uses_rs1=0, uses_rs2=0, uses_rd=0, mem_read=0, mem_write=0, mem_size=0,
    mem_unsigned=0, reg_write=0, wb_sel=WB_ALU,
)

def bundle(**overrides):
    """The expected bundle: INERT with `overrides` applied.

    Every row goes through this, so a row cannot accidentally leave a field
    unstated - and `test_all_rv32i_opcodes_decode` asserts the result is
    complete, so a new decoder output cannot be added without a table update
    failing loudly.
    """
    expected = dict(INERT)
    unknown = set(overrides) - set(INERT)
    assert not unknown, "unknown bundle field(s): %s" % sorted(unknown)
    expected.update(overrides)
    return expected


# (name, word, expected bundle) - one row per instruction.
RV32I = [
    # LUI: rd = imm[31:12].  Adds zero to a U-immediate, so op1_sel is ZERO.
    ("LUI", LUI, bundle(op1_sel=OP1_ZERO, op2_sel=OP2_IMM, imm_sel=IMM_U,
                        uses_rd=1, reg_write=1)),

    # AUIPC: rd = pc + imm[31:12].  Adds the PC to the PC, so *both* operand
    # selects are PC - the one instruction where op2_sel is PC.
    ("AUIPC", AUIPC, bundle(op1_sel=OP1_PC, op2_sel=OP2_PC, imm_sel=IMM_U,
                            uses_rd=1, reg_write=1)),

    # JAL: target = pc + imm, link = pc+4.  Reads neither rs1 nor rs2 - see
    # test_jal_sets_uses_rd_but_not_uses_rs1 for why that matters.
    ("JAL", JAL, bundle(op1_sel=OP1_PC, op2_sel=OP2_IMM, imm_sel=IMM_J,
                        is_jal=1, uses_rd=1, reg_write=1, wb_sel=WB_PC4)),

    # JALR: target = (rs1 + imm) & ~1, link = pc+4.  Unlike JAL it reads rs1.
    ("JALR", JALR, bundle(op2_sel=OP2_IMM, is_jalr=1, uses_rs1=1, uses_rd=1,
                          reg_write=1, wb_sel=WB_PC4)),

    # Branches: subtract, so `zero` answers BEQ and slt/sltu answer the rest.
    # No rd, so no uses_rd and no reg_write.
    ("BEQ", BEQ, bundle(alu_op=ALU_SUB, imm_sel=IMM_B, branch_funct3=0b000,
                        is_branch=1, uses_rs1=1, uses_rs2=1)),
    ("BNE", BNE, bundle(alu_op=ALU_SUB, imm_sel=IMM_B, branch_funct3=0b001,
                        is_branch=1, uses_rs1=1, uses_rs2=1)),
    ("BLT", BLT, bundle(alu_op=ALU_SUB, imm_sel=IMM_B, branch_funct3=0b100,
                        is_branch=1, uses_rs1=1, uses_rs2=1)),
    ("BGE", BGE, bundle(alu_op=ALU_SUB, imm_sel=IMM_B, branch_funct3=0b101,
                        is_branch=1, uses_rs1=1, uses_rs2=1)),
    ("BLTU", BLTU, bundle(alu_op=ALU_SUB, imm_sel=IMM_B, branch_funct3=0b110,
                          is_branch=1, uses_rs1=1, uses_rs2=1)),
    ("BGEU", BGEU, bundle(alu_op=ALU_SUB, imm_sel=IMM_B, branch_funct3=0b111,
                          is_branch=1, uses_rs1=1, uses_rs2=1)),

    # Loads: address is rs1 + imm, writeback comes from memory.
    ("LB", LB, bundle(op2_sel=OP2_IMM, mem_read=1, mem_size=MEM_BYTE,
                      mem_unsigned=0, uses_rs1=1, uses_rd=1, reg_write=1,
                      wb_sel=WB_MEM)),
    ("LH", LH, bundle(op2_sel=OP2_IMM, mem_read=1, mem_size=MEM_HALF,
                      mem_unsigned=0, uses_rs1=1, uses_rd=1, reg_write=1,
                      wb_sel=WB_MEM)),
    ("LW", LW, bundle(op2_sel=OP2_IMM, mem_read=1, mem_size=MEM_WORD,
                      mem_unsigned=0, uses_rs1=1, uses_rd=1, reg_write=1,
                      wb_sel=WB_MEM)),
    ("LBU", LBU, bundle(op2_sel=OP2_IMM, mem_read=1, mem_size=MEM_BYTE,
                        mem_unsigned=1, uses_rs1=1, uses_rd=1, reg_write=1,
                        wb_sel=WB_MEM)),
    ("LHU", LHU, bundle(op2_sel=OP2_IMM, mem_read=1, mem_size=MEM_HALF,
                        mem_unsigned=1, uses_rs1=1, uses_rd=1, reg_write=1,
                        wb_sel=WB_MEM)),

    # Stores: address is rs1 + imm but the stored *value* is rs2, so op2_sel is
    # RS2 and the immediate comes from `imm_sel` alone.  No writeback at all.
    ("SB", SB, bundle(imm_sel=IMM_S, mem_write=1, mem_size=MEM_BYTE,
                      uses_rs1=1, uses_rs2=1)),
    ("SH", SH, bundle(imm_sel=IMM_S, mem_write=1, mem_size=MEM_HALF,
                      uses_rs1=1, uses_rs2=1)),
    ("SW", SW, bundle(imm_sel=IMM_S, mem_write=1, mem_size=MEM_WORD,
                      uses_rs1=1, uses_rs2=1)),

    # OP-IMM: rs1 op imm12.  Every one of them, so the funct3-to-alu_op mapping
    # is pinned one instruction at a time rather than by sampling.
    ("ADDI", ADDI, bundle(alu_op=ALU_ADD, op2_sel=OP2_IMM, uses_rs1=1,
                          uses_rd=1, reg_write=1)),
    ("SLLI", SLLI, bundle(alu_op=ALU_SLL, op2_sel=OP2_IMM, uses_rs1=1,
                          uses_rd=1, reg_write=1)),
    ("SLTI", SLTI, bundle(alu_op=ALU_SLT, op2_sel=OP2_IMM, uses_rs1=1,
                          uses_rd=1, reg_write=1)),
    ("SLTIU", SLTIU, bundle(alu_op=ALU_SLTU, op2_sel=OP2_IMM, uses_rs1=1,
                            uses_rd=1, reg_write=1)),
    ("XORI", XORI, bundle(alu_op=ALU_XOR, op2_sel=OP2_IMM, uses_rs1=1,
                          uses_rd=1, reg_write=1)),
    ("SRLI", SRLI, bundle(alu_op=ALU_SRL, op2_sel=OP2_IMM, uses_rs1=1,
                          uses_rd=1, reg_write=1)),
    ("SRAI", SRAI, bundle(alu_op=ALU_SRA, op2_sel=OP2_IMM, uses_rs1=1,
                          uses_rd=1, reg_write=1)),
    ("ORI", ORI, bundle(alu_op=ALU_OR, op2_sel=OP2_IMM, uses_rs1=1,
                        uses_rd=1, reg_write=1)),
    ("ANDI", ANDI, bundle(alu_op=ALU_AND, op2_sel=OP2_IMM, uses_rs1=1,
                          uses_rd=1, reg_write=1)),

    # OP: rs1 op rs2.  No immediate is consumed, so op2_sel is RS2 throughout and
    # imm_sel stays at the inert I.
    ("ADD", ADD, bundle(alu_op=ALU_ADD, uses_rs1=1, uses_rs2=1, uses_rd=1,
                        reg_write=1)),
    ("SUB", SUB, bundle(alu_op=ALU_SUB, uses_rs1=1, uses_rs2=1, uses_rd=1,
                        reg_write=1)),
    ("SLL", SLL, bundle(alu_op=ALU_SLL, uses_rs1=1, uses_rs2=1, uses_rd=1,
                        reg_write=1)),
    ("SLT", SLT, bundle(alu_op=ALU_SLT, uses_rs1=1, uses_rs2=1, uses_rd=1,
                        reg_write=1)),
    ("SLTU", SLTU, bundle(alu_op=ALU_SLTU, uses_rs1=1, uses_rs2=1, uses_rd=1,
                          reg_write=1)),
    ("XOR", XOR, bundle(alu_op=ALU_XOR, uses_rs1=1, uses_rs2=1, uses_rd=1,
                        reg_write=1)),
    ("SRL", SRL, bundle(alu_op=ALU_SRL, uses_rs1=1, uses_rs2=1, uses_rd=1,
                        reg_write=1)),
    ("SRA", SRA, bundle(alu_op=ALU_SRA, uses_rs1=1, uses_rs2=1, uses_rd=1,
                        reg_write=1)),
    ("OR", OR, bundle(alu_op=ALU_OR, uses_rs1=1, uses_rs2=1, uses_rd=1,
                      reg_write=1)),
    ("AND", AND, bundle(alu_op=ALU_AND, uses_rs1=1, uses_rs2=1, uses_rd=1,
                        reg_write=1)),
]


@cocotb.test()
async def test_all_rv32i_opcodes_decode(dut):
    """Every base RV32I instruction, checked against its full control bundle.

    One row per instruction, and the row asserts *all eighteen* outputs: the
    ones named in the table, and zero for every other.  That matters because a
    row that only checked `is_illegal` and `alu_op` would pass against a decoder
    that set `mem_read` on `addi`.
    """
    for name, word, wanted in RV32I:
        assert tuple(wanted) == OUTPUTS, (
            "%s: the expected bundle is missing %s.  Every row must state all "
            "%d outputs, or a newly added decoder output would go unchecked "
            "here." % (name, sorted(set(OUTPUTS) - set(wanted)), len(OUTPUTS))
        )
        await expect(dut, word, name, **wanted)


@cocotb.test()
async def test_no_rv32i_instruction_decodes_illegal(dut):
    """The other half of the table: not one legal instruction is illegal.

    Checked as its own test so that a failure says which direction the mistake
    went.  "Everything is illegal" passes a test that only ever looks for
    `is_illegal`, and it is exactly as broken as "nothing is".
    """
    for name, word, _ in RV32I:
        got = await decode(dut, word)
        assert got["is_illegal"] == 0, (
            "%s (instr=%08x) decodes as illegal; it is base RV32I.  "
            "bundle: %s" % (name, word, got)
        )


@cocotb.test()
async def test_rv32i_table_covers_the_whole_base_isa(dut):
    """The table above is complete: 34 instructions, none missing.

    A test table that quietly omits an instruction tests nothing about it.  This
    asserts the count and the names, so adding an instruction to the table
    without updating this check fails loudly instead of passing quietly.
    """
    names = [row[0] for row in RV32I]
    assert len(names) == 37, (
        "expected 37 RV32I instructions in the table, found %d" % len(names)
    )
    assert len(set(names)) == len(names), "the table has a duplicate entry"
    expected = {
        "LUI", "AUIPC", "JAL", "JALR",
        "BEQ", "BNE", "BLT", "BGE", "BLTU", "BGEU",
        "LB", "LH", "LW", "LBU", "LHU",
        "SB", "SH", "SW",
        "ADDI", "SLLI", "SLTI", "SLTIU", "XORI", "SRLI", "SRAI", "ORI", "ANDI",
        "ADD", "SUB", "SLL", "SLT", "SLTU", "XOR", "SRL", "SRA", "OR", "AND",
    }
    assert set(names) == expected, (
        "the table differs from the RV32I instruction list; "
        "missing: %s, unexpected: %s"
        % (sorted(expected - set(names)), sorted(set(names) - expected))
    )
    # FENCE and FENCE.I are the remaining two RV32I encodings, and they are
    # deliberately handled separately: they are legal no-ops.
    assert "FENCE" not in expected and "FENCE.I" not in expected


# ---------------------------------------------------------------------------
# Review Focus 5 - illegal by default, never a working operation
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_unknown_opcode_is_illegal(dut):
    """`0xFFFF_FFFF` is illegal and does nothing at all.

    This is Review Focus 5, verbatim from the plan: "Expected: 0xFFFF_FFFF
    decodes illegal and no add is performed."  `expect_illegal` checks every
    output, so "no add is performed" is enforced by `reg_write`, `uses_rd` and
    `alu_op` all being 0 - not merely by `is_illegal` being 1.
    """
    await expect_illegal(dut, 0xFFFFFFFF, "all ones")


@cocotb.test()
async def test_all_ones_in_the_funct_fields_is_still_illegal(dut):
    """A valid opcode with every funct bit set is illegal.

    This is the shape of the bug the default-arm warning is about: the opcode
    matches, so a decoder that switches on the opcode alone falls into a working
    arm.  Eight of the eleven implemented opcodes are checked here with their
    funct fields saturated.
    """
    for opcode, name in (
        (OP_LOAD, "LOAD"),
        (OP_MISC_MEM, "MISC-MEM"),
        (OP_STORE, "STORE"),
        (OP_OP, "OP"),
        (OP_JALR, "JALR"),
        (OP_SYSTEM, "SYSTEM"),
    ):
        word = (0xFFFFFFFF & ~0x7F) | opcode
        await expect_illegal(dut, word, "%s with all funct bits set" % name)

    # BRANCH is not in that list either, for the same reason as OP-IMM: its
    # funct3 *is* the whole operation, so 111 is BGEU - a legal instruction with
    # every funct bit set.  The reserved branch funct3 values are checked
    # individually by test_reserved_branch_funct3_is_illegal.

    # OP-IMM is deliberately NOT in that list, and the reason is worth stating
    # because it is the subtlest thing in this block.  In opcode 0010011,
    # instr[31:25] is imm[11:5] for six of the eight funct3 values, so
    # "all funct bits set" is not an invalid funct field there - it is `addi` with
    # the immediate -1.  Saturating it produces a perfectly legal instruction.
    # Only funct3 001 and 101 (SLLI, SRLI/SRAI) put an operation-selecting funct7
    # in those bits, and those are checked separately by
    # test_other_reserved_funct7_values_are_illegal.  A decoder that checked
    # funct7 on *every* OP-IMM funct3 would reject `addi rd, rs1, -1`, which is
    # the most common instruction in the ISA.


@cocotb.test()
async def test_unknown_opcode_does_not_produce_an_add(dut):
    """Explicitly: no unknown opcode yields `reg_write`, `mem_read` or `mem_write`.

    Stated separately from the all-ones case because this is the property the
    whole default-to-illegal design exists to provide, and it should hold for
    *every* unimplemented encoding rather than for one memorable constant.
    """
    # Every 7-bit opcode that is not one of the eleven this core implements.
    implemented = {
        OP_LOAD, OP_MISC_MEM, OP_OP_IMM, OP_AUIPC, OP_STORE, OP_OP,
        OP_LUI, OP_BRANCH, OP_JALR, OP_JAL, OP_SYSTEM,
    }
    for opcode in range(128):
        if opcode in implemented:
            continue
        word = (0xABCDEF01 & ~0x7F) | opcode
        got = await decode(dut, word)
        assert got["is_illegal"] == 1, (
            "opcode %02x is not implemented but decoded legal.  bundle: %s"
            % (opcode, got)
        )
        for name in ("reg_write", "mem_read", "mem_write", "is_branch",
                     "is_jal", "is_jalr", "uses_rs1", "uses_rs2", "uses_rd"):
            assert got[name] == 0, (
                "opcode %02x is illegal but sets %s=%d.  bundle: %s"
                % (opcode, name, got[name], got)
            )


# ---------------------------------------------------------------------------
# The M extension - illegal in phase 1, per docs/TEAM.md
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_m_extension_is_illegal(dut):
    """M-extension encodings are illegal here; phase 2 adds them.

    `docs/TEAM.md` is explicit: "Phase 1 is RV32I only, so the M-extension and
    C-extension encodings are illegal here, not silently ignored."  MUL, MULH,
    MULHSU, MULHU, DIV, DIVU, REM and REMU share opcodes 0110011 and 0010011
    with the base ALU ops and are told apart only by funct7 == 0000001.  A
    decoder that checks funct3 but not funct7 decodes all eight as something
    else - and since funct3 000 would be ADD, `mul x5,x6,x7` becomes an add.
    """
    for funct3, name in (
        (0b000, "MUL"), (0b001, "MULH"), (0b010, "MULHSU"), (0b011, "MULHU"),
        (0b100, "DIV"), (0b101, "DIVU"), (0b110, "REM"), (0b111, "REMU"),
    ):
        await expect_illegal(
            dut, r_type(0x01, RS2, RS1, funct3, RD, OP_OP), "OP " + name
        )

    # Only the R-type form exists: every M-extension instruction is
    # funct7 = 0000001 under opcode 0110011.  There is no M encoding in
    # 0010011, because in that opcode those seven bits are imm[11:5] - so a
    # word that looks like `MUL` there is just `addi` with a different immediate,
    # and is legal.  See
    # test_op_imm_non_shift_forms_accept_every_imm11_to_5_value.


@cocotb.test()
async def test_other_reserved_funct7_values_are_illegal(dut):
    """In opcode 0110011, funct7 must be 0000000 or (for two funct3s) 0100000.

    Only ADD/SUB and SRL/SRA accept the 0100000 funct7.  Every other funct7 is an
    unimplemented encoding - the M extension among them - and must not be
    decoded as the base operation it shares funct3 with.
    """
    for funct7 in range(0x80):
        if funct7 in (0x00, 0x20):
            continue
        for funct3 in range(8):
            await expect_illegal(
                dut,
                r_type(funct7, RS2, RS1, funct3, RD, OP_OP),
                "OP funct7=%02x funct3=%d" % (funct7, funct3),
            )

    # In OP-IMM the same seven bits are imm[11:5] for six of the eight funct3
    # values, so there is no "reserved funct7" to sweep - only the two shift
    # funct3s put an operation-selecting field there.  See
    # test_op_imm_non_shift_forms_accept_every_imm11_to_5_value for the other
    # half of that asymmetry.
    for funct7 in range(0x80):
        if funct7 in (0x00, 0x20):
            continue
        for funct3 in (0b001, 0b101):
            await expect_illegal(
                dut,
                i_type((funct7 << 5) | 0x1F, RS1, funct3, RD, OP_OP_IMM),
                "OP-IMM shift funct7=%02x funct3=%d" % (funct7, funct3),
            )


@cocotb.test()
async def test_op_imm_non_shift_forms_accept_every_imm11_to_5_value(dut):
    """ADDI and friends must accept *every* value of instr[31:25].

    The counterpart to the test above, and the one that catches the bug a
    too-eager funct7 check causes.  `addi rd, rs1, -1` has imm[11:5] = 1111111,
    which is not the ADD funct7 of 0000000; a decoder that checks funct7 on the
    non-shift OP-IMM forms calls the most common instruction in the ISA
    illegal - and a functional test still passes, because almost every test
    program uses positive immediates and never reaches the negative ones.
    """
    for funct3, name in ((0b000, "ADDI"), (0b010, "SLTI"), (0b011, "SLTIU"),
                         (0b100, "XORI"), (0b110, "ORI"), (0b111, "ANDI")):
        for imm11_5 in range(0x80):
            word = i_type((imm11_5 << 5) | 0x1F, RS1, funct3, RD, OP_OP_IMM)
            got = await decode(dut, word)
            assert got["is_illegal"] == 0, (
                "%s with imm[11:5]=%s (instr=%08x) decoded illegal.  In OP-IMM "
                "those bits are immediate data, not a funct field, so every "
                "value is legal.  bundle: %s"
                % (name, format(imm11_5, "07b"), word, got)
            )


@cocotb.test()
async def test_add_and_sub_accept_only_their_own_funct7(dut):
    """funct3 000 in OP is ADD with funct7 0 and SUB with funct7 0100000.

    Checked as a pair per funct7 so that a decoder which mapped both to SUB, or
    both to ADD, fails on exactly one of them.
    """
    await expect(dut, r_type(0x00, RS2, RS1, 0b000, RD, OP_OP), "ADD",
                 alu_op=ALU_ADD, op1_sel=OP1_RS1, op2_sel=OP2_RS2,
                 imm_sel=IMM_I, uses_rs1=1, uses_rs2=1, uses_rd=1, reg_write=1)
    await expect(dut, r_type(0x20, RS2, RS1, 0b000, RD, OP_OP), "SUB",
                 alu_op=ALU_SUB, op1_sel=OP1_RS1, op2_sel=OP2_RS2,
                 imm_sel=IMM_I, uses_rs1=1, uses_rs2=1, uses_rd=1, reg_write=1)


@cocotb.test()
async def test_srl_and_sra_accept_only_their_own_funct7(dut):
    """funct3 101 in OP is SRL with funct7 0 and SRA with funct7 0100000."""
    await expect(dut, r_type(0x00, RS2, RS1, 0b101, RD, OP_OP), "SRL",
                 alu_op=ALU_SRL, op1_sel=OP1_RS1, op2_sel=OP2_RS2,
                 imm_sel=IMM_I, uses_rs1=1, uses_rs2=1, uses_rd=1, reg_write=1)
    await expect(dut, r_type(0x20, RS2, RS1, 0b101, RD, OP_OP), "SRA",
                 alu_op=ALU_SRA, op1_sel=OP1_RS1, op2_sel=OP2_RS2,
                 imm_sel=IMM_I, uses_rs1=1, uses_rs2=1, uses_rd=1, reg_write=1)


@cocotb.test()
async def test_srai_needs_the_sra_funct7_in_op_imm(dut):
    """SRAI is funct3 101 with funct7 0100000; SRLI is the same funct3 with 0.

    In OP-IMM the funct7 lives in instr[31:25], so the shift amount is
    instr[24:20] and the "funct" is the top seven bits.  A decoder that reads
    only instr[24:20] turns `srai` into `srli`, which is wrong for every
    negative value shifted right.
    """
    await expect(dut, i_type(0x01F, RS1, 0b101, RD, OP_OP_IMM), "SRLI",
                 alu_op=ALU_SRL, op1_sel=OP1_RS1, op2_sel=OP2_IMM, imm_sel=IMM_I,
                 uses_rs1=1, uses_rd=1, reg_write=1)
    await expect(dut, i_type(0x400 | 0x01F, RS1, 0b101, RD, OP_OP_IMM), "SRAI",
                 alu_op=ALU_SRA, op1_sel=OP1_RS1, op2_sel=OP2_IMM, imm_sel=IMM_I,
                 uses_rs1=1, uses_rd=1, reg_write=1)


# ---------------------------------------------------------------------------
# The C extension - illegal in phase 1, phase 2 adds it
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_compressed_encodings_are_illegal(dut):
    """Every 16-bit instruction is illegal: phase 1 has no C extension.

    A word with `instr[1:0] != 11` is a 16-bit instruction, and all sixteen
    C-extension encodings have that shape.

    An honest note on what this test can and cannot prove.  `instr[1:0]` is the
    bottom of the opcode field, so a 16-bit word also has an opcode that no
    implemented arm matches - which means these words come out illegal through
    the opcode `default` even if the explicit length gate in `decode` were
    deleted.  The gate is therefore redundant *in phase 1*, and this test passes
    either way; deleting the gate is not caught here.

    It is kept anyway, and the reason is phase 2.  When the C extension lands,
    `decode` will start matching 16-bit opcodes, and `instr[1:0]` is exactly the
    field that says whether the word is 16 or 32 bits wide.  Without the gate
    checked *before* the opcode switch, a 16-bit instruction would be dispatched
    on its upper bits as though it were a 32-bit one.  So the gate is insurance
    against a future bug rather than a present one, and
    test_length_gate_is_not_redundant_in_phase_two says so where a reader will
    find it before phase 2 does.
    """
    for low in (0b00, 0b01, 0b10):
        for body in (0x0000, 0x4501, 0xFFFF0000):
            word = (body & ~0x3) | low
            await expect_illegal(dut, word, "16-bit encoding, instr[1:0]=%s" % bin(low))


@cocotb.test()
async def test_length_gate_is_not_redundant_in_phase_two(dut):
    """No phase-1 opcode can be reached through a 16-bit or over-long word.

    This is the property that makes the length gate currently redundant, stated
    as an assertion so that it is checked rather than assumed - and so that if a
    future phase *does* add an opcode whose low bits are not `11`, this test
    fails and points at the gate that will then be load-bearing.

    Concretely: every implemented opcode already has `instr[1:0] == 11` and
    `instr[4:2] != 111`.  Phase 2's C extension is what changes that, and the
    gate exists for when it does.
    """
    implemented = (
        OP_LOAD, OP_MISC_MEM, OP_OP_IMM, OP_AUIPC, OP_STORE, OP_OP,
        OP_LUI, OP_BRANCH, OP_JALR, OP_JAL, OP_SYSTEM,
    )
    for opcode in implemented:
        assert opcode & 0b011 == 0b011, (
            "implemented opcode %s has instr[1:0] != 11, so it can be reached "
            "by a 16-bit word and the length gate is now load-bearing"
            % format(opcode, "07b")
        )
        assert (opcode >> 2) & 0b111 != 0b111, (
            "implemented opcode %s has instr[4:2] == 111, so it can be reached "
            "by an over-long word and the length gate is now load-bearing"
            % format(opcode, "07b")
        )

    # And behaviourally: a word that is a *legal* instruction in every bit but
    # the length field must still be illegal, because the length field is not
    # negotiable.
    legal = ADD  # a plain, fully legal `add x7, x5, x6`
    await expect_illegal(dut, legal & ~0b011, "ADD with instr[1:0] cleared")
    await expect_illegal(dut, (legal & ~0b0011100) | 0b111 << 2, "ADD marked over-long")


@cocotb.test()
async def test_instructions_longer_than_32_bits_are_illegal(dut):
    """instr[4:2] == 111 marks the escape to 48-bit and longer encodings.

    No such instruction exists in phase 1, and treating one as an ordinary
    32-bit word would decode whatever sits in its upper half as an opcode.
    Sixteen of the 128 opcode values have `instr[4:2] == 111`; none is
    implemented, so each is swept here.
    """
    swept = 0
    for opcode in range(128):
        if (opcode >> 2) & 0b111 != 0b111:
            continue
        for funct3 in range(8):
            word = (0xDEADBEEF & ~0x7FFF) | (funct3 << 12) | opcode
            await expect_illegal(dut, word, "over-long opcode %s" % format(opcode, "07b"))
            swept += 1
    assert swept == 16 * 8, "expected to sweep 16 over-long opcodes, swept %d" % swept


# ---------------------------------------------------------------------------
# SYSTEM, FENCE, and the reserved funct3 values
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_system_opcode_is_illegal_in_phase_one(dut):
    """The whole SYSTEM opcode (1110011) is illegal.

    ECALL and EBREAK are base RV32I, but acting on them means taking a trap and
    phase 1 has no trap path: `decode` has no port to raise one through.  So the
    honest verdict is illegal, which is what stops `ecall` from silently
    behaving like a no-op.  Phase 3 re-opens this arm.  CSR access (Zicsr) is
    phase 3 too.
    """
    for imm12, funct3, name in (
        (0x000, 0b000, "ECALL"),
        (0x001, 0b000, "EBREAK"),
        (0x002, 0b000, "reserved 0x002"),
        (0x000, 0b001, "CSRRW"),
        (0x000, 0b010, "CSRRS"),
        (0x000, 0b011, "CSRRC"),
        (0x000, 0b101, "CSRRWI"),
        (0x000, 0b110, "CSRRSI"),
        (0x000, 0b111, "CSRRCI"),
    ):
        await expect_illegal(dut, i_type(imm12, 0, funct3, 0, OP_SYSTEM), name)


@cocotb.test()
async def test_fence_is_a_legal_no_op(dut):
    """FENCE and FENCE.I are legal, and do nothing.

    Phase 1 is single-issue and in-order with one data port, no cache and no
    store buffer, so there is no reordering for a fence to prevent.  Marking
    these illegal would trap a conforming program on an instruction the ISA
    requires to be legal, which is a worse failure than the no-op.
    """
    for word, name in ((FENCE, "FENCE"), (FENCE_I, "FENCE.I")):
        await expect_fields(dut, word, name, is_illegal=0)


@cocotb.test()
async def test_reserved_misc_mem_funct3_is_illegal(dut):
    """MISC-MEM funct3 010 and above is reserved."""
    for funct3 in (0b010, 0b011, 0b100, 0b101, 0b110, 0b111):
        await expect_illegal(dut, i_type(0, 0, funct3, 0, OP_MISC_MEM),
                             "MISC-MEM funct3=%d" % funct3)


@cocotb.test()
async def test_reserved_load_funct3_is_illegal(dut):
    """LOAD funct3 011, 110 and 111 are reserved."""
    for funct3 in (0b011, 0b110, 0b111):
        await expect_illegal(dut, i_type(0x004, RS1, funct3, RD, OP_LOAD),
                             "LOAD funct3=%d" % funct3)


@cocotb.test()
async def test_reserved_store_funct3_is_illegal(dut):
    """STORE funct3 011 and above are reserved."""
    for funct3 in (0b011, 0b100, 0b101, 0b110, 0b111):
        await expect_illegal(dut, s_type(0x004, RS2, RS1, funct3, OP_STORE),
                             "STORE funct3=%d" % funct3)


@cocotb.test()
async def test_reserved_branch_funct3_is_illegal(dut):
    """BRANCH funct3 010 and 011 are reserved."""
    for funct3 in (0b010, 0b011):
        await expect_illegal(dut, b_type(0x010, RS2, RS1, funct3),
                             "BRANCH funct3=%d" % funct3)


@cocotb.test()
async def test_jalr_requires_funct3_zero(dut):
    """JALR has exactly one funct3.  The other seven are reserved and illegal.

    `jalr` writes a register, so a JALR that decoded as a no-op would lose the
    link register; and one that decoded as something else would redirect
    somewhere arbitrary.  Both are worth catching here.
    """
    for funct3 in range(1, 8):
        await expect_illegal(dut, i_type(0x004, RS1, funct3, RD, OP_JALR),
                             "JALR funct3=%d" % funct3)


# ---------------------------------------------------------------------------
# The three control-class signals are mutually exclusive
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_is_branch_is_jal_and_is_jalr_are_mutually_exclusive(dut):
    """At most one of the three is ever high, for every instruction tested.

    `ex_stage` resolves a branch or a jump from these three plus `branch_funct3`
    without re-decoding the opcode, so two being high is a genuinely ambiguous
    state rather than a harmless redundancy.  This sweeps the whole funct3 space
    of all three relevant opcodes, plus a sample of others.
    """
    words = []
    for funct3 in range(8):
        words.append(b_type(0x010, RS2, RS1, funct3))
        words.append(j_type(0x010, RD))
        words.append(i_type(0x004, RS1, funct3, RD, OP_JALR))
        words.append(i_type(0x004, RS1, funct3, RD, OP_LOAD))
        words.append(s_type(0x004, RS2, RS1, funct3, OP_STORE))
        words.append(r_type(0x00, RS2, RS1, funct3, RD, OP_OP))
        words.append(i_type(0x01F, RS1, funct3, RD, OP_OP_IMM))
    words += [LUI, AUIPC, FENCE, FENCE_I, 0xFFFFFFFF, 0x00000013, 0x00000037]

    for word in words:
        got = await decode(dut, word)
        total = got["is_branch"] + got["is_jal"] + got["is_jalr"]
        assert total <= 1, (
            "instr=%08x sets is_branch=%d is_jal=%d is_jalr=%d: at most one "
            "may be high.  bundle: %s"
            % (word, got["is_branch"], got["is_jal"], got["is_jalr"], got)
        )


@cocotb.test()
async def test_illegal_never_sets_a_control_class_signal(dut):
    """`is_illegal` and the three control-class signals are independent fields.

    The contract says an unimplemented encoding "sets `is_illegal` and none of
    the three".  Swept over every opcode so it cannot be an artefact of one
    encoding.
    """
    for opcode in range(128):
        for funct3 in range(8):
            word = (0xFFFFFFFF & ~0x7F) | opcode
            word = (word & ~0x7000) | (funct3 << 12)
            got = await decode(dut, word)
            if got["is_illegal"]:
                assert not (got["is_branch"] or got["is_jal"] or got["is_jalr"]), (
                    "instr=%08x is illegal but is also a branch or jump: %s"
                    % (word, got)
                )


# ---------------------------------------------------------------------------
# Immediate format selection
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_immediate_formats_are_selected(dut):
    """`imm_sel` says which of the five formats this instruction carries.

    One instruction per format, because `imm_gen` consumes this and a wrong
    selection gives a plausible wrong address: a store using the I format reads
    the wrong imm bits and writes to the wrong place.
    """
    for word, sel, name in (
        (ADDI, IMM_I, "ADDI (I)"),
        (JALR, IMM_I, "JALR (I)"),
        (LW, IMM_I, "LW (I)"),
        (SLLI, IMM_I, "SLLI (I)"),
        (SB, IMM_S, "SB (S)"),
        (SW, IMM_S, "SW (S)"),
        (BEQ, IMM_B, "BEQ (B)"),
        (BGEU, IMM_B, "BGEU (B)"),
        (LUI, IMM_U, "LUI (U)"),
        (AUIPC, IMM_U, "AUIPC (U)"),
        (JAL, IMM_J, "JAL (J)"),
    ):
        got = await decode(dut, word)
        assert got["imm_sel"] == sel, (
            "%s: imm_sel is %d, expected %d.  bundle: %s" % (name, got["imm_sel"], sel, got)
        )


# ---------------------------------------------------------------------------
# Operand field usage
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_jal_sets_uses_rd_but_not_uses_rs1(dut):
    """JAL writes rd and reads neither rs1 nor rs2.

    The plan's Task 3 lists a test called `test_jal_sets_uses_rs1_and_uses_rd`,
    which is a mistake in the *plan*: JAL has no rs1 field.  Its rs1 field bits
    are part of the immediate.  Asserting `uses_rs1 = 1` for JAL would make the
    hazard unit compare a register index that is really immediate data, and a
    dependent load could then stall for no reason - or, worse, a forwarding
    unit could substitute a register value into the jump target.  So this test
    asserts the opposite of the plan's name, and says why.
    """
    await expect_fields(dut, JAL, "JAL", uses_rs1=0, uses_rs2=0, uses_rd=1, reg_write=1)


@cocotb.test()
async def test_jalr_and_branches_read_rs1_and_rs2_correctly(dut):
    """JALR reads rs1 only; branches read rs1 and rs2; none of them read rd.

    JALR against JAL is the interesting pair: they have the same link-register
    behaviour and different operand behaviour, and a decoder that gives them the
    same `uses_rs1` breaks forwarding into a JALR target.
    """
    await expect_fields(dut, JALR, "JALR", uses_rs1=1, uses_rs2=0, uses_rd=1, reg_write=1)
    for word, name in ((BEQ, "BEQ"), (BGEU, "BGEU")):
        await expect_fields(dut, word, name, uses_rs1=1, uses_rs2=1, uses_rd=0, reg_write=0)


@cocotb.test()
async def test_lui_and_auIPC_read_no_registers(dut):
    """LUI and AUIPC read no register at all, so `uses_rs1` and `uses_rs2` are 0.

    Their rd-independent behaviour is what makes them the cheapest instructions
    in the pipeline.  A decoder that set `uses_rs1` for them would make the
    hazard unit compare garbage against a live destination and insert a
    pointless stall before every `lui`.
    """
    await expect_fields(dut, LUI, "LUI", uses_rs1=0, uses_rs2=0, uses_rd=1, reg_write=1)
    await expect_fields(dut, AUIPC, "AUIPC", uses_rs1=0, uses_rs2=0, uses_rd=1, reg_write=1)


@cocotb.test()
async def test_uses_rd_is_set_exactly_where_reg_write_is(dut):
    """In base RV32I the two always agree - and the test says so explicitly.

    The contract requires them to be separate signals because in a later phase
    they will differ, and merging them would turn that into a port-list change
    for every downstream module.  This test documents the phase-1 relationship
    and would flag it if a future edit silently diverged them.
    """
    for name, word, _ in RV32I:
        got = await decode(dut, word)
        assert got["uses_rd"] == got["reg_write"], (
            "%s: uses_rd=%d but reg_write=%d.  In base RV32I every instruction "
            "that mentions rd writes it, so these must agree in phase 1; if "
            "they have diverged, this test needs updating to say which "
            "instructions now differ." % (name, got["uses_rd"], got["reg_write"])
        )


@cocotb.test()
async def test_branches_and_stores_do_not_set_uses_rd(dut):
    """A branch and a store mention no rd, so `uses_rd` must be 0.

    This is the case that makes `uses_rd` worth having at all rather than a copy
    of `reg_write`: without it, `core` extracts `instr[11:7]` as a destination
    index for a branch, and the hazard unit compares it against a live rd and
    inserts a stall.  The data-dependent behaviour is in `core`, but the signal
    that prevents it starts here.
    """
    await expect_fields(dut, BEQ, "BEQ", uses_rd=0)
    await expect_fields(dut, BLTU, "BLTU", uses_rd=0)
    await expect_fields(dut, SW, "SW", uses_rd=0)
    await expect_fields(dut, SH, "SH", uses_rd=0)
    await expect_fields(dut, FENCE, "FENCE", uses_rd=0)


# ---------------------------------------------------------------------------
# Operand selects
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_operand_selects_per_instruction_class(dut):
    """op1_sel and op2_sel for each class of instruction.

    The four shapes are: rs1+rs2 (OP, branches, stores), rs1+imm (OP-IMM, loads,
    JALR), pc+pc (AUIPC), pc+imm (JAL), and zero+imm (LUI).  A store is the one
    that mixes the shapes - its *address* is rs1+imm but its *data* is rs2, and
    since one `op2_sel` serves both purposes the immediate comes from `imm_sel`
    and the stored value from rs2.  Getting that backwards stores the address.
    """
    for word, op1, op2, name in (
        (ADD, OP1_RS1, OP2_RS2, "ADD"),
        (BEQ, OP1_RS1, OP2_RS2, "BEQ"),
        (SW, OP1_RS1, OP2_RS2, "SW"),
        (ADDI, OP1_RS1, OP2_IMM, "ADDI"),
        (LW, OP1_RS1, OP2_IMM, "LW"),
        (JALR, OP1_RS1, OP2_IMM, "JALR"),
        (LUI, OP1_ZERO, OP2_IMM, "LUI"),
        (AUIPC, OP1_PC, OP2_PC, "AUIPC"),
        (JAL, OP1_PC, OP2_IMM, "JAL"),
    ):
        got = await decode(dut, word)
        assert got["op1_sel"] == op1, "%s: op1_sel=%d, expected %d" % (name, got["op1_sel"], op1)
        assert got["op2_sel"] == op2, "%s: op2_sel=%d, expected %d" % (name, got["op2_sel"], op2)


@cocotb.test()
async def test_op2_sel_never_selects_the_constant_four_encoding(dut):
    """`op2_sel` = 2 (the literal constant 4) is enumerated but never selected.

    The contract lists it: "2 = 4".  No RV32I encoding needs a constant 4 as its
    second operand.  Where a `+4` does appear - the `JAL`/`JALR` link register -
    it arrives through `wb_sel`, not through an operand select, so there is
    nothing for `op2_sel = 2` to express.  Nothing here may ever produce it.

    If a future phase does need it, this test will fail and can be revisited
    then, deliberately.
    """
    for name, word, _ in RV32I:
        got = await decode(dut, word)
        assert got["op2_sel"] != OP2_FOUR, (
            "%s: op2_sel=2 (constant 4), which no RV32I encoding requires.  "
            "bundle: %s" % (name, got)
        )
    for opcode in range(128):
        for funct3 in range(8):
            word = (0xFFFFFFFF & ~0x7FFF) | (funct3 << 12) | opcode
            got = await decode(dut, word)
            assert got["op2_sel"] != OP2_FOUR, (
                "instr=%08x selected op2_sel=2" % word
            )


# ---------------------------------------------------------------------------
# branch_funct3
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_branch_funct3_is_published_for_every_branch(dut):
    """`branch_funct3` must carry the branch's own funct3 for all six of them.

    `ex_stage` uses it to choose the comparison and does not re-decode the
    opcode, so this is the only channel through which BEQ and BNE are told
    apart.  Getting it wrong turns every conditional branch into whichever one
    the hardwired constant names.
    """
    for word, funct3, name in (
        (BEQ, 0b000, "BEQ"),
        (BNE, 0b001, "BNE"),
        (BLT, 0b100, "BLT"),
        (BGE, 0b101, "BGE"),
        (BLTU, 0b110, "BLTU"),
        (BGEU, 0b111, "BGEU"),
    ):
        got = await decode(dut, word)
        assert got["is_branch"] == 1, "%s did not set is_branch" % name
        assert got["branch_funct3"] == funct3, (
            "%s: branch_funct3=%d, expected %d.  bundle: %s"
            % (name, got["branch_funct3"], funct3, got)
        )


@cocotb.test()
async def test_the_six_branch_funct3_values_are_all_distinct(dut):
    """The six branches must produce six different `branch_funct3` values.

    A copy-paste slip that made BNE report BEQ's funct3 would pass a test that
    only checks BEQ.  This checks they are pairwise distinct, which is a property
    of the table rather than of any one row.
    """
    seen = {}
    for word, name in ((BEQ, "BEQ"), (BNE, "BNE"), (BLT, "BLT"),
                       (BGE, "BGE"), (BLTU, "BLTU"), (BGEU, "BGEU")):
        got = await decode(dut, word)
        value = got["branch_funct3"]
        assert value not in seen, (
            "%s and %s both report branch_funct3=%d" % (seen.get(value), name, value)
        )
        seen[value] = name
    assert set(seen) == {0b000, 0b001, 0b100, 0b101, 0b110, 0b111}, (
        "branch_funct3 values are %s" % sorted(seen)
    )


# ---------------------------------------------------------------------------
# mem_size / mem_unsigned
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_mem_size_and_mem_unsigned_for_every_load_and_store(dut):
    """All eight memory instructions, checking both memory-control fields.

    `mem_size` and `mem_unsigned` are the two fields that make LB/LBU and
    LH/LHU differ from each other, and they are what make `SB` write one byte
    instead of four.  A decoder that got LB and LBU the same would silently
    zero-extend a signed load, which corrupts every negative byte it reads.
    """
    for word, size, unsigned, name in (
        (LB, MEM_BYTE, 0, "LB"),
        (LBU, MEM_BYTE, 1, "LBU"),
        (LH, MEM_HALF, 0, "LH"),
        (LHU, MEM_HALF, 1, "LHU"),
        (LW, MEM_WORD, 0, "LW"),
        (SB, MEM_BYTE, 0, "SB"),
        (SH, MEM_HALF, 0, "SH"),
        (SW, MEM_WORD, 0, "SW"),
    ):
        got = await decode(dut, word)
        assert got["mem_size"] == size, (
            "%s: mem_size=%d, expected %d.  bundle: %s" % (name, got["mem_size"], size, got)
        )
        assert got["mem_unsigned"] == unsigned, (
            "%s: mem_unsigned=%d, expected %d.  bundle: %s"
            % (name, got["mem_unsigned"], unsigned, got)
        )
        is_mem = got["mem_read"] or got["mem_write"]
        assert is_mem, "%s: neither mem_read nor mem_write is set" % name


@cocotb.test()
async def test_lbu_and_lhu_differ_from_lb_and_lh_only_in_mem_unsigned(dut):
    """The signed and unsigned pairs must differ in exactly one bit.

    Asserted as a difference rather than as a table, because the failure mode is
    a copy-paste that changes two fields at once - which a per-row table of
    expected values would catch only if the table had been written independently.
    """
    for signed_word, unsigned_word, name in (
        (LB, LBU, "LB/LBU"),
        (LH, LHU, "LH/LHU"),
    ):
        a = await decode(dut, signed_word)
        b = await decode(dut, unsigned_word)
        differing = [k for k in a if a[k] != b[k]]
        assert differing == ["mem_unsigned"], (
            "%s: the signed and unsigned forms differ in %s, expected only "
            "mem_unsigned.  %s vs %s" % (name, differing, a, b)
        )


@cocotb.test()
async def test_non_memory_instructions_leave_mem_size_at_zero(dut):
    """`mem_size` is 0 for every instruction that does not access memory.

    The contract says "`mem_size` is meaningful only when `mem_read` or
    `mem_write` is high and is `0` otherwise".  Leaving it at a stale nonzero
    value is harmless *today* because `lsu` qualifies on `mem_read`/`mem_write`,
    but it puts an X or a stale bit into a bundle field for no reason.
    """
    for name, word, _ in RV32I:
        got = await decode(dut, word)
        if not (got["mem_read"] or got["mem_write"]):
            assert got["mem_size"] == 0, (
                "%s: no memory access but mem_size=%d.  bundle: %s"
                % (name, got["mem_size"], got)
            )
            assert got["mem_unsigned"] == 0, (
                "%s: no memory access but mem_unsigned=%d" % (name, got["mem_unsigned"])
            )


# ---------------------------------------------------------------------------
# wb_sel
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_wb_sel_selects_the_right_writeback_source(dut):
    """Three sources: ALU, memory, and pc+4 for the two link registers.

    `wb_sel` is a 2-bit explicit select rather than a one-bit `MemToReg` because
    there are three sources.  The pc+4 case is the one a one-bit select cannot
    express, and getting it wrong makes `jal` return the jump target instead of
    the return address - which is a wrong answer that still looks like a valid
    address.
    """
    for word, sel, name in (
        (ADDI, WB_ALU, "ADDI"),
        (ADD, WB_ALU, "ADD"),
        (SW, WB_ALU, "SW (no writeback at all)"),
        (LUI, WB_ALU, "LUI"),
        (AUIPC, WB_ALU, "AUIPC"),
        (LB, WB_MEM, "LB"),
        (LW, WB_MEM, "LW"),
        (LHU, WB_MEM, "LHU"),
        (JAL, WB_PC4, "JAL"),
        (JALR, WB_PC4, "JALR"),
    ):
        got = await decode(dut, word)
        assert got["wb_sel"] == sel, (
            "%s: wb_sel=%d, expected %d.  bundle: %s" % (name, got["wb_sel"], sel, got)
        )


@cocotb.test()
async def test_wb_sel_never_selects_an_unimplemented_encoding(dut):
    """`wb_sel` never takes the value 3, which the contract does not define.

    A three-way select with a 2-bit field has one spare encoding.  Nothing may
    ever select it, because `mem_stage` would have to decide what it means and
    there is no fourth source.
    """
    for name, word, _ in RV32I:
        got = await decode(dut, word)
        assert got["wb_sel"] != 3, "%s: wb_sel=3 is not a valid source" % name
    for opcode in range(128):
        word = (0xDEADBEEF & ~0x7F) | opcode
        got = await decode(dut, word)
        assert got["wb_sel"] != 3, "instr=%08x selected wb_sel=3" % word


# ---------------------------------------------------------------------------
# The `alu_op` encoding - the cross-owner agreement with P3
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_alu_op_encoding_is_the_documented_table(dut):
    """Pin the `alu_op` numbers, because `alu` is on P3's side of the freeze.

    `docs/contracts/phase1-interfaces.md` deliberately does not enumerate the
    `alu_op` encoding - "internal to the execute block, which is built by a
    single owner" - but `alu` and `decode` are owned by *different* people, so
    the table has to be agreed rather than merely internal.  It is written in
    `decode.v`'s header (DESIGN NOTE 2) and P3's `alu` must implement it.

    This test pins the numbers so that changing one here fails loudly and
    immediately rather than surfacing as mysterious wrong arithmetic after
    integration.  If P3 and P2 ever disagree, this is the test that says so.
    """
    for word, alu_op, name in (
        (ADD, ALU_ADD, "ADD"),
        (ADDI, ALU_ADD, "ADDI"),
        (AUIPC, ALU_ADD, "AUIPC"),
        (LUI, ALU_ADD, "LUI"),
        (JAL, ALU_ADD, "JAL"),
        (JALR, ALU_ADD, "JALR"),
        (LB, ALU_ADD, "LB"),
        (SW, ALU_ADD, "SW"),
        (SUB, ALU_SUB, "SUB"),
        (BEQ, ALU_SUB, "BEQ (address arithmetic and BEQ comparison)"),
        (SLL, ALU_SLL, "SLL"),
        (SLLI, ALU_SLL, "SLLI"),
        (SLT, ALU_SLT, "SLT"),
        (SLTI, ALU_SLT, "SLTI"),
        (SLTU, ALU_SLTU, "SLTU"),
        (SLTIU, ALU_SLTU, "SLTIU"),
        (XOR, ALU_XOR, "XOR"),
        (XORI, ALU_XOR, "XORI"),
        (SRL, ALU_SRL, "SRL"),
        (SRLI, ALU_SRL, "SRLI"),
        (SRA, ALU_SRA, "SRA"),
        (SRAI, ALU_SRA, "SRAI"),
        (OR, ALU_OR, "OR"),
        (ORI, ALU_OR, "ORI"),
        (AND, ALU_AND, "AND"),
        (ANDI, ALU_AND, "ANDI"),
    ):
        got = await decode(dut, word)
        assert got["alu_op"] == alu_op, (
            "%s: alu_op=%d, expected %d.  The alu_op encoding is frozen "
            "between `decode` (P2) and `alu` (P3) in decode.v DESIGN NOTE 2; "
            "if one of them changed, they must be changed together.  "
            "bundle: %s" % (name, got["alu_op"], alu_op, got)
        )


@cocotb.test()
async def test_alu_op_never_selects_an_unimplemented_operation(dut):
    """`alu_op` stays within 0..9 for every word, legal or not.

    The field is 4 bits, so 10..15 are spare.  Nothing may select them, because
    `alu` implements exactly ten operations and would have to invent a
    behaviour.  Swept over the whole funct7/funct3 space of both ALU opcodes as
    well as the RV32I table, so it holds even for the encodings that are
    illegal.
    """
    for name, word, _ in RV32I:
        got = await decode(dut, word)
        assert got["alu_op"] <= ALU_AND, "%s: alu_op=%d" % (name, got["alu_op"])

    for opcode in (OP_OP, OP_OP_IMM):
        for funct7 in range(0x80):
            for funct3 in range(8):
                word = r_type(funct7, RS2, RS1, funct3, RD, opcode)
                got = await decode(dut, word)
                assert got["alu_op"] <= ALU_AND, (
                    "instr=%08x gave alu_op=%d, above 9" % (word, got["alu_op"])
                )

    # And for every other opcode too.
    for opcode in range(128):
        for funct3 in range(8):
            word = (0xFFFFFFFF & ~0x7FFF) | (funct3 << 12) | opcode
            got = await decode(dut, word)
            assert got["alu_op"] <= ALU_AND, (
                "instr=%08x gave alu_op=%d, above 9" % (word, got["alu_op"])
            )


# ---------------------------------------------------------------------------
# No state, and no dependence on anything but `instr`
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_decode_is_stateless(dut):
    """The same word decodes identically whatever came before it.

    `decode` is purely combinational with no pipeline state, so this is a check
    on the module having no hidden latch: `regfile` has memory and `if_stage`
    has a handshake, and a stray `reg` in `decode` would show up here.
    """
    sequence = [ADDI, LW, SW, BEQ, JAL, LUI, 0xFFFFFFFF, ADD, JALR, SRAI]
    first = {}
    for word in sequence:
        first[word] = await decode(dut, word)

    # Repeat in the same order, then in reverse, then interleaved with others.
    for word in sequence:
        got = await decode(dut, word)
        assert got == first[word], (
            "instr=%08x decoded differently the second time: %s vs %s"
            % (word, got, first[word])
        )
    for word in reversed(sequence):
        got = await decode(dut, word)
        assert got == first[word], (
            "instr=%08x decoded differently after other words: %s vs %s"
            % (word, got, first[word])
        )
    for _ in range(3):
        for word in sequence[3:] + sequence[:3]:
            got = await decode(dut, word)
            assert got == first[word], "instr=%08x is order-dependent" % word


@cocotb.test()
async def test_rd_field_does_not_affect_the_control_bundle(dut):
    """Changing only rd must not change any output.

    `decode` has no rd output - `core` extracts `instr[11:7]` as wiring - so the
    rd bits must not reach the decoder's own logic.  They do reach it in the I,
    R and J formats' *immediate* handling in other modules, but `imm_gen` is a
    separate module; here the control bundle must be rd-independent.

    This is checked for the opcodes where rd is genuinely a destination field.
    """
    for opcode, name in (
        (OP_LUI, "LUI"),
        (OP_AUIPC, "AUIPC"),
        (OP_OP, "OP"),
        (OP_OP_IMM, "OP-IMM"),
        (OP_LOAD, "LOAD"),
        (OP_JALR, "JALR"),
        (OP_JAL, "JAL"),
    ):
        for rd in (0, 1, 15, 31):
            if opcode in (OP_LUI, OP_AUIPC):
                word = u_type(0x00001000, rd, opcode)
            elif opcode == OP_JAL:
                word = j_type(0x00001000, rd)
            elif opcode == OP_OP:
                word = r_type(0x00, RS2, RS1, 0b000, rd, opcode)
            else:
                word = i_type(0x004, RS1, 0b000, rd, opcode)
            got = await decode(dut, word)
            reference = await decode(dut, word & ~0xF80)
            assert got == reference, (
                "%s with rd=x%d gave %s, but with rd=x0 it gave %s: the rd bits "
                "must not reach the control logic" % (name, rd, got, reference)
            )


@cocotb.test()
async def test_rs1_and_rs2_fields_do_not_affect_the_control_bundle(dut):
    """Changing only rs1/rs2 must not change any output either.

    Same reasoning as the rd test: the operand *addresses* are `core`'s wiring,
    so the decoder's control outputs cannot depend on them.  What does depend on
    the immediate bits is `imm_gen`, which is a separate module.
    """
    for word, name, mask in (
        (ADD, "ADD", None),
        (SW, "SW", None),
        (BEQ, "BEQ", None),
        (LW, "LW", None),
        (ADDI, "ADDI", None),
    ):
        base = await decode(dut, word)
        for field, shift, width in (("rs1", 15, 5), ("rs2", 20, 5)):
            for value in (0, 1, 31):
                variant = (word & ~(((1 << width) - 1) << shift)) | (
                    value << shift
                )
                got = await decode(dut, variant)
                assert got == base, (
                    "%s: changing only %s to x%d changed the control bundle: "
                    "%s vs %s" % (name, field, value, got, base)
                )


@cocotb.test()
async def test_every_output_is_driven_for_every_opcode(dut):
    """No output may be left undriven, for any opcode.

    A two-state simulator reads an undriven wire as 0 and a four-state one
    propagates X, so an undriven output is invisible in one simulation and
    poisonous in the other.  This checks that every output is a defined 0 or 1
    for all 128 opcodes - which under Icarus, via `make test-4state`, is a real
    check that nothing is X.

    The values are not constrained here beyond being 0 or 1: this is about
    *definedness*, and the other tests in this file pin the values.
    """
    for opcode in range(128):
        for funct3 in range(8):
            word = (0xFFFFFFFF & ~0x7FFF) | (funct3 << 12) | opcode
            got = await decode(dut, word)
            for name, value in got.items():
                width = WIDTH.get(name, 1)
                assert 0 <= value < (1 << width), (
                    "instr=%08x: %s is %d, which does not fit in %d bit(s) - it "
                    "is undriven or X" % (word, name, value, width)
                )


@cocotb.test()
async def test_control_class_signals_are_zero_for_non_control_instructions(dut):
    """`is_branch`, `is_jal` and `is_jalr` are 0 for everything else.

    Swept over the ALU, memory and U-immediate opcodes, which is where a
    copy-paste slip in the case statement would leak a stray `is_jal = 1` into
    an `addi`.
    """
    for name, word, _ in RV32I:
        got = await decode(dut, word)
        is_control = name in ("BEQ", "BNE", "BLT", "BGE", "BLTU", "BGEU",
                              "JAL", "JALR")
        assert (got["is_branch"] or got["is_jal"] or got["is_jalr"]) == is_control, (
            "%s: control-class signals are branch=%d jal=%d jalr=%d, expected "
            "%s.  bundle: %s"
            % (name, got["is_branch"], got["is_jal"], got["is_jalr"],
               is_control, got)
        )

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

    # Stores: the effective address is rs1 + imm, so op2_sel is the immediate
    # exactly as for a load. The stored *value* is rs2, but `ex_stage` takes it
    # off ex_rs2_data, so it never reaches the ALU. `op2_sel` used to go
    # unasserted here, which is how it stayed wrong for so long -- it is now
    # pinned. No writeback at all.
    ("SB", SB, bundle(imm_sel=IMM_S, op1_sel=OP1_RS1, op2_sel=OP2_IMM,
                      alu_op=ALU_ADD, mem_write=1, mem_size=MEM_BYTE,
                      uses_rs1=1, uses_rs2=1)),
    ("SH", SH, bundle(imm_sel=IMM_S, op1_sel=OP1_RS1, op2_sel=OP2_IMM,
                      alu_op=ALU_ADD, mem_write=1, mem_size=MEM_HALF,
                      uses_rs1=1, uses_rs2=1)),
    ("SW", SW, bundle(imm_sel=IMM_S, op1_sel=OP1_RS1, op2_sel=OP2_IMM,
                      alu_op=ALU_ADD, mem_write=1, mem_size=MEM_WORD,
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

    Only opcodes that end in `11` are 32-bit opcodes: with `instr[1:0] != 11`
    the low bits select a compressed quadrant instead, so those words are not
    "unknown 32-bit opcodes" and are covered by the C-extension tests.
    """
    # Every 7-bit opcode that is not one of the eleven this core implements.
    implemented = {
        OP_LOAD, OP_MISC_MEM, OP_OP_IMM, OP_AUIPC, OP_STORE, OP_OP,
        OP_LUI, OP_BRANCH, OP_JALR, OP_JAL, OP_SYSTEM,
    }
    for opcode in range(128):
        if opcode in implemented or opcode & 0b11 != 0b11:
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
# The C extension - expand, then decode
# ---------------------------------------------------------------------------
#
# `decode` rewrites a 16-bit instruction into its canonical 32-bit equivalent
# (the `instr_eff` output) and then runs the same 32-bit decode on it.  So a
# test asserts two things: that `instr_eff` is exactly the word the assembler
# would have produced for the equivalent 32-bit instruction, and that the
# control bundle is what that word decodes to.
#
# `instr_eff` is read back as a whole 32-bit number and parsed by the helpers
# below, so the expansion is checked field by field rather than only through
# the control signals it happens to influence.


def eff_rd(eff):
    return (eff >> 7) & 0x1F


def eff_rs1(eff):
    return (eff >> 15) & 0x1F


def eff_rs2(eff):
    return (eff >> 20) & 0x1F


def eff_opcode(eff):
    return eff & 0x7F


def eff_imm_i(eff):
    v = (eff >> 20) & 0xFFF
    return v - 0x1000 if v & 0x800 else v


def eff_imm_s(eff):
    v = (((eff >> 25) & 0x7F) << 5) | ((eff >> 7) & 0x1F)
    return v - 0x1000 if v & 0x800 else v


def eff_imm_j(eff):
    v = (((eff >> 31) & 1) << 20) | (((eff >> 21) & 0x3FF) << 1)
    v |= (((eff >> 20) & 1) << 11) | (((eff >> 12) & 0xFF) << 12)
    return v - (1 << 21) if v & (1 << 20) else v


def eff_imm_b(eff):
    v = (((eff >> 31) & 1) << 12) | (((eff >> 25) & 0x3F) << 5)
    v |= (((eff >> 8) & 0xF) << 1) | (((eff >> 7) & 1) << 11)
    return v - (1 << 13) if v & (1 << 12) else v


async def expanded(dut, word):
    """Present one instruction word and read the post-expansion 32-bit word."""
    dut.instr.value = word
    await Timer(1, unit="ns")
    return int(dut.instr_eff.value)


@cocotb.test()
async def test_compressed_and_32_bit_words_are_distinguished_by_instr_1_0(dut):
    """instr[1:0] != 2'b11 selects the expander; == 2'b11 selects the decoder.

    Both words below are hard anchors: 0x4504 is `c.lw s1, 8(a0)` and 0x00C58533
    is `add a0, a1, a2`, both taken from the toolchain's own disassembly.
    """
    got = await decode(dut, 0x4504)          # c.lw x9, 8(x10)
    assert got["mem_read"] == 1, (
        "c.lw must decode as a load, not illegal: %s" % got
    )
    got = await decode(dut, 0x00C58533)      # add a0, a1, a2
    assert got["alu_op"] == ALU_ADD, "a 32-bit add must still decode: %s" % got


@cocotb.test()
async def test_over_32_bit_forms_are_illegal(dut):
    """A word with instr[4:2] == 111 is longer than 32 bits and is illegal.

    The 16-bit length gate (`instr[1:0] != 11`) is now the expander *selector*,
    not an illegal verdict, so the over-32-bit gate is the only length check
    still rejecting a word outright.  This is the load-bearing half of the
    phase-1 test of the same name.
    """
    legal = ADD  # a plain, fully legal `add x7, x5, x6`
    await expect_illegal(dut, (legal & ~0b0011100) | 0b111 << 2, "ADD marked over-long")


# --- quadrant 0 ------------------------------------------------------------
#
# h[15:13]: 000 C.ADDI4SPN, 010 C.LW, 011 C.LD (RV32 illegal),
#           110 C.SW, 111 C.SD (RV32 illegal).  All the words below are the
#           toolchain's own encodings.

C_ADDI4SPN_S0_SP_16 = 0x0800   # c.addi4spn s0, sp, 16
C_LW_S1_8_A0 = 0x4504          # c.lw s1, 8(a0)
C_SW_S1_8_A0 = 0xC504          # c.sw s1, 8(a0)


@cocotb.test()
async def test_c_addi4spn_expands_to_addi_sp(dut):
    """c.addi4spn rd', nzuimm == `addi rd', x2, nzuimm`.

    rd' is x8 (`s0`), rs1 is x2, and the addi immediate is 16, exactly as the
    assembler encodes `addi s0, sp, 16` -> 0x01010413.
    """
    word = C_ADDI4SPN_S0_SP_16
    eff = await expanded(dut, word)
    assert eff == 0x01010413, (
        "c.addi4spn s0,sp,16 expanded to %08x, expected addi s0,sp,16 (0x01010413)"
        % eff
    )
    assert (eff_opcode(eff), eff_rd(eff), eff_rs1(eff), eff_imm_i(eff)) == (
        OP_OP_IMM, 8, 2, 16
    ), "expanded word is not `addi x8, x2, 16`: %08x" % eff
    await expect_fields(dut, word, "c.addi4spn s0,sp,16",
                        alu_op=ALU_ADD, op1_sel=OP1_RS1, op2_sel=OP2_IMM,
                        imm_sel=IMM_I, uses_rs1=1, uses_rd=1, reg_write=1)


@cocotb.test()
async def test_c_lw_expands_to_lw(dut):
    """c.lw rd', offset(rs1') == `lw rd', offset(rs1')`.

    rd' is x9 (`s1`), rs1' is x10 (`a0`), offset 8; the assembler's equivalent
    `lw s1, 8(a0)` is 0x00852483.
    """
    word = C_LW_S1_8_A0
    eff = await expanded(dut, word)
    assert eff == 0x00852483, (
        "c.lw s1,8(a0) expanded to %08x, expected lw s1,8(a0) (0x00852483)" % eff
    )
    assert (eff_opcode(eff), eff_rd(eff), eff_rs1(eff), eff_imm_i(eff)) == (
        OP_LOAD, 9, 10, 8
    ), "expanded word is not `lw x9, 8(x10)`: %08x" % eff
    await expect_fields(dut, word, "c.lw s1,8(a0)",
                        alu_op=ALU_ADD, op1_sel=OP1_RS1, op2_sel=OP2_IMM,
                        imm_sel=IMM_I, mem_read=1, mem_size=MEM_WORD,
                        uses_rs1=1, uses_rd=1, reg_write=1, wb_sel=WB_MEM)


@cocotb.test()
async def test_c_sw_expands_to_sw(dut):
    """c.sw rs2', offset(rs1') == `sw rs2', offset(rs1')`.

    rs2' is x9, rs1' is x10, offset 8; the assembler's equivalent
    `sw s1, 8(a0)` is 0x00952423.
    """
    word = C_SW_S1_8_A0
    eff = await expanded(dut, word)
    assert eff == 0x00952423, (
        "c.sw s1,8(a0) expanded to %08x, expected sw s1,8(a0) (0x00952423)" % eff
    )
    assert (eff_opcode(eff), eff_rs1(eff), eff_rs2(eff), eff_imm_s(eff)) == (
        OP_STORE, 10, 9, 8
    ), "expanded word is not `sw x9, 8(x10)`: %08x" % eff
    await expect_fields(dut, word, "c.sw s1,8(a0)",
                        alu_op=ALU_ADD, op1_sel=OP1_RS1, op2_sel=OP2_IMM,
                        imm_sel=IMM_S, mem_write=1, mem_size=MEM_WORD,
                        uses_rs1=1, uses_rs2=1, reg_write=0)


@cocotb.test()
async def test_c_addi4spn_with_zero_immediate_is_illegal(dut):
    """c.addi4spn with nzuimm == 0 is a reserved encoding, not `addi rd, sp, 0`.

    0x0004 has rd' = 1 (x9) and an all-zero nzuimm: a nonzero destination, so
    this is specifically the zero-immediate rule and not the all-zero word.
    """
    await expect_illegal(dut, 0x0004, "c.addi4spn x9, sp, 0")


@cocotb.test()
async def test_rv64_quadrant0_forms_are_illegal(dut):
    """C.LD (funct3 011) and C.SD (funct3 111) are RV64 and illegal in RV32.

    Review Focus 4: the decoder must not silently accept the 64-bit forms just
    because they share quadrant 0 with C.LW/C.SW.
    """
    await expect_illegal(dut, 0x6000, "C.LD")
    await expect_illegal(dut, 0xE000, "C.SD")


@cocotb.test()
async def test_instructions_longer_than_32_bits_are_illegal(dut):
    """instr[4:2] == 111 with instr[1:0] == 11 escapes to a longer encoding.

    No such instruction exists, and treating one as an ordinary 32-bit word
    would decode whatever sits in its upper half as an opcode. Only words that
    also have `instr[1:0] == 11` are over-long: when `instr[1:0] != 11` the word
    is a 16-bit *compressed* instruction and those bits belong to it, which is
    what the C-extension tests below cover. So the sweep is restricted to the
    four opcodes with both fields set.
    """
    swept = 0
    for opcode in range(128):
        if (opcode >> 2) & 0b111 != 0b111 or opcode & 0b11 != 0b11:
            continue
        for funct3 in range(8):
            word = (0xDEADBEEF & ~0x7FFF) | (funct3 << 12) | opcode
            await expect_illegal(dut, word, "over-long opcode %s" % format(opcode, "07b"))
            swept += 1
    assert swept == 4 * 8, "expected to sweep 4 over-long opcodes, swept %d" % swept


# --- quadrant 1 ------------------------------------------------------------
#
# Every word below is the toolchain's own encoding, and every expected value is
# the toolchain's own encoding of the equivalent 32-bit instruction (checked
# with `riscv64-elf-objdump -D -b binary -m riscv:rv32`).

C_NOP = 0x0001                 # c.nop
C_ADDI_S0_M1 = 0x147D          # c.addi s0, -1
C_LI_S1_5 = 0x4495             # c.li s1, 5
C_LUI_S1_1 = 0x6485            # c.lui s1, 0x1
C_ADDI16SP_SP_32 = 0x6105      # c.addi16sp sp, 32
C_SRLI_S1_3 = 0x808D           # c.srli s1, 3
C_SRAI_S1_3 = 0x848D           # c.srai s1, 3
C_ANDI_S1_3 = 0x888D           # c.andi s1, 3
C_SUB_S1_A0 = 0x8C89           # c.sub s1, a0
C_XOR_S1_A0 = 0x8CA9           # c.xor s1, a0
C_OR_S1_A0 = 0x8CC9            # c.or s1, a0
C_AND_S1_A0 = 0x8CE9           # c.and s1, a0
C_JAL_44 = 0x2035              # c.jal 44
C_J_24 = 0xA821                # c.j 24
C_BEQZ_S1_22 = 0xC899          # c.beqz s1, 22
C_BNEZ_S1_20 = 0xE891          # c.bnez s1, 20


@cocotb.test()
async def test_c_nop_expands_to_inert_addi(dut):
    """c.nop == `addi x0, x0, 0`.  rd is x0, so it has no architectural effect."""
    eff = await expanded(dut, C_NOP)
    assert eff == 0x00000013, "c.nop expanded to %08x, expected 0x00000013" % eff
    assert eff_rd(eff) == 0, "c.nop must target x0: %08x" % eff
    await expect_fields(dut, C_NOP, "c.nop", alu_op=ALU_ADD, op2_sel=OP2_IMM,
                        imm_sel=IMM_I, uses_rs1=1, uses_rd=1, reg_write=1)


@cocotb.test()
async def test_c_addi_expands_to_addi_rd_rd(dut):
    """c.addi rd, imm == `addi rd, rd, imm`, imm sign-extended."""
    eff = await expanded(dut, C_ADDI_S0_M1)
    assert eff == 0xFFF40413, "c.addi s0,-1 expanded to %08x, expected 0xFFF40413" % eff
    assert (eff_opcode(eff), eff_rd(eff), eff_rs1(eff), eff_imm_i(eff)) == (
        OP_OP_IMM, 8, 8, -1
    ), "expanded word is not `addi x8, x8, -1`: %08x" % eff
    await expect_fields(dut, C_ADDI_S0_M1, "c.addi s0,-1", alu_op=ALU_ADD,
                        op2_sel=OP2_IMM, imm_sel=IMM_I, uses_rs1=1, uses_rd=1,
                        reg_write=1)


@cocotb.test()
async def test_c_li_expands_to_addi_rd_x0(dut):
    """c.li rd, imm == `addi rd, x0, imm`."""
    eff = await expanded(dut, C_LI_S1_5)
    assert eff == 0x00500493, "c.li s1,5 expanded to %08x, expected 0x00500493" % eff
    assert (eff_opcode(eff), eff_rd(eff), eff_rs1(eff), eff_imm_i(eff)) == (
        OP_OP_IMM, 9, 0, 5
    ), "expanded word is not `addi x9, x0, 5`: %08x" % eff
    await expect_fields(dut, C_LI_S1_5, "c.li s1,5", alu_op=ALU_ADD,
                        op2_sel=OP2_IMM, imm_sel=IMM_I, uses_rd=1, reg_write=1)


@cocotb.test()
async def test_c_lui_expands_to_lui(dut):
    """c.lui rd, nzimm == `lui rd, nzimm`, nzimm in imm[17:12]."""
    eff = await expanded(dut, C_LUI_S1_1)
    assert eff == 0x000014B7, "c.lui s1,0x1 expanded to %08x, expected 0x000014B7" % eff
    assert eff_opcode(eff) == OP_LUI and eff_rd(eff) == 9, (
        "expanded word is not `lui x9, 0x1`: %08x" % eff
    )
    await expect_fields(dut, C_LUI_S1_1, "c.lui s1,0x1", alu_op=ALU_ADD,
                        op1_sel=OP1_ZERO, op2_sel=OP2_IMM, imm_sel=IMM_U,
                        uses_rd=1, reg_write=1)


@cocotb.test()
async def test_c_addi16sp_expands_to_addi_sp(dut):
    """c.addi16sp sp, nzimm == `addi sp, sp, nzimm` (a multiple of 16)."""
    eff = await expanded(dut, C_ADDI16SP_SP_32)
    assert eff == 0x02010113, "c.addi16sp sp,32 expanded to %08x, expected 0x02010113" % eff
    assert (eff_opcode(eff), eff_rd(eff), eff_rs1(eff), eff_imm_i(eff)) == (
        OP_OP_IMM, 2, 2, 32
    ), "expanded word is not `addi x2, x2, 32`: %08x" % eff
    await expect_fields(dut, C_ADDI16SP_SP_32, "c.addi16sp sp,32", alu_op=ALU_ADD,
                        op2_sel=OP2_IMM, imm_sel=IMM_I, uses_rs1=1, uses_rd=1,
                        reg_write=1)


@cocotb.test()
async def test_c_shift_and_andi_expand(dut):
    """c.srli/c.srai/c.andi operate on rd' == rs1' (the primitive registers)."""
    cases = [
        (C_SRLI_S1_3, 0x0034D493, ALU_SRL, "c.srli s1,3"),
        (C_SRAI_S1_3, 0x4034D493, ALU_SRA, "c.srai s1,3"),
        (C_ANDI_S1_3, 0x0034F493, ALU_AND, "c.andi s1,3"),
    ]
    for word, want, alu, note in cases:
        eff = await expanded(dut, word)
        assert eff == want, "%s expanded to %08x, expected %08x" % (note, eff, want)
        assert (eff_opcode(eff), eff_rs1(eff), eff_rd(eff)) == (
            OP_OP_IMM, 9, 9
        ), "%s did not expand to rd' == rs1' == x9: %08x" % (note, eff)
        assert (eff >> 20) & 0x1F == 3, (
            "%s did not expand with shamt/imm 3: %08x" % (note, eff)
        )
        await expect_fields(dut, word, note, alu_op=alu, op2_sel=OP2_IMM,
                            imm_sel=IMM_I, uses_rs1=1, uses_rd=1, reg_write=1)


@cocotb.test()
async def test_c_register_alu_ops_expand(dut):
    """c.sub/c.xor/c.or/c.and == the register forms on rd', rs1', rs2'."""
    cases = [
        (C_SUB_S1_A0, 0x40A484B3, ALU_SUB, "c.sub s1,a0"),
        (C_XOR_S1_A0, 0x00A4C4B3, ALU_XOR, "c.xor s1,a0"),
        (C_OR_S1_A0, 0x00A4E4B3, ALU_OR, "c.or s1,a0"),
        (C_AND_S1_A0, 0x00A4F4B3, ALU_AND, "c.and s1,a0"),
    ]
    for word, want, alu, note in cases:
        eff = await expanded(dut, word)
        assert eff == want, "%s expanded to %08x, expected %08x" % (note, eff, want)
        assert (eff_opcode(eff), eff_rd(eff), eff_rs1(eff), eff_rs2(eff)) == (
            OP_OP, 9, 9, 10
        ), "%s did not expand to rd'=rs1'=x9, rs2'=x10: %08x" % (note, eff)
        await expect_fields(dut, word, note, alu_op=alu, op2_sel=OP2_RS2,
                            uses_rs1=1, uses_rs2=1, uses_rd=1, reg_write=1)


@cocotb.test()
async def test_c_jal_expands_to_jal(dut):
    """c.jal offset == `jal x1, offset`; the offset is the same branch target."""
    eff = await expanded(dut, C_JAL_44)
    assert eff == 0x02C000EF, "c.jal 44 expanded to %08x, expected 0x02C000EF" % eff
    assert (eff_opcode(eff), eff_rd(eff), eff_imm_j(eff)) == (OP_JAL, 1, 44), (
        "expanded word is not `jal x1, 44`: %08x" % eff
    )
    await expect_fields(dut, C_JAL_44, "c.jal 44", op1_sel=OP1_PC,
                        op2_sel=OP2_IMM, imm_sel=IMM_J, is_jal=1, uses_rd=1,
                        reg_write=1, wb_sel=WB_PC4)


@cocotb.test()
async def test_c_j_expands_to_jal_x0(dut):
    """c.j offset == `jal x0, offset` (the link register is discarded)."""
    eff = await expanded(dut, C_J_24)
    assert eff == 0x0180006F, "c.j 24 expanded to %08x, expected 0x0180006F" % eff
    assert (eff_opcode(eff), eff_rd(eff), eff_imm_j(eff)) == (OP_JAL, 0, 24), (
        "expanded word is not `jal x0, 24`: %08x" % eff
    )
    await expect_fields(dut, C_J_24, "c.j 24", op1_sel=OP1_PC, op2_sel=OP2_IMM,
                        imm_sel=IMM_J, is_jal=1, uses_rd=1, reg_write=1,
                        wb_sel=WB_PC4)


@cocotb.test()
async def test_c_beqz_bnez_expand_to_branches(dut):
    """c.beqz/c.bnez rs1' == `beq`/`bne rs1', x0` with the same offset."""
    cases = [
        (C_BEQZ_S1_22, 0x00048B63, 0b000, 22, "c.beqz s1,22"),
        (C_BNEZ_S1_20, 0x00049A63, 0b001, 20, "c.bnez s1,20"),
    ]
    for word, want, f3, off, note in cases:
        eff = await expanded(dut, word)
        assert eff == want, "%s expanded to %08x, expected %08x" % (note, eff, want)
        assert (eff_opcode(eff), eff_imm_b(eff), eff_rs1(eff), eff_rs2(eff)) == (
            OP_BRANCH, off, 9, 0
        ), "%s did not expand to a branch on x9 vs x0: %08x" % (note, eff)
        await expect_fields(dut, word, note, alu_op=ALU_SUB, imm_sel=IMM_B,
                            branch_funct3=f3, is_branch=1, uses_rs1=1,
                            uses_rs2=1)


@cocotb.test()
async def test_quadrant1_zero_immediates_are_reserved(dut):
    """c.addi16sp nzimm == 0 and c.lui nzimm == 0 are reserved, not nops."""
    await expect_illegal(dut, 0x6101, "c.addi16sp sp, 0")
    await expect_illegal(dut, 0x6401, "c.lui s0, 0")


@cocotb.test()
async def test_rv64_quadrant1_forms_are_illegal(dut):
    """c.subw and friends live at h[12:10] == 111 and are RV64-only.

    The same bit pattern in RV32 is reserved and must be illegal, not decoded as
    the RV64 word-wide arithmetic.
    """
    await expect_illegal(dut, 0x9C89, "c.subw s1, a0")


# --- quadrant 2 ------------------------------------------------------------
#
# As above: toolchain words in, toolchain words out.

C_SLLI_S1_3 = 0x048E           # c.slli s1, 3
C_LWSP_T0_4_SP = 0x4292        # c.lwsp t0, 4(sp)
C_JR_RA = 0x8082               # c.jr ra   (the `ret` the toolchain emits)
C_MV_T0_T1 = 0x829A            # c.mv t0, t1
C_EBREAK = 0x9002              # c.ebreak
C_JALR_RA = 0x9082             # c.jalr ra
C_ADD_T0_T1 = 0x929A           # c.add t0, t1
C_SWSP_S1_8_SP = 0xC426        # c.swsp s1, 8(sp)


@cocotb.test()
async def test_c_slli_expands_to_slli(dut):
    """c.slli rd, shamt == `slli rd, rd, shamt` (shamt[5] must be 0 in RV32)."""
    eff = await expanded(dut, C_SLLI_S1_3)
    assert eff == 0x00349493, "c.slli s1,3 expanded to %08x, expected 0x00349493" % eff
    assert (eff_opcode(eff), eff_rd(eff), eff_rs1(eff), (eff >> 20) & 0x1F) == (
        OP_OP_IMM, 9, 9, 3
    ), "expanded word is not `slli x9, x9, 3`: %08x" % eff
    await expect_fields(dut, C_SLLI_S1_3, "c.slli s1,3", alu_op=ALU_SLL,
                        op2_sel=OP2_IMM, imm_sel=IMM_I, uses_rs1=1, uses_rd=1,
                        reg_write=1)


@cocotb.test()
async def test_c_lwsp_expands_to_lw(dut):
    """c.lwsp rd, offset == `lw rd, offset(x2)`; rd == x0 is reserved."""
    eff = await expanded(dut, C_LWSP_T0_4_SP)
    assert eff == 0x00412283, "c.lwsp t0,4(sp) expanded to %08x, expected 0x00412283" % eff
    assert (eff_opcode(eff), eff_rd(eff), eff_rs1(eff), eff_imm_i(eff)) == (
        OP_LOAD, 5, 2, 4
    ), "expanded word is not `lw x5, 4(x2)`: %08x" % eff
    await expect_fields(dut, C_LWSP_T0_4_SP, "c.lwsp t0,4(sp)", alu_op=ALU_ADD,
                        op1_sel=OP1_RS1, op2_sel=OP2_IMM, imm_sel=IMM_I,
                        mem_read=1, mem_size=MEM_WORD, uses_rs1=1, uses_rd=1,
                        reg_write=1, wb_sel=WB_MEM)


@cocotb.test()
async def test_c_swsp_expands_to_sw(dut):
    """c.swsp rs2, offset == `sw rs2, offset(x2)`."""
    eff = await expanded(dut, C_SWSP_S1_8_SP)
    assert eff == 0x00912423, "c.swsp s1,8(sp) expanded to %08x, expected 0x00912423" % eff
    assert (eff_opcode(eff), eff_rs1(eff), eff_rs2(eff), eff_imm_s(eff)) == (
        OP_STORE, 2, 9, 8
    ), "expanded word is not `sw x9, 8(x2)`: %08x" % eff
    await expect_fields(dut, C_SWSP_S1_8_SP, "c.swsp s1,8(sp)", alu_op=ALU_ADD,
                        op1_sel=OP1_RS1, op2_sel=OP2_IMM, imm_sel=IMM_S,
                        mem_write=1, mem_size=MEM_WORD, uses_rs1=1, uses_rs2=1,
                        reg_write=0)


@cocotb.test()
async def test_c_jr_expands_to_jalr_x0(dut):
    """c.jr rs1 == `jalr x0, 0(rs1)`: rd is discarded, so it is a plain jump."""
    eff = await expanded(dut, C_JR_RA)
    assert eff == 0x00008067, "c.jr ra expanded to %08x, expected 0x00008067" % eff
    assert (eff_opcode(eff), eff_rd(eff), eff_rs1(eff), eff_imm_i(eff)) == (
        OP_JALR, 0, 1, 0
    ), "expanded word is not `jalr x0, 0(x1)`: %08x" % eff
    await expect_fields(dut, C_JR_RA, "c.jr ra", op2_sel=OP2_IMM, imm_sel=IMM_I,
                        is_jalr=1, uses_rs1=1, uses_rd=1, reg_write=1, wb_sel=WB_PC4)


@cocotb.test()
async def test_c_jalr_expands_to_jalr_x1(dut):
    """c.jalr rs1 == `jalr x1, 0(rs1)`."""
    eff = await expanded(dut, C_JALR_RA)
    assert eff == 0x000080E7, "c.jalr ra expanded to %08x, expected 0x000080E7" % eff
    assert (eff_opcode(eff), eff_rd(eff), eff_rs1(eff)) == (OP_JALR, 1, 1), (
        "expanded word is not `jalr x1, 0(x1)`: %08x" % eff
    )
    await expect_fields(dut, C_JALR_RA, "c.jalr ra", imm_sel=IMM_I, is_jalr=1,
                        uses_rs1=1, uses_rd=1, reg_write=1, wb_sel=WB_PC4)


@cocotb.test()
async def test_c_mv_expands_to_add_rd_x0_rs2(dut):
    """c.mv rd, rs2 == `add rd, x0, rs2` (a copy through x0)."""
    eff = await expanded(dut, C_MV_T0_T1)
    assert eff == 0x006002B3, "c.mv t0,t1 expanded to %08x, expected 0x006002B3" % eff
    assert (eff_opcode(eff), eff_rd(eff), eff_rs1(eff), eff_rs2(eff)) == (
        OP_OP, 5, 0, 6
    ), "expanded word is not `add x5, x0, x6`: %08x" % eff
    await expect_fields(dut, C_MV_T0_T1, "c.mv t0,t1", alu_op=ALU_ADD,
                        op2_sel=OP2_RS2, uses_rs2=1, uses_rd=1, reg_write=1)


@cocotb.test()
async def test_c_add_expands_to_add_rd_rd_rs2(dut):
    """c.add rd, rs2 == `add rd, rd, rs2`."""
    eff = await expanded(dut, C_ADD_T0_T1)
    assert eff == 0x006282B3, "c.add t0,t1 expanded to %08x, expected 0x006282B3" % eff
    assert (eff_opcode(eff), eff_rd(eff), eff_rs1(eff), eff_rs2(eff)) == (
        OP_OP, 5, 5, 6
    ), "expanded word is not `add x5, x5, x6`: %08x" % eff
    await expect_fields(dut, C_ADD_T0_T1, "c.add t0,t1", alu_op=ALU_ADD,
                        op2_sel=OP2_RS2, uses_rs1=1, uses_rs2=1, uses_rd=1,
                        reg_write=1)


@cocotb.test()
async def test_c_ebreak_expands_to_ebreak_which_is_illegal(dut):
    """c.ebreak expands to EBREAK, which the base decoder already rejects.

    There is no trap machinery in phase 1, so this is illegal like ECALL; the
    point is that the expander produces the real EBREAK word (not 0), so the
    illegal verdict comes from the base decoder's SYSTEM arm.
    """
    eff = await expanded(dut, C_EBREAK)
    assert eff == 0x00100073, "c.ebreak expanded to %08x, expected 0x00100073" % eff
    await expect_illegal(dut, C_EBREAK, "c.ebreak")


@cocotb.test()
async def test_quadrant2_reserved_and_rv64_forms_are_illegal(dut):
    """Reserved encodings and the RV64 / F/D stack forms must not decode."""
    # reserved: c.jr x0; c.lwsp x0; c.slli with shamt[5] == 1
    await expect_illegal(dut, 0x8002, "c.jr x0")
    await expect_illegal(dut, 0x4002, "c.lwsp x0, 0(sp)")
    await expect_illegal(dut, 0x148E, "c.slli s1, shamt[5] set")
    # RV64 / D: C.FLDSP, C.LDSP, C.FSDSP, C.SDSP
    await expect_illegal(dut, 0x2002, "C.FLDSP")
    await expect_illegal(dut, 0x6002, "C.LDSP")
    await expect_illegal(dut, 0xA002, "C.FSDSP")
    await expect_illegal(dut, 0xE002, "C.SDSP")


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

    The shapes are: rs1+rs2 (OP, branches), rs1+imm (OP-IMM, loads, JALR,
    and *stores*), pc+pc (AUIPC), pc+imm (JAL), and zero+imm (LUI).

    A store looks like it mixes two shapes - its address is rs1+imm, its data is
    rs2 - but it does not, because the data never goes through the ALU:
    `ex_stage` takes it off `ex_rs2_data` directly. So a store is plain rs1+imm.
    Selecting rs2 here is not a harmless choice: the `lsu` is handed the ALU
    result as the access address, so it would store to rs1+rs2 and the address
    check would usually reject the access outright.
    """
    for word, op1, op2, name in (
        (ADD, OP1_RS1, OP2_RS2, "ADD"),
        (BEQ, OP1_RS1, OP2_RS2, "BEQ"),
        (SW, OP1_RS1, OP2_IMM, "SW"),
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

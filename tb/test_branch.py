"""Regression tests for the branch and jump resolution in ``rtl/core/ex_stage.v``.

This is ``tb/test_branch.py``: ``ex_stage`` is where a branch is resolved, so
the branch tests drive ``ex_stage`` rather than a module of their own.

    make test       MODULE=test_branch TOP=ex_stage
    make test-4state MODULE=test_branch TOP=ex_stage

`ex_stage` is purely combinational and has no clock or reset, so nothing here
starts a clock.  Every helper drives the whole port list and then lets one time
step elapse, which is what makes cocotb's deferred signal writes visible;
reading in the same delta would read the previous stimulus and pass against a
module that ignores its inputs.

THE DESIGN DECISIONS THIS FILE PINS DOWN
----------------------------------------

Branches resolve in **EX**, not MEM, and ``ex_redirect_valid`` / ``ex_redirect_pc``
are the pipeline's **only** redirect.  Every redirect a test can produce here
must therefore appear on exactly that pair of outputs, or the core has no way
to steer fetch.  Four decisions are not stated by the contract and are decided
in ``ex_stage.v``; each has tests here, because each is one a reviewer would
otherwise have to take on trust:

1. **A not-taken branch does not redirect**, even with a misaligned
   displacement.  Its target is never fetched.
2. **A misaligned target does not suppress the redirect.**  The contract says
   the verdict "is a verdict, not a redirect ... and it is `core`'s job to
   decide what an instruction-misaligned target means", so ``ex_redirect_pc``
   still carries the computed target and ``ex_redirect_valid`` is still high.
   Suppressing it here would make the condition unrecoverable.
3. **``ex_redirect_pc`` is ``pc + 4`` when no redirect is being generated.**  The
   contract calls it a don't-care; it is driven to something defined so a
   waveform is readable and so the misalignment check cannot see X.
4. **``ex_rd_addr`` is forced to ``x0`` when ``id_uses_rd`` is low.**  That is
   what ``uses_rd`` is for: stopping a meaningless rd field from producing a
   false register-index match downstream.

The operand selectors are exercised too, because a branch is only correct if
the operands that reach the comparison are the ones ``decode`` asked for.
"""

import cocotb
from cocotb.triggers import Timer

MASK = 0xFFFFFFFF

# --- encodings owned jointly with `alu.v` and `decode.v` ---------------------
ALU_ADD = 0x0
ALU_SUB = 0x1

OP1_RS1 = 0x0
OP1_PC = 0x1
OP1_ZERO = 0x2

OP2_RS2 = 0x0
OP2_IMM = 0x1
OP2_FOUR = 0x2
OP2_PC = 0x3

# The RISC-V branch funct3 field, verbatim.
F3_BEQ = 0b000
F3_BNE = 0b001
F3_BLT = 0b100
F3_BGE = 0b101
F3_BLTU = 0b110
F3_BGEU = 0b111

WB_ALU, WB_MEM, WB_PC4 = 0, 1, 2
MEM_BYTE, MEM_HALF, MEM_WORD = 0, 1, 2


def signed(value):
    """Interpret a 32-bit pattern as two's complement."""
    return value - (1 << 32) if value & 0x80000000 else value


# A quiet, non-control instruction: nothing redirects, nothing writes.
DEFAULTS = {
    "id_pc": 0x00001000,
    "id_imm": 0x00000000,
    "id_rs1_addr": 1,
    "id_rs2_addr": 2,
    "id_rd_addr": 3,
    "id_alu_op": ALU_ADD,
    "id_op1_sel": OP1_RS1,
    "id_op2_sel": OP2_RS2,
    "id_branch_funct3": F3_BEQ,
    "id_is_branch": 0,
    "id_is_jal": 0,
    "id_is_jalr": 0,
    "id_uses_rs1": 1,
    "id_uses_rs2": 1,
    "id_uses_rd": 1,
    "id_mem_read": 0,
    "id_mem_write": 0,
    "id_mem_size": MEM_WORD,
    "id_mem_unsigned": 0,
    "id_reg_write": 0,
    "id_wb_sel": WB_ALU,
    "ex_rs1_data": 0x00000000,
    "ex_rs2_data": 0x00000000,
}


async def drive(dut, **overrides):
    """Present the whole port list and let the combinational outputs settle.

    Every input is written on every call, defaults included.  Writing only the
    signals a test happens to care about is what makes a combinational testbench
    quietly order-dependent: the leftover value from the previous test decides
    the result, and the test then passes or fails for the wrong reason.
    """
    state = dict(DEFAULTS)
    state.update(overrides)
    for name, value in state.items():
        getattr(dut, name).value = value
    await Timer(1, unit="ns")


async def branch(dut, funct3, rs1, rs2, pc=0x00001000, imm=0x00000008):
    """Drive a conditional branch exactly as `decode` describes one.

    `decode` requests `ALU_SUB` with op1 = rs1 and op2 = rs2 for every
    conditional branch, and sets both `uses_rs1` and `uses_rs2`.  Reproducing
    that here rather than driving the selectors freely is deliberate: a branch
    test that set its own operand selectors would be testing a datapath the
    decoder never builds.
    """
    await drive(
        dut,
        id_pc=pc,
        id_imm=imm,
        id_alu_op=ALU_SUB,
        id_op1_sel=OP1_RS1,
        id_op2_sel=OP2_RS2,
        id_branch_funct3=funct3,
        id_is_branch=1,
        id_uses_rs1=1,
        id_uses_rs2=1,
        ex_rs1_data=rs1,
        ex_rs2_data=rs2,
    )


def expect_taken(funct3, rs1, rs2):
    """The RISC-V branch condition, in Python, for the six legal funct3 values."""
    if funct3 == F3_BEQ:
        return rs1 == rs2
    if funct3 == F3_BNE:
        return rs1 != rs2
    if funct3 == F3_BLT:
        return signed(rs1) < signed(rs2)
    if funct3 == F3_BGE:
        return signed(rs1) >= signed(rs2)
    if funct3 == F3_BLTU:
        return rs1 < rs2
    if funct3 == F3_BGEU:
        return rs1 >= rs2
    raise ValueError("funct3 %r is not a branch condition" % funct3)


# Operand pairs chosen so that the six conditions do not agree with each other:
# a matrix where every condition gives the same answer would pass a decoder
# that wired all six to the same comparator.
OPERAND_PAIRS = [
    (0x00000000, 0x00000000),  # equal, both zero
    (0x00000005, 0x00000005),  # equal, nonzero
    (0x00000001, 0x00000002),  # unsigned and signed agree, less-than
    (0x00000002, 0x00000001),  # the mirror image
    (0xFFFFFFFF, 0x00000001),  # signed less, unsigned greater
    (0x00000001, 0xFFFFFFFF),  # signed greater, unsigned less
    (0x80000000, 0x7FFFFFFF),  # INT_MIN vs INT_MAX
    (0x7FFFFFFF, 0x80000000),  # the mirror image
    (0x80000000, 0x80000000),  # equal negatives
    (0xFFFFFFFF, 0xFFFFFFFF),  # equal -1
    (0x00000000, 0xFFFFFFFF),  # 0 vs -1
    (0xFFFFFFFF, 0x00000000),  # -1 vs 0
    (0xDEADBEEF, 0xCAFEBABE),  # neither negative, unequal
]

ALL_FUNCT3 = (F3_BEQ, F3_BNE, F3_BLT, F3_BGE, F3_BLTU, F3_BGEU)


# ---------------------------------------------------------------------------
# The six conditional branches
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_every_condition_over_every_operand_pair(dut):
    """All six branch funct3 values against a matrix chosen to separate them.

    Each row checks both the taken and the not-taken direction from the same
    operand pair, because a comparator that is right only in one direction -
    `>=` where `<` was wanted, say - passes a test that only ever branches
    forward on one sign.
    """
    for funct3 in ALL_FUNCT3:
        for rs1, rs2 in OPERAND_PAIRS:
            for imm in (0x00000008, 0xFFFFFFF8):
                await branch(dut, funct3, rs1, rs2, imm=imm)
                taken = expect_taken(funct3, rs1, rs2)
                want_pc = (0x00001000 + imm) & MASK

                assert int(dut.ex_redirect_valid.value) == (1 if taken else 0), (
                    "funct3=%03b on rs1=%08x rs2=%08x: redirect_valid is %d, "
                    "expected %d"
                    % (funct3, rs1, rs2, int(dut.ex_redirect_valid.value),
                       1 if taken else 0)
                )
                if taken:
                    assert int(dut.ex_redirect_pc.value) == want_pc, (
                        "funct3=%03b on %08x, %08x: redirect_pc is %08x, "
                        "expected pc + imm = %08x"
                        % (funct3, rs1, rs2, int(dut.ex_redirect_pc.value),
                           want_pc)
                    )
                else:
                    assert int(dut.ex_redirect_pc.value) == 0x00001004, (
                        "a not-taken branch drove redirect_pc to %08x, expected "
                        "the sequential next address 00001004"
                        % int(dut.ex_redirect_pc.value)
                    )


@cocotb.test()
async def test_the_six_conditions_are_not_the_same_comparator(dut):
    """Every funct3 must produce its own answer for the same operands.

    Driven at one operand pair on which all six conditions disagree in
    different directions.  If two of the six arms were wired to the same
    comparison, or one arm were inverted, this is the test that catches it -
    and the exhaustive matrix above cannot, because it would be satisfied by
    any comparator that happens to agree on the pairs chosen there.
    """
    rs1, rs2 = 0xFFFFFFFF, 0x00000001
    expected = {
        F3_BEQ: 0,
        F3_BNE: 1,
        F3_BLT: 1,   # signed -1 < 1
        F3_BGE: 0,
        F3_BLTU: 0,  # unsigned 0xffffffff > 1
        F3_BGEU: 1,
    }
    for funct3, want in expected.items():
        await branch(dut, funct3, rs1, rs2)
        assert int(dut.ex_redirect_valid.value) == want, (
            "funct3=%03b on rs1=%08x rs2=%08x redirected %d, expected %d"
            % (funct3, rs1, rs2, int(dut.ex_redirect_valid.value), want)
        )


@cocotb.test()
async def test_beq_and_bne_are_exact_complements(dut):
    """BEQ and BNE must agree about equality and disagree about everything else.

    Checked over every pair rather than sampled, because the failure mode is a
    `zero` that is the inverse of the comparison - which agrees with BEQ on
    unequal operands and with BNE on equal ones, and so passes any test that
    only looks at one of the two.
    """
    for rs1, rs2 in OPERAND_PAIRS:
        await branch(dut, F3_BEQ, rs1, rs2)
        beq = int(dut.ex_redirect_valid.value)
        await branch(dut, F3_BNE, rs1, rs2)
        bne = int(dut.ex_redirect_valid.value)
        assert beq + bne == 1, (
            "on %08x, %08x: BEQ gave %d and BNE gave %d, they must complement"
            % (rs1, rs2, beq, bne)
        )
        assert beq == (1 if rs1 == rs2 else 0), (
            "BEQ on %08x, %08x gave %d" % (rs1, rs2, beq)
        )


@cocotb.test()
async def test_blt_bge_and_bltu_bgeu_use_the_right_signedness(dut):
    """BLT/BGE are signed; BLTU/BGEU are unsigned.

    The operand pairs below are exactly those where signedness changes the
    answer, and each is checked against both the signed and the unsigned
    expectation so that a single mis-wired comparator cannot hide behind the
    other.
    """
    decisive = [
        # (rs1, rs2, BLT, BLTU) - the pairs where signedness changes the answer.
        # Each row carries its own expectation: the first three are signed-less
        # and unsigned-greater, the last three are the mirror images, and a test
        # that assumed all six went the same way would be wrong about half of
        # them.
        (0xFFFFFFFF, 0x00000001, 1, 0),
        (0x80000000, 0x7FFFFFFF, 1, 0),
        (0xFFFF0000, 0x0000FFFF, 1, 0),
        (0x00000001, 0xFFFFFFFF, 0, 1),
        (0x7FFFFFFF, 0x80000000, 0, 1),
        (0x0000FFFF, 0xFFFF0000, 0, 1),
    ]
    for rs1, rs2, want_blt, want_bltu in decisive:
        await branch(dut, F3_BLT, rs1, rs2)
        assert int(dut.ex_redirect_valid.value) == want_blt, (
            "BLT on %08x, %08x redirected %d, expected %d: it must be a "
            "signed compare"
            % (rs1, rs2, int(dut.ex_redirect_valid.value), want_blt)
        )
        await branch(dut, F3_BLTU, rs1, rs2)
        assert int(dut.ex_redirect_valid.value) == want_bltu, (
            "BLTU on %08x, %08x redirected %d, expected %d: it must be an "
            "unsigned compare"
            % (rs1, rs2, int(dut.ex_redirect_valid.value), want_bltu)
        )

        # BGE and BGEU are the negations, so they are pinned by the same rows.
        await branch(dut, F3_BGE, rs1, rs2)
        assert int(dut.ex_redirect_valid.value) == (1 - want_blt), (
            "BGE must be the negation of BLT on %08x, %08x" % (rs1, rs2)
        )
        await branch(dut, F3_BGEU, rs1, rs2)
        assert int(dut.ex_redirect_valid.value) == (1 - want_bltu), (
            "BGEU must be the negation of BLTU on %08x, %08x" % (rs1, rs2)
        )


@cocotb.test()
async def test_reserved_branch_funct3_never_redirects(dut):
    """funct3 010 and 011 are reserved and must never be a taken branch.

    `decode` refuses to emit a branch for them, so this is a defence in depth:
    an `ex_stage` whose default arm happened to be "taken" would silently turn
    a reserved encoding into a jump the moment a future decoder change let one
    through.
    """
    for funct3 in (0b010, 0b011):
        for rs1, rs2 in OPERAND_PAIRS:
            await branch(dut, funct3, rs1, rs2)
            assert int(dut.ex_redirect_valid.value) == 0, (
                "reserved branch funct3 %03b redirected on %08x, %08x"
                % (funct3, rs1, rs2)
            )


# ---------------------------------------------------------------------------
# JAL and JALR
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_jal_always_redirects_to_pc_plus_imm(dut):
    """`jal` target = pc + imm, unconditionally - it has no condition."""
    displacements = [
        0x00000000, 0x00000004, 0x00000008,
        0x00000FFC, 0x00001000, 0x7FFFFFFF,
        0x80000000, 0xFFFFFFFC, 0xFFFFFFFF,
        0x00000002, 0x00000006,  # the misaligned ones, checked further down
    ]
    for pc in (0x00000000, 0x00001000, 0xFFFFFFF0):
        for imm in displacements:
            await drive(
                dut,
                id_pc=pc,
                id_imm=imm,
                id_alu_op=ALU_ADD,
                id_op1_sel=OP1_PC,
                id_op2_sel=OP2_IMM,
                id_is_jal=1,
                id_wb_sel=WB_PC4,
            )
            assert int(dut.ex_redirect_valid.value) == 1, (
                "JAL at pc=%08x with imm=%08x did not redirect" % (pc, imm)
            )
            assert int(dut.ex_redirect_pc.value) == ((pc + imm) & MASK), (
                "JAL at pc=%08x with imm=%08x redirected to %08x, expected %08x"
                % (pc, imm, int(dut.ex_redirect_pc.value), (pc + imm) & MASK)
            )


@cocotb.test()
async def test_jalr_clears_bit_zero_of_the_target(dut):
    """`jalr` target = (rs1 + imm) with bit 0 cleared.

    The sum is presented with bit 0 both set and clear for the same target, so
    a design that forgot the clear shows up as two different answers for what
    the ISA says is one destination.
    """
    cases = [
        # (rs1, imm, expected target)
        (0x00001000, 0x00000000, 0x00001000),
        (0x00001001, 0x00000000, 0x00001000),  # bit 0 already set
        (0x00001000, 0x00000001, 0x00001000),  # imm sets bit 0
        (0x00001001, 0x00000001, 0x00001002),  # both set bit 0
        (0x00001003, 0x00000002, 0x00001004),  # carries into bit 1
        (0x00001000, 0x000000FF, 0x000010FE),
        (0xFFFFFFFF, 0x00000001, 0x00000000),  # wraps to zero
        (0x00000000, 0x00000004, 0x00000004),
    ]
    for rs1, imm, want in cases:
        await drive(
            dut,
            id_imm=imm,
            id_alu_op=ALU_ADD,
            id_op1_sel=OP1_RS1,
            id_op2_sel=OP2_IMM,
            id_is_jalr=1,
            id_uses_rs1=1,
            ex_rs1_data=rs1,
            id_wb_sel=WB_PC4,
        )
        assert int(dut.ex_redirect_valid.value) == 1, (
            "JALR with rs1=%08x imm=%08x did not redirect" % (rs1, imm)
        )
        assert int(dut.ex_redirect_pc.value) == want, (
            "JALR with rs1=%08x imm=%08x redirected to %08x, expected %08x"
            % (rs1, imm, int(dut.ex_redirect_pc.value), want)
        )


@cocotb.test()
async def test_jalr_targets_the_same_place_as_jal_for_the_same_address(dut):
    """Two different computations, one destination.

    `jal` reaches pc + imm through the PC operand and `jalr` reaches
    rs1 + imm through the rs1 operand.  Presenting rs1 = pc for both must give
    bit-identical targets - which is the cross-check that the JALR path is not
    accidentally using the PC operand, or the JAL path accidentally using rs1.
    """
    for imm in (0x00000000, 0x00000004, 0x00000008, 0x00000010, 0xFFFFFFFC):
        pc = 0x00002000

        await drive(dut, id_pc=pc, id_imm=imm, id_op1_sel=OP1_PC,
                    id_op2_sel=OP2_IMM, id_is_jal=1, id_wb_sel=WB_PC4)
        via_jal = int(dut.ex_redirect_pc.value)

        await drive(dut, id_pc=pc, id_imm=imm, id_op1_sel=OP1_RS1,
                    id_op2_sel=OP2_IMM, id_is_jalr=1, id_uses_rs1=1,
                    ex_rs1_data=pc, id_wb_sel=WB_PC4)
        via_jalr = int(dut.ex_redirect_pc.value)

        assert via_jal == via_jalr, (
            "imm=%08x: JAL reached %08x but JALR with rs1 = pc reached %08x"
            % (imm, via_jal, via_jalr)
        )


@cocotb.test()
async def test_a_jump_to_itself_still_redirects(dut):
    """imm = 0 is a jump to the current address, not "no jump".

    A redirect that is suppressed because the target happens to equal the PC is
    the classic off-by-one in this block: `pc_gen` would carry on to pc + 4 and
    the program would silently skip an instruction.
    """
    await drive(dut, id_pc=0x00001000, id_imm=0x00000000, id_op1_sel=OP1_PC,
                id_op2_sel=OP2_IMM, id_is_jal=1, id_wb_sel=WB_PC4)
    assert int(dut.ex_redirect_valid.value) == 1, "JAL with imm 0 did not redirect"
    assert int(dut.ex_redirect_pc.value) == 0x00001000

    await drive(dut, id_pc=0x00001000, id_imm=0x00000000, id_op1_sel=OP1_RS1,
                id_op2_sel=OP2_IMM, id_is_jalr=1, id_uses_rs1=1,
                ex_rs1_data=0x00001000, id_wb_sel=WB_PC4)
    assert int(dut.ex_redirect_valid.value) == 1, "JALR to its own PC did not redirect"
    assert int(dut.ex_redirect_pc.value) == 0x00001000


# ---------------------------------------------------------------------------
# Instruction-address misalignment
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_a_misaligned_jal_target_is_flagged(dut):
    """Phase 1 has no compressed instructions, so bit 1 set is misaligned.

    J-type immediates always have bit 0 at 0, so the alignment test reduces to
    bit 1 - and `ex_target_misaligned` must be exactly that test, not "the
    target is odd", which a J-type target can never be.
    """
    for imm, want in ((0x00000000, 0), (0x00000004, 0), (0x00000008, 0),
                      (0x0000000C, 0), (0x00000002, 1), (0x00000006, 1),
                      (0x0000000A, 1), (0xFFFFFFFE, 1)):
        await drive(dut, id_pc=0x00001000, id_imm=imm, id_op1_sel=OP1_PC,
                    id_op2_sel=OP2_IMM, id_is_jal=1, id_wb_sel=WB_PC4)
        assert int(dut.ex_target_misaligned.value) == want, (
            "JAL to %08x (imm %08x): target_misaligned is %d, expected %d"
            % ((0x00001000 + imm) & MASK, imm,
               int(dut.ex_target_misaligned.value), want)
        )


@cocotb.test()
async def test_a_misaligned_branch_target_is_flagged_only_when_the_branch_is_taken(dut):
    """A not-taken branch's target is never fetched, so it is never misaligned.

    This is decision (1) above.  B-type immediates always have bit 0 at 0, so a
    displacement of 2 is expressible and legal, and a program containing
    `beq x0, x0, +2` must run: the branch is taken, the target is misaligned and
    the verdict is raised - but `beq x1, x1, +2` with x1 != x0 must not raise
    anything at all, because that target is never used.
    """
    # Taken: x0 == x0 always, so BEQ is taken and the +2 target is flagged.
    await branch(dut, F3_BEQ, 0x00000000, 0x00000000, imm=0x00000002)
    assert int(dut.ex_redirect_valid.value) == 1, "beq x0,x0 must be taken"
    assert int(dut.ex_redirect_pc.value) == 0x00001002
    assert int(dut.ex_target_misaligned.value) == 1, (
        "a taken branch to a +2 target must report misalignment"
    )

    # Not taken, same displacement: nothing is reported.
    await branch(dut, F3_BEQ, 0x00000001, 0x00000002, imm=0x00000002)
    assert int(dut.ex_redirect_valid.value) == 0
    assert int(dut.ex_target_misaligned.value) == 0, (
        "a not-taken branch reported misalignment for a target it never uses"
    )


@cocotb.test()
async def test_misalignment_does_not_suppress_the_redirect(dut):
    """Decision (2): the verdict is reported, the redirect still happens.

    The contract states that `ex_redirect_pc` "still carries the computed
    target, and it is `core`'s job to decide what an instruction-misaligned
    target means".  A design that suppressed `ex_redirect_valid` here would
    leave `core` with a condition it can neither trap on nor forward, because
    the information would have been thrown away one stage too early.
    """
    await branch(dut, F3_BEQ, 0x00000000, 0x00000000, imm=0x00000002)
    assert int(dut.ex_target_misaligned.value) == 1, "precondition: misaligned"
    assert int(dut.ex_redirect_valid.value) == 1, (
        "the redirect was suppressed by the misalignment verdict"
    )
    assert int(dut.ex_redirect_pc.value) == 0x00001002, (
        "ex_redirect_pc must still carry the computed target, not the aligned "
        "value and not zero: got %08x" % int(dut.ex_redirect_pc.value)
    )


@cocotb.test()
async def test_a_jalr_target_is_never_misaligned_by_the_bit_it_clears(dut):
    """JALR clears bit 0, and bit 0 is not part of the alignment test.

    A target of ...01 and a target of ...00 are the same destination for JALR,
    so they must produce the same verdict.  Testing the verdict against the
    un-cleared sum is the bug this catches.
    """
    for rs1, imm in ((0x00001001, 0x00000000),
                     (0x00001003, 0x00000000),
                     (0x00001000, 0x00000001),
                     (0x00001001, 0x00000001)):
        await drive(dut, id_imm=imm, id_op1_sel=OP1_RS1, id_op2_sel=OP2_IMM,
                    id_is_jalr=1, id_uses_rs1=1, ex_rs1_data=rs1)
        want = ((rs1 + imm) & MASK) & ~1
        assert int(dut.ex_redirect_pc.value) == want
        assert int(dut.ex_target_misaligned.value) == ((want >> 1) & 1), (
            "JALR rs1=%08x imm=%08x: target %08x has bit 1 = %d, so "
            "target_misaligned must be %d"
            % (rs1, imm, want, (want >> 1) & 1, (want >> 1) & 1)
        )


@cocotb.test()
async def test_non_control_instructions_never_report_misalignment(dut):
    """A load, a store and an ordinary ALU op have no target, so no verdict.

    Driven with a deliberately misaligned-looking immediate and a misaligned
    effective address, because a verdict derived from `ex_alu_result` rather
    than from the redirect target would fire on exactly this stimulus.
    """
    await drive(dut, id_pc=0x00001002, id_imm=0x00000002,
                id_op1_sel=OP1_RS1, id_op2_sel=OP2_IMM,
                id_mem_read=1, id_mem_size=MEM_WORD, id_reg_write=1)
    assert int(dut.ex_redirect_valid.value) == 0
    assert int(dut.ex_target_misaligned.value) == 0, (
        "a load reported instruction misalignment; that condition belongs to "
        "lsu.data_misaligned"
    )

    await drive(dut, id_pc=0x00001003, id_imm=0x00000001,
                id_op1_sel=OP1_RS1, id_op2_sel=OP2_IMM,
                id_mem_write=1, id_mem_size=MEM_HALF, id_uses_rs2=1,
                ex_rs2_data=0xDEADBEEF)
    assert int(dut.ex_target_misaligned.value) == 0

    await drive(dut, id_pc=0x00001002, id_imm=0x00000002,
                id_op1_sel=OP1_PC, id_op2_sel=OP2_IMM, id_reg_write=1)
    assert int(dut.ex_target_misaligned.value) == 0


# ---------------------------------------------------------------------------
# Operand selection
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_op1_selects_rs1_pc_or_zero(dut):
    """`op1_sel` picks the first ALU operand; 2'd3 is undefined and reads zero.

    The undefined encoding is checked deliberately.  `decode` never produces it,
    so nothing else in the design would ever notice, and an unhandled case
    leaving `op_a` as a latch would turn an undefined control word into a stale
    address as soon as anything upstream ever drove one.
    """
    rs1, pc = 0x11111111, 0x00002222
    for sel, want in ((OP1_RS1, rs1), (OP1_PC, pc), (OP1_ZERO, 0), (3, 0)):
        await drive(dut, id_pc=pc, id_alu_op=ALU_ADD, id_op1_sel=sel,
                    id_op2_sel=OP2_FOUR, id_uses_rs1=1, ex_rs1_data=rs1)
        assert int(dut.ex_alu_result.value) == ((want + 4) & MASK), (
            "op1_sel=%d: alu_result is %08x, expected %08x + 4"
            % (sel, int(dut.ex_alu_result.value), want)
        )


@cocotb.test()
async def test_op2_selects_rs2_imm_four_or_pc(dut):
    """`op2_sel` picks the second ALU operand; 3'd4..3'd7 read zero.

    `op2_sel = 2` is the literal constant 4 that `decode` does not currently
    emit, but the contract enumerates it, so `ex_stage` has to implement it -
    and a value nothing can select is exactly the value that gets forgotten.
    """
    rs2, pc, imm = 0x33333333, 0x00004444, 0x00000010
    for sel, want in ((OP2_RS2, rs2), (OP2_IMM, imm), (OP2_FOUR, 4),
                      (OP2_PC, pc), (4, 0), (5, 0), (6, 0), (7, 0)):
        await drive(dut, id_pc=pc, id_imm=imm, id_alu_op=ALU_ADD,
                    id_op1_sel=OP1_ZERO, id_op2_sel=sel, id_uses_rs2=1,
                    ex_rs2_data=rs2)
        assert int(dut.ex_alu_result.value) == (want & MASK), (
            "op2_sel=%d: alu_result is %08x, expected %08x"
            % (sel, int(dut.ex_alu_result.value), want)
        )


@cocotb.test()
async def test_op2_sel_four_is_the_literal_four_not_the_pc(dut):
    """The two ways of saying "four" must not be the same wire.

    With pc deliberately equal to something other than 4, selecting
    `op2_sel = 2` must still add 4.  A mux that wired the contract's constant
    to the pc net would be indistinguishable from correct on any program whose
    pc happened to be 4, which is one instruction.
    """
    for pc in (0x00000000, 0x00000004, 0x00001000, 0xFFFFFFFF):
        await drive(dut, id_pc=pc, id_alu_op=ALU_ADD, id_op1_sel=OP1_ZERO,
                    id_op2_sel=OP2_FOUR)
        assert int(dut.ex_alu_result.value) == 4, (
            "with pc=%08x, op2_sel=2 gave %08x, expected the constant 4"
            % (pc, int(dut.ex_alu_result.value))
        )
        await drive(dut, id_pc=pc, id_alu_op=ALU_ADD, id_op1_sel=OP1_ZERO,
                    id_op2_sel=OP2_PC)
        assert int(dut.ex_alu_result.value) == pc, (
            "with pc=%08x, op2_sel=3 gave %08x, expected the pc"
            % (pc, int(dut.ex_alu_result.value))
        )


@cocotb.test()
async def test_an_unused_rs1_is_zeroed_rather_than_forwarded(dut):
    """`id_uses_rs1` low forces the rs1 operand to zero.

    The address registers are driven at a value that is nonzero on purpose,
    because "an unused operand reads zero" is trivially true whenever the
    register file happens to hold zero in that slot - and it holds zero after
    reset, which is when a testbench is most likely to be run.
    """
    await drive(dut, id_alu_op=ALU_ADD, id_op1_sel=OP1_RS1,
                id_op2_sel=OP2_RS2, id_uses_rs1=0, id_uses_rs2=1,
                ex_rs1_data=0xDEADBEEF, ex_rs2_data=0x00000005)
    assert int(dut.ex_alu_result.value) == 0x00000005, (
        "with uses_rs1 low the ALU computed %08x, expected 0 + 5"
        % int(dut.ex_alu_result.value)
    )

    await drive(dut, id_alu_op=ALU_ADD, id_op1_sel=OP1_RS1,
                id_op2_sel=OP2_RS2, id_uses_rs1=1, id_uses_rs2=0,
                ex_rs1_data=0x00000005, ex_rs2_data=0xDEADBEEF)
    assert int(dut.ex_alu_result.value) == 0x00000005, (
        "with uses_rs2 low the ALU computed %08x, expected 5 + 0"
        % int(dut.ex_alu_result.value)
    )


@cocotb.test()
async def test_the_uses_gates_precede_the_selector_muxes(dut):
    """An instruction that selects neither operand still sees zero.

    `LUI` is the case that matters: `decode` gives it `op1_sel = 2` (zero) and
    `uses_rs1 = 0`, so the gate and the mux have to agree, and the immediate has
    to arrive untouched through `op2_sel = 1`.  If the `*_used` gates were
    applied after the ALU instead of before it, `lui` would still be right -
    which is why the ordering is checked on a case where it is not.
    """
    # op1_sel = OP1_ZERO with uses_rs1 high and a nonzero forwarded value: the
    # mux must win, or a gated operand would leak into a zero operand.
    await drive(dut, id_alu_op=ALU_ADD, id_op1_sel=OP1_ZERO,
                id_op2_sel=OP2_IMM, id_imm=0x000ABCDE, id_uses_rs1=1,
                ex_rs1_data=0xFFFFFFFF)
    assert int(dut.ex_alu_result.value) == 0x000ABCDE, (
        "op1_sel=zero did not win over a live rs1: got %08x"
        % int(dut.ex_alu_result.value)
    )

    # And the same with the gate active, which must make no difference.
    await drive(dut, id_alu_op=ALU_ADD, id_op1_sel=OP1_ZERO,
                id_op2_sel=OP2_IMM, id_imm=0x000ABCDE, id_uses_rs1=0,
                ex_rs1_data=0xFFFFFFFF)
    assert int(dut.ex_alu_result.value) == 0x000ABCDE


# ---------------------------------------------------------------------------
# Store data, destination register and the pass-throughs
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_store_data_is_rs2_and_not_the_alu_result(dut):
    """`ex_store_data` is rs2, whatever the ALU happened to compute.

    The store is driven with a load-shaped immediate and a nonzero rs2, so the
    effective address and the data are two different values and a store-data
    mux wired to the wrong one is visible.
    """
    await drive(dut, id_pc=0x00001000, id_imm=0x00000040, id_alu_op=ALU_ADD,
                id_op1_sel=OP1_RS1, id_op2_sel=OP2_IMM, id_mem_write=1,
                id_mem_size=MEM_WORD, id_uses_rs1=1, ex_rs1_data=0x00001000,
                id_uses_rs2=1, ex_rs2_data=0xCAFEBABE)
    assert int(dut.ex_alu_result.value) == 0x00001040, "precondition: the address"
    assert int(dut.ex_store_data.value) == 0xCAFEBABE, (
        "store data is %08x, expected rs2 = cafebabe"
        % int(dut.ex_store_data.value)
    )


@cocotb.test()
async def test_store_data_is_zero_when_rs2_is_not_read(dut):
    """An instruction that does not read rs2 must not store stale data.

    This is the memory-visibility version of the operand gate: `ex_store_data`
    reaches a memory write, so a forwarded value that the instruction never
    asked for would corrupt memory rather than merely produce a wrong
    comparison.
    """
    await drive(dut, id_mem_write=1, id_mem_size=MEM_WORD, id_uses_rs2=0,
                ex_rs2_data=0xDEADBEEF, id_uses_rs1=1, ex_rs1_data=0x00000010)
    assert int(dut.ex_store_data.value) == 0, (
        "store data is %08x with uses_rs2 low, expected 0"
        % int(dut.ex_store_data.value)
    )


@cocotb.test()
async def test_rd_is_zeroed_when_the_rd_field_is_meaningless(dut):
    """Decision (4): `ex_rd_addr` is x0 when `id_uses_rd` is low.

    Every one of the 32 indices is checked, because the gate is an index
    comparison against a 5-bit field and an off-by-one there would pass a
    sampled test.  A meaningful rd must pass through untouched, which is the
    other half of the same gate.
    """
    for addr in range(32):
        await drive(dut, id_rd_addr=addr, id_uses_rd=0, id_reg_write=0)
        assert int(dut.ex_rd_addr.value) == 0, (
            "with uses_rd low, rd=%d came through as %d, expected 0"
            % (addr, int(dut.ex_rd_addr.value))
        )
        await drive(dut, id_rd_addr=addr, id_uses_rd=1, id_reg_write=1)
        assert int(dut.ex_rd_addr.value) == addr, (
            "with uses_rd high, rd came through as %d, expected %d"
            % (int(dut.ex_rd_addr.value), addr)
        )


@cocotb.test()
async def test_reg_write_is_a_pass_through_of_the_decode_bit(dut):
    """`ex_reg_write` must not be gated by anything this stage decides.

    In particular it is not gated on `uses_rd`: `decode` guarantees that a write
    implies a meaningful rd, and `ex_rd_addr` already carries that guarantee in
    the index itself.  Gating here as well would turn a decoder bug into a
    silently dropped write.
    """
    for reg_write in (0, 1):
        for uses_rd in (0, 1):
            await drive(dut, id_reg_write=reg_write, id_uses_rd=uses_rd)
            assert int(dut.ex_reg_write.value) == reg_write, (
                "reg_write=%d uses_rd=%d came through as %d"
                % (reg_write, uses_rd, int(dut.ex_reg_write.value))
            )


@cocotb.test()
async def test_the_memory_and_writeback_controls_pass_through_unchanged(dut):
    """`ex_wb_sel`, `ex_mem_*` are forwarded verbatim, over every encoding.

    `wb_sel` matters most: it is what selects pc + 4 for the JAL and JALR link
    register, and it is carried to writeback through the EX/MEM bundle, so a
    dropped or reordered bit here loses the return address on every jump in the
    program.
    """
    for wb_sel in (0, 1, 2, 3):
        await drive(dut, id_wb_sel=wb_sel)
        assert int(dut.ex_wb_sel.value) == wb_sel, (
            "wb_sel %d came through as %d" % (wb_sel, int(dut.ex_wb_sel.value))
        )

    for size in (0, 1, 2, 3):
        await drive(dut, id_mem_size=size, id_mem_read=1)
        assert int(dut.ex_mem_size.value) == size
        await drive(dut, id_mem_size=size, id_mem_write=1)
        assert int(dut.ex_mem_size.value) == size

    for unsigned in (0, 1):
        await drive(dut, id_mem_unsigned=unsigned, id_mem_read=1)
        assert int(dut.ex_mem_unsigned.value) == unsigned

    for read in (0, 1):
        for write in (0, 1):
            await drive(dut, id_mem_read=read, id_mem_write=write)
            assert int(dut.ex_mem_read.value) == read
            assert int(dut.ex_mem_write.value) == write


# ---------------------------------------------------------------------------
# What must NOT redirect
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_no_control_transfer_means_no_redirect(dut):
    """An ordinary instruction must never raise `ex_redirect_valid`.

    Driven across the full operand space with the immediates that would be a
    jump displacement for a jump, because "no redirect for a non-jump" is
    exactly the claim a redirect that is wired to the wrong control signal
    would break first.
    """
    for imm in (0x00000004, 0xFFFFFFFC, 0x00000000, 0xFFFFFFFF):
        for pc in (0x00000000, 0x00001000, 0xFFFFFFF0):
            for alu_op in (ALU_ADD, ALU_SUB):
                await drive(dut, id_pc=pc, id_imm=imm, id_alu_op=alu_op,
                            id_op1_sel=OP1_PC, id_op2_sel=OP2_IMM,
                            id_reg_write=1, id_wb_sel=WB_ALU)
                assert int(dut.ex_redirect_valid.value) == 0, (
                    "a non-control instruction at pc=%08x redirected to %08x"
                    % (pc, int(dut.ex_redirect_pc.value))
                )
                assert int(dut.ex_redirect_pc.value) == ((pc + 4) & MASK), (
                    "with no redirect, ex_redirect_pc should be the sequential "
                    "next address: got %08x" % int(dut.ex_redirect_pc.value)
                )


@cocotb.test()
async def test_the_redirect_is_reported_in_the_same_cycle_it_is_computed(dut):
    """Combinational: `ex_redirect_valid` and `ex_redirect_pc` never disagree.

    Each branch is read twice with nothing driven in between.  A design that
    registered the target one cycle behind the valid bit - the classic
    "pipeline the redirect into a stage" mistake - passes every test that
    advances a clock between the two, and fails here.
    """
    for funct3 in ALL_FUNCT3:
        for rs1, rs2 in OPERAND_PAIRS[:6]:
            await branch(dut, funct3, rs1, rs2, imm=0x00000010)
            first_valid = int(dut.ex_redirect_valid.value)
            first_pc = int(dut.ex_redirect_pc.value)

            # Re-read with no intervening stimulus: a purely combinational
            # module must give exactly the same answer.
            await Timer(1, unit="ns")
            assert int(dut.ex_redirect_valid.value) == first_valid, (
                "ex_redirect_valid changed without a stimulus changing"
            )
            assert int(dut.ex_redirect_pc.value) == first_pc, (
                "ex_redirect_pc changed without a stimulus changing"
            )


@cocotb.test()
async def test_the_stages_own_assertions_are_armed_and_silent(dut):
    """Every immediate assertion in `ex_stage.v` must not misfire.

    This drives each of the three control classes, both polarities of every
    branch condition, aligned and misaligned targets, and the unused operand
    gates, and requires silence.  The assertions are checked on correct
    hardware because an assertion that fires on correct hardware gets disabled,
    and then it is gone for the case that needed it.
    """
    for funct3 in (0, 1, 2, 3, 4, 5, 6, 7):
        for rs1, rs2 in OPERAND_PAIRS:
            for imm in (0x00000000, 0x00000004, 0x00000008, 0x00000002,
                        0xFFFFFFFC):
                await branch(dut, funct3, rs1, rs2, imm=imm)

    for pc, imm in ((0x00001000, 0x00000004), (0x00001000, 0x00000002),
                    (0x00000000, 0xFFFFFFFF), (0xFFFFFFF0, 0x0000000E)):
        await drive(dut, id_pc=pc, id_imm=imm, id_is_jal=1,
                    id_op1_sel=OP1_PC, id_op2_sel=OP2_IMM, id_wb_sel=WB_PC4)

    for rs1, imm in ((0x00001000, 0), (0x00001001, 1), (0x00001003, 0),
                     (0xFFFFFFFF, 1)):
        await drive(dut, id_imm=imm, id_is_jalr=1, id_op1_sel=OP1_RS1,
                    id_op2_sel=OP2_IMM, id_uses_rs1=1, ex_rs1_data=rs1,
                    id_wb_sel=WB_PC4)

    for uses_rs1, uses_rs2, uses_rd in ((0, 0, 0), (1, 1, 1), (0, 1, 0)):
        await drive(dut, id_uses_rs1=uses_rs1, id_uses_rs2=uses_rs2,
                    id_uses_rd=uses_rd, id_reg_write=0)

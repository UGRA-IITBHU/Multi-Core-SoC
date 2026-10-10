`default_nettype none
// ============================================================================
// ex_stage - execute stage: operand select, ALU, branch and jump resolution.
//
// Purpose: consume the ID/EX operands, produce the memory address, store data
// and destination register, and raise the single redirect that steers fetch.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   id_pc             input  32  PC of the instruction in this stage
//   id_imm            input  32  immediate from `imm_gen`, registered
//   id_rs1_addr       input  5   rs1 index from decode
//   id_rs2_addr       input  5   rs2 index from decode
//   id_rd_addr        input  5   rd index from decode
//   id_alu_op         input  4   ALU operation select
//   id_op1_sel        input  2   first-operand select
//   id_op2_sel        input  3   second-operand select
//   id_branch_funct3  input  3   branch funct3
//   id_is_branch      input  1   conditional branch (BEQ/BNE/BLT/BGE/BLTU/BGEU)
//   id_is_jal         input  1   JAL
//   id_is_jalr        input  1   JALR
//   id_uses_rs1       input  1   instruction reads rs1
//   id_uses_rs2       input  1   instruction reads rs2
//   id_uses_rd        input  1   the rd field is meaningful
//   id_mem_read       input  1   instruction is a load
//   id_mem_write      input  1   instruction is a store
//   id_mem_size       input  2   0 = byte, 1 = half, 2 = word
//   id_mem_unsigned   input  1   load is unsigned
//   id_reg_write      input  1   instruction writes rd
//   id_wb_sel         input  2   writeback source select
//   ex_rs1_data       input  32  rs1 operand after hazard resolution
//   ex_rs2_data       input  32  rs2 operand after hazard resolution
//   ex_alu_result     output 32  ALU result; also the effective load/store address
//   ex_store_data     output 32  value to write on a store
//   ex_rd_addr        output 5   destination register index
//   ex_reg_write      output 1   this instruction writes rd
//   ex_wb_sel         output 2   writeback source select, forwarded to memory
//   ex_mem_read       output 1   this instruction is a load
//   ex_mem_write      output 1   this instruction is a store
//   ex_mem_size       output 2   access size
//   ex_mem_unsigned   output 1   load is unsigned
//   ex_redirect_valid output 1   fetch must redirect this cycle
//   ex_redirect_pc    output 32  redirect target
//   ex_target_misaligned output 1 branch/JAL/JALR target is not 4-byte aligned
//
// Guarantee to `core`, `lsu` and `pc_gen`: `ex_redirect_valid` is the only
// redirect source in the pipeline, and it is resolved in this stage in the
// cycle the branch or jump is in EX, so `pc_gen` has exactly one funnel to
// obey.  Branch and jump resolution needs nothing beyond this port list:
// `id_is_branch` / `id_is_jal` / `id_is_jalr` identify the instruction class,
// `id_branch_funct3` selects the comparison, `id_pc` gives the sequential and
// `pc + 4` target, `id_imm` gives the branch and JAL displacement, `id_alu_op`
// with `id_op1_sel` / `id_op2_sel` gives the address arithmetic, and
// `ex_rs1_data` / `ex_rs2_data` are the already-forwarded operands.
//
// `ex_alu_result` is the effective address for both loads and stores,
// so `lsu` needs no separate address computation.  When `id_uses_rs1` or
// `id_uses_rs2` is low the corresponding operand is forced to zero here, so an
// unforwarded operand never propagates stale data.
//
// Drop-in replaceable: this file holds the frozen port list and its body.
// Replacing the body must not change the port list and must not require any
// other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"
`include "ctrl_fields.vh"

module ex_stage (
  input  wire [`p_PC_W-1:0]       id_pc,
  input  wire [`p_XLEN-1:0]       id_imm,
  /* verilator lint_off UNUSEDSIGNAL */
  // `id_rs1_addr` and `id_rs2_addr` are genuinely unread here, and that is a
  // contract decision rather than an omission.  Operand *matching* is
  // `forwarding`'s job: it owns the comparators that decide whether the MEM or
  // the WB value wins, and it takes its own copies of these indices.  This
  // stage is handed the values that matching has already resolved, and reading
  // the indices only to throw them away would be dead logic that `synth` would
  // (correctly) optimise away while still costing a reader's time.
  input  wire [`p_REG_ADDR_W-1:0] id_rs1_addr,
  input  wire [`p_REG_ADDR_W-1:0] id_rs2_addr,
  /* verilator lint_on UNUSEDSIGNAL */
  input  wire [`p_REG_ADDR_W-1:0] id_rd_addr,
  input  wire [`p_ALU_OP_W-1:0]   id_alu_op,
  input  wire [`p_OP1_SEL_W-1:0]  id_op1_sel,
  input  wire [`p_OP2_SEL_W-1:0]  id_op2_sel,
  input  wire [`p_FUNCT3_W-1:0]   id_branch_funct3,
  input  wire [`p_IS_BRANCH_W-1:0] id_is_branch,
  input  wire [`p_IS_JAL_W-1:0]    id_is_jal,
  input  wire [`p_IS_JALR_W-1:0]   id_is_jalr,
  input  wire                     id_uses_rs1,
  input  wire                     id_uses_rs2,
  input  wire [`p_USES_RD_W-1:0]  id_uses_rd,
  input  wire                     id_mem_read,
  input  wire                     id_mem_write,
  input  wire [`p_MEM_SIZE_W-1:0] id_mem_size,
  input  wire                     id_mem_unsigned,
  input  wire                     id_reg_write,
  input  wire [`p_WB_SEL_W-1:0]   id_wb_sel,
  input  wire [`p_XLEN-1:0]       ex_rs1_data,
  input  wire [`p_XLEN-1:0]       ex_rs2_data,
  output wire [`p_XLEN-1:0]       ex_alu_result,
  output wire [`p_XLEN-1:0]       ex_store_data,
  output wire [`p_REG_ADDR_W-1:0] ex_rd_addr,
  output wire                     ex_reg_write,
  output wire [`p_WB_SEL_W-1:0]   ex_wb_sel,
  output wire                     ex_mem_read,
  output wire                     ex_mem_write,
  output wire [`p_MEM_SIZE_W-1:0] ex_mem_size,
  output wire                     ex_mem_unsigned,
  output wire                     ex_redirect_valid,
  output wire [`p_PC_W-1:0]       ex_redirect_pc,
  output wire                     ex_target_misaligned
);

  // --------------------------------------------------------------------------
  // DESIGN NOTE 1 - WHY THE ALU IS REPEATED HERE INSTEAD OF INSTANTIATED
  //
  // `docs/contracts/phase1-interfaces.md` draws `ex_stage -> alu`, and this
  // stage certainly needs the arithmetic.  It may NOT say `alu u_alu (...)`:
  //
  //   * the contract's drop-in rule states that "no module may reference
  //     another module.  `core` is the sole exception";
  //   * `make lint TOP=ex_stage`, `make asic-check TOP=ex_stage` and
  //     `make test TOP=ex_stage` all take their source list from
  //     `$(wildcard rtl/core/$(TOP).v)`, which for any TOP other than `core`
  //     is exactly one file.  An instantiation of `alu` here would make
  //     elaboration fail in all three;
  //   * `tb/test_stubs.py` additionally lints every module from its own
  //     source file alone.
  //
  // So the operation is written out here, and it is written out with the same
  // localparam names, the same encodings and the same body as `alu.v`.  The
  // two copies MUST stay in lockstep: they are the same function, and the only
  // thing keeping them honest is that `alu`'s own regression
  // (`tb/test_alu.py`) and this stage's (`tb/test_branch.py`) both check the
  // same operation table.  This duplication is a consequence of the frozen
  // source-list rule and is reported as such.
  // --------------------------------------------------------------------------
  localparam [`p_ALU_OP_W-1:0] ALU_ADD  = 4'd0;
  localparam [`p_ALU_OP_W-1:0] ALU_SUB  = 4'd1;
  localparam [`p_ALU_OP_W-1:0] ALU_SLL  = 4'd2;
  localparam [`p_ALU_OP_W-1:0] ALU_SLT  = 4'd3;
  localparam [`p_ALU_OP_W-1:0] ALU_SLTU = 4'd4;
  localparam [`p_ALU_OP_W-1:0] ALU_XOR  = 4'd5;
  localparam [`p_ALU_OP_W-1:0] ALU_SRL  = 4'd6;
  localparam [`p_ALU_OP_W-1:0] ALU_SRA  = 4'd7;
  localparam [`p_ALU_OP_W-1:0] ALU_OR   = 4'd8;
  localparam [`p_ALU_OP_W-1:0] ALU_AND  = 4'd9;

  // `op1_sel` / `op2_sel`, frozen by the contract.
  localparam [`p_OP1_SEL_W-1:0] OP1_RS1  = 2'd0;
  localparam [`p_OP1_SEL_W-1:0] OP1_PC   = 2'd1;
  localparam [`p_OP1_SEL_W-1:0] OP1_ZERO = 2'd2;

  localparam [`p_OP2_SEL_W-1:0] OP2_RS2  = 3'd0;
  localparam [`p_OP2_SEL_W-1:0] OP2_IMM  = 3'd1;
  localparam [`p_OP2_SEL_W-1:0] OP2_FOUR = 3'd2;
  localparam [`p_OP2_SEL_W-1:0] OP2_PC   = 3'd3;

  // Branch funct3, which is the RISC-V branch funct3 field verbatim.
  localparam [`p_FUNCT3_W-1:0] BR_BEQ  = 3'b000;
  localparam [`p_FUNCT3_W-1:0] BR_BNE  = 3'b001;
  localparam [`p_FUNCT3_W-1:0] BR_BLT  = 3'b100;
  localparam [`p_FUNCT3_W-1:0] BR_BGE  = 3'b101;
  localparam [`p_FUNCT3_W-1:0] BR_BLTU = 3'b110;
  localparam [`p_FUNCT3_W-1:0] BR_BGEU = 3'b111;

  // `mem_size`, frozen by the contract.  Only the top of the scale is named:
  // the assertion below asks "is this one of the three defined sizes?", and
  // spelling all three would leave two of them unused, which Verilator -Wall
  // reports as UNUSEDPARAM.  MEM_BYTE is 2'd0 and is used by `decode`.
  localparam [`p_MEM_SIZE_W-1:0] MEM_WORD = 2'd2;

  // The instruction size, spelled as a shift of 1 rather than as a sized
  // literal such as 32'd4, because the contract forbids a width written as a
  // literal number outside the shared headers.
  localparam [`p_XLEN-1:0] CONST_ONE  = {{(`p_XLEN-1){1'b0}}, 1'b1};
  localparam [`p_XLEN-1:0] CONST_PC4  = CONST_ONE << 2;
  localparam integer SHIFT_AMT_W = 5;

  // --------------------------------------------------------------------------
  // Operand qualification, then selection.
  //
  // The `*_used` gates come FIRST, before the selector muxes.  That order is
  // the contract's promise that "an unforwarded operand never propagates stale
  // data": an instruction that does not read rs1 must not have the register
  // file's last value for whatever index happened to be in `id_rs1_addr`
  // substituted into its address arithmetic, and no selector other than
  // OP1_RS1 can want it anyway - which is precisely why the gate is free.
  // --------------------------------------------------------------------------
  wire [`p_XLEN-1:0] rs1_val = id_uses_rs1 ? ex_rs1_data : {`p_XLEN{1'b0}};
  wire [`p_XLEN-1:0] rs2_val = id_uses_rs2 ? ex_rs2_data : {`p_XLEN{1'b0}};

  reg [`p_XLEN-1:0] op_a_r;
  always @(*) begin
    case (id_op1_sel)
      OP1_RS1  : op_a_r = rs1_val;
      OP1_PC   : op_a_r = id_pc;
      OP1_ZERO : op_a_r = {`p_XLEN{1'b0}};
      // 2'd3 is not an encoding the contract defines; zero is the only answer
      // that cannot turn an undefined control state into an address.
      default  : op_a_r = {`p_XLEN{1'b0}};
    endcase
  end

  reg [`p_XLEN-1:0] op_b_r;
  always @(*) begin
    case (id_op2_sel)
      OP2_RS2  : op_b_r = rs2_val;
      OP2_IMM  : op_b_r = id_imm;
      OP2_FOUR : op_b_r = CONST_PC4;
      OP2_PC   : op_b_r = id_pc;
      // 3'd4..3'd7 are not encodings the contract defines; zero, for the same
      // reason as OP1 above.
      default  : op_b_r = {`p_XLEN{1'b0}};
    endcase
  end

  // --------------------------------------------------------------------------
  // The ALU - see DESIGN NOTE 1 for why this is a copy of `alu.v` and not an
  // instantiation.  It must stay identical to that file.
  // --------------------------------------------------------------------------
  wire signed [`p_XLEN-1:0] op_a_s = op_a_r;
  wire signed [`p_XLEN-1:0] op_b_s = op_b_r;
  wire [`p_XLEN-1:0] shamt = op_b_r[SHIFT_AMT_W-1:0];

  reg [`p_XLEN-1:0] alu_result_r;
  wire [`p_XLEN-1:0] slt_result  = (op_a_s < op_b_s) ? CONST_ONE : {`p_XLEN{1'b0}};
  wire [`p_XLEN-1:0] sltu_result = (op_a_r < op_b_r) ? CONST_ONE : {`p_XLEN{1'b0}};

  always @(*) begin
    case (id_alu_op)
      ALU_ADD  : alu_result_r = op_a_r + op_b_r;
      ALU_SUB  : alu_result_r = op_a_r - op_b_r;
      ALU_SLL  : alu_result_r = op_a_r << shamt;
      ALU_SLT  : alu_result_r = slt_result;
      ALU_SLTU : alu_result_r = sltu_result;
      ALU_XOR  : alu_result_r = op_a_r ^ op_b_r;
      ALU_SRL  : alu_result_r = op_a_r >> shamt;
      ALU_SRA  : alu_result_r = op_a_s >>> shamt;
      ALU_OR   : alu_result_r = op_a_r | op_b_r;
      ALU_AND  : alu_result_r = op_a_r & op_b_r;
      default  : alu_result_r = {`p_XLEN{1'b0}};
    endcase
  end

  wire alu_zero = (alu_result_r == {`p_XLEN{1'b0}});
  wire alu_slt  = (op_a_s < op_b_s);
  wire alu_sltu = (op_a_r < op_b_r);

  // --------------------------------------------------------------------------
  // Conditional branch resolution.
  //
  // `decode` requests `ALU_SUB` with op1 = rs1 and op2 = rs2 for every
  // conditional branch, so on this instruction `alu_result_r` is rs1 - rs2 and
  // `alu_zero` is exactly the BEQ answer.  BLT/BGE come from `slt` and
  // BLTU/BGEU from `sltu`, both of which the ALU computes from the operands
  // themselves and therefore stay correct under `ALU_SUB`.
  //
  // funct3 010 and 011 are reserved by the ISA and `decode` already refuses to
  // emit a branch for them.  The `default` arm is taken not-taken rather than
  // "whatever": a reserved encoding must never be a taken branch.
  // --------------------------------------------------------------------------
  reg branch_taken_r;
  always @(*) begin
    case (id_branch_funct3)
      BR_BEQ   : branch_taken_r =  alu_zero;
      BR_BNE   : branch_taken_r = !alu_zero;
      BR_BLT   : branch_taken_r =  alu_slt;
      BR_BGE   : branch_taken_r = !alu_slt;
      BR_BLTU  : branch_taken_r =  alu_sltu;
      BR_BGEU  : branch_taken_r = !alu_sltu;
      default  : branch_taken_r = 1'b0;
    endcase
  end

  // --------------------------------------------------------------------------
  // Targets.
  //
  // Each is written out from its own operands rather than read back out of
  // `alu_result_r`.  That is deliberate and it is not duplication for its own
  // sake: on a conditional branch `alu_result_r` is the *comparison*, not the
  // target, so reusing it there would be wrong.  Writing all three explicitly
  // keeps the redirect correct no matter which operand selects happen to be on
  // the bus, which is what `ex_redirect_valid` being the pipeline's only
  // redirect source requires.
  //
  //   JAL     target = pc + imm
  //   JALR    target = (rs1 + imm) with bit 0 cleared
  //   BRANCH  target = pc + imm
  // --------------------------------------------------------------------------
  wire [`p_PC_W-1:0] pc_next_r     = id_pc + CONST_PC4;
  wire [`p_PC_W-1:0] pc_plus_imm_r = id_pc + id_imm;
  wire [`p_PC_W-1:0] jalr_sum_r    = rs1_val + id_imm;
  wire [`p_PC_W-1:0] jalr_target_r = {jalr_sum_r[`p_PC_W-1:1], 1'b0};

  reg redirect_valid_r;
  always @(*) begin
    if (id_is_jal)                     redirect_valid_r = 1'b1;
    else if (id_is_jalr)               redirect_valid_r = 1'b1;
    else if (id_is_branch)             redirect_valid_r = branch_taken_r;
    else                               redirect_valid_r = 1'b0;
  end

  reg [`p_PC_W-1:0] redirect_pc_r;
  always @(*) begin
    if (id_is_jal)                     redirect_pc_r = pc_plus_imm_r;
    else if (id_is_jalr)               redirect_pc_r = jalr_target_r;
    else if (id_is_branch && branch_taken_r) redirect_pc_r = pc_plus_imm_r;
    // No redirect this cycle, so the value is a don't-care by the contract.
    // It is driven to the sequential next address rather than left undefined
    // so that it is readable in a waveform and so that `ex_target_misaligned`
    // below cannot be evaluated against X.
    else                               redirect_pc_r = pc_next_r;
  end

  // --------------------------------------------------------------------------
  // Instruction-address misalignment.
  //
  // Phase 1 has no compressed instructions, so the instruction-address
  // alignment is 32 bits and a target is aligned exactly when bit 1 is low.
  // Bit 0 needs no test: B- and J-type immediates always have it at 0, and
  // JALR's target has just had it cleared.
  //
  // The verdict is raised only when a redirect is actually being generated.
  // A not-taken branch never fetches its target, so its displacement is not an
  // address the core ever uses and reporting it would fault a program that the
  // ISA says must run.
  //
  // The verdict does NOT suppress `ex_redirect_valid`.  The contract is
  // explicit that it "is a verdict, not a redirect: `ex_redirect_pc` still
  // carries the computed target, and it is `core`'s job to decide what an
  // instruction-misaligned target means", and lists consuming it under *Known
  // future contract changes*.  Suppressing the redirect here would make the
  // condition unrecoverable and take that decision away from the one module
  // that owns the bundles.
  // --------------------------------------------------------------------------
  reg target_misaligned_r;
  always @(*) begin
    if (redirect_valid_r) target_misaligned_r = redirect_pc_r[1];
    else                  target_misaligned_r = 1'b0;
  end

  // --------------------------------------------------------------------------
  // Outputs.
  // --------------------------------------------------------------------------

  // The ALU result is the effective address for both loads and stores.
  assign ex_alu_result = alu_result_r;

  // Store data is rs2.  It comes from the *qualified* rs2, so an instruction
  // that does not read rs2 cannot present whatever the forwarding network
  // happened to leave on that port as data to be written to memory.
  assign ex_store_data = rs2_val;

  // `uses_rd` is what stops a meaningless rd field from producing a false
  // register-index match downstream, so a meaningless index is forced to x0
  // rather than passed through.  `ex_reg_write` stays a pure pass-through:
  // `decode` already guarantees reg_write implies uses_rd, and an assertion
  // below checks that agreement on every cycle rather than assuming it.
  assign ex_rd_addr = id_uses_rd ? id_rd_addr : {`p_REG_ADDR_W{1'b0}};
  assign ex_reg_write = id_reg_write;

  assign ex_wb_sel       = id_wb_sel;
  assign ex_mem_read     = id_mem_read;
  assign ex_mem_write    = id_mem_write;
  assign ex_mem_size     = id_mem_size;
  assign ex_mem_unsigned = id_mem_unsigned;

  assign ex_redirect_valid    = redirect_valid_r;
  assign ex_redirect_pc       = redirect_pc_r;
  assign ex_target_misaligned = target_misaligned_r;

  // --------------------------------------------------------------------------
  // Invariants.  Each assertion is ONE LINE on purpose: scripts/yosys-prep.sh
  // deletes exactly whole-line `assert (...) else $error(...);` statements,
  // because Yosys's parser rejects the action clause.  A wrapped assertion
  // would survive the deletion and fail asic-check, which is loud rather than
  // silent, but it would still fail.
  //
  // The `$isunknown` guard is not decoration.  `always @(*)` fires once at
  // time zero, when every input is still X, and an immediate assertion whose
  // condition evaluates to X *fails* - so an unguarded assertion in a
  // combinational module reports itself before the testbench has applied any
  // stimulus at all.  Skipping only the undefined case keeps the assertions
  // live for every defined one.
  // --------------------------------------------------------------------------
  // The mutual-exclusion check is written as three pairwise terms rather than
  // as `id_is_branch + id_is_jal + id_is_jalr > 1`.  The sum version is a real
  // trap: IEEE 1364 makes the width of `a + b` the *self-determined* width of
  // its operands, which for three 1-bit signals is 1 bit, so `1 + 1` wraps to
  // 0 and the "more than one is high" condition silently becomes impossible.
  // It would then be an assertion that cannot fail, which is the dangerous kind:
  // it reads as a safety net that is not there.  A pairwise AND has no such
  // width to get wrong.
  always @(*) begin
    if (!$isunknown({id_is_branch, id_is_jal, id_is_jalr, id_mem_read,
                    id_mem_write, id_reg_write, id_uses_rd, id_alu_op,
                    id_mem_size, ex_redirect_valid, ex_target_misaligned})) begin
      assert (!(id_is_branch && id_is_jal) && !(id_is_branch && id_is_jalr) && !(id_is_jal && id_is_jalr)) else $error("ex_stage: is_branch/is_jal/is_jalr are not mutually exclusive");
      assert (!(id_mem_read && id_mem_write)) else $error("ex_stage: both mem_read and mem_write are high");
      assert (!id_reg_write || id_uses_rd) else $error("ex_stage: reg_write without uses_rd would write an index the instruction never meant");
      assert (id_alu_op <= ALU_AND) else $error("ex_stage: alu_op %h is not an RV32I operation", id_alu_op);
      assert (!(id_mem_read || id_mem_write) || (id_mem_size <= MEM_WORD)) else $error("ex_stage: mem_size 3 is not byte/half/word");
      assert (!ex_target_misaligned || ex_redirect_valid) else $error("ex_stage: a misalignment was reported for a cycle with no redirect");
    end
  end

endmodule
`default_nettype wire

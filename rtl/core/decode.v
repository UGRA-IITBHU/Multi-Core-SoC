`default_nettype none
// ============================================================================
// decode - RV32IMAC instruction decoder.
//
// Purpose: turn one instruction word into the control bundle that drives
// `imm_gen`, `ex_stage`, `lsu`, `mem_stage` and `wb_stage`.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   instr          input  32  instruction word from `if_stage`
//   alu_op         output 4   ALU operation select (encoding owned by `alu`)
//   op1_sel        output 2   0 = rs1, 1 = pc, 2 = zero
//   op2_sel        output 3   0 = rs2, 1 = imm, 2 = 4, 3 = pc
//   imm_sel        output 3   immediate format select for `imm_gen`
//   branch_funct3  output 3   funct3 for branch comparison in `ex_stage`
//   is_branch      output 1   conditional branch (BEQ/BNE/BLT/BGE/BLTU/BGEU)
//   is_jal         output 1   JAL
//   is_jalr        output 1   JALR
//   is_illegal     output 1   opcode or funct encoding not implemented
//   uses_rs1       output 1   instruction reads rs1
//   uses_rs2       output 1   instruction reads rs2
//   uses_rd        output 1   the rd field is meaningful
//   mem_read       output 1   instruction is a load
//   mem_write      output 1   instruction is a store
//   mem_size       output 2   0 = byte, 1 = half, 2 = word
//   mem_unsigned   output 1   load is unsigned (LBU / LHU)
//   reg_write      output 1   instruction writes rd
//   wb_sel         output 2   0 = alu, 1 = mem, 2 = pc+4
//
// Guarantee to `imm_gen` and `ex_stage`: every output describes exactly one
// instruction, combinationally and with no pipeline state, so `core` can pack
// them into ID/EX in the same cycle the instruction is decoded.  `imm_sel`
// encoding is 0 = I, 1 = S, 2 = B, 3 = U, 4 = J.  `mem_size` is meaningful
// only when `mem_read` or `mem_write` is high, and is `0` otherwise.
//
// Note - what `is_illegal` does and does not cover.  It is the CANONICAL
// illegal-instruction signal for the whole design: high when the opcode or a
// funct field encodes something this core does not implement.  Two other
// misalignment conditions exist and neither uses this name, because they have
// different owners and different stages: `lsu.data_misaligned` is a misaligned
// *data* access, and `ex_stage.ex_target_misaligned` is a misaligned branch,
// JAL or JALR *target*.  Carrying `is_illegal` on to a trap or to writeback
// suppression is `core`'s job, because `core` owns the bundles; see
// docs/contracts/phase1-interfaces.md.
//
// Drop-in replaceable: this file currently holds only the frozen port list.
// Replacing it with a real implementation must not change the port list and
// must not require any other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"
`include "ctrl_fields.vh"

/* verilator lint_off UNDRIVEN */
/* verilator lint_off UNUSEDSIGNAL */
module decode (
  input  wire [`p_INSTR_W-1:0]    instr,
  output wire [`p_ALU_OP_W-1:0]   alu_op,
  output wire [`p_OP1_SEL_W-1:0]  op1_sel,
  output wire [`p_OP2_SEL_W-1:0]  op2_sel,
  output wire [`p_IMM_SEL_W-1:0]  imm_sel,
  output wire [`p_FUNCT3_W-1:0]   branch_funct3,
  output wire [`p_IS_BRANCH_W-1:0] is_branch,
  output wire [`p_IS_JAL_W-1:0]    is_jal,
  output wire [`p_IS_JALR_W-1:0]   is_jalr,
  output wire [`p_IS_ILLEGAL_W-1:0] is_illegal,
  output wire                     uses_rs1,
  output wire                     uses_rs2,
  output wire [`p_USES_RD_W-1:0]  uses_rd,
  output wire                     mem_read,
  output wire                     mem_write,
  output wire [`p_MEM_SIZE_W-1:0] mem_size,
  output wire                     mem_unsigned,
  output wire                     reg_write,
  output wire [`p_WB_SEL_W-1:0]   wb_sel
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  Combinational module, so the not-implemented assertion
  // reports at time zero, before any input has settled.
  initial begin
    assert (1'b0) else $error("not implemented: decode.alu_op");
    assert (1'b0) else $error("not implemented: decode.op1_sel");
    assert (1'b0) else $error("not implemented: decode.op2_sel");
    assert (1'b0) else $error("not implemented: decode.imm_sel");
    assert (1'b0) else $error("not implemented: decode.branch_funct3");
    assert (1'b0) else $error("not implemented: decode.is_branch");
    assert (1'b0) else $error("not implemented: decode.is_jal");
    assert (1'b0) else $error("not implemented: decode.is_jalr");
    assert (1'b0) else $error("not implemented: decode.is_illegal");
    assert (1'b0) else $error("not implemented: decode.uses_rs1");
    assert (1'b0) else $error("not implemented: decode.uses_rs2");
    assert (1'b0) else $error("not implemented: decode.uses_rd");
    assert (1'b0) else $error("not implemented: decode.mem_read");
    assert (1'b0) else $error("not implemented: decode.mem_write");
    assert (1'b0) else $error("not implemented: decode.mem_size");
    assert (1'b0) else $error("not implemented: decode.mem_unsigned");
    assert (1'b0) else $error("not implemented: decode.reg_write");
    assert (1'b0) else $error("not implemented: decode.wb_sel");
  end

endmodule
`default_nettype wire

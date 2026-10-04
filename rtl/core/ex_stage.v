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
//
// Guarantee to `core`, `lsu` and `pc_gen`: `ex_redirect_valid` is the only
// redirect source in the pipeline, and it is resolved in this stage in the
// cycle the branch or jump is in EX, so `pc_gen` has exactly one funnel to
// obey.  Branch and jump resolution needs nothing beyond this port list:
// `id_is_branch` / `id_is_jal` / `id_is_jalr` identify the instruction class,
// `id_branch_funct3` selects the comparison, `id_pc` gives the sequential and
// `pc + 4` target, `id_imm` gives the branch and JAL displacement, `id_alu_op`
// with `id_op1_sel` / `id_op2_sel` gives the address arithmetic, and
// `ex_rs1_data` / `ex_rs2_data` are the already-forwarded operands.  `ex_alu_result` is the effective address for both loads and stores,
// so `lsu` needs no separate address computation.  When `id_uses_rs1` or
// `id_uses_rs2` is low the corresponding operand is forced to zero here, so an
// unforwarded operand never propagates stale data.
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
module ex_stage (
  input  wire [`p_PC_W-1:0]       id_pc,
  input  wire [`p_XLEN-1:0]       id_imm,
  input  wire [`p_REG_ADDR_W-1:0] id_rs1_addr,
  input  wire [`p_REG_ADDR_W-1:0] id_rs2_addr,
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
  output wire [`p_PC_W-1:0]       ex_redirect_pc
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  Combinational module, so the not-implemented assertion
  // reports at time zero, before any input has settled.
  initial begin
    assert (1'b0) else $error("not implemented: ex_stage.ex_alu_result");
    assert (1'b0) else $error("not implemented: ex_stage.ex_store_data");
    assert (1'b0) else $error("not implemented: ex_stage.ex_rd_addr");
    assert (1'b0) else $error("not implemented: ex_stage.ex_reg_write");
    assert (1'b0) else $error("not implemented: ex_stage.ex_wb_sel");
    assert (1'b0) else $error("not implemented: ex_stage.ex_mem_read");
    assert (1'b0) else $error("not implemented: ex_stage.ex_mem_write");
    assert (1'b0) else $error("not implemented: ex_stage.ex_mem_size");
    assert (1'b0) else $error("not implemented: ex_stage.ex_mem_unsigned");
    assert (1'b0) else $error("not implemented: ex_stage.ex_redirect_valid");
    assert (1'b0) else $error("not implemented: ex_stage.ex_redirect_pc");
  end

endmodule

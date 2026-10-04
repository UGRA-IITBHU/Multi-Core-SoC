// ============================================================================
// mem_stage - memory stage, owner of the MEM/WB pipeline register.
//
// Purpose: take the single-cycle data-memory response, select the value that
// will be written back, report a misaligned data access, and hand the result
// to `core` to be registered into MEM/WB.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   clk             input  1    rising-edge clock
//   rst_n           input  1    active-low synchronous reset
//   stall           input  1    hold the MEM/WB register
//   mem_alu_result  input  32   effective address / ALU result from EX/MEM
//   mem_pc          input  32   PC from EX/MEM, needed for the pc+4 source
//   mem_rsp_rdata   input  32   data returned by `lsu`
//   mem_rd_addr     input  5    destination register index
//   mem_reg_write   input  1    the access writes rd
//   mem_wb_sel      input  2    0 = alu, 1 = mem, 2 = pc+4
//   lsu_data_misaligned input 1  misaligned access, verdict from `lsu`
//   mem_rd_data     output 32   value written back to rd
//   data_misaligned output 1    a misaligned data access reached this stage
//
// Note - naming: the input is named for its source (`lsu_data_misaligned`, the
// same source-naming convention as `mem_rsp_rdata` and as `regfile`'s
// `wb_*` write port) and the output carries the plain condition name, so the two
// are never confused.  Neither is an illegal-instruction condition:
// `decode.is_illegal` is that, and it has a different owner.
//
// Guarantee to `wb_stage` and `forwarding`: `mem_rd_data` is the single
// already-selected writeback value for this instruction, so `wb_stage` needs no
// multiplexer of its own.
//
// Guarantee to `core`: this module REPORTS a misaligned data access, it does not
// gate anything.  `mem_reg_write` is an input here, so this module cannot gate
// it - `core` applies the rule while packing the MEM/WB bundle:
// `mem_wb__reg_write = mem_reg_write && !mem_stage.data_misaligned`.  A
// misaligned access therefore never commits a register write, and the decision
// lives with the module that owns the bundle.
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
module mem_stage (
  input  wire                     clk,
  input  wire                     rst_n,
  input  wire                     stall,
  input  wire [`p_XLEN-1:0]       mem_alu_result,
  input  wire [`p_PC_W-1:0]       mem_pc,
  input  wire [`p_DATA_W-1:0]     mem_rsp_rdata,
  input  wire [`p_REG_ADDR_W-1:0] mem_rd_addr,
  input  wire                     mem_reg_write,
  input  wire [`p_WB_SEL_W-1:0]   mem_wb_sel,
  input  wire                     lsu_data_misaligned,
  output wire [`p_XLEN-1:0]       mem_rd_data,
  output wire                     data_misaligned
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  The body is deliberately empty: every output reports itself
  // as not implemented until the memory block is built.
  always @(posedge clk) begin
    assert (1'b0) else $error("not implemented: mem_stage.mem_rd_data");
    assert (1'b0) else $error("not implemented: mem_stage.data_misaligned");
  end

endmodule

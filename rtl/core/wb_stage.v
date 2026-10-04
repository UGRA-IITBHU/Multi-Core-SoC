// ============================================================================
// wb_stage - writeback stage: register write port and WB-stage forwarding
// source.
//
// Purpose: present the writeback value to `regfile` and publish the youngest
// architectural result so `forwarding` can select it with the highest priority.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   mem_rd_data     input  32  writeback value from `mem_stage`
//   mem_rd_addr     input  5   destination register index
//   mem_reg_write   input  1   the instruction writes rd
//   mem_illegal     input  1   an illegal access reached the memory stage
//   wb_we           output 1   commit the register write this cycle
//   wb_wdata        output 32  data to write
//   wb_waddr        output 5   register to write
//   fwd_rd_addr     output 5   destination of the WB-stage forwarding value
//   fwd_rd_data     output 32  WB-stage forwarding value
//   fwd_reg_write   output 1   WB-stage forwarding value is valid
//
// Guarantee to `regfile` and `forwarding`: `wb_we` is the single write enable
// for the whole pipeline and is low whenever `mem_reg_write` is low, whenever
// `mem_illegal` is high, or whenever `mem_rd_addr` is `x0`, so writes to `x0`
// are discarded.  `fwd_reg_write` carries that same `x0` exclusion, so
// `forwarding` can never forward `x0` as an architectural value; the
// register file discards `x0` writes independently, so the discard is
// enforced at both ends of the writeback path.
//
// Note: this module is purely combinational in phase 1; the MEM/WB pipeline
// register lives in `mem_stage`, which owns the memory stage timing.
//
// Drop-in replaceable: this file currently holds only the frozen port list.
// Replacing it with a real implementation must not change the port list and
// must not require any other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"

/* verilator lint_off UNDRIVEN */
/* verilator lint_off UNUSEDSIGNAL */
module wb_stage (
  input  wire [`p_XLEN-1:0]       mem_rd_data,
  input  wire [`p_REG_ADDR_W-1:0] mem_rd_addr,
  input  wire                     mem_reg_write,
  input  wire                     mem_illegal,
  output wire                     wb_we,
  output wire [`p_XLEN-1:0]       wb_wdata,
  output wire [`p_REG_ADDR_W-1:0] wb_waddr,
  output wire [`p_REG_ADDR_W-1:0] fwd_rd_addr,
  output wire [`p_XLEN-1:0]       fwd_rd_data,
  output wire                     fwd_reg_write
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  Combinational module, so the not-implemented assertion
  // reports at time zero, before any input has settled.
  initial begin
    assert (1'b0) else $error("not implemented: wb_stage.wb_we");
    assert (1'b0) else $error("not implemented: wb_stage.wb_wdata");
    assert (1'b0) else $error("not implemented: wb_stage.wb_waddr");
    assert (1'b0) else $error("not implemented: wb_stage.fwd_rd_addr");
    assert (1'b0) else $error("not implemented: wb_stage.fwd_rd_data");
    assert (1'b0) else $error("not implemented: wb_stage.fwd_reg_write");
  end

endmodule

// ============================================================================
// forwarding - operand forwarding network.
//
// Purpose: supply `ex_stage` with the newest architectural value for each
// operand, selecting between the MEM-stage and the WB-stage producer.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   ex_rs1_addr    input  5   rs1 index of the instruction in execute
//   ex_rs2_addr    input  5   rs2 index of the instruction in execute
//   id_uses_rs1    input  1   the decode instruction reads rs1
//   id_uses_rs2    input  1   the decode instruction reads rs2
//   mem_rd_addr    input  5   destination of the MEM-stage value
//   mem_rd_data    input  32  MEM-stage value
//   mem_reg_write  input  1   the MEM-stage value is valid
//   fwd_rd_addr    input  5   destination of the WB-stage value
//   fwd_rd_data    input  32  WB-stage value
//   fwd_reg_write  input  1   the WB-stage value is valid
//   fwd_rs1_valid  output 1   forward into `ex_rs1_data`
//   fwd_rs1_data   output 32  forwarded rs1 operand
//   fwd_rs2_valid  output 1   forward into `ex_rs2_data`
//   fwd_rs2_data   output 32  forwarded rs2 operand
//
// Guarantee to `ex_stage`: when `fwd_rs1_valid` is high, `fwd_rs1_data` is
// the newest value written to `ex_rs1_addr` by any earlier instruction, and
// `fwd_rs1_valid` is low when no forwarding is needed.  Where both the MEM
// and the WB stage can supply the operand, the MEM stage wins, because it is
// the younger value.  `x0` is never forwarded: `mem_reg_write` and
// `fwd_reg_write` already exclude `x0` at their producers.  The decode-stage
// `id_rs1_addr` / `id_rs2_addr` inputs are present so that a hazard that
// cannot be forwarded is reported to `core` rather than silently mis-resolved.
//
// Drop-in replaceable: this file currently holds only the frozen port list.
// Replacing it with a real implementation must not change the port list and
// must not require any other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"

/* verilator lint_off UNDRIVEN */
/* verilator lint_off UNUSEDSIGNAL */
module forwarding (
  input  wire [`p_REG_ADDR_W-1:0] ex_rs1_addr,
  input  wire [`p_REG_ADDR_W-1:0] ex_rs2_addr,
  input  wire                     id_uses_rs1,
  input  wire                     id_uses_rs2,
  input  wire [`p_REG_ADDR_W-1:0] mem_rd_addr,
  input  wire [`p_XLEN-1:0]       mem_rd_data,
  input  wire                     mem_reg_write,
  input  wire [`p_REG_ADDR_W-1:0] fwd_rd_addr,
  input  wire [`p_XLEN-1:0]       fwd_rd_data,
  input  wire                     fwd_reg_write,
  output wire                     fwd_rs1_valid,
  output wire [`p_XLEN-1:0]       fwd_rs1_data,
  output wire                     fwd_rs2_valid,
  output wire [`p_XLEN-1:0]       fwd_rs2_data
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  Combinational module, so the not-implemented assertion
  // reports at time zero, before any input has settled.
  initial begin
    assert (1'b0) else $error("not implemented: forwarding.fwd_rs1_valid");
    assert (1'b0) else $error("not implemented: forwarding.fwd_rs1_data");
    assert (1'b0) else $error("not implemented: forwarding.fwd_rs2_valid");
    assert (1'b0) else $error("not implemented: forwarding.fwd_rs2_data");
  end

endmodule

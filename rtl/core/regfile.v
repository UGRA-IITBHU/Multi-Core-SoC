`default_nettype none
// ============================================================================
// regfile - 32x32 register file with combinational reads and clocked writes.
//
// Purpose: supply the two decode-stage operand read ports and absorb the
// single writeback port.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   clk        input  1    rising-edge clock
//   rst_n      input  1    active-low synchronous reset to all-zero
//   rs1_addr   input  5    first source register index
//   rs2_addr   input  5    second source register index
//   rs1_used   input  1    instruction reads rs1; when low the read is forced 0
//   rs2_used   input  1    instruction reads rs2; when low the read is forced 0
//   wb_we      input  1    commit the writeback port this cycle
//   wb_waddr   input  5    writeback destination index
//   wb_wdata   input  32   writeback data
//   rs1_data   output 32   rs1 value after writeback bypass
//   rs2_data   output 32   rs2 value after writeback bypass
//
// Guarantee to `ex_stage` via `core`: reads are combinational and bypass the
// writeback port in the same cycle, so a load-use distance of one needs no
// hazard stall; `rs1_data`/`rs2_data` are exactly `0` when the corresponding
// `*_used` is low, and reading `x0` always yields `0`.  Writes to `x0` are
// discarded here as well as at `wb_stage`, so the discard is enforced at both
// ends of the writeback path.
//
// Drop-in replaceable: this file currently holds only the frozen port list.
// Replacing it with a real implementation must not change the port list and
// must not require any other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"

/* verilator lint_off UNDRIVEN */
/* verilator lint_off UNUSEDSIGNAL */
module regfile (
  input  wire                   clk,
  input  wire                   rst_n,
  input  wire [`p_REG_ADDR_W-1:0] rs1_addr,
  input  wire [`p_REG_ADDR_W-1:0] rs2_addr,
  input  wire                   rs1_used,
  input  wire                   rs2_used,
  input  wire                   wb_we,
  input  wire [`p_REG_ADDR_W-1:0] wb_waddr,
  input  wire [`p_XLEN-1:0]     wb_wdata,
  output wire [`p_XLEN-1:0]     rs1_data,
  output wire [`p_XLEN-1:0]     rs2_data
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  The body is deliberately empty: every output reports itself
  // as not implemented until the decode block is built.
  always @(posedge clk) begin
    assert (1'b0) else $error("not implemented: regfile.rs1_data");
    assert (1'b0) else $error("not implemented: regfile.rs2_data");
  end

endmodule
`default_nettype wire

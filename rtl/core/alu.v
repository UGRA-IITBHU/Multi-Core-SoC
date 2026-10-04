// ============================================================================
// alu - 32-bit integer ALU.
//
// Purpose: perform the arithmetic, logic, shift and compare operation selected
// by `decode`, and expose the comparison results branch resolution needs.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   op_a    input  32  first operand, already selected by `ex_stage`
//   op_b    input  32  second operand, already selected by `ex_stage`
//   alu_op  input  4   operation select from `decode`
//   result  output 32  operation result, `p_XLEN` bits
//   zero    output 1   result is zero
//   slt     output 1   signed less-than
//   sltu    output 1   unsigned less-than
//
// Guarantee to `ex_stage`: all four outputs are consistent with each other in
// the same cycle, so branch resolution needs one ALU instance and no second
// comparison pass.  `result` is the store-data-mux-excluded operand result
// only; `ex_stage` owns choosing which value is written back.
//
// Note: the `alu_op` encoding is owned jointly by this module and `ex_stage`
// and is not enumerated here, because the two are built by the same owner and
// the encoding is internal to the execute block.
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
module alu (
  input  wire [`p_XLEN-1:0]     op_a,
  input  wire [`p_XLEN-1:0]     op_b,
  input  wire [`p_ALU_OP_W-1:0] alu_op,
  output wire [`p_XLEN-1:0]     result,
  output wire                   zero,
  output wire                   slt,
  output wire                   sltu
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  Combinational module, so the not-implemented assertion
  // reports at time zero, before any input has settled.
  initial begin
    assert (1'b0) else $error("not implemented: alu.result");
    assert (1'b0) else $error("not implemented: alu.zero");
    assert (1'b0) else $error("not implemented: alu.slt");
    assert (1'b0) else $error("not implemented: alu.sltu");
  end

endmodule

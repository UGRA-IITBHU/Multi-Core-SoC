// ============================================================================
// imm_gen - immediate generator.
//
// Purpose: produce the sign-extended 32-bit immediate selected by `decode`.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   instr    input  32  instruction word
//   imm_sel  input  3   format select from `decode`
//                       0 = I, 1 = S, 2 = B, 3 = U, 4 = J
//   imm      output 32  sign-extended immediate, ready for `ex_stage`
//
// Guarantee to `ex_stage`: `imm` is fully sign-extended to `p_XLEN` and is
// combinationally derived from `instr` and `imm_sel` alone, so `core` can
// register it into ID/EX in the decode cycle.  For formats 0 to 4 the result
// is the standard RV32 I/S/B/U/J immediate; any other `imm_sel` value must
// drive `imm` to zero rather than to undefined bits.
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
module imm_gen (
  input  wire [`p_INSTR_W-1:0]  instr,
  input  wire [`p_IMM_SEL_W-1:0] imm_sel,
  output wire [`p_XLEN-1:0]   imm
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  Combinational module, so the not-implemented assertion
  // reports at time zero, before any input has settled.
  initial begin
    assert (1'b0) else $error("not implemented: imm_gen.imm");
  end

endmodule

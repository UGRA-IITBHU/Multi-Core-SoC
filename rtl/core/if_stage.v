// ============================================================================
// if_stage - instruction fetch stage.
//
// Purpose: turn the address from `pc_gen` into an instruction word and publish
// the static next-PC prediction that `pc_gen` consumes.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   clk          input  1    rising-edge clock
//   rst_n        input  1    active-low synchronous reset
//   stall        input  1    hold the fetched instruction
//   flush        input  1    discard the fetched instruction (wrong path)
//   pc           input  32   address from `pc_gen`
//   instr        output 32   instruction word being handed to decode
//   pred_taken   output 1    static prediction is a taken branch
//   pred_pc      output 32   predicted next PC
//
// Guarantee to `decode` / `regfile` / `imm_gen`: while `stall` is low and
// `flush` is low, `instr` is the instruction at `pc`; when `flush` is high the
// instruction in flight is squashed so the following stage sees no stale
// instruction.  `pred_taken` and `pred_pc` are the only prediction state and
// are consumed by nothing else.
//
// Note: instruction memory is an implementation detail of this module.  It is
// deliberately not a port, because the top-level memory interface belongs to
// `lsu` alone.  Phase 1 exposes no top-level port for loading programs; that
// arrives with the memory subsystem.
//
// Drop-in replaceable: this file currently holds only the frozen port list.
// Replacing it with a real implementation must not change the port list and
// must not require any other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"

/* verilator lint_off UNDRIVEN */
/* verilator lint_off UNUSEDSIGNAL */
module if_stage (
  input  wire                 clk,
  input  wire                 rst_n,
  input  wire                 stall,
  input  wire                 flush,
  input  wire [`p_PC_W-1:0]   pc,
  output wire [`p_INSTR_W-1:0] instr,
  output wire                 pred_taken,
  output wire [`p_PC_W-1:0]   pred_pc
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  The body is deliberately empty: every output reports itself
  // as not implemented until the fetch block is built.
  always @(posedge clk) begin
    assert (1'b0) else $error("not implemented: if_stage.instr");
    assert (1'b0) else $error("not implemented: if_stage.pred_taken");
    assert (1'b0) else $error("not implemented: if_stage.pred_pc");
  end

endmodule

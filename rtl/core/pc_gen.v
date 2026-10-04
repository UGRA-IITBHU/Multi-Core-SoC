// ============================================================================
// pc_gen - next-instruction-address generator for the fetch stage.
//
// Purpose: hold the address of the instruction being fetched, apply fetch
// stalls, and apply the single redirect funnel that overrides the static
// next-PC prediction.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   clk              input  1    rising-edge clock
//   rst_n            input  1    active-low synchronous reset to `p_RESET_VEC
//   stall            input  1    hold `pc`; a fetch stall arrives here
//   redirect_valid   input  1    take `redirect_pc` this cycle
//   redirect_pc      input  32   resolved redirect target
//   pred_taken       input  1    static prediction says the next PC is `pred_pc
//   pred_pc          input  32   predicted next PC
//   pc               output 32   address of the instruction being fetched
//   next_pc          output 32   combinational next address after the arbiter
//
// Guarantee to `if_stage`: `pc` always holds the address of the instruction
// currently being fetched; while `stall` is high `pc` does not advance, and
// `redirect_valid` takes priority over both `pred_taken` and the sequential
// +4 step in the same cycle it is presented.
//
// Guarantee to `core`: `next_pc` is the combinational result of that same
// priority arbiter - `redirect_valid` > `pred_taken` > `pc + 4` - and is valid
// in the same cycle as `pc`, so the arbiter's decision is observable without
// waiting a cycle for `pc` to register.  `pc` and `next_pc` never disagree
// about which source won.
//
// Note: `pc_gen` deliberately has no memory-response port.  The instruction
// fetch handshake belongs to `if_stage` and the load/store handshake to `lsu`,
// so a fetch stall can only reach this module through `stall`.
//
// Drop-in replaceable: this file currently holds only the frozen port list.
// Replacing it with a real implementation must not change the port list and
// must not require any other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"

/* verilator lint_off UNDRIVEN */
/* verilator lint_off UNUSEDSIGNAL */
module pc_gen (
  input  wire                clk,
  input  wire                rst_n,
  input  wire                stall,
  input  wire                redirect_valid,
  input  wire [`p_PC_W-1:0]  redirect_pc,
  input  wire                pred_taken,
  input  wire [`p_PC_W-1:0]  pred_pc,
  output wire [`p_PC_W-1:0]  pc,
  output wire [`p_PC_W-1:0]  next_pc
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  The body is deliberately empty: every output reports itself
  // as not implemented until the fetch block is built.
  always @(posedge clk) begin
    assert (1'b0) else $error("not implemented: pc_gen.pc");
    assert (1'b0) else $error("not implemented: pc_gen.next_pc");
  end

endmodule

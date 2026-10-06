`default_nettype none
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
// Note - the one redirect funnel.  Every redirect in the core arrives here:
// the branch arm of `ex_stage.ex_redirect_valid` today, and the trap and
// interrupt arms from phase 3.  There is no second path into the PC and there
// must never be one; a phase that needs a new redirect source adds an arm to
// the arbiter below.
//
// Note - a redirect outranks `stall`.  `redirect_valid` is raised by EX on
// precisely the cycles the front end may be stalled by the load-use interlock,
// and a redirect swallowed by a stall would leave the core fetching the wrong
// path for the whole stall window with nothing downstream reporting an error.
// So the priority is `rst_n` > `redirect_valid` > `!stall`.  This is reported
// to the integrator because it is the one place the frozen wording admits two
// readings: "`pc` only advances when `stall` is low" holds for the sequential
// and predicted steps, and the redirect is applied even when `stall` is high.
// Wiring `stall` so that it is never asserted together with a redirect -- for
// example `stall = if_req_valid && !redirect_valid` -- also keeps this correct
// if that reading is preferred instead.
//
// Note - `pred_taken` / `pred_pc` are inputs tied to constants by `core` in
// phase 1 (spec decision 8).  No predictor lives here; `if_stage` publishes
// the not-taken fall-through, and phase 5 replaces that with a real predictor
// without touching this port list.
//
// Drop-in replaceable: the port list above is frozen and unchanged; this file
// implements exactly those ports from its own source alone.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"

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

  // One instruction is 4 bytes.  This constant belongs in `defs.vh` with the
  // other global datapath constants; `defs.vh` is a frozen contract header, so
  // the addition is reported to the controller rather than made here.
  localparam [`p_PC_W-1:0] p_PC_STEP = `p_PC_W'd4;

  reg [`p_PC_W-1:0] pc_q;

  assign pc = pc_q;

  // The single redirect funnel.  Priority: `redirect_valid` > `pred_taken` >
  // `pc + 4`.  `next_pc` is the decision itself, not a delayed copy of it, so
  // the PC and `next_pc` can never disagree about which source won.
  assign next_pc = redirect_valid ? redirect_pc :
                   pred_taken    ? pred_pc    :
                                   (pc_q + p_PC_STEP);

  always @(posedge clk) begin
    if (!rst_n)
      pc_q <= `p_RESET_VEC;
    else if (redirect_valid)
      // Outranks `stall`, for the reason given in the header.
      pc_q <= redirect_pc;
    else if (!stall)
      // `next_pc` with no redirect and no prediction is the sequential step.
      pc_q <= next_pc;
  end

  // The arbiter is the contract's guarantee, so it is asserted rather than
  // assumed.  Each arm is checked with the other two high as well, which is
  // the only stimulus that orders them.
  always @(posedge clk) begin
    if (rst_n) begin
      assert (!redirect_valid || next_pc == redirect_pc) else $error("pc_gen: a redirect must win the next_pc arbiter");
      assert (redirect_valid || !pred_taken || next_pc == pred_pc) else $error("pc_gen: a prediction must outrank the sequential step");
      assert (redirect_valid || pred_taken || next_pc == pc + p_PC_STEP) else $error("pc_gen: next_pc must fall through to pc + 4");
    end
  end

endmodule
`default_nettype wire

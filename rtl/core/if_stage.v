`default_nettype none
// ============================================================================
// if_stage - instruction fetch stage, owner of the instruction-fetch interface.
//
// Purpose: turn the address from `pc_gen` into an instruction word over the
// instruction-fetch memory port, and publish the static next-PC prediction that
// `pc_gen` consumes.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   clk          input  1    rising-edge clock
//   rst_n        input  1    active-low synchronous reset
//   stall        input  1    hold the fetched instruction
//   flush        input  1    discard the fetched instruction (wrong path)
//   pc           input  32   address from `pc_gen`
//   if_rsp_rdata input  32   instruction word returned by fetch memory
//   if_rsp_valid input  1    fetch memory has returned an instruction
//   if_req_valid output 1    request is being presented to fetch memory
//   if_req_addr  output 32   request address (4-byte aligned)
//   instr       output 32   instruction word being handed to decode
//   instr_len   output 3    length of `instr` in bytes (2 or 4)
//   pred_taken  output 1    static prediction is a taken branch
//   pred_pc     output 32   predicted next PC
//
// Guarantee to `decode` / `regfile` / `imm_gen`: while `stall` and `flush` are
// both low, `instr` is the instruction at `pc`; when `flush` is high the
// instruction in flight is squashed so the following stage sees no stale
// instruction.  `pred_taken` and `pred_pc` are the only prediction state: they
// ride in IF/ID and feed `pc_gen`'s arbiter, and `core` ties them to constants
// in this phase (see the predictor note below).  `instr` is a word only in the
// cycle after a response has been accepted; outside that cycle it is zero, so
// a `valid` bit that slips cannot turn into a stale instruction.
//
// Guarantee to the fetch memory: `if_req_valid` stays high from the cycle the
// request is presented until `if_rsp_valid` is seen, and `if_req_addr` remains
// stable for the whole of that window, so fetch memory may accept the request
// at its own pace.  A request that has been presented is never withdrawn: it
// is answered before the stage moves on, so a memory that has accepted one
// always gets its response accepted exactly once.
//
// Note - how `core` wires this.  Two requirements, both of them consequences
// of the frozen port list rather than choices this module made:
//   * `pc_gen.stall` must be asserted whenever `if_req_valid` is high or `stall`
//     is high -- that is, `pc_gen.stall = if_req_valid || stall`.  That freezes
//     `pc` across the request window and across a held instruction, which is
//     what makes the guarantee above hold at the IF/ID boundary: the instruction
//     presented in any cycle belongs to the `pc` of that same cycle, so `core`
//     can pack `if_id__pc` straight from `pc_gen`.
//   * `if_id__valid` is `core`'s bit and is core's to derive, one cycle after
//     the response is accepted.  The handshake alone does not express the one
//     case where no instruction follows -- a `flush` that arrives with a request
//     still outstanding, whose response is drained and thrown away -- so `core`
//     mirrors that one condition with a bit of its own state:
//         flush_discard  = flush && if_req_valid && !if_rsp_valid
//         if_id__valid  <= if_req_valid && if_rsp_valid && !flush
//                          && !flush_discard
//     A cleaner answer is a contract change -- an instruction-valid output on
//     this module -- and it is reported to the integrator rather than made
//     unilaterally, because four other owners build against this port list.
//
// Note - timing.  Fetch is serialised against the PC rather than pipelined: one
// address is in flight at a time, because the only pairing information this
// module owns is the instruction word and `pc_gen` owns the address.  A
// pipelined fetch would need either a PC output here or a PC queue in `core`
// to pair `instr` with the address it was fetched from; both are contract
// changes and both are reported to the integrator rather than made here.
//
// Note - 32-bit instructions at a halfword offset.  The C extension allows a
// 32-bit instruction to begin on any 16-bit boundary, so `pc[1]` may be 1 with
// a 32-bit opcode in the fetched word's high half.  The instruction then spans
// two words: its low half is `word0[31:16]` and its high half is `word1[15:0]`.
// The stage issues that second read itself (ST_HIGH2) and presents the
// assembled word with a length of 4; a compressed instruction at `pc[1]` is
// complete in the high half and needs no second read.  This makes `instr` a
// registered value assembled across the response(s) rather than a combinational
// slice of `if_rsp_rdata`.
//
// Note - no predictor in phase 1 (spec decision 8).  `pred_taken` is low and
// `pred_pc` is the sequential fall-through `pc + 4`, which is the "predicted
// not taken" encoding.  Phase 5 replaces those two assignments with a real
// predictor and nothing else changes.
//
// Note - `flush` cannot cancel a read.  A memory read already presented is not
// withdrawable, so `flush` squashes the instruction and the prediction, keeps
// the outstanding request outstanding, and discards its response before
// refetching from the current `pc`.  Latching a stale response instead would
// present the wrong-path word as the instruction at the new address, and no
// value check downstream would catch it.
//
// Note - two ports, one address space: instruction fetch has its own port pair
// (`if_req_*` / `if_rsp_*`) rather than sharing `mem_req_*` / `mem_rsp_*` with
// `lsu`, even though both address the same unified memory.  Phase 4 gives the
// core separate L1 I$ and D$ that need independent bandwidth, and one
// arbitrated port would force the fetch path to be redesigned then, and would
// stall instruction fetch whenever the load/store unit is active.  The data
// memory port therefore has two owners: `if_stage` for fetch and `lsu` for
// load/store.  The same pair is exposed at the top level by `core`.
//
// Drop-in replaceable: the port list above is frozen and unchanged; this file
// implements exactly those ports from its own source alone.  `if_req_*` and
// `if_rsp_*` are also the top-level port names of `core`, so they must not be
// renamed without changing `core` in the same commit.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"

module if_stage (
  input  wire                  clk,
  input  wire                  rst_n,
  input  wire                  stall,
  input  wire                  flush,
  input  wire [`p_PC_W-1:0]    pc,
  input  wire [`p_INSTR_W-1:0] if_rsp_rdata,
  input  wire                  if_rsp_valid,
  output wire                  if_req_valid,
  output wire [`p_PC_W-1:0]    if_req_addr,
  output wire [`p_INSTR_W-1:0] instr,
  output wire [2:0]            instr_len,
  output wire                  pred_taken,
  output wire [`p_PC_W-1:0]    pred_pc
);

  // See `pc_gen`: this constant belongs in the frozen `defs.vh`, and the
  // addition is reported to the controller rather than made here.
  localparam [`p_PC_W-1:0] p_PC_STEP = `p_PC_W'd4;

  // --- fetch state --------------------------------------------------------
  //   ST_IDLE     a fresh request for the current `pc` is being presented
  //   ST_REQ      that request is outstanding, awaiting its response
  //   ST_HIGH2    a 32-bit instruction starting at pc[1]==1 has its low half in
  //               the fetched word's high half; the second request fetches the
  //               next word to obtain the instruction's high half
  //   ST_HOLD     the (assembled) instruction has been latched and is presented
  //   ST_DISCARD  a response to a request outstanding at a `flush` is being
  //               drained and thrown away, so it cannot be mistaken for the
  //               instruction at the new `pc`
  localparam [2:0] ST_IDLE    = 3'd0;
  localparam [2:0] ST_REQ     = 3'd1;
  localparam [2:0] ST_HOLD    = 3'd2;
  localparam [2:0] ST_DISCARD = 3'd3;
  localparam [2:0] ST_HIGH2   = 3'd4;

  reg [2:0]               state;
  reg [15:0]              word_hi_q; // word0[31:16], held for the second read
  reg [`p_INSTR_W-1:0]    instr_q;   // the assembled instruction presented in HOLD
  reg [2:0]               len_q;     // its length in bytes (2 or 4)
  reg [`p_PC_W-1:0]      req_addr_q;

  // The 4-byte-aligned word containing `pc`; with the C extension `pc` may
  // itself be halfword aligned.
  wire [`p_PC_W-1:0] fetch_base = {pc[`p_PC_W-1:2], 2'b00};

  // A request is presented whenever the stage is not holding an instruction,
  // so it is never withdrawn before its response is accepted.  ST_HIGH2 is a
  // request window too: it is the second read of a boundary-crossing 32-bit
  // instruction.
  assign if_req_valid = (state == ST_IDLE) || (state == ST_REQ) ||
                        (state == ST_DISCARD) || (state == ST_HIGH2);

  // Stable for the whole window.  In ST_IDLE it is the address being presented
  // now; in the two states that carry a request it is the address captured when
  // the request was presented (`fetch_base + 4` for the second read).
  assign if_req_addr  = (state == ST_IDLE) ? fetch_base : req_addr_q;

  // The instruction is assembled across the two fetched words before it is
  // presented, so it is a registered value, not a slice of `if_rsp_rdata`.
  assign instr     = instr_q;
  assign instr_len = len_q;

  assign pred_taken = 1'b0;
  assign pred_pc    = pc + p_PC_STEP;

  // --- first-word assembly -------------------------------------------------
  // A first-word response is one of four things, decided by `pc[1]` and the
  // low two bits of the selected half:
  //   * pc[1]==0, low half == 2'b11 : a complete 32-bit instruction (the word)
  //   * pc[1]==0, otherwise         : a complete compressed instruction (low)
  //   * pc[1]==1, high half == 2'b11: the LOW half of a 32-bit instruction that
  //                                   crosses the word boundary -> read on
  //   * pc[1]==1, otherwise         : a complete compressed instruction (high)
  // A 32-bit instruction may start on any 16-bit boundary when C is present,
  // so the third case is legal and common; it is not a misalignment.
  wire        first_low32 = (pc[1] == 1'b0) && (if_rsp_rdata[1:0]   == 2'b11);
  wire        first_bit32 = (pc[1] == 1'b1) && (if_rsp_rdata[17:16] == 2'b11);
  wire [31:0] first_instr = pc[1] ? {16'b0, if_rsp_rdata[31:16]}
                                  : (first_low32 ? if_rsp_rdata
                                                 : {16'b0, if_rsp_rdata[15:0]});
  wire [2:0]  first_len   = first_low32 ? 3'd4 : 3'd2;

  always @(posedge clk) begin
    if (!rst_n) begin
      state      <= ST_IDLE;
      word_hi_q  <= 16'b0;
      instr_q    <= {`p_INSTR_W{1'b0}};
      len_q      <= 3'd0;
      req_addr_q <= `p_RESET_VEC;
    end else if (flush) begin
      // Squash the instruction in flight and the prediction.  An outstanding
      // request is not cancelled -- a read cannot be withdrawn -- so its
      // response is drained in ST_DISCARD, at the same address it was made for.
      instr_q <= {`p_INSTR_W{1'b0}};
      len_q   <= 3'd0;
      if (state == ST_IDLE)
        req_addr_q <= fetch_base;
      if (if_req_valid && !if_rsp_valid)
        state <= ST_DISCARD;
      else
        state <= ST_IDLE;
    end else begin
      // The fetch handshake progresses whatever `stall` says: `stall` holds
      // the *presented* instruction, and gating the response on it would
      // deadlock the request against a stall raised for its own sake.
      case (state)
        ST_IDLE: begin
          // Capture the address now, so the request window that follows is
          // stable whatever `pc` does -- the guarantee must not depend on how
          // `core` wires `pc_gen.stall`.
          req_addr_q <= fetch_base;
          if (if_rsp_valid) begin
            // A zero-latency memory answers in the request's own cycle; the
            // transfer is complete, so nothing is left outstanding.
            word_hi_q <= if_rsp_rdata[31:16];
            if (first_bit32) begin
              req_addr_q <= fetch_base + `p_PC_W'd4;
              state      <= ST_HIGH2;
            end else begin
              instr_q <= first_instr;
              len_q   <= first_len;
              state   <= ST_HOLD;
            end
          end else begin
            state <= ST_REQ;
          end
        end
        ST_REQ:
          if (if_rsp_valid) begin
            word_hi_q <= if_rsp_rdata[31:16];
            if (first_bit32) begin
              req_addr_q <= fetch_base + `p_PC_W'd4;
              state      <= ST_HIGH2;
            end else begin
              instr_q <= first_instr;
              len_q   <= first_len;
              state   <= ST_HOLD;
            end
          end
        ST_HIGH2:
          if (if_rsp_valid) begin
            // Low half from the first word's high half, high half from the
            // second word's low half.
            instr_q <= {if_rsp_rdata[15:0], word_hi_q};
            len_q   <= 3'd4;
            state   <= ST_HOLD;
          end
        ST_DISCARD:
          if (if_rsp_valid)
            state <= ST_IDLE;
        ST_HOLD:
          // The instruction has been handed to the IF/ID register in `core`.
          if (!stall) begin
            instr_q <= {`p_INSTR_W{1'b0}};
            len_q   <= 3'd0;
            state   <= ST_IDLE;
          end
        default:
          state <= ST_IDLE;
      endcase
    end
  end

  // The handshake properties this module guarantees to fetch memory.  Each is
  // stated per cycle rather than against a past value, so no assertion state
  // is needed and the checks hold in every cycle the design spends awake.
  always @(posedge clk) begin
    if (rst_n) begin
      assert (state != ST_IDLE || if_req_addr == fetch_base) else $error("if_stage: a fresh request must carry the current pc, word-aligned");
      assert (state != ST_HOLD || !if_req_valid) else $error("if_stage: no request may be outstanding while an instruction is presented");
      // The nonzero-instruction check is gone: with compressed encodings an
      // instruction may have a zero high half, so nonzero is no longer the
      // invariant.  `ST_HOLD` itself is the valid bit.
      assert (state != ST_IDLE || instr == {`p_INSTR_W{1'b0}}) else $error("if_stage: no instruction may be presented before the response arrives");
      assert (!pred_taken) else $error("if_stage: phase 1 has no predictor, so pred_taken must stay low");
    end
  end

endmodule
`default_nettype wire

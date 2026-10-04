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
//   if_req_addr  output 32   request address
//   instr       output 32   instruction word being handed to decode
//   pred_taken  output 1    static prediction is a taken branch
//   pred_pc     output 32   predicted next PC
//
// Guarantee to `decode` / `regfile` / `imm_gen`: while `stall` is low and
// `flush` is low, `instr` is the instruction at `pc`; when `flush` is high the
// instruction in flight is squashed so the following stage sees no stale
// instruction.  `pred_taken` and `pred_pc` are the only prediction state and
// are consumed by nothing else.
//
// Guarantee to the fetch memory: `if_req_valid` stays high from the cycle the
// request is presented until `if_rsp_valid` is seen, and `if_req_addr` remains
// stable for the whole of that window, so fetch memory may accept the request
// at its own pace.
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
// Drop-in replaceable: this file currently holds only the frozen port list.
// Replacing it with a real implementation must not change the port list and
// must not require any other module to change.  `if_req_*` and `if_rsp_*` are
// also the top-level port names of `core`, so they must not be renamed without
// changing `core` in the same commit.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"

/* verilator lint_off UNDRIVEN */
/* verilator lint_off UNUSEDSIGNAL */
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
  output wire                  pred_taken,
  output wire [`p_PC_W-1:0]    pred_pc
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  The body is deliberately empty: every output reports itself
  // as not implemented until the fetch block is built.
  always @(posedge clk) begin
    assert (1'b0) else $error("not implemented: if_stage.if_req_valid");
    assert (1'b0) else $error("not implemented: if_stage.if_req_addr");
    assert (1'b0) else $error("not implemented: if_stage.instr");
    assert (1'b0) else $error("not implemented: if_stage.pred_taken");
    assert (1'b0) else $error("not implemented: if_stage.pred_pc");
  end

endmodule

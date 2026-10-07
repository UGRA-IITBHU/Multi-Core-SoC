`default_nettype none
// ============================================================================
// hazard_unit - load-use hazard interlock.
//
// Purpose: report the decode-stage stall needed for a load-use hazard.  That is
// the module's whole job.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   id_uses_rs1       input  1  decode instruction reads rs1
//   id_uses_rs2       input  1  decode instruction reads rs2
//   id_rs1_addr       input  5  rs1 index of the decode instruction
//   id_rs2_addr       input  5  rs2 index of the decode instruction
//   ex_mem_read       input  1  EX/MEM instruction is a load
//   ex_mem_write      input  1  EX/MEM instruction is a store
//   ex_rd_addr        input  5  rd of the EX/MEM instruction
//   id_stall          output 1  hold the decode stage this cycle
//
// Guarantee to `core`: `id_stall` is asserted for exactly one cycle for each
// load-use dependency and covers every non-forwardable case.  It is
// combinational over the listed inputs only, so there is no hidden pipeline
// state.
//
// Note - no MEM stall, no wb_stall.  There is deliberately no
// `ex_stall_from_mem` output: a MEM stall is `mem_req_valid && !mem_rsp_valid`,
// and `core` derives it directly because `core` owns both the memory request and
// the stall chain.  A previous revision of this contract gave this module a
// `mem_rsp_valid` input with the OPPOSITE sense to the identically named signal
// at `lsu` and `core`; that input has been removed rather than repeated.  There
// is also no `wb_stall` output: in phase 1 the memory stage is a single-cycle
// pass-through, so nothing downstream of writeback could consume such a signal.
// If a multi-cycle memory or a wider writeback port is added later, adding
// `wb_stall` is a contract change under the gate in the plan.
//
// WHY ONE STALL IS ENOUGH, AND WHY ONLY LOADS NEED ONE
//
// The EX/MEM instruction is two stages ahead of the decode instruction.  After
// one stall the load reaches writeback while the decode instruction reaches
// execute, so the operand is available exactly when it is first needed, and
// `regfile`'s writeback bypass (regfile.v, "WRITE-BACK BYPASS") supplies it
// with no further stall.  That is why this is a one-cycle interlock and not a
// hold-until-clear one.
//
// Every other producer is covered without a stall by `forwarding`:
//   ALU result in EX      -> forwarded from EX/MEM by `forwarding`
//   ALU result in MEM/WB  -> forwarded, or bypassed by `regfile`
//   load result in MEM    -> the one value that is NOT ready in time
// A store writes memory and never writes a register, so it can never be the
// source of a dependency, which is what `ex_mem_write` records.
//
// Drop-in replaceable: this file builds and lints from its own source alone.
// Replacing it with another implementation must not change the port list and
// must not require any other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"

module hazard_unit (
  input  wire                     id_uses_rs1,
  input  wire                     id_uses_rs2,
  input  wire [`p_REG_ADDR_W-1:0] id_rs1_addr,
  input  wire [`p_REG_ADDR_W-1:0] id_rs2_addr,
  input  wire                     ex_mem_read,
  input  wire                     ex_mem_write,
  input  wire [`p_REG_ADDR_W-1:0] ex_rd_addr,
  output wire                     id_stall
);

  // x0's index, declared at the address width rather than as a bare integer.
  // Same reason as REG_ADDR0 in regfile.v: a bare `0` is silently widened to
  // `p_REG_ADDR_W` bits in each comparison, which is the same value but is a
  // WIDTHEXPAND warning, and a WIDTHEXPAND is a failure under -Wall.
  localparam [`p_REG_ADDR_W-1:0] REG_ADDR0 = {`p_REG_ADDR_W{1'b0}};

  // --- does the EX/MEM instruction produce a late value? ----------------------
  // Only a load does.  A load's data does not exist until the memory interface
  // answers, so it cannot be forwarded from EX/MEM the way an ALU result can.
  //
  // `!ex_mem_write` is redundant for well-formed input - a load is not also a
  // store, so the two bits are never both set - and it is kept deliberately: it
  // names the invariant in the gate instead of relying on it, so that a store
  // can never be turned into a stall by a future edit to a producer that drives
  // these bits more loosely.  The assertion at the foot of the module checks it.
  wire ex_mem_is_load = ex_mem_read && !ex_mem_write && (ex_rd_addr != REG_ADDR0);

  // --- does the decode instruction want that value? --------------------------
  // The address comparison is only meaningful for a source the instruction
  // actually reads: an unused rs field still carries whatever bits the opcode
  // put there, and comparing it would manufacture a spurious dependency.
  wire dep_on_rs1 = id_uses_rs1 && (id_rs1_addr == ex_rd_addr);
  wire dep_on_rs2 = id_uses_rs2 && (id_rs2_addr == ex_rd_addr);

  // One combinational term: no pipeline state, so there is nothing to reset and
  // nothing to initialise.  Either source is enough to hold decode.
  assign id_stall = ex_mem_is_load && (dep_on_rs1 || dep_on_rs2);

  // --------------------------------------------------------------------------
  // Invariants.  This module has no `clk` - the frozen port list gives it none,
  // and it holds no state - so the check is combinational rather than sampled on
  // a clock edge, matching `decode.v`, the other purely combinational module.
  //
  // Each assertion is ONE LINE on purpose: scripts/yosys-prep.sh deletes exactly
  // whole-line `assert (...) else $error(...);` statements, because Yosys's
  // parser rejects the action clause.  A wrapped assertion would survive the
  // deletion and fail asic-check.
  // --------------------------------------------------------------------------
  always @(*) begin
    // Regression check on the `!ex_mem_write` term above: a store writes memory
    // and never a register, so it can never be the source of a dependency.  If a
    // future edit drops that term, this fires on exactly the cycles that
    // regressed.
    //
    // The comparisons are `===` rather than `==`/`&&` DELIBERATELY.  A
    // combinational block evaluates once while the inputs are still X at time
    // zero, and `assert (!(X && X))` is `assert (!X)`, which FAILS - the
    // test_stubs.py wrapper then reports this as a spurious
    // "stall asserted for a store" before any input has settled.  Case equality
    // yields a hard 0 for an X operand, so the assertion is X-safe while still
    // firing whenever both signals are genuinely 1.  This is the same reasoning
    // as regfile.v's "it also makes the guard X-safe", reached here by case
    // equality because `id_stall` is derived from the very inputs that are X.
    assert (!((id_stall === 1'b1) && (ex_mem_write === 1'b1))) else $error("hazard_unit: stall asserted for a store");
  end

endmodule
`default_nettype wire

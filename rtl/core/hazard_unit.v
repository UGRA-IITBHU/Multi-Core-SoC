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
// Drop-in replaceable: this file currently holds only the frozen port list.
// Replacing it with a real implementation must not change the port list and
// must not require any other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"

/* verilator lint_off UNDRIVEN */
/* verilator lint_off UNUSEDSIGNAL */
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
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  Combinational module, so the not-implemented assertion
  // reports at time zero, before any input has settled.
  initial begin
    assert (1'b0) else $error("not implemented: hazard_unit.id_stall");
  end

endmodule
`default_nettype wire

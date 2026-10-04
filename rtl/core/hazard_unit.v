// ============================================================================
// hazard_unit - pipeline hazard detector.
//
// Purpose: report the decode-stage stall needed for a load-use hazard and the
// execute-stage stall needed while the memory stage is busy.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   id_uses_rs1       input  1  decode instruction reads rs1
//   id_uses_rs2       input  1  decode instruction reads rs2
//   id_rs1_addr       input  5  rs1 index of the decode instruction
//   id_rs2_addr       input  5  rs2 index of the decode instruction
//   ex_mem_read       input  1  EX/MEM instruction is a load
//   ex_mem_write      input  1  EX/MEM instruction is a store
//   ex_rd_addr        input  5  rd of the EX/MEM instruction
//   mem_rsp_valid     input  1  memory has not yet returned the outstanding data
//   id_stall          output 1  hold the decode stage this cycle
//   ex_stall_from_mem output 1  hold the execute stage this cycle
//
// Guarantee to `core`: `id_stall` is asserted for exactly one cycle for each
// load-use dependency and covers every non-forwardable case; `ex_stall_from_mem`
// is asserted for exactly as long as the memory stage holds an outstanding
// data access, so a single-cycle memory response produces no stall at all.
// Both outputs are combinational and depend only on the listed inputs, so
// there is no hidden pipeline state.
//
// Note: there is deliberately no `wb_stall` output.  In phase 1 the memory
// stage is a single-cycle pass-through, so nothing downstream of writeback
// could ever consume such a signal.  If a multi-cycle memory or a wider
// writeback port is added later, adding `wb_stall` is a contract change under
// the gate in the plan.
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
  input  wire                     mem_rsp_valid,
  output wire                     id_stall,
  output wire                     ex_stall_from_mem
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  Combinational module, so the not-implemented assertion
  // reports at time zero, before any input has settled.
  initial begin
    assert (1'b0) else $error("not implemented: hazard_unit.id_stall");
    assert (1'b0) else $error("not implemented: hazard_unit.ex_stall_from_mem");
  end

endmodule

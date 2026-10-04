// ============================================================================
// core - top level of the RV32IMAC 5-stage pipelined SoC.
//
// Purpose: instantiate and connect the whole pipeline, own the four pipeline
// registers, and expose the data memory interface to the outside world.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   clk            input  1   rising-edge clock
//   rst_n          input  1   active-low synchronous reset
//   mem_rsp_rdata  input  32  data returned by memory
//   mem_rsp_valid  input  1   memory has returned data
//   mem_req_valid  output 1   request is being presented to memory
//   mem_req_addr   output 32  request address
//   mem_req_wdata  output 32  request write data
//   mem_req_we     output 1   request is a write
//
// Guarantee to the surrounding system: the data memory interface is exposed at
// the top level under exactly the names `lsu` uses for it, so a memory
// subsystem or an AXI bridge attaches without any hierarchical reference into
// this design.  The instruction memory interface is deliberately absent: in
// phase 1 instruction memory is internal to `if_stage`.
//
// Note: this module owns all bundle packing.  It assembles `if_id__*`,
// `id_ex__*`, `ex_mem__*` and `mem_rd_*` using the offsets in
// pipeline_regs.vh from its stages' discrete signals.  `id_ex__*` in
// particular is assembled here, from `decode` control fields, `regfile` read
// data and `imm_gen` output; no stage module packs a bundle itself.
//
// Drop-in replaceable: this file currently holds only the frozen port list.
// Replacing it with a real implementation must not change the port list and
// must not require any other module to change.  It is the one module that
// instantiates the other twelve, so it is the only file that may reference
// them.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"
`include "ctrl_fields.vh"
`include "pipeline_regs.vh"

/* verilator lint_off UNDRIVEN */
/* verilator lint_off UNUSEDSIGNAL */
module core (
  input  wire                 clk,
  input  wire                 rst_n,
  input  wire [`p_DATA_W-1:0] mem_rsp_rdata,
  input  wire                 mem_rsp_valid,
  output wire                 mem_req_valid,
  output wire [`p_ADDR_W-1:0] mem_req_addr,
  output wire [`p_DATA_W-1:0] mem_req_wdata,
  output wire                 mem_req_we
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  The body is deliberately empty: every output reports itself
  // as not implemented until the pipeline is integrated.
  always @(posedge clk) begin
    assert (1'b0) else $error("not implemented: core.mem_req_valid");
    assert (1'b0) else $error("not implemented: core.mem_req_addr");
    assert (1'b0) else $error("not implemented: core.mem_req_wdata");
    assert (1'b0) else $error("not implemented: core.mem_req_we");
  end

endmodule

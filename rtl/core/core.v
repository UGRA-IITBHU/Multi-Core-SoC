// ============================================================================
// core - top level of the RV32IMAC 5-stage pipelined SoC.
//
// Purpose: instantiate and connect the whole pipeline, own the four pipeline
// registers, and expose both memory port pairs to the outside world.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   clk            input  1   rising-edge clock
//   rst_n          input  1   active-low synchronous reset
//   if_rsp_rdata   input  32  instruction returned by fetch memory
//   if_rsp_valid   input  1   fetch memory has returned an instruction
//   mem_rsp_rdata  input  32  data returned by memory
//   mem_rsp_valid  input  1   memory has returned data
//   if_req_valid   output 1   fetch request is being presented to memory
//   if_req_addr    output 32  fetch request address
//   mem_req_valid  output 1   request is being presented to memory
//   mem_req_addr   output 32  request address
//   mem_req_wdata  output 32  request write data
//   mem_req_we     output 1   request is a write
//   mem_req_wstrb  output 4   per-byte write enables, one bit per byte lane
//   stage_valid    output 4   verification observability, see below
//
// Guarantee to the surrounding system: both memory interfaces are exposed at
// the top level under exactly the names their owners use for them - the fetch
// pair exactly as `if_stage` names it, the load/store pair exactly as `lsu`
// names it - so a memory subsystem or an AXI bridge attaches without any
// hierarchical reference into this design.
//
// Note - two ports, one address space: instruction fetch and load/store have
// separate port pairs even though both address the same unified memory.  Phase
// 4 gives the core separate L1 I$ and D$ that need independent bandwidth; a
// single arbitrated port would force the fetch path to be redesigned then, and
// would stall instruction fetch whenever the load/store unit is active.  The
// data memory port therefore has two owners: `if_stage` for fetch and `lsu` for
// load/store.
//
// `mem_req_wstrb` is the load/store pair's byte-enable bus, one bit per byte
// lane, driven from `lsu`.  It is the only way a sub-word store is expressed.
//
// `stage_valid` is a VERIFICATION-OBSERVABILITY port, not a functional output.
// Bit 0 is `if_id__valid`, bit 1 `id_ex__valid`, bit 2 `ex_mem__valid`, bit 3
// `mem_wb__valid`.  Those four bits are real fields of the four bundles, and
// `core` forces all of them low while `rst_n` is asserted.  `stage_valid`
// publishes them at the top level so a testbench can check the reset-validity
// guarantee without a hierarchical reference.  It stays through phase 10.
//
// Note: this module owns all bundle packing.  It assembles `if_id__*`,
// `id_ex__*`, `ex_mem__*` and `mem_wb__*` using the offsets in
// pipeline_regs.vh from its stages' discrete signals.  `id_ex__*` in
// particular is assembled here, from `decode` control fields, `regfile` read
// data and `imm_gen` output; no stage module packs a bundle itself.
//
// Three bundle fields are produced by wiring in this module rather than by a
// stage module, because the value is already here or is a fixed bit range:
// the register indices `rs1_addr` / `rs2_addr` / `rd_addr`, taken straight from
// `instr` and supplied both to `regfile` in ID and to the ID/EX bundle;
// `ex_mem__pc`, copied from `id_ex__pc`; and the data-misalignment gate on
// `mem_wb__reg_write`, applied as `mem_reg_write && !mem_stage.data_misaligned`.
// This module also derives the MEM stall itself, as
// `mem_req_valid && !mem_rsp_valid`.
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
  input  wire                  clk,
  input  wire                  rst_n,
  input  wire [`p_INSTR_W-1:0] if_rsp_rdata,
  input  wire                  if_rsp_valid,
  input  wire [`p_DATA_W-1:0]  mem_rsp_rdata,
  input  wire                  mem_rsp_valid,
  output wire                  if_req_valid,
  output wire [`p_PC_W-1:0]    if_req_addr,
  output wire                  mem_req_valid,
  output wire [`p_ADDR_W-1:0]  mem_req_addr,
  output wire [`p_DATA_W-1:0]  mem_req_wdata,
  output wire                  mem_req_we,
  output wire [3:0]            mem_req_wstrb,
  output wire [3:0]            stage_valid
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  The body is deliberately empty: every output reports itself
  // as not implemented until the pipeline is integrated.
  always @(posedge clk) begin
    assert (1'b0) else $error("not implemented: core.if_req_valid");
    assert (1'b0) else $error("not implemented: core.if_req_addr");
    assert (1'b0) else $error("not implemented: core.mem_req_valid");
    assert (1'b0) else $error("not implemented: core.mem_req_addr");
    assert (1'b0) else $error("not implemented: core.mem_req_wdata");
    assert (1'b0) else $error("not implemented: core.mem_req_we");
    assert (1'b0) else $error("not implemented: core.mem_req_wstrb");
    assert (1'b0) else $error("not implemented: core.stage_valid");
  end

endmodule

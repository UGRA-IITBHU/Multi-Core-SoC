`default_nettype none
// ============================================================================
// lsu - load/store unit and owner of the data memory interface.
//
// Purpose: turn an EX/MEM access into a memory request, hold it until it is
// granted, capture the returned data, and flag misaligned accesses.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   clk             input  1    rising-edge clock
//   rst_n           input  1    active-low synchronous reset
//   stall           input  1    hold the outstanding request
//   ex_mem_addr     input  32   effective address from `ex_stage`
//   ex_store_data   input  32   value to write on a store
//   ex_mem_read     input  1    access is a load
//   ex_mem_write    input  1    access is a store
//   ex_mem_size     input  2    0 = byte, 1 = half, 2 = word
//   ex_mem_unsigned input  1    load is unsigned
//   ex_rd_addr      input  5    destination register index
//   ex_reg_write    input  1    access writes rd
//   ex_wb_sel       input  2    writeback source select for a load
//   mem_rsp_rdata   input  32   data returned by memory
//   mem_rsp_valid   input  1    memory has returned data
//   mem_req_valid   output 1    request is being presented to memory
//   mem_req_addr    output 32   request address
//   mem_req_wdata   output 32   request write data
//   mem_req_we      output 1    request is a write
//   mem_req_wstrb   output 4    per-byte write enables, one bit per byte lane
//   data_misaligned output 1    misaligned word or halfword access
//   mem_rd_addr     output 5    destination register index for MEM/WB
//   mem_reg_write   output 1    MEM/WB writes rd
//   mem_wb_sel      output 2    MEM/WB writeback source select
//
// Guarantee to `core` and `mem_stage`: `mem_req_valid` stays high from the
// cycle the request is presented until `mem_rsp_valid` is seen, and
// `mem_req_addr`, `mem_req_wdata` and `mem_req_we` remain stable for the
// whole of that window, so memory may accept the request at its own pace.
// `mem_rsp_rdata` is passed straight through to `mem_stage`.  This module owns
// the load/store port pair only: instruction fetch has its own pair,
// `if_req_*` / `if_rsp_*`, owned by `if_stage`, because phase 4 gives the core
// separate L1 I$ and D$ that need independent bandwidth.
//
// `mem_req_wstrb` carries one enable bit per byte lane and is the only way a
// sub-word store is expressed.  It is asserted for writes and driven to zero
// for reads.  It is derived here, from `ex_mem_addr[1:0]` together with the
// `ex_mem_size` this module already receives, so the derivation lives in one
// place and `core` and the memory subsystem both see the same lanes.
//
// `data_misaligned` is raised for a misaligned word or halfword access rather
// than silently performing the access.  `core` uses it to suppress the
// MEM/WB register write; this module only reports the condition.
//
// Drop-in replaceable: this file currently holds only the frozen port list.
// Replacing it with a real implementation must not change the port list and
// must not require any other module to change.  `mem_req_*` and `mem_rsp_*`
// are also the top-level port names of `core`, so they must not be renamed
// without changing `core` in the same commit.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"
`include "ctrl_fields.vh"

/* verilator lint_off UNDRIVEN */
/* verilator lint_off UNUSEDSIGNAL */
module lsu (
  input  wire                     clk,
  input  wire                     rst_n,
  input  wire                     stall,
  input  wire [`p_ADDR_W-1:0]     ex_mem_addr,
  input  wire [`p_DATA_W-1:0]     ex_store_data,
  input  wire                     ex_mem_read,
  input  wire                     ex_mem_write,
  input  wire [`p_MEM_SIZE_W-1:0] ex_mem_size,
  input  wire                     ex_mem_unsigned,
  input  wire [`p_REG_ADDR_W-1:0] ex_rd_addr,
  input  wire                     ex_reg_write,
  input  wire [`p_WB_SEL_W-1:0]   ex_wb_sel,
  input  wire [`p_DATA_W-1:0]     mem_rsp_rdata,
  input  wire                     mem_rsp_valid,
  output wire                     mem_req_valid,
  output wire [`p_ADDR_W-1:0]     mem_req_addr,
  output wire [`p_DATA_W-1:0]     mem_req_wdata,
  output wire                     mem_req_we,
  output wire [3:0]               mem_req_wstrb,
  output wire                     data_misaligned,
  output wire [`p_REG_ADDR_W-1:0] mem_rd_addr,
  output wire                     mem_reg_write,
  output wire [`p_WB_SEL_W-1:0]   mem_wb_sel
);
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNDRIVEN */

  // Phase-1 stub.  The body is deliberately empty: every output reports itself
  // as not implemented until the memory block is built.
  always @(posedge clk) begin
    assert (1'b0) else $error("not implemented: lsu.mem_req_valid");
    assert (1'b0) else $error("not implemented: lsu.mem_req_addr");
    assert (1'b0) else $error("not implemented: lsu.mem_req_wdata");
    assert (1'b0) else $error("not implemented: lsu.mem_req_we");
    assert (1'b0) else $error("not implemented: lsu.mem_req_wstrb");
    assert (1'b0) else $error("not implemented: lsu.data_misaligned");
    assert (1'b0) else $error("not implemented: lsu.mem_rd_addr");
    assert (1'b0) else $error("not implemented: lsu.mem_reg_write");
    assert (1'b0) else $error("not implemented: lsu.mem_wb_sel");
  end

endmodule
`default_nettype wire

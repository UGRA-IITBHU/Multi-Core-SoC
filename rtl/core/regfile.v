`default_nettype none
// ============================================================================
// regfile - 32x32 register file with combinational reads and clocked writes.
//
// Purpose: supply the two decode-stage operand read ports and absorb the
// single writeback port.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   clk        input  1    rising-edge clock
//   rst_n      input  1    active-low synchronous reset to all-zero
//   rs1_addr   input  5    first source register index
//   rs2_addr   input  5    second source register index
//   rs1_used   input  1    instruction reads rs1; when low the read is forced 0
//   rs2_used   input  1    instruction reads rs2; when low the read is forced 0
//   wb_we      input  1    commit the writeback port this cycle
//   wb_waddr   input  5    writeback destination index
//   wb_wdata   input  32   writeback data
//   rs1_data   output 32   rs1 value after writeback bypass
//   rs2_data   output 32   rs2 value after writeback bypass
//
// Guarantee to `ex_stage` via `core`: reads are combinational and bypass the
// writeback port in the same cycle, so a load-use distance of one needs no
// hazard stall; `rs1_data`/`rs2_data` are exactly `0` when the corresponding
// `*_used` is low, and reading `x0` always yields `0`.  Writes to `x0` are
// discarded here as well as at `wb_stage`, so the discard is enforced at both
// ends of the writeback path.
//
// x0 IS DISCARDED TWICE, DELIBERATELY
//
// The contract says "discarded twice", and the two discards fail differently,
// which is the reason for doing both:
//
//   1. The write port is gated with `wb_we && (wb_waddr != 0)`, so nothing ever
//      reaches the storage array at index 0.  This is what protects the array.
//   2. Every read of index 0 is forced to 0 independently of the array
//      contents, by the `addr == 0` term in each read mux.
//
// Discard 1 alone would be enough for `addi x0, x0, 1`, but it depends on the
// array initialising correctly.  Discard 2 makes `x0` read as 0 even if the
// array is uninitialised, and it keeps the guarantee independent of reset.
// Both are kept because `wb_stage` applies the same rule at the other end of
// the path, and the ISA depends on the discard surviving a change to either
// module.
//
// WRITE-BACK BYPASS
//
// The read mux prefers the writeback port over the array whenever the write is
// committed and the address matches.  That makes a WB->ID distance of one cost
// zero stall cycles, which is what the contract's "load-use distance of one
// needs no hazard stall" guarantee rests on.  The bypass is gated on the same
// `wb_we && (wb_waddr != 0)` term as the write itself, so a discarded write to
// x0 is also not visible on the read side.
//
// Drop-in replaceable: this file builds and lints from its own source alone.
// Replacing it with another implementation must not change the port list and
// must not require any other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"

module regfile (
  input  wire                   clk,
  input  wire                   rst_n,
  input  wire [`p_REG_ADDR_W-1:0] rs1_addr,
  input  wire [`p_REG_ADDR_W-1:0] rs2_addr,
  input  wire                   rs1_used,
  input  wire                   rs2_used,
  input  wire                   wb_we,
  input  wire [`p_REG_ADDR_W-1:0] wb_waddr,
  input  wire [`p_XLEN-1:0]     wb_wdata,
  output wire [`p_XLEN-1:0]     rs1_data,
  output wire [`p_XLEN-1:0]     rs2_data
);

  localparam integer NREGS = 32;

  // x0's index, declared at the address width rather than as a bare integer so
  // every comparison against it is width-exact and Verilator's -Wall stays
  // silent.  A plain `0` here is silently widened to 32 bits in each
  // comparison, which is the same value but is a WIDTHEXPAND warning and a
  // WIDTHEXPAND is a failure under -Wall.
  localparam [`p_REG_ADDR_W-1:0] REG_ADDR0 = {`p_REG_ADDR_W{1'b0}};

  // The architectural state.  `regs[0]` is never written (see the write gate
  // below) and is never read as storage (see the read muxes); it exists only so
  // the array is a complete 32 entries for synthesis and for review.
  reg [`p_XLEN-1:0] regs [0:NREGS-1];

  integer i;

  // --- synchronous reset ---------------------------------------------------
  // Reset is synchronous and clears the whole array, so a register read
  // immediately after reset deasserts is a defined 0 rather than whatever the
  // flops happened to power up with.  Verilator's two-state model would hide
  // that difference, which is why `make test-4state` exists.
  always @(posedge clk) begin
    if (!rst_n) begin
      for (i = 0; i < NREGS; i = i + 1) begin
        regs[i] <= {`p_XLEN{1'b0}};
      end
    end else if (wb_we && (wb_waddr != REG_ADDR0)) begin
      // Write port.  `wb_waddr != 0` is the first of the two x0 discards.
      regs[wb_waddr] <= wb_wdata;
    end
  end

  // --- writeback bypass enable ---------------------------------------------
  // The same term that permits the write also permits the bypass, so the two
  // can never disagree.
  wire wb_commit = wb_we && (wb_waddr != REG_ADDR0);

  // --- read ports, purely combinational ------------------------------------
  // Priority per port: unused -> x0 -> writeback bypass -> array.  The x0 term
  // is the second of the two x0 discards.
  wire [`p_XLEN-1:0] rs1_mux = (!rs1_used)            ? {`p_XLEN{1'b0}} :
                               (rs1_addr == REG_ADDR0) ? {`p_XLEN{1'b0}} :
                               (wb_commit && (wb_waddr == rs1_addr))
                                                         ? wb_wdata
                                                         : regs[rs1_addr];

  wire [`p_XLEN-1:0] rs2_mux = (!rs2_used)            ? {`p_XLEN{1'b0}} :
                               (rs2_addr == REG_ADDR0) ? {`p_XLEN{1'b0}} :
                               (wb_commit && (wb_waddr == rs2_addr))
                                                         ? wb_wdata
                                                         : regs[rs2_addr];

  assign rs1_data = rs1_mux;
  assign rs2_data = rs2_mux;

  // --- a write to x0 must never change it ------------------------------------
  // Review Focus 3 (plan, Task 3) turned into hardware's own check: if a future
  // edit routes an index-0 write around the gate above, this fires on exactly
  // that cycle.
  //
  // The condition is folded *into* the assertion rather than wrapped around it in
  // an `if`, for a mechanical reason worth knowing about:
  // scripts/yosys-prep.sh deletes exactly whole-line
  // `assert (...) else $error(...);` statements, because Yosys's parser rejects
  // the `else` action clause.  If the guard were an `if` on its own line, the
  // deletion would leave `if (cond)` with an empty statement list and Yosys
  // would fail to parse the file - a loud failure, but one that blocks
  // synthesis rather than testing anything.
  //
  // Folding it in also makes the guard X-safe.  Verilog's `&&` yields 0 if any
  // operand is a definite 0, so while `rst_n` is low - or while no write to x0
  // is in flight - the term is 0 regardless of the array's power-up value, and
  // the assertion cannot fire on a legitimately uninitialised `regs[0]`.
  always @(posedge clk) begin
    assert (!(rst_n && wb_we && (wb_waddr == REG_ADDR0) && (regs[REG_ADDR0] != {`p_XLEN{1'b0}}))) else $error("regfile: a write to x0 changed it to %h", regs[REG_ADDR0]);
  end

endmodule
`default_nettype wire

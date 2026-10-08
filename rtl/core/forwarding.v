`default_nettype none
// ============================================================================
// forwarding - operand forwarding network.
//
// Purpose: supply `ex_stage` with the newest architectural value for each
// operand, selecting between the MEM-stage and the WB-stage producer.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   ex_rs1_addr    input  5   rs1 index of the instruction in execute
//   ex_rs2_addr    input  5   rs2 index of the instruction in execute
//   id_uses_rs1    input  1   the decode instruction reads rs1
//   id_uses_rs2    input  1   the decode instruction reads rs2
//   mem_rd_addr    input  5   destination of the MEM-stage value
//   mem_rd_data    input  32  MEM-stage value
//   mem_reg_write  input  1   the MEM-stage value is valid
//   fwd_rd_addr    input  5   destination of the WB-stage value
//   fwd_rd_data    input  32  WB-stage value
//   fwd_reg_write  input  1   the WB-stage value is valid
//   fwd_rs1_valid  output 1   forward into `ex_rs1_data`
//   fwd_rs1_data   output 32  forwarded rs1 operand
//   fwd_rs2_valid  output 1   forward into `ex_rs2_data`
//   fwd_rs2_data   output 32  forwarded rs2 operand
//
// Guarantee to `ex_stage`: when `fwd_rs1_valid` is high, `fwd_rs1_data` is
// the newest value written to `ex_rs1_addr` by any earlier instruction, and
// `fwd_rs1_valid` is low when no forwarding is needed.  Where both the MEM
// and the WB stage can supply the operand, the MEM stage wins, because it is
// the younger value.  `x0` is never forwarded: `mem_reg_write` and
// `fwd_reg_write` already exclude `x0` at their producers.  The decode-stage
// `id_rs1_addr` / `id_rs2_addr` inputs are present so that a hazard that
// cannot be forwarded is reported to `core` rather than silently mis-resolved.
//
// MEM WINS OVER WB, AND WHY THAT IS THE ONLY PRIORITY THAT MATTERS
//
// The two producers are the two youngest instructions that can have written
// `ex_rs1_addr`, and the MEM-stage one is younger by one.  So a value arriving
// from MEM supersedes the same register's value arriving from WB, and the
// network is two independent equality tests with MEM taking the first.  There
// is no third producer to arbitrate against: the EX stage's own result is this
// cycle's output, and a load's data is not in this network at all -- it is the
// one value `forwarding` cannot supply, which is why `hazard_unit` exists and
// holds decode for that cycle instead.
//
// `id_uses_rs1` / `id_uses_rs2` GATE THE VALID FLAGS
//
// The address inputs `ex_rs1_addr` / `ex_rs2_addr` carry whatever bits the
// encoding put in that field whether or not the instruction reads that
// register: for `lui` and `addi`, bits [19:15] are part of the immediate.  So
// an address match on its own is not evidence of a dependency.  Gating each
// match on the corresponding `id_uses_*` is what keeps `fwd_*_valid` meaning
// "this operand is being replaced", which is what `ex_stage` acts on; a match
// on an unread source would report a forward that nothing consumes.
//
// x0 IS EXCLUDED HERE AS WELL AS AT ITS PRODUCERS
//
// The contract already excludes `x0` at `mem_reg_write` / `fwd_reg_write`, so
// neither term can fire for `rd == 0` on its own.  The explicit `!= REG_ADDR0`
// is kept deliberately for the same reason regfile.v discards an x0 write
// twice: it makes this module's guarantee independent of its producers, so a
// future edit to `mem_stage` or `wb_stage` that lets an x0 write through
// cannot start forwarding a non-zero value into an instruction that reads x0.
// The cost is two comparators that must be correct, and the alternative is
// trusting three modules at once to stay in step.
//
// Drop-in replaceable: this file builds and lints from its own source alone.
// Replacing it with another implementation must not change the port list and
// must not require any other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"

module forwarding (
  input  wire [`p_REG_ADDR_W-1:0] ex_rs1_addr,
  input  wire [`p_REG_ADDR_W-1:0] ex_rs2_addr,
  input  wire                     id_uses_rs1,
  input  wire                     id_uses_rs2,
  input  wire [`p_REG_ADDR_W-1:0] mem_rd_addr,
  input  wire [`p_XLEN-1:0]       mem_rd_data,
  input  wire                     mem_reg_write,
  input  wire [`p_REG_ADDR_W-1:0] fwd_rd_addr,
  input  wire [`p_XLEN-1:0]       fwd_rd_data,
  input  wire                     fwd_reg_write,
  output wire                     fwd_rs1_valid,
  output wire [`p_XLEN-1:0]       fwd_rs1_data,
  output wire                     fwd_rs2_valid,
  output wire [`p_XLEN-1:0]       fwd_rs2_data
);

  // x0's index, declared at the address width rather than as a bare integer.
  // Same reason as REG_ADDR0 in regfile.v and hazard_unit.v: a bare `0` is
  // silently widened to `p_REG_ADDR_W` bits in each comparison, which is the
  // same value but is a WIDTHEXPAND warning, and a WIDTHEXPAND is a failure
  // under -Wall.
  localparam [`p_REG_ADDR_W-1:0] REG_ADDR0 = {`p_REG_ADDR_W{1'b0}};

  // --- per-source producer matches -------------------------------------------
  // One match per (source, producer).  Both sources are computed independently
  // because rs1 and rs2 may legitimately be the same register.
  //
  // The `!id_uses_*` term is not optional: see the header note on the address
  // fields carrying immediate bits.  The `!= REG_ADDR0` term is the local half
  // of the x0 guarantee; see the header note on discarding x0 twice.
  wire mem_hits_rs1 = id_uses_rs1 && mem_reg_write &&
                      (mem_rd_addr != REG_ADDR0) && (mem_rd_addr == ex_rs1_addr);
  wire wb_hits_rs1  = id_uses_rs1 && fwd_reg_write &&
                      (fwd_rd_addr != REG_ADDR0) && (fwd_rd_addr == ex_rs1_addr);

  wire mem_hits_rs2 = id_uses_rs2 && mem_reg_write &&
                      (mem_rd_addr != REG_ADDR0) && (mem_rd_addr == ex_rs2_addr);
  wire wb_hits_rs2  = id_uses_rs2 && fwd_reg_write &&
                      (fwd_rd_addr != REG_ADDR0) && (fwd_rd_addr == ex_rs2_addr);

  // --- selection -------------------------------------------------------------
  // MEM first: it is the younger of the two producers, so when both match it is
  // the newer value and must win.  The data output is driven unconditionally
  // because `ex_stage` may read it without consulting the valid flag; the flag
  // is what says whether the value is meaningful.
  assign fwd_rs1_valid = mem_hits_rs1 || wb_hits_rs1;
  assign fwd_rs1_data  = mem_hits_rs1 ? mem_rd_data : fwd_rd_data;

  assign fwd_rs2_valid = mem_hits_rs2 || wb_hits_rs2;
  assign fwd_rs2_data  = mem_hits_rs2 ? mem_rd_data : fwd_rd_data;

  // --------------------------------------------------------------------------
  // No invariant assertions in this module, and that is a decision rather than
  // an omission.  An assertion is worth having only when the property it checks
  // is independent of the expression under test.  Here the candidate property is
  // "the MEM producer outranks the WB producer", and it cannot be asserted:
  //
  //   * Checking the INPUTS cannot work.  When both producers target the same
  //     register, the inputs look identical whether the data mux has the right
  //     priority or the wrong one, so an input-side test either never fires or
  //     fires on correct behaviour.  It is the latter that happened: a first
  //     attempt asserted "not both hit while their data differs", which is an
  //     entirely legal situation -- two consecutive instructions writing one
  //     register is ordinary, `addi x5, x5, 1` twice -- so it aborted the
  //     simulator on valid stimulus and took every later test with it.
  //   * Checking the OUTPUTS would be circular: the "expected" data is produced
  //     by the very mux being checked.
  //
  // So priority is verified where it can be observed independently, in
  // tb/test_forwarding.py, by driving both producers at the same register with
  // different data and requiring the MEM value on the output.  The x0 and
  // id_uses_* gates carry no such circularity and are covered by that testbench
  // too, over the whole address space.
  // --------------------------------------------------------------------------

endmodule
`default_nettype wire

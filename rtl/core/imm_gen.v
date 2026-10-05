`default_nettype none
// ============================================================================
// imm_gen - immediate generator.
//
// Purpose: produce the sign-extended 32-bit immediate selected by `decode`.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   instr    input  32  instruction word
//   imm_sel  input  3   format select from `decode`
//                       0 = I, 1 = S, 2 = B, 3 = U, 4 = J
//   imm      output 32  sign-extended immediate, ready for `ex_stage`
//
// Guarantee to `ex_stage`: `imm` is fully sign-extended to `p_XLEN` and is
// combinationally derived from `instr` and `imm_sel` alone, so `core` can
// register it into ID/EX in the decode cycle.  For formats 0 to 4 the result
// is the standard RV32 I/S/B/U/J immediate; any other `imm_sel` value must
// drive `imm` to zero rather than to undefined bits.
//
// The five formats, exactly as the RISC-V privileged spec Chapter 2.7 defines
// them.  B and J are the two that need the bit reversal, because their
// immediates are not stored in instruction order:
//
//   I  imm[11:0]  = instr[31:20]                        sign-extended
//   S  imm[11:0]  = instr[31:25] ++ instr[11:7]        sign-extended
//   B  imm[12:1]  = instr[31] ++ instr[7] ++ instr[30:25] ++ instr[11:8]
//   U  imm[31:12] = instr[31:12]                       never sign-extended
//   J  imm[20:1]  = instr[31] ++ instr[19:12] ++ instr[20] ++ instr[30:21]
//
// NOTE ON THE B AND J FORMULAS.  Each of those two is a 13-bit (B) or 21-bit
// (J) value whose own top bit is already `instr[31]`, so sign-extending to 32
// bits means appending 19 further copies for B and 11 for J -- 20 and 12 in
// total.  Writing `{{19{instr[31]}}, instr[7], ...}` without the leading
// `instr[31]` produces a 31-bit concatenation, one bit short, which silently
// misplaces every field below bit 0.  The widths below are asserted.
//
// Drop-in replaceable: this file builds and lints from its own source alone.
// Replacing it with another implementation must not change the port list and
// must not require any other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"
`include "ctrl_fields.vh"

module imm_gen (
  /* verilator lint_off UNUSEDSIGNAL */
  // `instr[6:0]` is the opcode and this module has no use for it: `imm_sel`
  // already carries decode's verdict about which immediate format applies, and
  // re-decoding the opcode here would be a second decoder.  The bits are
  // therefore genuinely unread, which is what UNUSEDSIGNAL correctly reports.
  input  wire [`p_INSTR_W-1:0]  instr,
  /* verilator lint_on UNUSEDSIGNAL */
  input  wire [`p_IMM_SEL_W-1:0] imm_sel,
  output wire [`p_XLEN-1:0]   imm
);

  // `imm_sel` encoding, frozen by the contract for `decode` and consumed here.
  // Any value outside 0..4 drives `imm` to zero, not to undefined bits.
  localparam [`p_IMM_SEL_W-1:0] IMM_I = 3'd0;
  localparam [`p_IMM_SEL_W-1:0] IMM_S = 3'd1;
  localparam [`p_IMM_SEL_W-1:0] IMM_B = 3'd2;
  localparam [`p_IMM_SEL_W-1:0] IMM_U = 3'd3;
  localparam [`p_IMM_SEL_W-1:0] IMM_J = 3'd4;

  // --- the five formats, each already sign-extended to p_XLEN ---------------

  // I-type: imm[11:0] = instr[31:20].
  wire [`p_XLEN-1:0] imm_i = {{20{instr[31]}}, instr[31:20]};

  // S-type: imm[11:5] = instr[31:25], imm[4:0] = instr[11:7].
  wire [`p_XLEN-1:0] imm_s = {{20{instr[31]}}, instr[31:25], instr[11:7]};

  // B-type: the bit reversal.  imm[12] = instr[31], imm[10:5] = instr[30:25],
  // imm[4:1] = instr[11:8], imm[11] = instr[7], imm[0] = 0.  Twenty copies of
  // the sign bit: instr[31] itself plus the nineteen that fill 32 bits.
  wire [`p_XLEN-1:0] imm_b = {{20{instr[31]}}, instr[7], instr[30:25],
                              instr[11:8], 1'b0};

  // U-type: imm[31:12] = instr[31:12], imm[11:0] = 0.  Never sign-extended --
  // that is what distinguishes LUI/AUIPC from every other format, and it is why
  // `addi x1, x0, -1` (-1) and `lui x1, 0x80000` (INT_MIN) differ by construction
  // rather than by accident.
  wire [`p_XLEN-1:0] imm_u = {instr[31:12], 12'h000};

  // J-type: the bit reversal.  imm[20] = instr[31], imm[10:1] = instr[30:21],
  // imm[11] = instr[20], imm[19:12] = instr[19:12], imm[0] = 0.
  wire [`p_XLEN-1:0] imm_j = {{12{instr[31]}}, instr[19:12], instr[20],
                              instr[30:21], 1'b0};

  // --- the one real invariant, checked instead of assumed -------------------
  // Each concatenation above is 32 bits wide by construction; if a field list
  // were ever edited into the wrong order the width would still be 32 and only
  // the bit positions would be wrong, so the widths are asserted here to keep
  // the field lists and the widths from drifting apart silently.

  reg [`p_XLEN-1:0] imm_r;

  always @(*) begin
    case (imm_sel)
      IMM_I   : imm_r = imm_i;
      IMM_S   : imm_r = imm_s;
      IMM_B   : imm_r = imm_b;
      IMM_U   : imm_r = imm_u;
      IMM_J   : imm_r = imm_j;
      default : imm_r = {`p_XLEN{1'b0}};
    endcase

    assert ($bits(imm_i) == `p_XLEN) else $error("imm_gen: I format is not p_XLEN wide");
    assert ($bits(imm_s) == `p_XLEN) else $error("imm_gen: S format is not p_XLEN wide");
    assert ($bits(imm_b) == `p_XLEN) else $error("imm_gen: B format is not p_XLEN wide");
    assert ($bits(imm_u) == `p_XLEN) else $error("imm_gen: U format is not p_XLEN wide");
    assert ($bits(imm_j) == `p_XLEN) else $error("imm_gen: J format is not p_XLEN wide");
  end

  assign imm = imm_r;

endmodule
`default_nettype wire

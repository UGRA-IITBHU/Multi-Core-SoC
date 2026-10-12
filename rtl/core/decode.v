`default_nettype none
// ============================================================================
// decode - RV32I instruction decoder.
//
// Purpose: turn one instruction word into the control bundle that drives
// `imm_gen`, `ex_stage`, `lsu`, `mem_stage` and `wb_stage`.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   instr          input  32  instruction word from `if_stage`
//   instr_eff      output 32  the word after RV32C expansion: the 32-bit
//                             equivalent of a compressed encoding, or `instr`
//                             unchanged for a 32-bit instruction.  `core` takes
//                             the register indices and the immediate from this,
//                             never from the raw word, because a compressed
//                             encoding carries both in different bit positions.
//   alu_op         output 4   ALU operation select (encoding owned by `alu`)
//   op1_sel        output 2   0 = rs1, 1 = pc, 2 = zero
//   op2_sel        output 3   0 = rs2, 1 = imm, 2 = 4, 3 = pc
//   imm_sel        output 3   immediate format select for `imm_gen`
//   branch_funct3  output 3   funct3 for branch comparison in `ex_stage`
//   is_branch      output 1   conditional branch (BEQ/BNE/BLT/BGE/BLTU/BGEU)
//   is_jal         output 1   JAL
//   is_jalr        output 1   JALR
//   is_illegal     output 1   opcode or funct encoding not implemented
//   uses_rs1       output 1   instruction reads rs1
//   uses_rs2       output 1   instruction reads rs2
//   uses_rd        output 1   the rd field is meaningful
//   mem_read       output 1   instruction is a load
//   mem_write      output 1   instruction is a store
//   mem_size       output 2   0 = byte, 1 = half, 2 = word
//   mem_unsigned   output 1   load is unsigned (LBU / LHU)
//   reg_write      output 1   instruction writes rd
//   wb_sel         output 2   0 = alu, 1 = mem, 2 = pc+4
//
// Guarantee to `imm_gen` and `ex_stage`: every output describes exactly one
// instruction, combinationally and with no pipeline state, so `core` can pack
// them into ID/EX in the same cycle the instruction is decoded.  `imm_sel`
// encoding is 0 = I, 1 = S, 2 = B, 3 = U, 4 = J.  `mem_size` is meaningful
// only when `mem_read` or `mem_write` is high, and is `0` otherwise.
//
// Note - what `is_illegal` does and does not cover.  It is the CANONICAL
// illegal-instruction signal for the whole design: high when the opcode or a
// funct field encodes something this core does not implement.  Two other
// misalignment conditions exist and neither uses this name, because they have
// different owners and different stages: `lsu.data_misaligned` is a misaligned
// *data* access, and `ex_stage.ex_target_misaligned` is a misaligned branch,
// JAL or JALR *target*.  Carrying `is_illegal` on to a trap or to writeback
// suppression is `core`'s job, because `core` owns the bundles; see
// docs/contracts/phase1-interfaces.md.
//
// ---------------------------------------------------------------------------
// DESIGN NOTE 1 - every output DEFAULTS TO ILLEGAL, NEVER TO A WORKING OP
//
// The defaults at the top of the combinational block are
//
//     is_illegal = 1, reg_write = 0, mem_read = 0, mem_write = 0,
//     uses_rs1 = uses_rs2 = uses_rd = 0, is_branch = is_jal = is_jalr = 0
//
// and each recognised encoding *clears* `is_illegal` on its way past.  This is
// the opposite of the usual decoder shape, where a case statement has a
// `default:` arm that does something harmless.  That shape is a bug factory:
// an opcode nobody thought about falls into `default: alu_op <= ADD` and the
// core silently executes an add on garbage operands.  Here an unknown encoding
// produces `is_illegal = 1` and no side effect at all.  Review Focus 5 (plan,
// Task 3) is exactly this, and its named test is that `0xFFFF_FFFF` decodes
// illegal and performs no add.
//
// ---------------------------------------------------------------------------
// DESIGN NOTE 2 - THE `alu_op` ENCODING, WHICH P3's `alu` MUST MATCH
//
// `docs/contracts/phase1-interfaces.md` deliberately leaves the `alu_op`
// encoding unenumerated: "The `alu_op` encoding is internal to the execute
// block ... and is therefore not enumerated here."  That means P2 (this file)
// and P3 (`alu.v`) have to agree on it, and the only place it can be written
// down is here.  It is:
//
//     4'd0 ALU_ADD    4'd5 ALU_XOR
//     4'd1 ALU_SUB    4'd6 ALU_SRL
//     4'd2 ALU_SLL    4'd7 ALU_SRA
//     4'd3 ALU_SLT    4'd8 ALU_OR
//     4'd4 ALU_SLTU   4'd9 ALU_AND
//
// Ten encodings, which is what the ISA has, in a 4-bit field.  4'd10..4'd15
// are unused and are not produced by any legal encoding.
//
// This is a cross-owner coupling that cannot be expressed in the frozen port
// list, so it is called out here, in `alu.v`'s header when P3 writes it, and
// in the report.  It is a naming/encoding agreement, not a port change, so it
// needs no contract change -- but if P3 picks a different table, one of the two
// files has to move and only P2's is being handed in now.
//
// ---------------------------------------------------------------------------
// DESIGN NOTE 3 - BRANCHES REQUEST ALU_SUB, AND WHY THAT IS THE ROBUST CHOICE
//
// A conditional branch needs a comparison, and the contract gives `ex_stage`
// exactly one ALU instance whose `zero`, `slt` and `sltu` outputs are all
// "consistent with each other in the same cycle".  `alu_op <= ALU_SUB` is
// correct under either of the two implementations `alu` might use:
//
//   * if `slt` is computed as `($signed(op_a) < $signed(op_b))` directly, then
//     BLT/BGE/BLTU/BGEU are right for free, and `result = op_a - op_b` makes
//     `zero` the BEQ answer;
//   * if `slt` is computed as `($signed(result) < 0)`, then with `result =
//     op_a - op_b` that is still exactly `$signed(op_a) < $signed(op_b)`.
//
// Either way SUB gives the right `zero` and the right `slt`/`sltu`, so P3 does
// not have to know which convention it picked and I do not have to guess.
//
// ---------------------------------------------------------------------------
// DESIGN NOTE 4 - WHAT IS *NOT* ILLEGAL HERE, AND WHY
//
// One case is a legal no-op rather than illegal, because getting it wrong would
// be worse than doing nothing:
//
//   * FENCE (0001111, funct3 000) and FENCE.I (0001111, funct3 001) are base
//     RV32I.  Phase 1 is a single-issue in-order core with one data port, no
//     cache and no store buffer, so there is no reordering for a fence to
//     prevent and the architecturally correct behaviour is to do nothing.  Mark
//     them illegal and a conforming program traps on an instruction that is
//     required to be legal; that is a real bug, not a conservative choice.
//
// Everything else that is unimplemented is illegal, including:
//
//   * M-extension encodings - opcode 0110011 with funct7 0000001.  Note that
//     there is *no* M encoding in opcode 0010011: in OP-IMM those seven bits
//     are imm[11:5] for six of the eight funct3 values, so a word that looks
//     like `mul` there is just `addi` with a different immediate.  Checking
//     funct7 on those funct3s would reject `addi rd, rs1, -1`, whose imm[11:5]
//     is 1111111 - the most common instruction in the ISA.  Only the two shift
//     funct3s (001 and 101) put an operation-selecting field in instr[31:25],
//     and only those are checked.  Phase 2 adds M.
//   * C-extension encodings that are not implemented - the expander (DESIGN
//     NOTE 6) rewrites every recognised 16-bit encoding into a 32-bit word with
//     `instr_eff[1:0] == 11`, and returns 0 for everything else, so an
//     unimplemented compressed encoding still fails the `not_32bit` gate below.
//   * Instructions longer than 32 bits - caught by `instr[4:2] == 3'b111`.
//   * The whole SYSTEM opcode (1110011), which covers ECALL, EBREAK and the
//     Zicsr CSR accesses.  ECALL and EBREAK *are* base RV32I, but acting on
//     them means taking a trap, and phase 1 has no trap mechanism at all:
//     `decode` has no port through which to raise one, and `core` has nothing
//     to catch.  Decoding them as legal no-ops would make `ecall` silently
//     return to the next instruction, which is the classic silent-wrong-answer
//     bug.  Phase 3 re-opens this arm when the trap path exists.
//
// A NOTE ON THE TWO LENGTH GATES.  `not_32bit` and `longer_than_32` are
// checked before the opcode switch, so a word cannot half-match an opcode.
// Both now test `instr_eff`, not the raw `instr`: after expansion every
// recognised instruction is a canonical 32-bit word with `instr_eff[1:0] == 11`
// and `instr_eff[4:2] != 111`, and an unsupported encoding expands to 0, which
// fails `not_32bit`.  So the gates reject over-long words and unsupported
// compressed encodings without either needing a special case.
//
// ---------------------------------------------------------------------------
// DESIGN NOTE 6 - RV32C EXPANSION, AND WHY `instr_eff` IS AN OUTPUT
//
// When `instr[1:0] != 2'b11` the word is a 16-bit (compressed) instruction, and
// `rvc_expand` rewrites it into its canonical 32-bit equivalent before the
// decode case runs.  This "expand, then decode" shape (spec 4.5) keeps one
// control-generation path, so a compressed form cannot drift from its 32-bit
// twin, and every encoding is unit-testable by asserting on its expansion.
//
// `instr_eff` is exposed as a port, not kept internal, because expansion moves
// the register indices and the immediate: a compressed form carries rd'/rs1'/
// rs2' in different bit positions and a scrambled immediate, so `core` must
// take those fields from the expanded word.  `imm_gen` also consumes
// `instr_eff`, for the same reason.  `instr_eff == instr` for every 32-bit
// instruction, so nothing outside the compressed path changes.
//
// ---------------------------------------------------------------------------
// DESIGN NOTE 5 - `uses_rd` VERSUS `reg_write`
//
// The contract requires them to be separate signals: `reg_write` says the
// instruction updates rd, `uses_rd` says the rd field carries a meaningful
// index, and "the two differ for instructions that merely mention rd".  In
// base RV32I no instruction mentions rd without writing it, so in phase 1 the
// two are driven identically - but they are separate signals here, and the
// distinction starts to pay in phase 2.  Merging them would quietly turn
// phase 2 into a port-list change for every downstream module.
//
// Drop-in replaceable: this file builds and lints from its own source alone.
// Replacing it with another implementation must not change the port list and
// must not require any other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"
`include "ctrl_fields.vh"

module decode (
  /* verilator lint_off UNUSEDSIGNAL */
  // `instr[24:15]` (rs1, rs2) and `instr[11:7]` (rd) are genuinely unread here,
  // and that is a contract decision rather than an omission: "You do not
  // produce register addresses.  The integrator extracts rs1/rs2/rd from the
  // instruction bits directly - that is wiring, not decoding" (docs/TEAM.md).
  // Reading them would only be to throw them away.  This is the same warning
  // class the stubs suppress around their port lists, and for the same reason.
  input  wire [`p_INSTR_W-1:0]    instr,
  /* verilator lint_on UNUSEDSIGNAL */
  output wire [`p_INSTR_W-1:0]    instr_eff,
  output wire [`p_ALU_OP_W-1:0]   alu_op,
  output wire [`p_OP1_SEL_W-1:0]  op1_sel,
  output wire [`p_OP2_SEL_W-1:0]  op2_sel,
  output wire [`p_IMM_SEL_W-1:0]  imm_sel,
  output wire [`p_FUNCT3_W-1:0]   branch_funct3,
  output wire [`p_IS_BRANCH_W-1:0] is_branch,
  output wire [`p_IS_JAL_W-1:0]    is_jal,
  output wire [`p_IS_JALR_W-1:0]   is_jalr,
  output wire [`p_IS_ILLEGAL_W-1:0] is_illegal,
  output wire                     uses_rs1,
  output wire                     uses_rs2,
  output wire [`p_USES_RD_W-1:0]  uses_rd,
  output wire                     mem_read,
  output wire                     mem_write,
  output wire [`p_MEM_SIZE_W-1:0] mem_size,
  output wire                     mem_unsigned,
  output wire                     reg_write,
  output wire [`p_WB_SEL_W-1:0]   wb_sel
);

  // --------------------------------------------------------------------------
  // `alu_op` encoding.  See DESIGN NOTE 2 above: P3's `alu` must use this
  // table.  The names are localparams so neither side can misspell an encoding
  // as a bare literal.
  // --------------------------------------------------------------------------
  localparam [`p_ALU_OP_W-1:0] ALU_ADD  = 4'd0;
  localparam [`p_ALU_OP_W-1:0] ALU_SUB  = 4'd1;
  localparam [`p_ALU_OP_W-1:0] ALU_SLL  = 4'd2;
  localparam [`p_ALU_OP_W-1:0] ALU_SLT  = 4'd3;
  localparam [`p_ALU_OP_W-1:0] ALU_SLTU = 4'd4;
  localparam [`p_ALU_OP_W-1:0] ALU_XOR  = 4'd5;
  localparam [`p_ALU_OP_W-1:0] ALU_SRL  = 4'd6;
  localparam [`p_ALU_OP_W-1:0] ALU_SRA  = 4'd7;
  localparam [`p_ALU_OP_W-1:0] ALU_OR   = 4'd8;
  localparam [`p_ALU_OP_W-1:0] ALU_AND  = 4'd9;

  // `op1_sel` / `op2_sel`, frozen by the contract.
  localparam [`p_OP1_SEL_W-1:0] OP1_RS1  = 2'd0;
  localparam [`p_OP1_SEL_W-1:0] OP1_PC   = 2'd1;
  localparam [`p_OP1_SEL_W-1:0] OP1_ZERO = 2'd2;

  localparam [`p_OP2_SEL_W-1:0] OP2_RS2  = 3'd0;
  localparam [`p_OP2_SEL_W-1:0] OP2_IMM  = 3'd1;
  localparam [`p_OP2_SEL_W-1:0] OP2_PC   = 3'd3;
  // The contract also enumerates op2_sel = 2 ("4", a literal constant 4 as the
  // second operand).  No RV32I encoding selects it: `ex_stage` adds 4 by using
  // OP2_PC, which already means "this stage's pc", so a second way to spell
  // the same constant would be an encoding nothing could ever select.  It is
  // deliberately not declared here - an unused localparam is a lint warning,
  // and the contract, not this file, owns the port's encoding.

  // `imm_sel`, frozen by the contract: 0 = I, 1 = S, 2 = B, 3 = U, 4 = J.
  localparam [`p_IMM_SEL_W-1:0] IMM_I = 3'd0;
  localparam [`p_IMM_SEL_W-1:0] IMM_S = 3'd1;
  localparam [`p_IMM_SEL_W-1:0] IMM_B = 3'd2;
  localparam [`p_IMM_SEL_W-1:0] IMM_U = 3'd3;
  localparam [`p_IMM_SEL_W-1:0] IMM_J = 3'd4;

  // `mem_size`, frozen by the contract.
  localparam [`p_MEM_SIZE_W-1:0] MEM_BYTE = 2'd0;
  localparam [`p_MEM_SIZE_W-1:0] MEM_HALF = 2'd1;
  localparam [`p_MEM_SIZE_W-1:0] MEM_WORD = 2'd2;

  // `wb_sel`, frozen by the contract.
  localparam [`p_WB_SEL_W-1:0] WB_ALU = 2'd0;
  localparam [`p_WB_SEL_W-1:0] WB_MEM = 2'd1;
  localparam [`p_WB_SEL_W-1:0] WB_PC4 = 2'd2;

  // Opcodes.  `OPCODE_W` is not in defs.vh because no port uses it - the
  // contract forbids a width written as a literal number outside the headers,
  // but this is a signal slice rather than a port width, and the immediate
  // fields in the same file are slices too.  7 bits is the architectural
  // opcode field width.
  localparam [6:0] OP_LOAD     = 7'b000_0011;
  localparam [6:0] OP_MISC_MEM = 7'b000_1111;  // FENCE / FENCE.I
  localparam [6:0] OP_OP_IMM   = 7'b001_0011;
  localparam [6:0] OP_AUIPC    = 7'b001_0111;
  localparam [6:0] OP_STORE    = 7'b010_0011;
  localparam [6:0] OP_OP       = 7'b011_0011;
  localparam [6:0] OP_LUI      = 7'b011_0111;
  localparam [6:0] OP_BRANCH   = 7'b110_0011;
  localparam [6:0] OP_JALR     = 7'b110_0111;
  localparam [6:0] OP_JAL      = 7'b110_1111;
  localparam [6:0] OP_SYSTEM   = 7'b111_0011;  // ECALL / EBREAK / CSR

  // funct3 values used by more than one arm.
  localparam [2:0] F3_BEQ  = 3'b000;
  localparam [2:0] F3_BNE  = 3'b001;
  localparam [2:0] F3_BLT  = 3'b100;
  localparam [2:0] F3_BGE  = 3'b101;
  localparam [2:0] F3_BLTU = 3'b110;
  localparam [2:0] F3_BGEU = 3'b111;

  // funct7 values.  Only these two are legal in RV32I: everything else, M
  // extension included, is rejected.
  localparam [6:0] F7_ALU  = 7'b000_0000;
  localparam [6:0] F7_ALT  = 7'b010_0000;  // SUB / SRA

  // --------------------------------------------------------------------------
  // Instruction fields.  `decode` deliberately has no rs1/rs2/rd *outputs*:
  // extracting three fixed bit ranges is wiring, and `core` does it.
  // --------------------------------------------------------------------------
  // --------------------------------------------------------------------------
  // RV32C expansion (see DESIGN NOTE 6).  A compressed instruction is rewritten
  // into its canonical 32-bit equivalent before any decoding happens, so the
  // opcode switch below sees one uniform 32-bit encoding.  `instr_eff` is the
  // word the rest of this module works on, and `core` reads the register
  // indices and the immediate from it.
  // --------------------------------------------------------------------------
  reg [`p_INSTR_W-1:0] instr_eff_r;
  always @(*) begin
    instr_eff_r = (instr[1:0] == 2'b11) ? instr : rvc_expand(instr[15:0]);
  end

  wire [6:0] opcode  = instr_eff_r[6:0];
  wire [2:0] funct3  = instr_eff_r[14:12];
  wire [6:0] funct7  = instr_eff_r[31:25];

  // An unexpanded word (32-bit or an unsupported compressed encoding) is
  // "not 32 bit" only when it did not expand to a canonical opcode: an
  // unsupported encoding expands to 0, whose instr_eff[1:0] is not 11, so the
  // gate below still rejects it.  Instructions longer than 32 bits have
  // instr[4:2] == 111.
  wire not_32bit   = (instr_eff_r[1:0] != 2'b11);
  wire longer_than_32 = (instr_eff_r[4:2] == 3'b111);

  // --------------------------------------------------------------------------
  // RV32C expander (DESIGN NOTE 6).  Each quadrant function returns the
  // canonical 32-bit word, or 0 for any encoding it does not implement -- 0
  // then falls out illegal through the opcode `default`, so there is no
  // separate legality flag to keep in sync.  Words are built with the same
  // field layouts the 32-bit encoder uses (I-type / S-type).
  //
  // Compressed register operands are always x8..x15, spelled `2'b01` + the
  // 3-bit field.  The immediate bit-maps are RISC-V Volume I, section 16.7.
  // --------------------------------------------------------------------------
  function [`p_INSTR_W-1:0] rvc_q0;
    /* verilator lint_off UNUSEDSIGNAL */
    // h[1:0] is the quadrant selector, spent in `rvc_expand` before dispatch.
    input [15:0] h;
    /* verilator lint_on UNUSEDSIGNAL */
    reg [4:0]  rd_p;
    reg [4:0]  rs1_p;
    reg [4:0]  rs2_p;
    reg [11:0] imm;
    begin
      rd_p    = {2'b01, h[4:2]};
      rs1_p   = {2'b01, h[9:7]};
      rs2_p   = {2'b01, h[4:2]};
      imm     = 12'b0;
      rvc_q0  = 32'h0000_0000;
      case (h[15:13])
        3'b000: begin  // C.ADDI4SPN -> addi rd', x2, nzuimm
          imm = {2'b00, h[10:7], h[12:11], h[5], h[6], 2'b00};
          if (imm != 12'b0)
            rvc_q0 = {imm, 5'd2, 3'b000, rd_p, OP_OP_IMM};
        end
        3'b010: begin  // C.LW -> lw rd', uimm(rs1')
          imm = {5'b0, h[5], h[12:10], h[6], 2'b00};
          rvc_q0 = {imm, rs1_p, 3'b010, rd_p, OP_LOAD};
        end
        3'b110: begin  // C.SW -> sw rs2', uimm(rs1')
          imm = {5'b0, h[5], h[12:10], h[6], 2'b00};
          rvc_q0 = {imm[11:5], rs2_p, rs1_p, 3'b010, imm[4:0], OP_STORE};
        end
        default: begin
          // C.LD (011) and C.SD (111) are RV64-only, and 001/100/101 are
          // reserved: all stay 0 and decode illegal.
        end
      endcase
    end
  endfunction

  function [`p_INSTR_W-1:0] rvc_q1;
    /* verilator lint_off UNUSEDSIGNAL */
    // h[1:0] is the quadrant selector, spent in `rvc_expand` before dispatch.
    input [15:0] h;
    /* verilator lint_on UNUSEDSIGNAL */
    reg [4:0]  rd;
    reg [4:0]  rd_p;
    reg [4:0]  rs1_p;
    reg [4:0]  rs2_p;
    reg [11:0] imm;
    // jimm/bimm carry only bits [20:1] / [12:1]: jump and branch targets are
    // 2-byte aligned, so bit 0 is structurally zero and is not stored.
    reg [20:1] jimm;
    reg [12:1] bimm;
    begin
      rd     = h[11:7];
      rd_p   = {2'b01, h[9:7]};
      rs1_p  = {2'b01, h[9:7]};
      rs2_p  = {2'b01, h[4:2]};
      // 6-bit signed immediate {h[12], h[6:2]}, sign-extended to 12 bits.
      imm    = {{6{h[12]}}, h[12], h[6:2]};
      // C.J offset, placed in the 32-bit J-type layout (sign bit is h[12]).
      jimm   = {{9{h[12]}}, h[12], h[8], h[10:9], h[6], h[7], h[2], h[11],
                h[5:3]};
      // C.BEQZ/C.BNEZ offset, placed in the 32-bit B-type layout.
      bimm   = {{4{h[12]}}, h[12], h[6:5], h[2], h[11:10], h[4:3]};
      rvc_q1 = 32'h0000_0000;
      case (h[15:13])
        3'b000: begin  // C.NOP / C.ADDI -> addi rd, rd, imm
          rvc_q1 = {imm, rd, 3'b000, rd, OP_OP_IMM};
        end
        3'b001: begin  // C.JAL -> jal x1, offset
          rvc_q1 = {jimm[20], jimm[10:1], jimm[11], jimm[19:12], 5'd1, OP_JAL};
        end
        3'b010: begin  // C.LI -> addi rd, x0, imm
          rvc_q1 = {imm, 5'd0, 3'b000, rd, OP_OP_IMM};
        end
        3'b011: begin
          if (rd == 5'd2) begin  // C.ADDI16SP -> addi x2, x2, nzimm
            imm = {{2{h[12]}}, h[12], h[4:3], h[5], h[2], h[6], 4'b0000};
            if (imm != 12'b0)
              rvc_q1 = {imm, 5'd2, 3'b000, 5'd2, OP_OP_IMM};
          end
          else if (rd != 5'd0) begin  // C.LUI -> lui rd, nzimm (nzimm != 0)
            if (h[12] || (h[6:2] != 5'b0))
              rvc_q1 = {{15{h[12]}}, h[6:2], rd, OP_LUI};
          end
          // rd == 0 and rd == 2 with nzimm == 0 are reserved: stay 0.
        end
        3'b100: begin
          case (h[12:10])
            3'b000:  // C.SRLI -> srli rd', rd', shamt
              rvc_q1 = {7'b0000000, h[6:2], rs1_p, 3'b101, rd_p, OP_OP_IMM};
            3'b001:  // C.SRAI -> srai rd', rd', shamt
              rvc_q1 = {7'b0100000, h[6:2], rs1_p, 3'b101, rd_p, OP_OP_IMM};
            3'b010:  // C.ANDI -> andi rd', rd', imm
              rvc_q1 = {imm, rs1_p, 3'b111, rd_p, OP_OP_IMM};
            3'b011: begin  // C.SUB/C.XOR/C.OR/C.AND, selected by h[6:5]
              case (h[6:5])
                2'b00: rvc_q1 = {7'b0100000, rs2_p, rs1_p, 3'b000, rd_p, OP_OP};
                2'b01: rvc_q1 = {7'b0000000, rs2_p, rs1_p, 3'b100, rd_p, OP_OP};
                2'b10: rvc_q1 = {7'b0000000, rs2_p, rs1_p, 3'b110, rd_p, OP_OP};
                2'b11: rvc_q1 = {7'b0000000, rs2_p, rs1_p, 3'b111, rd_p, OP_OP};
              endcase
            end
            default: begin
              // h[12:10] = 1xx is reserved in RV32 (the C.JR/C.MV and
              // C.EBREAK/C.JALR/C.ADD groups live in quadrant 2).
            end
          endcase
        end
        3'b101: begin  // C.J -> jal x0, offset
          rvc_q1 = {jimm[20], jimm[10:1], jimm[11], jimm[19:12], 5'd0, OP_JAL};
        end
        3'b110: begin  // C.BEQZ -> beq rs1', x0, offset
          rvc_q1 = {bimm[12], bimm[10:5], 5'd0, rs1_p, 3'b000, bimm[4:1],
                    bimm[11], OP_BRANCH};
        end
        3'b111: begin  // C.BNEZ -> bne rs1', x0, offset
          rvc_q1 = {bimm[12], bimm[10:5], 5'd0, rs1_p, 3'b001, bimm[4:1],
                    bimm[11], OP_BRANCH};
        end
      endcase
    end
  endfunction

  function [`p_INSTR_W-1:0] rvc_q2;
    /* verilator lint_off UNUSEDSIGNAL */
    // h[1:0] is the quadrant selector, spent in `rvc_expand` before dispatch.
    input [15:0] h;
    /* verilator lint_on UNUSEDSIGNAL */
    reg [4:0]  rd;
    reg [4:0]  rs1;
    reg [4:0]  rs2;
    reg [11:0] imm;
    begin
      // Quadrant 2 uses full 5-bit register fields, unlike quadrant 1.
      rd     = h[11:7];
      rs1    = h[11:7];      // C.JR / C.JALR source
      rs2    = h[6:2];
      imm    = 12'b0;
      rvc_q2 = 32'h0000_0000;
      case (h[15:13])
        3'b000: begin  // C.SLLI -> slli rd, rd, shamt  (RV32: shamt[5] == 0)
          if (h[12] == 1'b0)
            rvc_q2 = {7'b0, h[6:2], rd, 3'b001, rd, OP_OP_IMM};
        end
        3'b010: begin  // C.LWSP -> lw rd, offset(x2)
          imm = {4'b0, h[3:2], h[12], h[6:4], 2'b00};
          if (rd != 5'd0)
            rvc_q2 = {imm, 5'd2, 3'b010, rd, OP_LOAD};
        end
        3'b100: begin
          if (h[12] == 1'b0) begin  // C.JR / C.MV
            if (rs2 == 5'd0) begin  // C.JR -> jalr x0, 0(rs1)
              if (rs1 != 5'd0)
                rvc_q2 = {12'b0, rs1, 3'b000, 5'd0, OP_JALR};
            end
            else  // C.MV -> add rd, x0, rs2
              rvc_q2 = {7'b0, rs2, 5'd0, 3'b000, rd, OP_OP};
          end
          else begin  // C.EBREAK / C.JALR / C.ADD
            if (rs2 == 5'd0) begin
              if (rs1 == 5'd0)  // C.EBREAK (rd == 0 and rs2 == 0)
                rvc_q2 = {12'h001, 5'd0, 3'b000, 5'd0, OP_SYSTEM};
              else  // C.JALR -> jalr x1, 0(rs1)
                rvc_q2 = {12'b0, rs1, 3'b000, 5'd1, OP_JALR};
            end
            else  // C.ADD -> add rd, rd, rs2
              rvc_q2 = {7'b0, rs2, rd, 3'b000, rd, OP_OP};
          end
        end
        3'b110: begin  // C.SWSP -> sw rs2, offset(x2)
          imm = {4'b0, h[8:7], h[12:9], 2'b00};
          rvc_q2 = {imm[11:5], rs2, 5'd2, 3'b010, imm[4:0], OP_STORE};
        end
        default: begin
          // C.FLDSP (001), C.LDSP (011), C.FSDSP (101) and C.SDSP (111) are
          // not RV32I: they stay 0 and decode illegal.
        end
      endcase
    end
  endfunction

  function [`p_INSTR_W-1:0] rvc_expand;
    input [15:0] h;
    begin
      case (h[1:0])
        2'b00:   rvc_expand = rvc_q0(h);
        2'b01:   rvc_expand = rvc_q1(h);
        2'b10:   rvc_expand = rvc_q2(h);
        default: rvc_expand = 32'h0000_0000;
      endcase
    end
  endfunction

  // --------------------------------------------------------------------------
  // Combinational decode.  Outputs are wires in the frozen port list, so the
  // block computes into internal regs which are then assigned out.
  // --------------------------------------------------------------------------
  reg [`p_ALU_OP_W-1:0]   alu_op_r;
  reg [`p_OP1_SEL_W-1:0]  op1_sel_r;
  reg [`p_OP2_SEL_W-1:0]  op2_sel_r;
  reg [`p_IMM_SEL_W-1:0]  imm_sel_r;
  reg [`p_FUNCT3_W-1:0]   branch_funct3_r;
  reg                     is_branch_r;
  reg                     is_jal_r;
  reg                     is_jalr_r;
  reg                     is_illegal_r;
  reg                     uses_rs1_r;
  reg                     uses_rs2_r;
  reg                     uses_rd_r;
  reg                     mem_read_r;
  reg                     mem_write_r;
  reg [`p_MEM_SIZE_W-1:0] mem_size_r;
  reg                     mem_unsigned_r;
  reg                     reg_write_r;
  reg [`p_WB_SEL_W-1:0]   wb_sel_r;

  always @(*) begin
    // ---- defaults: illegal, and with no effect on anything ----------------
    // DESIGN NOTE 1.  Anything not explicitly cleared below stays illegal.
    is_illegal_r  = 1'b1;
    reg_write_r   = 1'b0;
    mem_read_r    = 1'b0;
    mem_write_r   = 1'b0;
    uses_rs1_r    = 1'b0;
    uses_rs2_r    = 1'b0;
    uses_rd_r     = 1'b0;
    is_branch_r   = 1'b0;
    is_jal_r      = 1'b0;
    is_jalr_r     = 1'b0;

    // Neutral operand/format selects.  These are inert while `is_illegal` is
    // high, and every legal arm overwrites the ones it cares about.
    alu_op_r        = ALU_ADD;
    op1_sel_r       = OP1_RS1;
    op2_sel_r       = OP2_RS2;
    imm_sel_r       = IMM_I;
    mem_size_r      = MEM_BYTE;
    mem_unsigned_r  = 1'b0;
    wb_sel_r        = WB_ALU;

    // `branch_funct3` defaults to 0 and is set only by the BRANCH arm.  It is
    // meaningful only when `is_branch` is high, and holding it at 0 otherwise
    // is what makes "an illegal encoding sets nothing at all" checkable on
    // every output uniformly: `expect_illegal` in the testbench requires
    // `branch_funct3` to be 0 too, and that requirement is only honest if this
    // module really does leave it at 0 rather than mirroring instr[14:12].
    branch_funct3_r = 3'b000;

    // ---- length gates -----------------------------------------------------
    // 16-bit and over-long encodings are not RV32I.  Checked before the opcode
    // so a compressed encoding can never reach an arm that would half-match it.
    if (!not_32bit && !longer_than_32) begin
      case (opcode)
        // ---- LUI: rd = imm[31:12] ------------------------------------------
        // op1 = zero, op2 = imm: the ALU adds 0 to the U-immediate.
        OP_LUI: begin
          is_illegal_r = 1'b0;
          alu_op_r     = ALU_ADD;
          op1_sel_r    = OP1_ZERO;
          op2_sel_r    = OP2_IMM;
          imm_sel_r    = IMM_U;
          reg_write_r  = 1'b1;
          uses_rd_r    = 1'b1;
        end

        // ---- AUIPC: rd = pc + imm[31:12] -----------------------------------
        OP_AUIPC: begin
          is_illegal_r = 1'b0;
          alu_op_r     = ALU_ADD;
          op1_sel_r    = OP1_PC;
          op2_sel_r    = OP2_PC;
          imm_sel_r    = IMM_U;
          reg_write_r  = 1'b1;
          uses_rd_r    = 1'b1;
        end

        // ---- JAL: rd = pc + 4, target = pc + imm ---------------------------
        // `wb_sel = pc+4` is what writes the link register; `alu_op = ADD` with
        // op1 = pc and op2 = imm is what computes the target.  One ALU, two
        // results, which is why `wb_sel` has to be an explicit select and not a
        // single MemToReg bit.
        OP_JAL: begin
          is_illegal_r = 1'b0;
          alu_op_r     = ALU_ADD;
          op1_sel_r    = OP1_PC;
          op2_sel_r    = OP2_IMM;
          imm_sel_r    = IMM_J;
          reg_write_r  = 1'b1;
          uses_rd_r    = 1'b1;
          wb_sel_r     = WB_PC4;
          is_jal_r     = 1'b1;
        end

        // ---- JALR: rd = pc + 4, target = (rs1 + imm) & ~1 -----------------
        // funct3 must be 000; the other seven funct3 encodings are reserved
        // and are illegal here.  JALR does read rs1, unlike JAL.
        OP_JALR: begin
          if (funct3 == 3'b000) begin
            is_illegal_r = 1'b0;
            alu_op_r     = ALU_ADD;
            op1_sel_r    = OP1_RS1;
            op2_sel_r    = OP2_IMM;
            imm_sel_r    = IMM_I;
            reg_write_r  = 1'b1;
            uses_rs1_r   = 1'b1;
            uses_rd_r    = 1'b1;
            wb_sel_r     = WB_PC4;
            is_jalr_r    = 1'b1;
          end
        end

        // ---- BRANCH: BEQ / BNE / BLT / BGE / BLTU / BGEU -------------------
        // funct3 010 and 011 are reserved and stay illegal.  No rd, so no
        // reg_write and no uses_rd.
        OP_BRANCH: begin
          case (funct3)
            F3_BEQ, F3_BNE, F3_BLT, F3_BGE, F3_BLTU, F3_BGEU: begin
              is_illegal_r  = 1'b0;
              alu_op_r      = ALU_SUB;  // DESIGN NOTE 3
              op1_sel_r     = OP1_RS1;
              op2_sel_r     = OP2_RS2;
              imm_sel_r     = IMM_B;
              branch_funct3_r = funct3;
              uses_rs1_r    = 1'b1;
              uses_rs2_r    = 1'b1;
              is_branch_r   = 1'b1;
            end
            default: begin
              // reserved funct3: keep the illegal default
            end
          endcase
        end

        // ---- LOAD: LB / LH / LW / LBU / LHU --------------------------------
        OP_LOAD: begin
          // The load size is spelled out per instruction rather than taken as
          // funct3[1:0], even though the two agree.  funct3[1:0] would be
          // shorter, but it hides the LBU/LHU size behind a coincidence of bit
          // positions, and a future encoding that reuses those funct3 values
          // would then silently inherit the wrong size.  Written out, each arm
          // is the ISA's own table.
          case (funct3)
            3'b000: begin  // LB
              is_illegal_r   = 1'b0;
              alu_op_r       = ALU_ADD;   // rs1 + imm = effective address
              op1_sel_r      = OP1_RS1;
              op2_sel_r      = OP2_IMM;
              imm_sel_r      = IMM_I;
              mem_read_r     = 1'b1;
              mem_size_r     = MEM_BYTE;
              mem_unsigned_r = 1'b0;       // sign-extended
              reg_write_r    = 1'b1;
              uses_rs1_r     = 1'b1;
              uses_rd_r      = 1'b1;
              wb_sel_r       = WB_MEM;
            end

            3'b001: begin  // LH
              is_illegal_r   = 1'b0;
              alu_op_r       = ALU_ADD;
              op1_sel_r      = OP1_RS1;
              op2_sel_r      = OP2_IMM;
              imm_sel_r      = IMM_I;
              mem_read_r     = 1'b1;
              mem_size_r     = MEM_HALF;
              mem_unsigned_r = 1'b0;
              reg_write_r    = 1'b1;
              uses_rs1_r     = 1'b1;
              uses_rd_r      = 1'b1;
              wb_sel_r       = WB_MEM;
            end

            3'b010: begin  // LW
              is_illegal_r   = 1'b0;
              alu_op_r       = ALU_ADD;
              op1_sel_r      = OP1_RS1;
              op2_sel_r      = OP2_IMM;
              imm_sel_r      = IMM_I;
              mem_read_r     = 1'b1;
              mem_size_r     = MEM_WORD;
              mem_unsigned_r = 1'b0;
              reg_write_r    = 1'b1;
              uses_rs1_r     = 1'b1;
              uses_rd_r      = 1'b1;
              wb_sel_r       = WB_MEM;
            end

            3'b100: begin  // LBU
              is_illegal_r   = 1'b0;
              alu_op_r       = ALU_ADD;
              op1_sel_r      = OP1_RS1;
              op2_sel_r      = OP2_IMM;
              imm_sel_r      = IMM_I;
              mem_read_r     = 1'b1;
              mem_size_r     = MEM_BYTE;
              mem_unsigned_r = 1'b1;       // zero-extended
              reg_write_r    = 1'b1;
              uses_rs1_r     = 1'b1;
              uses_rd_r      = 1'b1;
              wb_sel_r       = WB_MEM;
            end

            3'b101: begin  // LHU
              is_illegal_r   = 1'b0;
              alu_op_r       = ALU_ADD;
              op1_sel_r      = OP1_RS1;
              op2_sel_r      = OP2_IMM;
              imm_sel_r      = IMM_I;
              mem_read_r     = 1'b1;
              mem_size_r     = MEM_HALF;
              mem_unsigned_r = 1'b1;
              reg_write_r    = 1'b1;
              uses_rs1_r     = 1'b1;
              uses_rd_r      = 1'b1;
              wb_sel_r       = WB_MEM;
            end

            default: begin
              // funct3 011, 110, 111 are reserved: keep the illegal default
            end
          endcase
        end

        // ---- STORE: SB / SH / SW ------------------------------------------
        // The effective address is rs1 + imm exactly as for a load, so
        // `op2_sel` is the immediate -- the ALU's job here is the *address*,
        // and its result is what `core` hands the `lsu` as the access address.
        // (Choosing rs2 would make the ALU add the stored value to rs1 and
        // quietly produce a garbage address, which the `lsu` then refuses as
        // misaligned -- a store that silently never happens.)
        //
        // The stored *value* is rs2, but it never reaches the ALU: `ex_stage`
        // takes it straight off `ex_rs2_data` into `ex_store_data`. So a store
        // sets neither wb_sel nor reg_write.  funct3 011..111 stay illegal.
        OP_STORE: begin
          case (funct3)
            3'b000: begin  // SB
              is_illegal_r = 1'b0;
              alu_op_r     = ALU_ADD;
              op1_sel_r    = OP1_RS1;
              op2_sel_r    = OP2_IMM;
              imm_sel_r    = IMM_S;
              mem_write_r  = 1'b1;
              mem_size_r   = MEM_BYTE;
              uses_rs1_r   = 1'b1;
              uses_rs2_r   = 1'b1;
            end

            3'b001: begin  // SH
              is_illegal_r = 1'b0;
              alu_op_r     = ALU_ADD;
              op1_sel_r    = OP1_RS1;
              op2_sel_r    = OP2_IMM;
              imm_sel_r    = IMM_S;
              mem_write_r  = 1'b1;
              mem_size_r   = MEM_HALF;
              uses_rs1_r   = 1'b1;
              uses_rs2_r   = 1'b1;
            end

            3'b010: begin  // SW
              is_illegal_r = 1'b0;
              alu_op_r     = ALU_ADD;
              op1_sel_r    = OP1_RS1;
              op2_sel_r    = OP2_IMM;
              imm_sel_r    = IMM_S;
              mem_write_r  = 1'b1;
              mem_size_r   = MEM_WORD;
              uses_rs1_r   = 1'b1;
              uses_rs2_r   = 1'b1;
            end

            default: begin
              // funct3 011 and above are reserved: keep the illegal default
            end
          endcase
        end

        // ---- OP-IMM: ADDI SLLI SLTI SLTIU XORI SRLI SRAI ORI ANDI ---------
        // The distinction that matters here: in the R-type OP opcode,
        // instr[31:25] is funct7 and constrains the operation, but in OP-IMM it
        // is imm[11:5] for every form except the two shifts.  So:
        //
        //   * the two shift forms (funct3 001 and 101) carry an operation-
        //     selecting funct7 there, and it must be checked - otherwise `srai`
        //       with a junk funct7 decodes as `srli`, which is wrong for every
        //       negative value shifted right, and a reserved funct7 would be
        //       silently accepted;
        //
        //   * the other six forms put a *data* bit in those positions.  It is
        //     part of the 12-bit immediate and every value is legal, so it must
        //     NOT be checked.  `addi rd, rs1, -1` has imm[11:5] = 1111111,
        //     which is not F7_ALU - a decoder that checked funct7 here would
        //     call the most common instruction in the ISA illegal.
        OP_OP_IMM: begin
          case (funct3)
            3'b001: begin
              // SLLI: instr[31:25] must be 0000000
              if (funct7 == F7_ALU) begin
                is_illegal_r = 1'b0;
                alu_op_r     = ALU_SLL;
                op1_sel_r    = OP1_RS1;
                op2_sel_r    = OP2_IMM;
                imm_sel_r    = IMM_I;
                reg_write_r  = 1'b1;
                uses_rs1_r   = 1'b1;
                uses_rd_r    = 1'b1;
              end
            end

            3'b101: begin
              // SRLI (0000000) or SRAI (0100000); nothing else
              if (funct7 == F7_ALU) begin
                is_illegal_r = 1'b0;
                alu_op_r     = ALU_SRL;
                op1_sel_r    = OP1_RS1;
                op2_sel_r    = OP2_IMM;
                imm_sel_r    = IMM_I;
                reg_write_r  = 1'b1;
                uses_rs1_r   = 1'b1;
                uses_rd_r    = 1'b1;
              end else if (funct7 == F7_ALT) begin
                is_illegal_r = 1'b0;
                alu_op_r     = ALU_SRA;
                op1_sel_r    = OP1_RS1;
                op2_sel_r    = OP2_IMM;
                imm_sel_r    = IMM_I;
                reg_write_r  = 1'b1;
                uses_rs1_r   = 1'b1;
                uses_rd_r    = 1'b1;
              end
            end

            default: begin
              // ADDI, SLTI, SLTIU, XORI, ORI, ANDI.  instr[31:25] is
              // imm[11:5] here and every value of it is legal.
              is_illegal_r = 1'b0;
              op1_sel_r    = OP1_RS1;
              op2_sel_r    = OP2_IMM;
              imm_sel_r    = IMM_I;
              reg_write_r  = 1'b1;
              uses_rs1_r   = 1'b1;
              uses_rd_r    = 1'b1;
              case (funct3)
                3'b000: alu_op_r = ALU_ADD;   // ADDI
                3'b010: alu_op_r = ALU_SLT;   // SLTI
                3'b011: alu_op_r = ALU_SLTU;  // SLTIU
                3'b100: alu_op_r = ALU_XOR;   // XORI
                3'b110: alu_op_r = ALU_OR;    // ORI
                3'b111: alu_op_r = ALU_AND;   // ANDI
                default: alu_op_r = ALU_ADD;  // unreachable
              endcase
            end
          endcase
        end

        // ---- OP: ADD SUB SLL SLT SLTU XOR SRL SRA OR AND -------------------
        // funct3 000 and 101 accept two funct7 values (ADD/SUB, SRL/SRA); the
        // other six accept only F7_ALU.  funct7 0000001 is the M extension and
        // is rejected by construction rather than by a special case.
        OP_OP: begin
          case (funct3)
            3'b000: begin
              if (funct7 == F7_ALU) begin
                is_illegal_r = 1'b0; alu_op_r = ALU_ADD;
              end else if (funct7 == F7_ALT) begin
                is_illegal_r = 1'b0; alu_op_r = ALU_SUB;
              end
            end

            3'b101: begin
              if (funct7 == F7_ALU) begin
                is_illegal_r = 1'b0; alu_op_r = ALU_SRL;
              end else if (funct7 == F7_ALT) begin
                is_illegal_r = 1'b0; alu_op_r = ALU_SRA;
              end
            end

            default: begin
              if (funct7 == F7_ALU) begin
                is_illegal_r = 1'b0;
                case (funct3)
                  3'b001: alu_op_r = ALU_SLL;
                  3'b010: alu_op_r = ALU_SLT;
                  3'b011: alu_op_r = ALU_SLTU;
                  3'b100: alu_op_r = ALU_XOR;
                  3'b110: alu_op_r = ALU_OR;
                  3'b111: alu_op_r = ALU_AND;
                  default: alu_op_r = ALU_ADD;  // unreachable
                endcase
              end
            end
          endcase

          if (!is_illegal_r) begin
            op1_sel_r   = OP1_RS1;
            op2_sel_r   = OP2_RS2;
            imm_sel_r   = IMM_I;   // unused by OP; I is the harmless default
            reg_write_r = 1'b1;
            uses_rs1_r  = 1'b1;
            uses_rs2_r  = 1'b1;
            uses_rd_r   = 1'b1;
          end
        end

        // ---- MISC-MEM: FENCE, FENCE.I --------------------------------------
        // DESIGN NOTE 4: legal no-ops.  Nothing to clear, because the defaults
        // already say "no effect" - this arm exists purely to say "not
        // illegal".  funct3 010 and above stay illegal.
        OP_MISC_MEM: begin
          if (funct3 == 3'b000 || funct3 == 3'b001) begin
            is_illegal_r = 1'b0;
          end
        end

        // ---- SYSTEM: ECALL / EBREAK / CSR ---------------------------------
        // DESIGN NOTE 4: illegal for the whole opcode.  Deliberately no arm at
        // all, so the illegal default stands; the comment is the record of why.
        OP_SYSTEM: begin
          // no trap mechanism exists in phase 1
        end

        default: begin
          // unknown opcode: the illegal default stands
        end
      endcase
    end
  end

  assign instr_eff     = instr_eff_r;
  assign alu_op        = alu_op_r;
  assign op1_sel       = op1_sel_r;
  assign op2_sel       = op2_sel_r;
  assign imm_sel       = imm_sel_r;
  assign branch_funct3 = branch_funct3_r;
  assign is_branch     = is_branch_r;
  assign is_jal        = is_jal_r;
  assign is_jalr       = is_jalr_r;
  assign is_illegal    = is_illegal_r;
  assign uses_rs1      = uses_rs1_r;
  assign uses_rs2      = uses_rs2_r;
  assign uses_rd       = uses_rd_r;
  assign mem_read      = mem_read_r;
  assign mem_write     = mem_write_r;
  assign mem_size      = mem_size_r;
  assign mem_unsigned  = mem_unsigned_r;
  assign reg_write     = reg_write_r;
  assign wb_sel        = wb_sel_r;

  // --------------------------------------------------------------------------
  // Invariants.  Each assertion is ONE LINE on purpose: scripts/yosys-prep.sh
  // deletes exactly whole-line `assert (...) else $error(...);` statements,
  // because Yosys's parser rejects the action clause.  A wrapped assertion
  // would survive the deletion and fail asic-check, which is loud rather than
  // silent, but it would still fail.
  // --------------------------------------------------------------------------
  always @(*) begin
    // The three control-class signals are mutually exclusive by contract.
    assert (!((is_branch_r + is_jal_r + is_jalr_r) > 1)) else $error("decode: is_branch/is_jal/is_jalr are not mutually exclusive");
    assert (!is_illegal_r || !(reg_write_r || mem_read_r || mem_write_r)) else $error("decode: illegal encoding has a side effect");
    assert (!is_illegal_r || !(is_branch_r || is_jal_r || is_jalr_r)) else $error("decode: illegal encoding is also a branch or jump");
    assert (alu_op_r <= ALU_AND) else $error("decode: alu_op %h is not an RV32I operation", alu_op_r);
    assert (!(mem_read_r && mem_write_r)) else $error("decode: both mem_read and mem_write are high");
  end

endmodule
`default_nettype wire

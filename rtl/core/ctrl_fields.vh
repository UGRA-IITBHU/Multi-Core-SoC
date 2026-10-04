// ============================================================================
// ctrl_fields.vh - names and widths of the decode/execute control bundle.
//
// `decode` produces these signals (see docs/contracts/phase1-interfaces.md).
// `core` re-packs them into the ID/EX and EX/MEM bundles using the bit
// positions from pipeline_regs.vh.  The field-name macros exist so that
// `core` and the stage modules never spell a control signal by hand.
//
// Owners: controller (Phase 1, Task 1).  Frozen from this commit.
// ============================================================================
`ifndef SOC_CTRL_FIELDS_VH
`define SOC_CTRL_FIELDS_VH

`include "defs.vh"

// ---------------------------------------------------------------------------
// Field widths
// ---------------------------------------------------------------------------
`define p_ALU_OP_W    4  // alu operation select, encoding owned by ex_stage/alu
`define p_OP1_SEL_W   2  // 0 = rs1, 1 = pc, 2 = zero
`define p_OP2_SEL_W   3  // 0 = rs2, 1 = imm, 2 = 4, 3 = pc
`define p_IMM_SEL_W   3  // immediate format select, consumed by imm_gen
`define p_FUNCT3_W    3  // funct3 for load/store width, signedness, branches
`define p_MEM_SIZE_W  2  // 0 = byte, 1 = half, 2 = word
`define p_WB_SEL_W    2  // 0 = alu, 1 = mem, 2 = pc+4
`define p_USES_RD_W   1  // the instruction's rd field is meaningful
`define p_IS_BRANCH_W 1  // conditional branch: BEQ/BNE/BLT/BGE/BLTU/BGEU
`define p_IS_JAL_W    1  // JAL
`define p_IS_JALR_W   1  // JALR
`define p_IS_ILLEGAL_W 1 // opcode or funct encoding not implemented

// ---------------------------------------------------------------------------
// Field names (used by `core` when packing the stage bundles)
// ---------------------------------------------------------------------------
`define c_ALU_OP        alu_op
`define c_OP1_SEL       op1_sel
`define c_OP2_SEL       op2_sel
`define c_IMM_SEL       imm_sel
`define c_BRANCH_FUNCT3 branch_funct3
`define c_IS_BRANCH     is_branch
`define c_IS_JAL        is_jal
`define c_IS_JALR       is_jalr
`define c_IS_ILLEGAL    is_illegal
`define c_USES_RS1      uses_rs1
`define c_USES_RS2      uses_rs2
`define c_USES_RD       uses_rd
`define c_MEM_READ      mem_read
`define c_MEM_WRITE     mem_write
`define c_MEM_SIZE      mem_size
`define c_MEM_UNSIGNED  mem_unsigned
`define c_REG_WRITE     reg_write
`define c_WB_SEL        wb_sel

// `is_branch`, `is_jal` and `is_jalr` are mutually exclusive: at most one is
// high for any instruction.  `is_illegal` is independent of them - an
// unimplemented encoding sets `is_illegal` and none of the three.
//
// The single-bit control fields are packed into whole bytes inside the stage
// bundles; pipeline_regs.vh places byte 0 (the memory-control and writeback
// group) at the bottom of ID/EX and EX/MEM, and byte 1 (the control-class and
// register-field-meaning group) above them in ID/EX only.
`define c_CTRL_BYTE_W   8

`endif // SOC_CTRL_FIELDS_VH

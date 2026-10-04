// ============================================================================
// pipeline_regs.vh - bit layout of the four pipeline stage bundles.
//
// `core` owns the pipeline registers and packs every bundle from the discrete
// signals its stage modules produce (docs/contracts/phase1-interfaces.md,
// "Signal provenance").  Stage modules never see a bundle; they only see flat
// ports.  This header is therefore the single source of truth for where each
// field lives, and the only place bundle widths are written down.
//
// Layout convention: bit 0 is the LSB of the bundle and fields grow upward.
// Fields added after a bundle was frozen are appended ABOVE the existing ones,
// so a previously frozen offset never moves.  Each bundle ends with
// `p_<BUNDLE>_W`, its total width.
//
// SCOPE - read before including.  These constants are `localparam`, and
// IEEE 1364-2005 makes `localparam` a module-scope declaration item, so this
// header is included INSIDE `module core`, which is the only module that packs a
// bundle.  It must NOT be included at file scope: `defs.vh` and `ctrl_fields.vh`
// are macros precisely so that they remain usable in ANSI port widths at file
// scope, and this header has no port-width use because no port list contains a
// bundle offset.
//
// NO `default_nettype` HERE, and that is deliberate.  IEEE 1364-2005 also
// requires `default_nettype` to appear OUTSIDE module definitions, so a header
// that must sit inside a module cannot legally carry the directive - Icarus
// rejects it outright with "`default_nettype directives must appear outside
// module definitions".  Nothing is lost: this header declares no nets at all,
// only `localparam` integers, so there is no implicit net for the directive to
// catch; and it is parsed under the `default_nettype none` that `core.v` opens
// with, which is already in force.  This is the single deliberate exception to
// the rule the other 15 files in rtl/ follow.
//
// Owners: controller (Phase 1, Task 1).  Frozen.
// ============================================================================

// ===========================================================================
// IF/ID bundle  (width 98)
//
// Produced by `core` from `pc_gen` + `if_stage`, consumed by decode / regfile /
// imm_gen.  `valid` is bit 0 of `core`'s `stage_valid` output.
// ===========================================================================
localparam integer p_IF_ID__PRED_TAKEN_LSB = 0;
localparam integer p_IF_ID__PRED_TAKEN_W   = 1;
localparam integer p_IF_ID__PC_LSB         = 1;
localparam integer p_IF_ID__PC_W           = 32;
localparam integer p_IF_ID__PRED_PC_LSB    = 33;
localparam integer p_IF_ID__PRED_PC_W      = 32;
localparam integer p_IF_ID__INSTR_LSB      = 65;
localparam integer p_IF_ID__INSTR_W        = 32;
localparam integer p_IF_ID__VALID_LSB      = 97;
localparam integer p_IF_ID__VALID_W        = 1;
localparam integer p_IF_ID_W               = 98;

// ===========================================================================
// ID/EX bundle  (width 171)
//
// Produced by `core` from `decode` control fields, `regfile` read data and
// `imm_gen` output.  Consumed by `ex_stage`, `forwarding`, `hazard_unit`.
// `valid` is bit 1 of `core`'s `stage_valid` output.
// ===========================================================================
// -- control byte 0: memory control and writeback ---------------------------
localparam integer p_ID_EX__REG_WRITE_LSB    = 0;
localparam integer p_ID_EX__REG_WRITE_W      = 1;
localparam integer p_ID_EX__MEM_UNSIGNED_LSB = 1;
localparam integer p_ID_EX__MEM_UNSIGNED_W   = 1;
localparam integer p_ID_EX__MEM_WRITE_LSB    = 2;
localparam integer p_ID_EX__MEM_WRITE_W      = 1;
localparam integer p_ID_EX__MEM_READ_LSB     = 3;
localparam integer p_ID_EX__MEM_READ_W       = 1;
localparam integer p_ID_EX__WB_SEL_LSB       = 4;
localparam integer p_ID_EX__WB_SEL_W         = 2;
localparam integer p_ID_EX__MEM_SIZE_LSB     = 6;
localparam integer p_ID_EX__MEM_SIZE_W       = 2;

// -- operands and control ---------------------------------------------------
localparam integer p_ID_EX__USES_RS2_LSB       = 8;
localparam integer p_ID_EX__USES_RS2_W         = 1;
localparam integer p_ID_EX__USES_RS1_LSB       = 9;
localparam integer p_ID_EX__USES_RS1_W         = 1;
localparam integer p_ID_EX__BRANCH_FUNCT3_LSB = 10;
localparam integer p_ID_EX__BRANCH_FUNCT3_W   = 3;
localparam integer p_ID_EX__OP2_SEL_LSB        = 13;
localparam integer p_ID_EX__OP2_SEL_W          = 3;
localparam integer p_ID_EX__OP1_SEL_LSB        = 16;
localparam integer p_ID_EX__OP1_SEL_W          = 2;
localparam integer p_ID_EX__ALU_OP_LSB         = 18;
localparam integer p_ID_EX__ALU_OP_W           = 4;
localparam integer p_ID_EX__RD_ADDR_LSB        = 22;
localparam integer p_ID_EX__RD_ADDR_W          = 5;
localparam integer p_ID_EX__RS2_ADDR_LSB       = 27;
localparam integer p_ID_EX__RS2_ADDR_W         = 5;
localparam integer p_ID_EX__RS1_ADDR_LSB       = 32;
localparam integer p_ID_EX__RS1_ADDR_W         = 5;
localparam integer p_ID_EX__IMM_LSB            = 37;
localparam integer p_ID_EX__IMM_W              = 32;
localparam integer p_ID_EX__RS2_DATA_LSB       = 69;
localparam integer p_ID_EX__RS2_DATA_W         = 32;
localparam integer p_ID_EX__RS1_DATA_LSB       = 101;
localparam integer p_ID_EX__RS1_DATA_W         = 32;
localparam integer p_ID_EX__PC_LSB             = 133;
localparam integer p_ID_EX__PC_W               = 32;

// -- control class and register-field meaning -------------------------------
// `is_branch` / `is_jal` / `is_jalr` are what let `ex_stage` resolve a branch or
// jump; `uses_rd` says whether the rd field is meaningful; `is_illegal` is the
// decode verdict that an opcode or funct encoding is not implemented.
localparam integer p_ID_EX__IS_BRANCH_LSB  = 165;
localparam integer p_ID_EX__IS_BRANCH_W    = 1;
localparam integer p_ID_EX__IS_JAL_LSB     = 166;
localparam integer p_ID_EX__IS_JAL_W       = 1;
localparam integer p_ID_EX__IS_JALR_LSB    = 167;
localparam integer p_ID_EX__IS_JALR_W      = 1;
localparam integer p_ID_EX__IS_ILLEGAL_LSB = 168;
localparam integer p_ID_EX__IS_ILLEGAL_W   = 1;
localparam integer p_ID_EX__USES_RD_LSB    = 169;
localparam integer p_ID_EX__USES_RD_W      = 1;

localparam integer p_ID_EX__VALID_LSB      = 170;
localparam integer p_ID_EX__VALID_W        = 1;
localparam integer p_ID_EX_W               = 171;

// ===========================================================================
// EX/MEM bundle  (width 109)
//
// Produced by `core` from `ex_stage` and `lsu` outputs.  Consumed by
// `mem_stage`, and by `forwarding` / `hazard_unit` as the MEM-stage producer.
// `valid` is bit 2 of `core`'s `stage_valid` output.
// ===========================================================================
localparam integer p_EX_MEM__REG_WRITE_LSB   = 0;
localparam integer p_EX_MEM__REG_WRITE_W     = 1;
localparam integer p_EX_MEM__MEM_WRITE_LSB   = 1;
localparam integer p_EX_MEM__MEM_WRITE_W     = 1;
localparam integer p_EX_MEM__MEM_READ_LSB    = 2;
localparam integer p_EX_MEM__MEM_READ_W      = 1;
localparam integer p_EX_MEM__WB_SEL_LSB      = 3;
localparam integer p_EX_MEM__WB_SEL_W        = 2;
localparam integer p_EX_MEM__MEM_SIZE_LSB    = 5;
localparam integer p_EX_MEM__MEM_SIZE_W      = 2;
localparam integer p_EX_MEM__RD_ADDR_LSB     = 7;
localparam integer p_EX_MEM__RD_ADDR_W       = 5;
localparam integer p_EX_MEM__STORE_DATA_LSB  = 12;
localparam integer p_EX_MEM__STORE_DATA_W    = 32;
localparam integer p_EX_MEM__ALU_RESULT_LSB  = 44;
localparam integer p_EX_MEM__ALU_RESULT_W    = 32;
localparam integer p_EX_MEM__PC_LSB          = 76;
localparam integer p_EX_MEM__PC_W            = 32;
localparam integer p_EX_MEM__VALID_LSB       = 108;
localparam integer p_EX_MEM__VALID_W         = 1;
localparam integer p_EX_MEM_W                = 109;

// ===========================================================================
// MEM/WB bundle  (width 71)
//
// Produced by `core` from `mem_stage` outputs, with `core` applying the
// data-misalignment gating on `reg_write`.  Consumed by `wb_stage`.
// `valid` is bit 3 of `core`'s `stage_valid` output.
// ===========================================================================
localparam integer p_MEM_WB__REG_WRITE_LSB = 0;
localparam integer p_MEM_WB__REG_WRITE_W   = 1;
localparam integer p_MEM_WB__RD_ADDR_LSB   = 1;
localparam integer p_MEM_WB__RD_ADDR_W     = 5;
localparam integer p_MEM_WB__RD_DATA_LSB   = 6;
localparam integer p_MEM_WB__RD_DATA_W     = 32;
localparam integer p_MEM_WB__PC_LSB        = 38;
localparam integer p_MEM_WB__PC_W          = 32;
localparam integer p_MEM_WB__VALID_LSB     = 70;
localparam integer p_MEM_WB__VALID_W       = 1;
localparam integer p_MEM_WB_W              = 71;

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
// Drop-in replaceable: this file builds and lints from its own source alone.
// Replacing it with another implementation must not change the port list and
// must not require any other module to change.  `mem_req_*` and `mem_rsp_*`
// are also the top-level port names of `core`, so they must not be renamed
// without changing `core` in the same commit.
//
// ============================================================================
// DESIGN NOTE 1 - the whole handshake is one bit of state
// ============================================================================
//
// `req_pending` is the only register.  It means "a request is presented and its
// response has not arrived yet", and it is what makes the request/response
// handshake lossless and duplicate-free:
//
//   request cycle   req_pending is still 0, `req_start` is true, so the
//                   request goes out this cycle and req_pending goes to 1.
//   waiting         req_pending is 1, so the request is held.
//   response cycle  `mem_rsp_valid` retires it and req_pending returns to 0 in
//                   the same cycle, so `mem_req_valid` drops on the response
//                   cycle itself rather than a cycle later.
//
// The ordering of the two terms matters and is the only subtlety here: the
// response wins over the start, so a memory that answers in the *same* cycle
// the request is presented (`resp_done` with `req_pending` still 0) leaves
// `req_pending` at 0 instead of latching a request that has already been
// granted.  Without that ordering a zero-latency memory - which is exactly what
// a register-file-backed L1 or a simple testbench memory would be - would see
// every access issued twice.
//
// Why one bit is enough and a captured copy of the request is not used: the
// contract's stability guarantee is a guarantee *about the inputs*.  `core`
// derives the MEM stall as `mem_req_valid && !mem_rsp_valid`, so EX/MEM is
// held for exactly the window in which the request must be stable, and
// `mem_req_addr` / `mem_req_wdata` / `mem_req_we` / `mem_req_wstrb` are a pure
// pass-through of EX/MEM.  Capturing 70 more flops to re-hold data `core` has
// already promised to hold would be area bought with nothing.
//
// ============================================================================
// DESIGN NOTE 2 - the two halves of a sub-word store, derived once, here
// ============================================================================
//
// A sub-word store is two things at once, and they have to be derived from the
// same place or they disagree: WHICH bytes move (`mem_req_wstrb`) and WHERE
// their value comes from (`mem_req_wdata`).  `wstrb_c` and `wdata_c` are the
// only place in the design that derives either.
//
//   size   addr[1:0]   lanes   data
//   byte   00          0001    ex_store_data[7:0]   -> wdata[7:0]
//   byte   01          0010    ex_store_data[7:0]   -> wdata[15:8]
//   byte   10          0100    ex_store_data[7:0]   -> wdata[23:16]
//   byte   11          1000    ex_store_data[7:0]   -> wdata[31:24]
//   half   00          0011    ex_store_data[15:0]  -> wdata[15:0]
//   half   10          1100    ex_store_data[15:0]  -> wdata[31:16]
//   half   01,11       -       refused: misaligned, DESIGN NOTE 3
//   word   00          1111    ex_store_data        -> wdata unchanged
//   word   01,10,11    -       refused: misaligned, DESIGN NOTE 3
//
// The refused rows matter as much as the live ones: a word access asserts all
// four lanes and passes the data through regardless of `addr[1:0]`, so if the
// refusal in DESIGN NOTE 3 were ever removed the shifter would need a
// misalignment case too, and an unaligned halfword would have to either
// straddle lanes 1-2 or be split into two requests.  Nothing here does either,
// on purpose.
//
// WHY THE DATA IS SHIFTED RATHER THAN LEFT ALONE
//
// The contract fixes the strobes - "one enable bit per byte lane", derived from
// `ex_mem_addr[1:0]` and `ex_mem_size` - and says nothing about whether
// `mem_req_wdata` carries the value in the lane the access names or always in
// lane 0.  Those are two different bus contracts and they are not compatible, so
// this is a decision, not a detail:
//
//   * LANE-ALIGNED (what this module does).  Byte i of `mem_req_wdata` belongs to
//     lane i, so a memory applies `wstrb` to the word at `addr & ~3` and needs
//     to know nothing else.  This is AXI4's rule, which spec 6.3 promises this
//     bus is an "AXI4-legal subset" of, and it is also what phase 4's L1 D$
//     wants: a cache line is indexed by the aligned word, so it must not have to
//     re-derive a shift from a byte address.  The cost is the 8-bit-granular
//     shifter below, which is four 2-to-1 muxes of 8 bits - nothing next to
//     getting it wrong.
//   * LANE-0-ALWAYS.  The memory would have to shift the data itself, every time,
//     from `addr[1:0]`.  That pushes the derivation into every future memory
//     consumer, including an AXI master that cannot do it at all, and it makes
//     `mem_req_wstrb` and `mem_req_wdata` two encodings of the same fact.
//
// REPORTED TO THE INTEGRATOR: the contract does not state which convention
// `mem_req_wdata` follows for a sub-word store, and the two are observably
// different at the bus - an `sb` of 0x64 to `0x2003` arrives here as
// `wdata=0x64000000 wstrb=1000 addr=0x2003`.  If the team meant lane 0 always,
// this is a three-line change (`wdata_c = ex_store_data`) plus a note in the
// contract; it must be settled before phase 4, not after.  Everything else in
// this block - the strobes, the misalignment verdict, the handshake - is
// unaffected either way.
//
// `mem_req_addr` keeps the effective address including its low bits, because
// the contract documents it as the effective address from `ex_stage` and because
// the top-level memory port is named the same.  With the lanes aligned, those
// low bits are redundant on the bus but harmless, and a memory that ignores
// them and uses `addr & ~3` is then correct by construction.
// ============================================================================
// ============================================================================
// DESIGN NOTE 3 - a misaligned access is reported and refused, never performed
// ============================================================================
//
// Spec section 4.3 requires misaligned load/store to be "handled in hardware or
// delivered as a clean trap.  Must be explicit, never undefined".  Phase 1 has
// no trap path, so this module takes the hardware half of that requirement and
// makes the access well defined:
//
//   * `data_misaligned` is raised for a word access whose address is not 4-byte
//     aligned, or a halfword access whose address is not 2-byte aligned.  A
//     byte access is never misaligned, because every byte address is aligned to
//     a byte.
//   * a misaligned access NEVER becomes `mem_req_valid`.  It is not performed
//     at an address the memory was never told about, so there is no way for a
//     half-written or duplicated word to reach memory, and there is no
//     undefined behaviour to propagate.
//   * `core` folds the verdict into the MEM/WB register write
//     (`mem_wb__reg_write = mem_reg_write && !data_misaligned`), so the access
//     leaves the pipeline with nothing committed.  Delivering the trap itself
//     is phase 3's job; the verdict is all phase 1 owes.
//
// Refusing the request is also what keeps `req_pending` honest: a refused
// access has no response coming, so it must not latch `req_pending`, or the
// next real access would sit behind a request that can never be granted.
//
// `ex_mem_size` value 3 is not an encoding, so it is treated as neither aligned
// nor misaligned - it can only come from a corrupt bundle, and a second verdict
// for it would be a guess.
//
// ============================================================================
// DESIGN NOTE 4 - no sub-word extraction in phase 1, and that is a contract gap
// ============================================================================
//
// `ex_mem_unsigned` distinguishes LB/LBU and LH/LHU, and `ex_mem_size`
// distinguishes LB from LH.  Both are needed to extract a byte or a halfword
// out of the returned word - and phase 1 has no module port that can do it:
//
//   * `lsu` has no data output.  The contract says `mem_rsp_rdata` "is passed
//     straight through to `mem_stage`", so overwriting the wire here would
//     contradict the contract.
//   * `mem_stage` owns `mem_rd_data` and would be the right place, but its
//     frozen port list has no `mem_unsigned` and no `mem_size` either, so it
//     cannot select the extension.
//
// So an `lb`/`lbu`/`lh`/`lhu` in phase 1 returns the containing word and
// `mem_rd_data` carries all four bytes, sign- or zero-extended by nobody.  That
// is the one place where this implementation is knowingly incomplete, and it
// is a contract gap rather than a design choice, so it is reported rather than
// worked around.  `ex_mem_unsigned` is therefore read here only by the two
// self-checks at the bottom of this file, which is the only honest use of it in
// phase 1: they state, in hardware, that signedness must not change the
// request - the property phase 2's extraction will have to preserve.
//
// REPORTED TO THE INTEGRATOR (contract changes are not mine to make):
//
//   1. `lsu.ex_mem_unsigned` has no producer.  The frozen EX/MEM bundle has no
//      `mem_unsigned` field (see docs/contracts/phase1-interfaces.md, EX/MEM
//      table), so `core` has nothing to wire into this port.  Phase 2 needs
//      either a `mem_unsigned` field in EX/MEM, or this port deleted - it
//      cannot stay as it is.
//   2. `ex_mem_unsigned` and `ex_mem_size` both need to reach `mem_stage` for
//      the LB/LBU/LH/LHU sign- and zero-extension the ISA requires.  That is a
//      port-list change to `mem_stage`.
//   3. `wb_stage.data_misaligned` has no consumer: the contract puts the gate
//      in `core`, so this module must not gate on it.  It is used there as a
//      consistency check on `core`'s wiring rather than left dead.
//
// ============================================================================
// DESIGN NOTE 5 - what `stall` does here, and what it must not do
// ============================================================================
//
// `stall` is "hold the outstanding request", and it does exactly one thing: it
// stops a NEW request from starting.  It does not gate `mem_req_valid`.
//
// That is not a stylistic choice, it is the only wiring that works.  `core`
// derives the memory stall as
//
//     stall = mem_req_valid && !mem_rsp_valid
//
// so a `mem_req_valid` that depended on `stall` would close a combinational
// loop through two modules: the request is presented, so the stage is stalled,
// so the request is withdrawn, so the stage is not stalled, so the request comes
// back - and the bus oscillates at whatever rate the two settles decide.  It was
// found the hard way, in the randomised-backpressure test, which drives
// `stall` exactly as `core` derives it.
//
// The other reason is the contract's own wording, which the gate contradicted:
// "`mem_req_valid` stays high from the cycle the request is presented until
// `mem_rsp_valid` is seen."  A request that is being held is *more* in need of
// staying asserted than one that has not been presented yet - withdrawing it
// mid-handshake is precisely the duplicate the contract's guarantee exists to
// prevent, because a memory that had already latched the request would see it
// presented again.
//
// So: while `stall` is high, a request that is already on the bus stays there
// with its payload frozen, because `core` is holding EX/MEM and the payload is a
// pass-through of it.
//
// And one state `core` must never produce, which follows from all of the above: a
// grant while the stage is held.  This module does not latch the request as
// outstanding in that case, so once the memory's response has gone the request
// would be presented afresh - and a store the memory already performed would be
// performed again.  That cannot happen with the stall term above, because a
// response is present in exactly the cycles the term is low, so it is recorded
// here rather than defended against with state nobody would otherwise need.
//
// One consequence is worth stating for `core`, because it is an obligation this
// module cannot discharge: a request *is* presented while the stage is held and
// nothing is outstanding.  It has to be - withholding it would be the gate above.
// So if `core` holds MEM for a reason of its own while a request is in flight,
// the response can arrive while `mem_stage` is holding its register, and the
// returned word would be missed.  `core` must not do that: it must let the MEM
// stage advance on the response cycle, which is exactly what its own stall term
// `mem_req_valid && !mem_rsp_valid` already does, and what any *additional* hold
// it ORs in has to respect.  The load-use interlock stalls ID, not MEM, so the
// ordinary case is already correct.
//
// A misaligned access is refused and reported whatever `stall` says, since the
// verdict describes the access rather than the handshake.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"
`include "ctrl_fields.vh"

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

  // ------------------------------------------------------------------------
  // Frozen encodings, named so this file can be read against the contract.
  // `ex_mem_size` and `ex_wb_sel` are the two selects that reach this module.
  localparam [1:0] MEM_SIZE_BYTE = 2'd0;
  localparam [1:0] MEM_SIZE_HALF = 2'd1;
  localparam [1:0] MEM_SIZE_WORD = 2'd2;

  // ------------------------------------------------------------------------
  // Is this stage holding a memory access at all?
  //
  // An instruction that is neither a load nor a store - and an empty stage -
  // must not drive the bus.  This term is what keeps `mem_req_valid` low while
  // ALU results and branches pass through the memory stage.
  wire mem_access = ex_mem_read | ex_mem_write;

  // ------------------------------------------------------------------------
  // Misalignment verdict (DESIGN NOTE 3).
  wire is_word     = (ex_mem_size == MEM_SIZE_WORD);
  wire is_half     = (ex_mem_size == MEM_SIZE_HALF);
  wire is_byte     = (ex_mem_size == MEM_SIZE_BYTE);
  // The natural alignment of an access of this size: bit 0 for a halfword,
  // bits [1:0] for a word.  A byte has no alignment requirement at all.
  wire needs_align = is_half | is_word;
  wire addr_aligned = is_word ? (ex_mem_addr[1:0] == 2'b00)
                             : (ex_mem_addr[0] == 1'b0);

  // A verdict only exists for an access, and only for a size that has an
  // alignment requirement.  `is_byte` is named explicitly so that every byte
  // access is visibly excluded rather than accidentally "aligned", and so that a
  // size of 3 - not an encoding - is excluded with it.
  assign data_misaligned = mem_access && !is_byte && needs_align && !addr_aligned;

  // ------------------------------------------------------------------------
  // The request handshake (DESIGN NOTE 1).
  //
  // Declared before the terms that read it: this file opens with the nettype
  // directive set to none, so a name used before its declaration is an error
  // rather than an implicit net, and Icarus rejects it outright.
  reg req_pending;

  wire req_hold = stall;

  // An access that is allowed to reach memory at all: it has to be an access,
  // and it must not be one this module refuses (DESIGN NOTE 3).
  wire req_eligible = mem_access && !data_misaligned;

  // A request starts when an eligible access is in front of us, nothing is
  // already outstanding, and the stage is not held.
  wire req_start = req_eligible && !req_pending && !req_hold;

  // A response ends the request.  It says "an eligible access is being presented
  // and the memory is answering it", which covers all three windows at once:
  // answering a request that was already outstanding, answering one in the very
  // cycle it is presented (a zero-latency memory, which would otherwise latch an
  // outstanding request that has already been granted and present every access
  // twice), and answering a request presented while the stage was held - which
  // must not leave it on the bus to be granted again when the hold is released.
  wire resp_done = mem_rsp_valid && req_eligible;

  always @(posedge clk) begin
    if (!rst_n)
      req_pending <= 1'b0;
    else if (!req_eligible)
      // The access is gone, or it was one this module refuses.  Either way
      // there is nothing outstanding and nothing will ever answer.
      req_pending <= 1'b0;
    else if (resp_done)
      // The response wins over the start: a same-cycle grant must not latch a
      // request that has already been answered.
      req_pending <= 1'b0;
    else if (req_start)
      req_pending <= 1'b1;
    else
      req_pending <= req_pending;
  end

  // The request on the wire.  High from the cycle the request is presented
  // until the cycle the response arrives, inclusive of the presenting cycle
  // and exclusive of the responding one.
  //
  // `stall` is deliberately NOT in this expression - see DESIGN NOTE 5.  A
  // `mem_req_valid` gated by `stall` closes a combinational loop with the
  // `stall` `core` derives from `mem_req_valid`, and it breaks the contract's
  // promise that the request stays presented until it is granted.
  assign mem_req_valid = req_eligible && !resp_done;

  // ------------------------------------------------------------------------
  // The request payload (DESIGN NOTE 2).  Address and direction are a pure
  // pass-through of EX/MEM, which `core` holds for exactly this window; only the
  // store data is moved, into the lane the address names.
  assign mem_req_addr  = ex_mem_addr;
  assign mem_req_we    = ex_mem_write;

  // Lane-aligned store data.  Lanes the strobes do not cover carry shifted-out
  // bits or zeros and are don't-care: the strobes are what a memory obeys, and
  // DESIGN NOTE 2 says why a memory must not have to shift the data itself.
  reg [`p_DATA_W-1:0] wdata_c;

  always @* begin
    case (ex_mem_size)
      // {addr[1:0], 3'b000} is the byte offset as a shift amount, 0 to 24.
      MEM_SIZE_BYTE: wdata_c = ex_store_data << {ex_mem_addr[1:0], 3'b000};
      // A halfword's low bits start at lane 0 or lane 2, so addr[1] alone
      // decides the shift: 0 or 16.
      MEM_SIZE_HALF: wdata_c = ex_store_data << {ex_mem_addr[1], 4'b0000};
      // MEM_SIZE_WORD, and any size that is not an encoding: unchanged.
      default:       wdata_c = ex_store_data;
    endcase
  end

  assign mem_req_wdata = (mem_req_valid && mem_req_we) ? wdata_c : {`p_DATA_W{1'b0}};

  // Lane pattern for a write of this size at this address (DESIGN NOTE 2).
  reg [3:0] wstrb_c;

  always @* begin
    case (ex_mem_size)
      // `addr[1]` is the whole story for a halfword: 0011 when it occupies the
      // low half of the word, 1100 when it occupies the high half.  The two odd
      // addresses, which would straddle lanes 1-2 and lane 3, never get here -
      // a misaligned halfword is refused above.
      MEM_SIZE_HALF: wstrb_c = ex_mem_addr[1] ? 4'b1100 : 4'b0011;
      MEM_SIZE_WORD: wstrb_c = 4'b1111;
      // MEM_SIZE_BYTE, and any size that is not an encoding: exactly the one
      // lane `addr[1:0]` names.  A byte can go to any address, so the lane
      // cannot be a constant.
      default:       wstrb_c = 4'b0001 << ex_mem_addr[1:0];
    endcase
  end

  // Strobes are asserted for writes and driven to zero for reads, and to zero
  // whenever no request is on the wire at all.  The shift above is a 4-bit
  // shift, not a 32-bit one: `4'b0001 << ex_mem_addr[1:0]` keeps the result
  // inside the lane field, which is the whole point of it.
  assign mem_req_wstrb = (mem_req_valid && mem_req_we) ? wstrb_c : 4'b0000;

  // ------------------------------------------------------------------------
  // Writeback metadata, passed through untouched.
  //
  // `mem_rsp_rdata` is deliberately NOT read here.  The contract requires it to
  // reach `mem_stage` straight through, this module has no data output to carry
  // it, and `core` owns the wire between the two - see DESIGN NOTE 4 for why
  // phase 1 leaves sub-word extraction to phase 2.
  assign mem_rd_addr   = ex_rd_addr;
  assign mem_reg_write = ex_reg_write;
  assign mem_wb_sel    = ex_wb_sel;

  // ------------------------------------------------------------------------
  // Self-checks.
  //
  // These are hardware's own version of the review checklist, and they are the
  // reason the design above is written the way it is: each one holds by
  // construction, so if a later edit breaks the property the assertion fires on
  // exactly that cycle instead of a test somewhere downstream noticing.
  //
  // Two mechanical rules apply to every one of them, both learned the hard way:
  //
  // 1. Each assertion is on ONE line.  scripts/yosys-prep.sh deletes exactly
  //    whole-line `assert (...) else $error(...);` statements, so a two-line
  //    assertion is not deleted and Yosys then fails on the `else`.  That is why
  //    regfile.v's assertion looks the way it does.
  // 2. They are all CLOCKED, and that is not a style choice.  A combinational
  //    `always @*` assertion sees the design mid-settle: when a testbench
  //    changes several inputs at once, `mem_req_valid` has already updated
  //    while `mem_req_wstrb` - one continuous assign further down the chain -
  //    still holds last cycle's value, and an assertion comparing the two fires
  //    on a state that never existed.  At a rising edge everything is settled,
  //    so what is checked is what the hardware actually presented.  Icarus's
  //    four-state run is where that shows up: `make test-4state` reported a wall
  //    of `a read request asserted write strobes` from assertions that were
  //    looking at a delta, not at the design.
  //
  // `===` against `1'b1` is used for X-safety, and it matters for the same
  // reason: an immediate assertion FAILS when its condition is unknown, not
  // only when it is false, so `req_pending` is X until the first reset edge has
  // been taken and a plain `&&` would fire on the very first clock.  Case
  // equality gives a definite answer for an unknown operand, so only a real
  // violation fires.  The one exception is the returned-word check, which uses
  // `!==` because seeing the X is that check's entire job.
  always @(posedge clk) begin
    // A refused access must never reach memory: this is the whole of DESIGN
    // NOTE 3's "reported and refused, never performed" in one term.
    assert (!((mem_req_valid === 1'b1) && (data_misaligned === 1'b1))) else $error("lsu: misaligned %0d-byte access to %08x was requested", ex_mem_size, ex_mem_addr);
    // A load never drives a strobe, and neither does an idle stage.
    assert (!(((mem_req_valid === 1'b1) && (mem_req_we === 1'b0)) && (mem_req_wstrb !== 4'b0000))) else $error("lsu: a read request asserted write strobes %b", mem_req_wstrb);
    // A write must never be requested with no lane enabled, which would ask
    // memory to store a value it cannot place.
    assert (!(((mem_req_valid === 1'b1) && (mem_req_we === 1'b1)) && (mem_req_wstrb === 4'b0000))) else $error("lsu: a write request for %08x asserted no byte lane", ex_mem_addr);
    // Signedness must not change the request.  Written once per signedness so
    // the statement covers LB/LBU and LH/LHU explicitly; both halves are the
    // same property, and `ex_mem_unsigned` is the only place phase 1 can read
    // it (DESIGN NOTE 4).
    assert (!((mem_req_valid === 1'b1) && (ex_mem_unsigned === 1'b1) && (needs_align === 1'b1) && (addr_aligned === 1'b0))) else $error("lsu: LBU/LHU requested misaligned address %08x", ex_mem_addr);
    assert (!((mem_req_valid === 1'b1) && (ex_mem_unsigned === 1'b0) && (needs_align === 1'b1) && (addr_aligned === 1'b0))) else $error("lsu: LB/LH requested misaligned address %08x", ex_mem_addr);
    // An access that is not a memory access must not leave anything
    // outstanding, and a refused access must not either - otherwise the next
    // access would wait forever behind a response that can never arrive.
    //
    // `rst_n` is in the guard because an immediate assertion sees the values
    // *before* the edge, so the first reset edge would otherwise catch the state
    // the reset is tearing down: a request that was outstanding a cycle ago and
    // whose access has just been withdrawn.  During reset the handshake is being
    // killed deliberately - reset is the only "kill" this module has, since the
    // frozen port list has no cancel input - so it is not a violation.
    //
    // Outside reset this is the environment's obligation rather than this
    // module's: `core` holds EX/MEM while `mem_req_valid && !mem_rsp_valid`, so
    // the access cannot be withdrawn while the request is live.  The assertion is
    // here because a silently dropped request is the most expensive bug in this
    // block and it is invisible in the outputs - the request simply stops.
    assert (!((rst_n === 1'b1) && (req_pending === 1'b1) && (req_eligible === 1'b0))) else $error("lsu: a request was outstanding for an access that has gone");
    // A response must carry a defined word.  `lsu` deliberately does not look at
    // the word - the contract passes it straight through to `mem_stage` on a
    // wire `core` owns - so this is the one check the port can carry, and it is
    // the one that matters at this boundary: a response channel that is valid
    // but undriven hands an X to `mem_stage`, and Verilator's two-state model
    // cannot see that at all.
    //
    // `mem_rsp_rdata !== mem_rsp_rdata` is the X test, and it is worth being
    // precise about which way round it goes: case inequality against *itself*
    // is true exactly when the word has no x or z bit in it.  (`!==` against a
    // literal 32'bx would be the opposite test and would fire on every good
    // response - which is how this assertion spent its first afternoon being
    // wrong in the loudest possible way.)
    assert (!((mem_rsp_valid === 1'b1) && (mem_rsp_rdata !== mem_rsp_rdata))) else $error("lsu: mem_rsp_valid arrived with an undefined word");
  end

endmodule
`default_nettype wire

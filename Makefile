# ============================================================================
# Makefile - build and verification harness for the RV32IMAC SoC.
#
# Two properties this file exists to enforce:
#
#   1. MODULAR / DROP-IN.  The source list for a build is derived from the
#      module NAME ($(TOP)), never from a glob, so a build can only ever
#      contain the one module named by $(TOP) plus the shared headers.  If a
#      module could be built only because a sibling happened to be on the
#      command line, the drop-in rule would be unenforced.
#
#   2. -Wall IS A HARD GATE.  `make lint` must report zero warnings for every
#      module.  No lint waivers are added here and -Wall is never weakened.
#
# NO '**' GLOBS ANYWHERE.  make invokes /bin/sh, and macOS /bin/sh (bash in
# POSIX mode) has no globstar, so '**' silently matches nothing -- and a lint
# run over zero files exits 0, so the gate would pass while checking nothing.
# The empty-source-list guard below is the backstop for that class of bug.
#
# Everyday commands:
#   make lint                make asic-check        make area
#   make test                make test-contracts
#   make test-4state
#   make sw                  make arch-test
#
# Selecting what is built / tested:
#   make lint TOP=alu                          lint one module on its own
#   make test TOP=alu                          run tb/test_alu.py against alu
#   make test-4state TOP=alu                   the same under Icarus (4-state)
#   make test MODULE=test_alu_a TOP=alu        a second regression for one DUT
# ============================================================================

# --- what to build / test ---------------------------------------------------
TOP    ?= core
# A test module is conventionally named test_<TOP>, so `make test TOP=alu` finds
# tb/test_alu.py on its own.  MODULE= still overrides it explicitly.
MODULE ?= test_$(TOP)

# --- tools -----------------------------------------------------------------
# cocotb lives in ./.venv (see docs/SETUP.md).  Fall back to whatever python3
# is on PATH so the Makefile still works on a machine set up by hand.
PYTHON ?= $(firstword $(wildcard .venv/bin/python) python3)

# --- shared headers --------------------------------------------------------
# Supplied on the include path so every module says `include "defs.vh" with no
# relative path, and can be built from its own source file alone.
INCDIRS  := +incdir+rtl/core +incdir+rtl/common
YOSYS_INC := -I rtl/core -I rtl/common

# --- per-module source list (drop-in rule) ---------------------------------
# The twelve modules `core` is allowed to instantiate.  Kept as an explicit
# name list, never a glob.  `core` is the documented exception in
# docs/contracts/phase1-interfaces.md: it is the one file allowed to
# instantiate the other twelve, so its source list is itself plus these.
CORE_CHILDREN := pc_gen if_stage regfile decode imm_gen alu ex_stage lsu \
                 mem_stage wb_stage hazard_unit forwarding

ifeq ($(TOP),core)
SRCS := rtl/core/core.v \
        $(addprefix rtl/core/,$(addsuffix .v,$(CORE_CHILDREN)))
else
# $(wildcard), NOT $(shell find ...).  $(wildcard) is evaluated by make itself with
# no shell, so this behaves identically on macOS, Linux and Windows.  $(shell find)
# breaks on Windows, where find.exe is a text-search tool, not Unix find.
# One module per file and file name == module name, so wildcard is exact.
SRCS := $(wildcard rtl/core/$(TOP).v rtl/common/$(TOP).v)
endif

# Backstop for "a glob matched no files, so the gate passed on nothing".
ifeq ($(strip $(SRCS)),)
$(error TOP='$(TOP)' matched no source file.  $(TOP).v does not exist under rtl/. \
Lint on zero files exits 0, so this must fail rather than pass.)
endif

# --- liberty ---------------------------------------------------------------
LIBERTY ?= third_party/sky130_fd_sc_hd__tt_025C_1v80.lib

.PHONY: lint asic-check area test test-4state test-contracts sw arch-test

# --- lint ------------------------------------------------------------------
# Verilator, one module at a time.  -Wall must come back with zero warnings.
lint:
	verilator --lint-only -Wall --top-module $(TOP) $(INCDIRS) $(SRCS)

# --- asic-check ------------------------------------------------------------
# Two gates, in this order:
#
#   hierarchy -check   REAL ELABORATION.  This is the only thing that catches an
#                     inconsistent port list -- an orphaned or renamed port in
#                     an instantiation.  Green lint does NOT prove it: every
#                     stub suppresses Verilator's UNDRIVEN and UNUSEDSIGNAL on
#                     its port list because the body is empty, so an orphan
#                     port lints clean.  Do not weaken lint and assume it
#                     covers this; hierarchy -check is the mechanism.
#   synth -flatten     synthesises the elaborated design for real.
#   dfflibmap + abc    map the result onto $(LIBERTY)'s cells.  Without this
#                     the netlist is still word-level ($_DFF_PN0_ and friends),
#                     which have no entry in the liberty file, and stat
#                     reports "Area for cell type ... is unknown!" instead of a
#                     number.
#   stat -liberty      reports the mapped cell area in um^2.
#
# scripts/yosys-prep.sh exists because Yosys's built-in Verilog frontend cannot
# parse the immediate-assertion form the modules use; see that script for the
# full explanation and for what it deliberately refuses to strip.
asic-check:
	@test -f $(LIBERTY) || { \
	  echo "asic-check: liberty file $(LIBERTY) is missing."; \
	  echo "            run: scripts/fetch-liberty.sh"; \
	  exit 1; \
	}
	@test -x scripts/yosys-prep.sh || { \
	  echo "asic-check: scripts/yosys-prep.sh is missing or not executable"; \
	  exit 1; \
	}
	@yosys_srcs="$$(CORE_CHILDREN='$(CORE_CHILDREN)' \
	              scripts/yosys-prep.sh $(TOP) build/yosys/$(TOP) $(SRCS))"; \
	 yosys -p "read_verilog -sv $(YOSYS_INC) $$yosys_srcs; \
	            hierarchy -check -top $(TOP); \
	            synth -flatten -top $(TOP); \
	            dfflibmap -liberty $(LIBERTY); \
	            abc -liberty $(LIBERTY); \
	            stat -liberty $(LIBERTY)"

# --- area ------------------------------------------------------------------
# Module -> um^2 table for every module in rtl/core.  Uses the same
# CORE_CHILDREN rule as the source list above.
area:
	@test -x scripts/asic-area.sh || { \
	  echo "area: scripts/asic-area.sh is missing or not executable"; exit 1; }
	LIBERTY="$(LIBERTY)" CORE_CHILDREN="$(CORE_CHILDREN)" scripts/asic-area.sh

# --- test (Verilator) ------------------------------------------------------
# cocotb regression, two-state X handling.  run_test.py is a thin wrapper over
# cocotb's Python runner, which is the supported flow in cocotb 2.x.
test:
	SIM=verilator TOP=$(TOP) MODULE=$(MODULE) SRCS="$(SRCS)" INCDIRS="$(INCDIRS)" \
	  $(PYTHON) tb/run_test.py

# --- test-4state (Icarus Verilog) ------------------------------------------
# The same regression under Icarus, so X propagation and the immediate
# assertions behave as they do in a 4-state simulator.  Icarus needs -g2012
# for the immediate assertions the stubs carry.
test-4state:
	SIM=icarus TOP=$(TOP) MODULE=$(MODULE) SRCS="$(SRCS)" INCDIRS="$(INCDIRS)" \
	  $(PYTHON) tb/run_test.py

# --- test-contracts --------------------------------------------------------
# The interface-freeze guard.  tb/test_stubs.py deliberately bypasses this
# Makefile: it is a self-driving stdlib unittest that generates its own Verilog
# wrappers and drives Icarus directly, because no $(TOP)-driven target can span
# all 13 modules at once.  Run it on its own -- never fold it into `make test`.
test-contracts:
	cd tb && $(abspath $(PYTHON)) -m unittest test_stubs -v

# --- sw (Task 9) -----------------------------------------------------------
# Fails loudly.  A target that succeeds while doing nothing would let the
# phase exit criteria look met for free.
sw:
	@if [ -x scripts/build-sw.sh ]; then \
	  scripts/build-sw.sh; \
	else \
	  echo "make sw: not implemented until Task 9."; \
	  echo "            scripts/build-sw.sh does not exist yet."; \
	  exit 1; \
	fi

# --- arch-test (Task 9) ----------------------------------------------------
arch-test:
	@if [ -x scripts/fetch-arch-tests.sh ]; then \
	  scripts/fetch-arch-tests.sh; \
	else \
	  echo "make arch-test: not implemented until Task 9."; \
	  echo "                    scripts/fetch-arch-tests.sh does not exist yet."; \
	  exit 1; \
	fi
"""Phase 1 interface-freeze tests for the 13 core module stubs.

This test is the mechanical guard for the contract in
``docs/contracts/phase1-interfaces.md``.  For every frozen module it checks
three things:

1.  **Frozen port list.**  The ``module`` header declares exactly the ports in
    the contract table -- same names, same directions, same widths.  A renamed
    or missing port is a failure for all five downstream owners, so it is
    checked here rather than discovered during integration.
2.  **Self-containment (the drop-in rule).**  ``rtl/core/<m>.v`` compiles and
    lints with zero warnings *from its own source file alone*, with only
    ``defs.vh`` / ``ctrl_fields.vh`` / ``pipeline_regs.vh`` on the include
    path.  If a stub reached out to another module, elaboration would fail.
3.  **Not-implemented assertion is armed.**  Every output of every stub carries
    an immediate assertion that reports ``not implemented: <module>.<output>``.
    A generated wrapper ties every input to a non-zero, width-specific pattern,
    clocks the design, and the test requires one such message per output.

Run directly (``python3 tb/test_stubs.py``) or via
``python3 -m unittest discover tb``.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RTL_CORE = os.path.join(REPO_ROOT, "rtl", "core")
RTL_COMMON = os.path.join(REPO_ROOT, "rtl", "common")
INCDIR_ARGS = ["+incdir+rtl/core", "+incdir+rtl/common"]


def rel(path):
    return os.path.relpath(path, REPO_ROOT)

# The frozen contract.  (name, direction, width) with direction "in" or "out".
# This table is a machine-readable mirror of docs/contracts/phase1-interfaces.md.
CONTRACT = {
    "pc_gen": {
        "ports": [
            ("clk", "in", 1),
            ("rst_n", "in", 1),
            ("stall", "in", 1),
            ("redirect_valid", "in", 1),
            ("redirect_pc", "in", 32),
            ("pred_taken", "in", 1),
            ("pred_pc", "in", 32),
            ("pc", "out", 32),
        ],
    },
    "if_stage": {
        "ports": [
            ("clk", "in", 1),
            ("rst_n", "in", 1),
            ("stall", "in", 1),
            ("flush", "in", 1),
            ("pc", "in", 32),
            ("if_rsp_rdata", "in", 32),
            ("if_rsp_valid", "in", 1),
            ("if_req_valid", "out", 1),
            ("if_req_addr", "out", 32),
            ("instr", "out", 32),
            ("pred_taken", "out", 1),
            ("pred_pc", "out", 32),
        ],
    },
    "regfile": {
        "ports": [
            ("clk", "in", 1),
            ("rst_n", "in", 1),
            ("rs1_addr", "in", 5),
            ("rs2_addr", "in", 5),
            ("rs1_used", "in", 1),
            ("rs2_used", "in", 1),
            ("wb_we", "in", 1),
            ("wb_waddr", "in", 5),
            ("wb_wdata", "in", 32),
            ("rs1_data", "out", 32),
            ("rs2_data", "out", 32),
        ],
    },
    "decode": {
        "ports": [
            ("instr", "in", 32),
            ("alu_op", "out", 4),
            ("op1_sel", "out", 2),
            ("op2_sel", "out", 3),
            ("imm_sel", "out", 3),
            ("branch_funct3", "out", 3),
            ("uses_rs1", "out", 1),
            ("uses_rs2", "out", 1),
            ("mem_read", "out", 1),
            ("mem_write", "out", 1),
            ("mem_size", "out", 2),
            ("mem_unsigned", "out", 1),
            ("reg_write", "out", 1),
            ("wb_sel", "out", 2),
        ],
    },
    "imm_gen": {
        "ports": [
            ("instr", "in", 32),
            ("imm_sel", "in", 3),
            ("imm", "out", 32),
        ],
    },
    "alu": {
        "ports": [
            ("op_a", "in", 32),
            ("op_b", "in", 32),
            ("alu_op", "in", 4),
            ("result", "out", 32),
            ("zero", "out", 1),
            ("slt", "out", 1),
            ("sltu", "out", 1),
        ],
    },
    "ex_stage": {
        "ports": [
            ("id_pc", "in", 32),
            ("id_imm", "in", 32),
            ("id_rs1_addr", "in", 5),
            ("id_rs2_addr", "in", 5),
            ("id_rd_addr", "in", 5),
            ("id_alu_op", "in", 4),
            ("id_op1_sel", "in", 2),
            ("id_op2_sel", "in", 3),
            ("id_branch_funct3", "in", 3),
            ("id_uses_rs1", "in", 1),
            ("id_uses_rs2", "in", 1),
            ("id_mem_read", "in", 1),
            ("id_mem_write", "in", 1),
            ("id_mem_size", "in", 2),
            ("id_mem_unsigned", "in", 1),
            ("id_reg_write", "in", 1),
            ("id_wb_sel", "in", 2),
            ("ex_rs1_data", "in", 32),
            ("ex_rs2_data", "in", 32),
            ("ex_alu_result", "out", 32),
            ("ex_store_data", "out", 32),
            ("ex_rd_addr", "out", 5),
            ("ex_reg_write", "out", 1),
            ("ex_wb_sel", "out", 2),
            ("ex_mem_read", "out", 1),
            ("ex_mem_write", "out", 1),
            ("ex_mem_size", "out", 2),
            ("ex_mem_unsigned", "out", 1),
            ("ex_redirect_valid", "out", 1),
            ("ex_redirect_pc", "out", 32),
        ],
    },
    "lsu": {
        "ports": [
            ("clk", "in", 1),
            ("rst_n", "in", 1),
            ("stall", "in", 1),
            ("ex_mem_addr", "in", 32),
            ("ex_store_data", "in", 32),
            ("ex_mem_read", "in", 1),
            ("ex_mem_write", "in", 1),
            ("ex_mem_size", "in", 2),
            ("ex_mem_unsigned", "in", 1),
            ("ex_rd_addr", "in", 5),
            ("ex_reg_write", "in", 1),
            ("ex_wb_sel", "in", 2),
            ("mem_rsp_rdata", "in", 32),
            ("mem_rsp_valid", "in", 1),
            ("mem_req_valid", "out", 1),
            ("mem_req_addr", "out", 32),
            ("mem_req_wdata", "out", 32),
            ("mem_req_we", "out", 1),
            ("is_illegal", "out", 1),
            ("mem_rd_addr", "out", 5),
            ("mem_reg_write", "out", 1),
            ("mem_wb_sel", "out", 2),
        ],
    },
    "mem_stage": {
        "ports": [
            ("clk", "in", 1),
            ("rst_n", "in", 1),
            ("stall", "in", 1),
            ("mem_alu_result", "in", 32),
            ("mem_pc", "in", 32),
            ("mem_rsp_rdata", "in", 32),
            ("mem_rd_addr", "in", 5),
            ("mem_reg_write", "in", 1),
            ("mem_wb_sel", "in", 2),
            ("is_illegal", "in", 1),
            ("mem_rd_data", "out", 32),
            ("mem_illegal", "out", 1),
        ],
    },
    "wb_stage": {
        "ports": [
            ("mem_rd_data", "in", 32),
            ("mem_rd_addr", "in", 5),
            ("mem_reg_write", "in", 1),
            ("mem_illegal", "in", 1),
            ("wb_we", "out", 1),
            ("wb_wdata", "out", 32),
            ("wb_waddr", "out", 5),
            ("fwd_rd_addr", "out", 5),
            ("fwd_rd_data", "out", 32),
            ("fwd_reg_write", "out", 1),
        ],
    },
    "hazard_unit": {
        "ports": [
            ("id_uses_rs1", "in", 1),
            ("id_uses_rs2", "in", 1),
            ("id_rs1_addr", "in", 5),
            ("id_rs2_addr", "in", 5),
            ("ex_mem_read", "in", 1),
            ("ex_mem_write", "in", 1),
            ("ex_rd_addr", "in", 5),
            ("mem_rsp_valid", "in", 1),
            ("id_stall", "out", 1),
            ("ex_stall_from_mem", "out", 1),
        ],
    },
    "forwarding": {
        "ports": [
            ("ex_rs1_addr", "in", 5),
            ("ex_rs2_addr", "in", 5),
            ("id_rs1_addr", "in", 5),
            ("id_rs2_addr", "in", 5),
            ("id_uses_rs1", "in", 1),
            ("id_uses_rs2", "in", 1),
            ("mem_rd_addr", "in", 5),
            ("mem_rd_data", "in", 32),
            ("mem_reg_write", "in", 1),
            ("fwd_rd_addr", "in", 5),
            ("fwd_rd_data", "in", 32),
            ("fwd_reg_write", "in", 1),
            ("fwd_rs1_valid", "out", 1),
            ("fwd_rs1_data", "out", 32),
            ("fwd_rs2_valid", "out", 1),
            ("fwd_rs2_data", "out", 32),
        ],
    },
    "core": {
        "ports": [
            ("clk", "in", 1),
            ("rst_n", "in", 1),
            ("if_rsp_rdata", "in", 32),
            ("if_rsp_valid", "in", 1),
            ("mem_rsp_rdata", "in", 32),
            ("mem_rsp_valid", "in", 1),
            ("if_req_valid", "out", 1),
            ("if_req_addr", "out", 32),
            ("mem_req_valid", "out", 1),
            ("mem_req_addr", "out", 32),
            ("mem_req_wdata", "out", 32),
            ("mem_req_we", "out", 1),
        ],
    },
}


def _strip_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def macro_table():
    """Width macros from the shared headers, so port widths are checked as
    numbers rather than as unexpanded text."""
    table = {}
    for header in ("defs.vh", "ctrl_fields.vh", "pipeline_regs.vh"):
        path = os.path.join(RTL_COMMON if header == "defs.vh" else RTL_CORE, header)
        if not os.path.isfile(path):
            continue
        with open(path) as handle:
            body = _strip_comments(handle.read())
        for line in body.splitlines():
            match = re.match(r"\s*`define\s+(\w+)\s+(\S+)", line)
            if match:
                table[match.group(1)] = match.group(2)
    return table


def expand_macros(text, table):
    for _ in range(8):
        replaced = re.sub(r"`(\w+)", lambda m: table.get(m.group(1), m.group(0)), text)
        if replaced == text:
            break
        text = replaced
    return text


_SAFE_EXPR = re.compile(r"^[0-9+\-]+$")


def _eval_width(expr):
    """Evaluate a fully macro-expanded width expression such as ``32-1``.

    Only digits, ``+`` and ``-`` are accepted, so this is plain arithmetic on
    the header's own literals with no expression evaluation.
    """
    text = expr.strip()
    if not _SAFE_EXPR.match(text):
        raise AssertionError("unresolved width expression: %r" % expr)
    total = 0
    sign = 1
    for token in re.findall(r"[+\-]|[0-9]+", text):
        if token == "+":
            sign = 1
        elif token == "-":
            sign = -1
        else:
            total += sign * int(token)
    return total


def _split_top_level(text):
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def parse_ports(source, table=None):
    """Return (ports, self_contained) for the first module in ``source``.

    ``ports`` is [(name, direction, width)].  ``self_contained`` is True when
    no unresolved `` `include `` or width macro is left in the module header,
    i.e. the port list is fully described by the shared headers.
    """
    text = _strip_comments(source)
    if table is not None:
        text = expand_macros(text, table)
    match = re.search(r"\bmodule\s+(\w+)\s*\(", text)
    if not match:
        return None
    start = match.end()
    depth = 1
    idx = start
    while depth:
        if text[idx] in "([":
            depth += 1
        elif text[idx] in ")]":
            depth -= 1
            if depth == 0:
                break
        idx += 1
    body = text[start:idx]
    self_contained = "`" not in body
    ports = []
    for entry in _split_top_level(body):
        tokens = entry.split()
        if "input" not in tokens and "output" not in tokens:
            raise AssertionError("unrecognised port entry: %r" % entry)
        direction = "in" if "input" in tokens else "out"
        if "[" in entry:
            hi, lo = re.search(r"\[\s*([^:\]]+):\s*([^:\]]+)\s*\]", entry).groups()
            width = _eval_width(hi) - _eval_width(lo) + 1
        else:
            width = 1
        name = tokens[-1]
        ports.append((name, direction, width))
    return ports, self_contained


def drive_pattern(width):
    """Non-zero, width-specific pattern so a mis-sized port is visible."""
    if width == 1:
        return "1'b1"
    return "%d'h%X" % (width, (1 << (width - 1)) | 1)


def build_wrapper(module, spec, path):
    lines = ["`timescale 1ns/1ps", "module tb_stub_wrapper;", "  reg clk = 1'b0;"]
    for name, direction, width in spec["ports"]:
        if direction == "in":
            if name == "clk":
                continue
            lines.append("  wire [%d:0] %s = %s;" % (width - 1, name, drive_pattern(width)))
    for name, direction, width in spec["ports"]:
        if direction == "out":
            lines.append(
                "  wire [%d:0] %s;" % (width - 1, name) if width > 1 else "  wire %s;" % name
            )
    conns = []
    for name, _, _ in spec["ports"]:
        conns.append(".%s(%s)" % (name, name))
    lines.append("  %s dut (" % module)
    lines.append("    " + ",\n    ".join(conns))
    lines.append("  );")
    lines.append("  always #5 clk = ~clk;")
    lines.append("  initial #40 $finish;")
    lines.append("endmodule")
    with open(path, "w") as handle:
        handle.write("\n".join(lines) + "\n")


class TestStubContracts(unittest.TestCase):
    maxDiff = None

    def test_all_thirteen_modules_are_declared(self):
        self.assertEqual(len(CONTRACT), 13)
        for module in sorted(CONTRACT):
            with self.subTest(module=module):
                self.assertTrue(
                    os.path.isfile(os.path.join(RTL_CORE, module + ".v")),
                    "%s.v is missing" % module,
                )

    def test_frozen_port_lists(self):
        for module, spec in sorted(CONTRACT.items()):
            with self.subTest(module=module):
                path = os.path.join(RTL_CORE, module + ".v")
                with open(path) as handle:
                    actual, self_contained = parse_ports(handle.read(), macro_table())
                self.assertTrue(
                    self_contained,
                    "%s.v has an unresolved macro in its port list" % module,
                )
                self.assertEqual(
                    actual,
                    spec["ports"],
                    "%s.v port list differs from the frozen contract" % module,
                )

    def test_stubs_lint_standalone_with_zero_warnings(self):
        verilator = shutil.which("verilator")
        if verilator is None:
            self.skipTest("verilator not installed")
        for module in sorted(CONTRACT):
            with self.subTest(module=module):
                cmd = [
                    verilator, "--lint-only", "-Wall", "--top-module", module,
                ] + INCDIR_ARGS + [rel(os.path.join(RTL_CORE, module + ".v"))]
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, cwd=REPO_ROOT
                )
                self.assertEqual(
                    proc.returncode,
                    0,
                    "verilator -Wall rejected %s.v:\n%s%s"
                    % (module, proc.stdout, proc.stderr),
                )

    def test_not_implemented_assertion_fires_for_every_output(self):
        iverilog = shutil.which("iverilog")
        vvp = shutil.which("vvp")
        if iverilog is None or vvp is None:
            self.skipTest("iverilog/vvp not installed")
        for module, spec in sorted(CONTRACT.items()):
            with self.subTest(module=module):
                with tempfile.TemporaryDirectory() as tmp:
                    wrapper = os.path.join(tmp, "tb_stub_wrapper.v")
                    binary = os.path.join(tmp, "sim.out")
                    build_wrapper(module, spec, wrapper)
                    cmd = [
                        iverilog, "-g2012", "-Wall", "-o", binary,
                        "-I", "rtl/core", "-I", "rtl/common",
                        rel(os.path.join(RTL_CORE, module + ".v")), wrapper,
                    ]
                    build = subprocess.run(
                        cmd, capture_output=True, text=True, cwd=REPO_ROOT
                    )
                    self.assertEqual(
                        build.returncode,
                        0,
                        "%s.v does not elaborate against the frozen port list:\n%s%s"
                        % (module, build.stdout, build.stderr),
                    )
                    self.assertEqual(
                        build.stderr.strip(), "",
                        "%s.v elaborated with warnings" % module,
                    )
                    run = subprocess.run([vvp, binary], capture_output=True, text=True)
                    log = run.stdout + run.stderr
                    for name, direction, _ in spec["ports"]:
                        if direction != "out":
                            continue
                        expected = "not implemented: %s.%s" % (module, name)
                        self.assertIn(
                            expected,
                            log,
                            "%s.v is missing the not-implemented assertion for %s" % (module, name),
                        )

    def test_contract_doc_matches_the_frozen_port_lists(self):
        """The contract doc is the deliverable five owners code against, so it
        must not be allowed to drift away from the code."""
        path = os.path.join(REPO_ROOT, "docs", "contracts", "phase1-interfaces.md")
        with open(path) as handle:
            doc = handle.read()
        row = re.compile(r"^\|\s*`(\w+)`\s*\|\s*(in|out)\s*\|\s*(\d+)\s*\|")
        documented = {}
        for section in re.split(r"\n## ", doc)[1:]:
            heading = re.match(r"\d+\. `(\w+)`", section)
            if not heading:
                # not a per-module section (e.g. "Signal provenance"); its
                # tables must not be attributed to the module above it
                continue
            module = heading.group(1)
            documented[module] = [
                (m.group(1), m.group(2), int(m.group(3)))
                for m in (row.match(line) for line in section.split("\n"))
                if m
            ]
        for module, spec in sorted(CONTRACT.items()):
            with self.subTest(module=module):
                self.assertIn(module, documented, "no section for %s" % module)
                self.assertEqual(
                    documented[module],
                    spec["ports"],
                    "docs/contracts/phase1-interfaces.md disagrees with the frozen port list for %s"
                    % module,
                )
        self.assertEqual(sorted(documented), sorted(CONTRACT))

    def test_pipeline_bundle_layouts_tile_exactly(self):
        """Every stage bundle must be a gapless, overlap-free partition whose
        computed width equals the declared `p_<BUNDLE>_W`, so `core` can pack
        a field by offset without arithmetic of its own."""
        table = macro_table()
        path = os.path.join(RTL_CORE, "pipeline_regs.vh")
        with open(path) as handle:
            text = _strip_comments(handle.read())
        for bundle in ("IF_ID", "ID_EX", "EX_MEM", "MEM_WB"):
            with self.subTest(bundle=bundle):
                fields = []
                for name, lsb in re.findall(
                    r"`define p_%s__(\w+)_LSB\s+(\d+)" % bundle, text
                ):
                    width = int(table["p_%s__%s_W" % (bundle, name)])
                    fields.append((int(lsb), width, name))
                self.assertTrue(fields, "no fields found for %s" % bundle)
                fields.sort()
                expected_lsb = 0
                for lsb, width, name in fields:
                    self.assertEqual(
                        lsb,
                        expected_lsb,
                        "p_%s__%s_LSB is %d but the previous field ends at %d"
                        % (bundle, name, lsb, expected_lsb),
                    )
                    expected_lsb = lsb + width
                self.assertEqual(
                    expected_lsb,
                    int(table["p_%s_W" % bundle]),
                    "p_%s_W disagrees with the sum of its fields" % bundle,
                )

    def test_every_input_is_driven_to_a_nonzero_pattern(self):
        """Guards the generator: if an input were left undriven, the
        not-implemented assertion check would pass without ever exercising the
        input side of the module."""
        for module, spec in sorted(CONTRACT.items()):
            with self.subTest(module=module):
                with tempfile.TemporaryDirectory() as tmp:
                    wrapper = os.path.join(tmp, "tb_stub_wrapper.v")
                    build_wrapper(module, spec, wrapper)
                    with open(wrapper) as handle:
                        text = handle.read()
                    for name, direction, width in spec["ports"]:
                        if direction != "in" or name == "clk":
                            continue
                        self.assertIn(
                            "wire [%d:0] %s = %s;" % (width - 1, name, drive_pattern(width)),
                            text,
                            "wrapper does not drive %s.%s" % (module, name),
                        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

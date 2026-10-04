#!/usr/bin/env python3
"""Run one cocotb regression against one HDL module.

Invoked by ``make test`` (Verilator) and ``make test-4state`` (Icarus Verilog).
Everything it needs arrives in the environment from the Makefile:

===========================  ================================================
``SIM``                      ``verilator`` or ``icarus``
``TOP``                      the module name; also the cocotb toplevel
``MODULE``                   the cocotb test module in ``tb/``
``SRCS``                     the per-module source list, space separated
``INCDIRS``                  ``+incdir+...`` tokens from the Makefile
===========================  ================================================

Why a wrapper script rather than cocotb's ``Makefile.sim``: cocotb 2.x
deprecates the Makefile flow in favour of the Python runner, and the Python
runner is the only flow in which ``test`` and ``test-4state`` differ by a
single variable.  ``tb/conftest.py`` is put on ``sys.path`` here so that a test
module can ``from conftest import ...``; cocotb propagates this process's
``sys.path`` to the simulator as ``PYTHONPATH``.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tb"))

from cocotb_tools.check_results import get_results
from cocotb_tools.runner import get_runner  # noqa: E402  (after sys.path fix)

# Simulator-specific build flags.  Source stays a strict Verilog-2001 subset,
# but Icarus needs -g2012 to accept the immediate assertions the stubs carry,
# and Verilator wants X initialisation to be reproducible rather than zero.
BUILD_ARGS = {
    "verilator": ["--x-assign", "unique", "--x-initial", "unique", "--assert"],
    "icarus": ["-g2012"],
}


def main():
    try:
        sim = os.environ["SIM"]
        top = os.environ["TOP"]
        module = os.environ["MODULE"]
    except KeyError as exc:
        sys.exit("tb/run_test.py: %s is not set; run this through `make test` "
                 "or `make test-4state`" % exc)

    sources = [Path(name) for name in os.environ.get("SRCS", "").split()]
    if not sources:
        sys.exit("tb/run_test.py: SRCS is empty -- TOP=%r matched no source "
                 "file, so there is nothing to simulate" % top)
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        sys.exit("tb/run_test.py: missing source file(s): %s"
                 % ", ".join(missing))

    if sim not in BUILD_ARGS:
        sys.exit("tb/run_test.py: unknown SIM=%r; expected one of %s"
                 % (sim, ", ".join(sorted(BUILD_ARGS))))

    includes = [
        token[len("+incdir+"):]
        for token in os.environ.get("INCDIRS", "").split()
        if token.startswith("+incdir+")
    ]
    build_dir = REPO_ROOT / "sim_build" / ("%s_%s" % (sim, top))

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        includes=includes,
        hdl_toplevel=top,
        build_args=BUILD_ARGS[sim],
        build_dir=build_dir,
        # Always rebuild: a Makefile target that reported a stale binary as a
        # pass would be a green gate that proved nothing.
        always=True,
    )
    results_file = runner.test(hdl_toplevel=top, test_module=module)

    # cocotb's runner only fails the process when it is running under pytest.
    # Driven from a Makefile it is not, so a FAILing test would otherwise exit
    # 0 and `make test` would go green having proved nothing.  Read the results
    # file and turn a failure into a non-zero exit ourselves.
    try:
        num_tests, num_failed = get_results(results_file)
    except RuntimeError as exc:
        print("tb/run_test.py: %s" % exc.args[0], file=sys.stderr)
        sys.exit(1)
    if num_failed:
        print("tb/run_test.py: %d of %d cocotb tests FAILED (%s %s %s)"
              % (num_failed, num_tests, sim, top, module), file=sys.stderr)
        sys.exit(1)
    print("tb/run_test.py: %d/%d cocotb tests passed (%s %s %s)"
          % (num_tests, num_tests, sim, top, module))


if __name__ == "__main__":
    main()
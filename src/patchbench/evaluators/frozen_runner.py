"""Standalone stdlib runner injected by PatchBench, never supplied by an Agent.

Run with -I -S -B. This protects evaluator selection, not execution of arbitrary
hostile production Python in the same interpreter.
"""

import json
from pathlib import Path
import sys
import types
import unittest


def main() -> int:
    control = Path(__file__).resolve().parent
    root = control.parent
    filenames = json.loads((control / "tests.json").read_text(encoding="utf-8"))
    # Standard-library runner imports above precede deliberate project imports.
    sys.path.append(str(root))
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for index, filename in enumerate(filenames):
        path = root / filename
        name = f"_patchbench_frozen_{index}"
        module = types.ModuleType(name)
        module.__file__ = str(path)
        sys.modules[name] = module
        # Read the restored source directly; never reuse Agent-created test pyc.
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
        suite.addTests(loader.loadTestsFromModule(module))
    if suite.countTestCases() == 0:
        print("Frozen unittest suite contains zero tests.", file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

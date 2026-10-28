import py_compile
from pathlib import Path

import pytest

FILES = sorted(p for p in Path(__file__).parent.glob("*.py"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_module_compiles(path):
    """A syntax error in admin.py/app.py is invisible to the logic tests but breaks the portal tile."""
    py_compile.compile(str(path), doraise=True)

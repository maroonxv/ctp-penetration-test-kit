"""
Path setup for modified lib packages (vnpy, vnpy_ctp, vnpy_ctptest).
Import this module before any vnpy imports to ensure the modified
versions in lib/ are used instead of pip-installed ones.
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
_lib = _root / "lib"

for subdir in ("vnpy", "vnpy_ctp", "vnpy_ctptest"):
    p = str(_lib / subdir)
    if p not in sys.path:
        sys.path.insert(0, p)

"""
Root conftest.py — ensures lib/ modified packages (vnpy, vnpy_ctp, vnpy_ctptest)
are found before pip-installed versions.
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent
_lib = _root / "lib"

# Prepend lib paths so modified vnpy/vnpy_ctp/vnpy_ctptest take priority
for subdir in ("vnpy", "vnpy_ctp", "vnpy_ctptest"):
    p = str(_lib / subdir)
    if p not in sys.path:
        sys.path.insert(0, p)

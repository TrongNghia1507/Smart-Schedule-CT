"""Lớp validation khả năng hoàn thành: nối schedule_input với conflict_resolver."""
import sys
from importlib.util import find_spec
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2]      # = <repo>/src
if find_spec("conflict_resolver") is None and (_SRC / "conflict_resolver").is_dir():
    sys.path.insert(0, str(_SRC))
from .policy import KindRule, ResolutionPolicy
from .service import (
    Finding,
    FeasibilityReport,
    HttpResolverClient,
    LocalResolverClient,
    check_feasibility,
    check_feasibility_sync,
)
from .edits import InputEdit, apply_edits, option_to_edits

__all__ = [
    "KindRule", "ResolutionPolicy", "Finding", "FeasibilityReport",
    "HttpResolverClient", "LocalResolverClient", "check_feasibility",
    "check_feasibility_sync", "InputEdit", "apply_edits", "option_to_edits",
]

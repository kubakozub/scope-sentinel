"""scope-sentinel: confirm bug-bounty scope before you test.

Public API::

    from scope_sentinel import Scope
    scope = Scope.from_file("program.yaml")
    result = scope.check("https://api.example.com/v1")
    print(result.verdict)          # IN_SCOPE / OUT_OF_SCOPE / NOT_LISTED
"""
from __future__ import annotations

__version__ = "1.0.0"

from .errors import ScopeError
from .rules import Rule, parse_target
from .scope import (IN_SCOPE, NOT_LISTED, OUT_OF_SCOPE, Result, Scope,
                    verdict_exit)

__all__ = [
    "Scope", "Result", "Rule", "ScopeError", "parse_target",
    "IN_SCOPE", "OUT_OF_SCOPE", "NOT_LISTED", "verdict_exit", "__version__",
]

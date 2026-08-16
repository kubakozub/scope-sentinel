"""Loading a program scope and checking targets against it."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional

from . import yamllite
from .errors import ScopeError
from .rules import Rule, TargetInfo, parse_target

# Verdicts
IN_SCOPE = "IN_SCOPE"
OUT_OF_SCOPE = "OUT_OF_SCOPE"
NOT_LISTED = "NOT_LISTED"

# Exit codes (documented in the README; usable to gate testing in CI).
EXIT_IN_SCOPE = 0        # in scope / all clear
EXIT_ERROR = 1           # runtime error (bad file, unparseable target, ...)
EXIT_OUT_OF_SCOPE = 2    # explicitly out of scope (deny)
EXIT_NOT_LISTED = 3      # not mentioned by the scope at all
EXIT_USAGE = 64          # command-line misuse (EX_USAGE)


def verdict_exit(verdict):
    return {
        IN_SCOPE: EXIT_IN_SCOPE,
        OUT_OF_SCOPE: EXIT_OUT_OF_SCOPE,
        NOT_LISTED: EXIT_NOT_LISTED,
    }[verdict]


@dataclass
class Result:
    """The outcome of checking a single target."""
    target: str
    info: TargetInfo
    verdict: str
    matched: Optional[Rule]
    in_matches: List[Rule]
    out_matches: List[Rule]
    reason: str

    def to_dict(self):
        return {
            "target": self.target,
            "host": self.info.host,
            "ip": self.info.ip.compressed if self.info.ip is not None else None,
            "path": self.info.path or None,
            "verdict": self.verdict,
            "matched_rule": self.matched.to_dict() if self.matched else None,
            "reason": self.reason,
            "in_scope_matches": [r.to_dict() for r in self.in_matches],
            "out_of_scope_matches": [r.to_dict() for r in self.out_matches],
            "exit_code": verdict_exit(self.verdict),
        }


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, (str, dict)):     # tolerate a single bare entry
        return [v]
    raise ScopeError(
        f"expected a list of scope entries, got {type(v).__name__}")


class Scope:
    """A program's in-/out-of-scope rules plus the checking logic."""

    def __init__(self, program=None, in_rules=None, out_rules=None, source=None):
        self.program = program
        self.in_rules = in_rules or []
        self.out_rules = out_rules or []
        self.source = source

    # -- construction --------------------------------------------------- #
    @classmethod
    def from_mapping(cls, data, source=None):
        if not isinstance(data, dict):
            raise ScopeError(
                "scope file must be a mapping with 'in_scope' / 'out_of_scope' keys")
        program = data.get('program') or data.get('name') or data.get('title')
        in_entries = data.get('in_scope', data.get('in', data.get('scope')))
        out_entries = data.get('out_of_scope', data.get('out', data.get('excluded')))
        in_rules = [Rule.from_entry(e, 'in_scope') for e in _as_list(in_entries)]
        out_rules = [Rule.from_entry(e, 'out_of_scope') for e in _as_list(out_entries)]
        if not in_rules and not out_rules:
            raise ScopeError("scope defines no in_scope or out_of_scope entries")
        return cls(program, in_rules, out_rules, source)

    @classmethod
    def from_text(cls, text, fmt=None, source=None):
        return cls.from_mapping(load_data(text, fmt), source)

    @classmethod
    def from_file(cls, path):
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                text = fh.read()
        except OSError as exc:
            raise ScopeError(f"cannot read scope file {path!r}: {exc}") from exc
        lower = path.lower()
        if lower.endswith('.json'):
            fmt = 'json'
        elif lower.endswith(('.yaml', '.yml')):
            fmt = 'yaml'
        else:
            fmt = None
        return cls.from_text(text, fmt=fmt, source=path)

    # -- checking ------------------------------------------------------- #
    def check(self, target):
        info = parse_target(target)
        in_matches = [r for r in self.in_rules if r.matches(info)]
        out_matches = [r for r in self.out_rules if r.matches(info)]

        if out_matches:
            best = max(out_matches, key=lambda r: r.specificity())
            reason = (f"{info.subject} matches out-of-scope {best.kind} rule "
                      f"'{best.pattern}'; out-of-scope always wins over in-scope")
            return Result(target, info, OUT_OF_SCOPE, best,
                          in_matches, out_matches, reason)

        if in_matches:
            best = max(in_matches, key=lambda r: r.specificity())
            reason = f"{info.subject} matches in-scope {best.kind} rule '{best.pattern}'"
            return Result(target, info, IN_SCOPE, best,
                          in_matches, out_matches, reason)

        reason = f"{info.subject} did not match any in-scope or out-of-scope rule"
        return Result(target, info, NOT_LISTED, None, in_matches, out_matches, reason)


def load_data(text, fmt=None):
    """Load a scope mapping from text as JSON or the YAML subset."""
    if fmt is None:
        stripped = text.lstrip()
        fmt = 'json' if stripped[:1] in ('{', '[') else 'yaml'
    if fmt == 'json':
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScopeError(f"invalid JSON scope: {exc}") from exc
    return yamllite.load(text)

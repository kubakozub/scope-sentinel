"""Exceptions for scope-sentinel."""


class ScopeError(Exception):
    """User-facing error.

    Raised for anything the operator can fix: an unreadable or malformed scope
    file, an unparseable target, an empty pattern, and so on. The CLI turns this
    into a friendly stderr message plus exit code 1 rather than a traceback.
    """

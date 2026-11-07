"""A tiny, dependency-free loader for the *subset* of YAML that scope-sentinel
scope files use. It exists so the tool has zero third-party dependencies.

Supported
---------
* Mappings:                 ``key: value``
* Nested mappings via indentation
* Block sequences:          ``- item``
* Sequences of mappings::

      - host: "*.example.com"
        type: web

* Scalars: bare or quoted (single/double); ``true``/``false``/``null`` become
  ``True``/``False``/``None``; ``[]`` and ``{}`` become an empty list/dict.
* ``#`` comments (a ``#`` at the start of a line or after whitespace)
* Blank lines

Not supported (documented limitation)
-------------------------------------
Flow collections with contents (``[a, b]``, ``{k: v}``), anchors/aliases,
multi-line/blocked scalars, and multiple documents. Indentation must use
spaces, not tabs. For anything richer, write the scope file as JSON instead:
JSON is parsed natively by the standard library.
"""
from __future__ import annotations

from .errors import ScopeError


class _Line:
    __slots__ = ("indent", "text", "lineno")

    def __init__(self, indent, text, lineno):
        self.indent = indent
        self.text = text
        self.lineno = lineno


def _strip_comment(s):
    """Remove a trailing ``#`` comment that is not inside a quoted string.

    A ``#`` only starts a comment at the beginning of the line or when preceded
    by whitespace, so URLs such as ``http://x`` (no ``#``) and values like
    ``a#b`` are left untouched. The result is right-stripped.
    """
    out = []
    quote = None
    for i, c in enumerate(s):
        if quote:
            out.append(c)
            if c == quote:
                quote = None
        elif c in ('"', "'"):
            quote = c
            out.append(c)
        elif c == '#' and (i == 0 or s[i - 1] in ' \t'):
            break
        else:
            out.append(c)
    return ''.join(out).rstrip()


def _tokenize(text):
    lines = []
    for n, raw in enumerate(text.splitlines(), start=1):
        content = _strip_comment(raw)
        if content.strip() == '':
            continue
        stripped = content.lstrip(' ')
        indent = len(content) - len(stripped)
        if '\t' in content[:indent]:
            raise ScopeError(f"line {n}: tab used for indentation (use spaces)")
        lines.append(_Line(indent, stripped, n))
    return lines


def _split_key(s):
    """If ``s`` looks like ``key: value`` (or ``key:``), return ``(key, value)``.

    The separating colon must be followed by a space or end-of-string and lie
    outside any quotes, so ``https://x`` and ``"a:b"`` are not mistaken for
    mappings. Returns ``None`` when ``s`` is not a mapping entry.
    """
    quote = None
    for i, c in enumerate(s):
        if quote:
            if c == quote:
                quote = None
        elif c in ('"', "'"):
            quote = c
        elif c == ':' and (i + 1 == len(s) or s[i + 1] in ' \t'):
            return s[:i].strip(), s[i + 1:].strip()
    return None


def _parse_scalar(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    if s == '[]':
        return []
    if s == '{}':
        return {}
    low = s.lower()
    if low == 'true':
        return True
    if low == 'false':
        return False
    if low in ('null', '~', ''):
        return None
    return s


class _Parser:
    """Recursive, indentation-driven parser over the tokenized lines."""

    def __init__(self, lines):
        self.lines = lines
        self.i = 0

    def peek(self):
        return self.lines[self.i] if self.i < len(self.lines) else None

    @staticmethod
    def _is_seq(line):
        return line.text == '-' or line.text.startswith('- ')

    def parse_document(self):
        if not self.lines:
            return None
        node = self.parse_node(self.lines[0].indent)
        extra = self.peek()
        if extra is not None:
            raise ScopeError(
                f"line {extra.lineno}: unexpected indentation or trailing content")
        return node

    def parse_node(self, indent):
        line = self.peek()
        if line is None:
            return None
        if self._is_seq(line):
            return self.parse_seq(indent)
        return self.parse_map(indent)

    def parse_seq(self, indent):
        items = []
        while True:
            line = self.peek()
            if line is None or line.indent != indent or not self._is_seq(line):
                break
            if line.text == '-':
                # value lives on the following, more-indented line(s)
                self.i += 1
                child = self.peek()
                if child is not None and child.indent > indent:
                    items.append(self.parse_node(child.indent))
                else:
                    items.append(None)
                continue
            after = line.text[1:]                 # drop the leading '-'
            stripped = after.lstrip(' ')
            col = line.indent + 1 + (len(after) - len(stripped))
            if _split_key(stripped) is not None:
                # The element is a block mapping that starts on this line.
                # Rewrite the current line so it sits at column `col` and hand
                # off to the mapping parser, which will also consume any aligned
                # continuation keys (e.g. a following `type:` line).
                self.lines[self.i] = _Line(col, stripped, line.lineno)
                items.append(self.parse_map(col))
            else:
                self.i += 1
                items.append(_parse_scalar(stripped))
        return items

    def parse_map(self, indent):
        mapping = {}
        while True:
            line = self.peek()
            if line is None or line.indent != indent or self._is_seq(line):
                break
            kv = _split_key(line.text)
            if kv is None:
                raise ScopeError(
                    f"line {line.lineno}: expected 'key: value', got {line.text!r}")
            key, val = kv
            key = _parse_scalar(key)
            if val == '':
                # nested block: a deeper mapping/sequence, or a same-indent
                # sequence (a common YAML style), otherwise an explicit null.
                self.i += 1
                child = self.peek()
                if child is not None and (
                        child.indent > indent
                        or (child.indent == indent and self._is_seq(child))):
                    mapping[key] = self.parse_node(child.indent)
                else:
                    mapping[key] = None
            else:
                self.i += 1
                mapping[key] = _parse_scalar(val)
        return mapping


def load(text):
    """Parse ``text`` (the documented YAML subset) and return Python data."""
    return _Parser(_tokenize(text)).parse_document()

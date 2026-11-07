"""Target parsing and scope-rule classification / matching.

A *rule* is one entry from a program's ``in_scope`` / ``out_of_scope`` list. A
*target* is the thing a researcher is about to test (a URL, a bare host, or an
IP). This module turns both into normalized forms and decides whether a rule
matches a target.

Matching semantics (also documented in the README):

* **exact host** ``api.example.com``: matches only that host.
* **wildcard domain** ``*.example.com``: matches the apex ``example.com`` *and*
  any sub-domain at any depth (``a.example.com``, ``a.b.example.com``). It never
  matches an unrelated host such as ``notexample.com``.
* **IP / CIDR** ``203.0.113.7`` or ``203.0.113.0/24`` or ``2001:db8::/48``:
  matches an IP target inside the range. Address families never cross (an IPv4
  target never matches an IPv6 range). Hostnames are **not** resolved to IPs.
* **URL prefix** ``https://example.com/api/*``: the target's host must match
  the host part, and its path must match the path part. ``*`` matches any run of
  characters; a path without ``*`` matches at a path boundary (``/api`` matches
  ``/api`` and ``/api/v1`` but not ``/apidocs``). The scheme is ignored, so a
  rule with or without ``http(s)://`` behaves the same.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

from .errors import ScopeError

KIND_HOST = "exact host"
KIND_WILDCARD = "wildcard domain"
KIND_IP = "IP/CIDR"
KIND_URL = "URL prefix"


# --------------------------------------------------------------------------- #
# Target parsing
# --------------------------------------------------------------------------- #
@dataclass
class TargetInfo:
    """A normalized target: what the user is about to test."""
    raw: str
    host: Optional[str]          # lower-cased hostname or IP literal (no port)
    ip: Optional[object]         # ipaddress.IPv4Address / IPv6Address, or None
    path: str                    # '' or a leading-'/' path (may include ?query)
    had_scheme: bool
    port: Optional[int]

    @property
    def subject(self) -> str:
        if self.ip is not None:
            return f"IP {self.ip.compressed}"
        if self.host:
            return f"host '{self.host}'"
        return f"target '{self.raw}'"


def _first_index(s, chars):
    hits = [s.find(c) for c in chars]
    hits = [i for i in hits if i != -1]
    return min(hits) if hits else None


def _split_hostport(hp):
    """Split ``host[:port]`` into ``(host, port|None)``, tolerating ``[ipv6]``."""
    hp = hp.strip()
    if hp.startswith('['):
        end = hp.find(']')
        if end == -1:
            return hp, None
        host = hp[1:end]
        tail = hp[end + 1:]
        if tail.startswith(':') and tail[1:].isdigit():
            return host, int(tail[1:])
        return host, None
    if hp.count(':') == 1:                 # exactly one colon => host:port
        host, port = hp.split(':', 1)
        if port.isdigit():
            return host, int(port)
    return hp, None                        # zero colons, or many (IPv6 literal)


def _try_network(text):
    """Return an ``ip_network`` for a lone IP or CIDR, else ``None``.

    A single address parses as a host route (``/32`` or ``/128``), so exact-IP
    rules and CIDR rules share one code path.
    """
    try:
        return ipaddress.ip_network(text, strict=False)
    except ValueError:
        return None


def parse_target(raw):
    """Normalize a target string into a :class:`TargetInfo`."""
    if raw is None:
        raise ScopeError("empty target")
    raw = raw.strip()
    if not raw:
        raise ScopeError("empty target")

    if '://' in raw:
        parts = urlsplit(raw)
        host = parts.hostname          # already lower-cased, brackets removed
        try:
            port = parts.port
        except ValueError:
            port = None
        path = parts.path or ''
        if parts.query:
            path = path + '?' + parts.query
        had_scheme = True
    else:
        had_scheme = False
        idx = _first_index(raw, '/?#')
        if idx is None:
            hostport, path = raw, ''
        else:
            hostport, path = raw[:idx], raw[idx:]
        if path.startswith('#'):
            path = ''
        host, port = _split_hostport(hostport)

    if host:
        host = host.strip()
        if host.startswith('[') and host.endswith(']'):
            host = host[1:-1]
        host = host.lower().rstrip('.')      # normalise FQDN root, e.g. "x.com."
    if '#' in path:
        path = path.split('#', 1)[0]

    ip = None
    if host:
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None

    return TargetInfo(raw=raw, host=host, ip=ip, path=path,
                      had_scheme=had_scheme, port=port)


# --------------------------------------------------------------------------- #
# Matching primitives
# --------------------------------------------------------------------------- #
def glob_match(pattern, text):
    """Match ``text`` against ``pattern`` where only ``*`` is special.

    ``*`` matches any run of characters (including empty); every other character
    is literal. Used for URL-path patterns and non-standard host wildcards.
    """
    regex = '^' + '.*'.join(re.escape(part) for part in pattern.split('*')) + '$'
    return re.match(regex, text) is not None


def wildcard_host_match(pattern, host):
    """Match a hostname against a wildcard-domain pattern.

    ``*.example.com`` matches the apex ``example.com`` and any sub-domain at any
    depth. Wildcards in other positions fall back to :func:`glob_match`.
    """
    if host is None:
        return False
    pattern = pattern.lower()
    host = host.lower()
    if pattern.startswith('*.'):
        base = pattern[2:]
        return host == base or host.endswith('.' + base)
    if '*' in pattern:
        return glob_match(pattern, host)
    return host == pattern


# --------------------------------------------------------------------------- #
# Rule
# --------------------------------------------------------------------------- #
@dataclass
class Rule:
    """One classified scope entry.

    Only the fields relevant to ``kind`` are populated; the rest stay ``None``.
    """
    pattern: str                       # original text, as written in the file
    side: str = ''                     # 'in_scope' | 'out_of_scope' (info only)
    asset_type: Optional[str] = None   # optional label from the scope file
    kind: str = KIND_HOST
    _host: Optional[str] = None
    _wild: Optional[str] = None
    _net: Optional[object] = None
    _host_matcher: Optional["Rule"] = None
    _path: Optional[str] = None

    # -- construction --------------------------------------------------- #
    @classmethod
    def classify(cls, pattern, side='', asset_type=None):
        raw = pattern
        p = pattern.strip()
        if not p:
            raise ScopeError("empty scope pattern")

        # 1) A bare IP address or CIDR (no scheme) -> IP rule.
        if '://' not in p:
            net = _try_network(p)
            if net is not None:
                return cls(raw, side, asset_type, KIND_IP, _net=net)

        # 2) Strip an optional scheme, then separate host from path.
        rest = p.split('://', 1)[1] if '://' in p else p
        idx = _first_index(rest, '/')
        if idx is None:
            host_part, path_part = rest, ''
        else:
            host_part, path_part = rest[:idx], rest[idx:]
        host_only, _ = _split_hostport(host_part)
        host_only = host_only.strip('[]').lower().rstrip('.')

        # 3) No path (or just '/') -> a host-level rule.
        if path_part in ('', '/'):
            if '*' in host_only:
                return cls(raw, side, asset_type, KIND_WILDCARD, _wild=host_only)
            net = _try_network(host_only)          # e.g. http://203.0.113.7
            if net is not None:
                return cls(raw, side, asset_type, KIND_IP, _net=net)
            return cls(raw, side, asset_type, KIND_HOST, _host=host_only)

        # 4) A real path -> URL-prefix rule (host matcher + path pattern).
        host_matcher = cls.classify(host_only, side, asset_type)
        return cls(raw, side, asset_type, KIND_URL,
                   _host_matcher=host_matcher, _path=path_part)

    @classmethod
    def from_entry(cls, entry, side=''):
        """Build a rule from a scope-file entry (string or mapping)."""
        if isinstance(entry, str):
            return cls.classify(entry, side, None)
        if isinstance(entry, dict):
            pattern = (entry.get('host') or entry.get('pattern') or entry.get('url')
                       or entry.get('value') or entry.get('cidr') or entry.get('ip')
                       or entry.get('domain') or entry.get('target'))
            if not pattern:
                raise ScopeError(f"scope entry has no host/pattern: {entry!r}")
            asset_type = (entry.get('type') or entry.get('asset_type')
                          or entry.get('category'))
            return cls.classify(str(pattern), side, asset_type)
        raise ScopeError(f"unsupported scope entry: {entry!r}")

    # -- matching ------------------------------------------------------- #
    def matches(self, info):
        if self.kind == KIND_HOST:
            return info.host is not None and info.host == self._host
        if self.kind == KIND_WILDCARD:
            return wildcard_host_match(self._wild, info.host)
        if self.kind == KIND_IP:
            if info.ip is None:
                return False
            if info.ip.version != self._net.version:
                return False
            return info.ip in self._net
        if self.kind == KIND_URL:
            if not self._host_matcher.matches(info):
                return False
            return self._path_matches(info.path)
        return False

    def _path_matches(self, target_path):
        pat = self._path
        if '*' in pat:
            return glob_match(pat, target_path)
        path_only = target_path.split('?', 1)[0]
        if path_only == pat:
            return True
        if pat.endswith('/'):
            return path_only.startswith(pat)
        return path_only.startswith(pat.rstrip('/') + '/')

    # -- presentation --------------------------------------------------- #
    def specificity(self):
        """A sortable score; higher wins when several rules match a target.

        Used only to choose which matching rule to *display*, it never changes
        the verdict (out-of-scope always wins regardless of specificity).
        """
        if self.kind == KIND_HOST:
            return 400 + len(self._host or '')
        if self.kind == KIND_URL:
            return 300 + len(self._path or '')
        if self.kind == KIND_IP:
            return 200 + (self._net.prefixlen if self._net is not None else 0)
        base = self._wild or ''
        if base.startswith('*.'):
            base = base[2:]
        return 100 + len(base)

    def to_dict(self):
        d = {"pattern": self.pattern, "kind": self.kind}
        if self.side:
            d["side"] = self.side
        if self.asset_type:
            d["type"] = self.asset_type
        return d

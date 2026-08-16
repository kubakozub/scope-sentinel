# scope-sentinel

**Confirm a target is *in scope* for a bug-bounty program before you touch it.**

`scope-sentinel` is a small, offline command-line tool that answers one question
reliably: *"Am I allowed to test this?"* You give it a program's scope (a simple
YAML or JSON file) and a target (URL, host, or IP), and it returns a clear
verdict — `IN_SCOPE`, `OUT_OF_SCOPE`, or `NOT_LISTED` — with the exact rule that
decided it and a script-friendly exit code.

> Requirements: **Python 3.9+**, standard library only. No third-party
> dependencies, no network calls. It is pure, local scope logic.

## Why this matters

Testing an asset that a program never authorized is the fastest way to turn good
research into an incident report. Scopes are fiddly: wildcards have surprising
edge cases, a single host is often *carved out* of an otherwise in-scope domain,
and "out of scope always wins" is easy to get wrong by hand. `scope-sentinel`
makes that decision explicit and repeatable so you can put it in front of every
scan, fuzzing run, or manual session — and in CI so an out-of-scope target
*fails the build* instead of getting probed.

This is a responsible-disclosure discipline tool. It never touches the target.

## Install

```bash
# Zero-install: clone and run as a module (no dependencies to install)
git clone <your-fork-url> scope-sentinel && cd scope-sentinel
python -m scope_sentinel --help

# Or install the `scope-sentinel` command onto your PATH
pip install -e .
scope-sentinel --help
```

## Quick start

Describe the program scope once (`program.yaml`):

```yaml
program: Example Corp Public Program
in_scope:
  - host: "*.example.com"          # apex + any sub-domain
    type: web
  - "api.example.com"
  - "https://example.com/api/*"    # only the /api area of the apex site
  - "203.0.113.0/24"
out_of_scope:
  - "blog.example.com"             # a specific host carved out
  - "*.internal.example.com"       # a whole sub-tree excluded
  - "https://example.com/api/legacy/*"
```

Check a single target:

```console
$ scope-sentinel check -s program.yaml https://api.example.com/v2/users
Target:  https://api.example.com/v2/users
Host:    api.example.com
Verdict: IN_SCOPE
Rule:    api.example.com  (exact host)
Reason:  host 'api.example.com' matches in-scope exact host rule 'api.example.com'
```

An excluded path loses, even though the host is otherwise in scope:

```console
$ scope-sentinel check -s program.yaml https://example.com/api/legacy/report
Target:  https://example.com/api/legacy/report
Host:    example.com
Verdict: OUT_OF_SCOPE
Rule:    https://example.com/api/legacy/*  (URL prefix)
Reason:  host 'example.com' matches out-of-scope URL prefix rule 'https://example.com/api/legacy/*'; out-of-scope always wins over in-scope
$ echo $?
2
```

## Scope file format

A scope file is a mapping with `in_scope` and `out_of_scope` lists. Both YAML (a
documented subset — see *Limitations*) and JSON are supported natively; the JSON
form is byte-for-byte the same structure. Each list entry is either:

* a **string** — the pattern itself, e.g. `"*.example.com"`; or
* a **mapping** with a `host` (or `pattern` / `url` / `cidr` / `ip`) key and an
  optional `type` label:

  ```yaml
  - host: "2001:db8:abcd::/48"
    type: infra
  ```

The `type` label is informational (surfaced in output and JSON); it does not
affect matching.

## Matching semantics (read this)

Entries are classified by their syntax and matched as follows:

| Form | Example | Matches |
|------|---------|---------|
| **Exact host** | `api.example.com` | that host only (case-insensitive, port ignored) |
| **Wildcard domain** | `*.example.com` | the apex `example.com` **and** any sub-domain at any depth (`a.example.com`, `a.b.example.com`) — never `notexample.com` |
| **IP address** | `203.0.113.7` | that address only |
| **CIDR range** | `203.0.113.0/24`, `2001:db8::/48` | any IP inside the range; IPv4 and IPv6 never cross |
| **URL prefix** | `https://example.com/api/*` | host matches *and* path matches (see below) |

Key rules:

* **Out-of-scope always wins.** If a target matches *any* out-of-scope entry, the
  verdict is `OUT_OF_SCOPE`, regardless of how many in-scope entries it also
  matched. Deny beats allow, always.
* **Wildcards include the apex.** `*.example.com` matches `example.com` itself,
  matching how most programs word their scope. It does *not* match unrelated
  suffixes such as `notexample.com`.
* **URL paths** support two styles:
  * `.../api/*` — glob: `*` matches any run of characters, so it matches
    everything strictly under `/api/`.
  * `.../api` — boundary prefix: matches `/api` and `/api/anything`, but **not**
    `/apidocs`.
  The scheme is ignored, so a rule works with or without `http(s)://`.
* **No DNS.** Hostnames are never resolved to IPs. A hostname is checked against
  host/wildcard/URL rules; an IP target is checked against IP/CIDR rules.

## Batch mode, CI, and exit codes

Feed many targets from a file (`-T`), from stdin (`--stdin` or `-`), or as
several arguments. You get a table and a summary:

```console
$ printf 'api.example.com\nblog.example.com\nhttps://example.com/api/users\n203.0.113.9\nexample.org\n' \
    | scope-sentinel check -s program.yaml --stdin
VERDICT       TARGET                         KIND        RULE                       TYPE
------------  -----------------------------  ----------  -------------------------  ----
IN_SCOPE      api.example.com                exact host  api.example.com            -
OUT_OF_SCOPE  blog.example.com               exact host  blog.example.com           -
IN_SCOPE      https://example.com/api/users  URL prefix  https://example.com/api/*  -
IN_SCOPE      203.0.113.9                    IP/CIDR     203.0.113.0/24             -
NOT_LISTED    example.org                    -           -                          -

Summary: 3 in-scope, 1 out-of-scope, 1 not-listed (5 total)
```

Exit codes are designed to gate testing in scripts and CI:

| Code | Meaning |
|------|---------|
| `0`  | in scope — all targets cleared to test |
| `2`  | out of scope — at least one target is explicitly denied |
| `3`  | not listed — no target is denied, but at least one isn't covered |
| `1`  | runtime error (missing/malformed scope file, bad target) |
| `64` | command-line usage error |

In batch mode the worst case wins: any out-of-scope target yields `2`. A simple
gate:

```bash
# Only proceed if every target is in scope
scope-sentinel check -s program.yaml -T targets.txt --quiet \
  && ./run-my-scan.sh \
  || echo "Refusing to run: a target is out of scope or not listed."
```

## JSON output

`--json` emits a structured document (single target or batch) including every
matching rule and the reason, for pipelines and dashboards:

```console
$ scope-sentinel check -s program.yaml --json https://example.com/api/legacy/report
{
  "program": "Example Corp Public Program",
  "results": [
    {
      "target": "https://example.com/api/legacy/report",
      "host": "example.com",
      "verdict": "OUT_OF_SCOPE",
      "matched_rule": { "pattern": "https://example.com/api/legacy/*", "kind": "URL prefix", "side": "out_of_scope" },
      "reason": "host 'example.com' matches out-of-scope URL prefix rule ...",
      ...
    }
  ],
  "summary": { "in_scope": 0, "out_of_scope": 1, "not_listed": 0, "total": 1 },
  "exit_code": 2
}
```

## Turning a pasted scope into a file

Program scopes usually live as a bulleted list on a web page. `convert-scope`
turns pasted text into a starter scope file:

```console
$ pbpaste | scope-sentinel convert-scope - --program "Example Corp" > program.yaml
```

It recognises `In scope` / `Out of scope` headings, strips bullets and markdown,
pulls out host/URL/IP/CIDR tokens, and skips obvious noise (email domains,
source-file names). This step is a **best-effort heuristic** — always read the
result before relying on it.

## Use as a library

```python
from scope_sentinel import Scope

scope = Scope.from_file("program.yaml")
result = scope.check("https://api.example.com/v1")
print(result.verdict)   # "IN_SCOPE"
print(result.reason)
```

## Limitations

* **Scope is only as good as the file.** The tool checks a target against the
  rules you give it; keeping the file faithful to the program policy is on you.
* **No DNS / no network.** Hostnames are not resolved; an IP target won't match a
  hostname rule and vice-versa. This is deliberate — the tool stays offline.
* **YAML is a documented subset** (mappings, block sequences, sequences of
  mappings, quoted/bare scalars, `#` comments; spaces for indentation). Flow
  collections, anchors, and multi-document files are not supported — use JSON for
  those. If PyYAML-level YAML matters to you, write the scope as JSON.
* **`convert-scope` is heuristic** and meant as a starting point, not a source of
  truth.
* **Not legal advice.** A machine verdict is a guardrail, not authorization —
  the program's written policy always governs.

## Responsible use

This tool exists to *prevent* out-of-scope testing, not to map attack surface.
Only test systems you are explicitly authorized to test, follow each program's
rules of engagement, and when the scope is ambiguous, ask the program before you
act. When in doubt, don't.

## License

MIT © 2026 Jakub Kozub. See [LICENSE](LICENSE).

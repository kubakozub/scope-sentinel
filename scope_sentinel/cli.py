"""Command-line interface for scope-sentinel."""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, textscope
from .errors import ScopeError
from .scope import (EXIT_ERROR, EXIT_IN_SCOPE, EXIT_NOT_LISTED,
                    EXIT_OUT_OF_SCOPE, EXIT_USAGE, IN_SCOPE, NOT_LISTED,
                    OUT_OF_SCOPE, Scope)

_COLOR = {IN_SCOPE: '32', OUT_OF_SCOPE: '31', NOT_LISTED: '33'}


# --------------------------------------------------------------------------- #
# Colour helpers (respect NO_COLOR and non-tty streams)
# --------------------------------------------------------------------------- #
def _color_enabled(stream, choice):
    if choice == 'always':
        return True
    if choice == 'never' or os.environ.get('NO_COLOR') is not None:
        return False
    return hasattr(stream, 'isatty') and stream.isatty()


def _paint(text, verdict, enabled):
    if not enabled:
        return text
    return f"\033[1;{_COLOR[verdict]}m{text}\033[0m"


def _trunc(s, n):
    s = str(s)
    return s if len(s) <= n else s[:n - 1] + '…'


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #
class _ArgParser(argparse.ArgumentParser):
    """Exit with EX_USAGE (64) on misuse so it never collides with a verdict."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser():
    p = _ArgParser(
        prog='scope-sentinel',
        description='Confirm whether a target is in scope for a bug-bounty '
                    'program before you test it. Out-of-scope always wins.')
    p.add_argument('--version', action='version',
                   version=f'scope-sentinel {__version__}')
    sub = p.add_subparsers(dest='command', required=True)

    c = sub.add_parser('check', help='check one or more targets against a scope file')
    c.add_argument('targets', nargs='*',
                   help="target URL / host / IP (use '-' to read from stdin)")
    c.add_argument('-s', '--scope', required=True,
                   help='scope file (.yaml / .yml / .json)')
    c.add_argument('-T', '--targets-file',
                   help='read targets (one per line, # comments ignored) from FILE')
    c.add_argument('--stdin', action='store_true',
                   help='read targets from standard input')
    c.add_argument('--json', action='store_true', help='emit JSON instead of text')
    c.add_argument('--table', action='store_true',
                   help='force table output even for a single target')
    c.add_argument('-q', '--quiet', action='store_true',
                   help='suppress output; rely on the exit code')
    c.add_argument('--color', choices=('auto', 'always', 'never'), default='auto',
                   help='colourise the verdict (default: auto)')
    c.set_defaults(func=cmd_check)

    v = sub.add_parser('convert-scope',
                       help='convert a pasted plain-text scope list to YAML/JSON')
    v.add_argument('input', nargs='?', default='-',
                   help="input text file (default: '-' = stdin)")
    v.add_argument('-o', '--out', help='output file (default: stdout)')
    v.add_argument('--json', action='store_true', help='emit JSON instead of YAML')
    v.add_argument('--program', help='program name to record in the output')
    v.set_defaults(func=cmd_convert)

    return p


# --------------------------------------------------------------------------- #
# `check`
# --------------------------------------------------------------------------- #
def _read_target_lines(fh):
    targets = []
    for line in fh:
        line = line.strip()
        if line and not line.startswith('#'):
            targets.append(line)
    return targets


def _gather_targets(args):
    targets, use_stdin = [], args.stdin
    for t in args.targets:
        if t == '-':
            use_stdin = True
        else:
            targets.append(t)
    if args.targets_file:
        try:
            with open(args.targets_file, 'r', encoding='utf-8') as fh:
                targets.extend(_read_target_lines(fh))
        except OSError as exc:
            raise ScopeError(
                f"cannot read targets file {args.targets_file!r}: {exc}") from exc
    if use_stdin:
        targets.extend(_read_target_lines(sys.stdin))
    return targets


def batch_exit(results):
    verdicts = {r.verdict for r in results}
    if OUT_OF_SCOPE in verdicts:
        return EXIT_OUT_OF_SCOPE
    if NOT_LISTED in verdicts:
        return EXIT_NOT_LISTED
    return EXIT_IN_SCOPE


def cmd_check(args, out):
    scope = Scope.from_file(args.scope)
    targets = _gather_targets(args)
    if not targets:
        raise ScopeError("no targets given (pass targets, --targets-file, or --stdin)")
    results = [scope.check(t) for t in targets]

    if args.quiet:
        pass
    elif args.json:
        _print_json(scope, results, out)
    elif len(results) == 1 and not args.table:
        _print_detail(results[0], out, _color_enabled(out, args.color))
    else:
        _print_table(results, out, _color_enabled(out, args.color))
    return batch_exit(results)


def _print_detail(r, out, color):
    print(f"Target:  {r.target}", file=out)
    if r.info.host and r.info.host != r.target:
        who = r.info.ip.compressed if r.info.ip is not None else r.info.host
        print(f"Host:    {who}", file=out)
    print(f"Verdict: {_paint(r.verdict, r.verdict, color)}", file=out)
    if r.matched:
        extra = f"  [type={r.matched.asset_type}]" if r.matched.asset_type else ''
        print(f"Rule:    {r.matched.pattern}  ({r.matched.kind}){extra}", file=out)
    else:
        print("Rule:    -", file=out)
    print(f"Reason:  {r.reason}", file=out)


def _print_table(results, out, color):
    headers = ('VERDICT', 'TARGET', 'KIND', 'RULE', 'TYPE')
    rows = []
    for r in results:
        rows.append((
            r.verdict,
            _trunc(r.target, 45),
            r.matched.kind if r.matched else '-',
            _trunc(r.matched.pattern, 40) if r.matched else '-',
            (r.matched.asset_type if (r.matched and r.matched.asset_type) else '-'),
        ))
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(cells):
        return '  '.join(c.ljust(widths[i]) for i, c in enumerate(cells)).rstrip()

    print(fmt(headers), file=out)
    print('  '.join('-' * w for w in widths), file=out)
    for r, row in zip(results, rows):
        line = fmt(row)
        if color:
            line = _paint(row[0].ljust(widths[0]), r.verdict, True) + line[widths[0]:]
        print(line, file=out)

    n = len(results)
    ins = sum(1 for r in results if r.verdict == IN_SCOPE)
    outs = sum(1 for r in results if r.verdict == OUT_OF_SCOPE)
    nls = sum(1 for r in results if r.verdict == NOT_LISTED)
    print('', file=out)
    print(f"Summary: {ins} in-scope, {outs} out-of-scope, {nls} not-listed "
          f"({n} total)", file=out)


def _print_json(scope, results, out):
    payload = {
        "program": scope.program,
        "scope_source": scope.source,
        "results": [r.to_dict() for r in results],
        "summary": {
            "in_scope": sum(1 for r in results if r.verdict == IN_SCOPE),
            "out_of_scope": sum(1 for r in results if r.verdict == OUT_OF_SCOPE),
            "not_listed": sum(1 for r in results if r.verdict == NOT_LISTED),
            "total": len(results),
        },
        "exit_code": batch_exit(results),
    }
    json.dump(payload, out, indent=2)
    out.write('\n')


# --------------------------------------------------------------------------- #
# `convert-scope`
# --------------------------------------------------------------------------- #
def cmd_convert(args, out):
    if args.input == '-':
        text = sys.stdin.read()
    else:
        try:
            with open(args.input, 'r', encoding='utf-8') as fh:
                text = fh.read()
        except OSError as exc:
            raise ScopeError(f"cannot read input {args.input!r}: {exc}") from exc

    scope = textscope.parse_text(text)
    rendered = (textscope.to_json(scope, args.program) if args.json
                else textscope.to_yaml(scope, args.program))

    if args.out:
        try:
            with open(args.out, 'w', encoding='utf-8') as fh:
                fh.write(rendered)
        except OSError as exc:
            raise ScopeError(f"cannot write output {args.out!r}: {exc}") from exc
        n_in = len(scope.get('in_scope') or [])
        n_out = len(scope.get('out_of_scope') or [])
        print(f"Wrote {args.out}: {n_in} in-scope, {n_out} out-of-scope entries "
              f"(heuristic -- please review).", file=sys.stderr)
    else:
        out.write(rendered)
    return EXIT_IN_SCOPE


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, sys.stdout)
    except ScopeError as exc:
        print(f"scope-sentinel: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return EXIT_ERROR


if __name__ == '__main__':          # pragma: no cover
    sys.exit(main())

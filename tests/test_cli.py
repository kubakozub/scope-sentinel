import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from scope_sentinel import cli

SCOPE_YAML = (
    "program: Demo\n"
    "in_scope:\n"
    '  - host: "*.example.com"\n'
    "    type: web\n"
    "  - api.example.com\n"
    "  - 203.0.113.0/24\n"
    "out_of_scope:\n"
    "  - blog.example.com\n"
    "  - https://example.com/api/legacy/*\n"
)


def run(argv, stdin_text=None):
    """Run cli.main(argv), returning (exit_code, stdout)."""
    buf = io.StringIO()
    old_stdin = None
    if stdin_text is not None:
        import sys
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(stdin_text)
    try:
        with redirect_stdout(buf):
            code = cli.main(argv)
    finally:
        if old_stdin is not None:
            import sys
            sys.stdin = old_stdin
    return code, buf.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.scope_path = os.path.join(self.dir.name, "scope.yaml")
        with open(self.scope_path, "w") as fh:
            fh.write(SCOPE_YAML)

    def _args(self, *extra):
        return ["check", "--scope", self.scope_path, *extra]

    # -- exit codes ----------------------------------------------------- #
    def test_exit_in_scope(self):
        code, out = run(self._args("api.example.com"))
        self.assertEqual(code, 0)
        self.assertIn("IN_SCOPE", out)

    def test_exit_out_of_scope(self):
        code, out = run(self._args("blog.example.com"))
        self.assertEqual(code, 2)
        self.assertIn("OUT_OF_SCOPE", out)

    def test_exit_not_listed(self):
        code, out = run(self._args("example.org"))
        self.assertEqual(code, 3)
        self.assertIn("NOT_LISTED", out)

    def test_batch_exit_is_worst_case(self):
        # one in, one out, one not-listed -> out-of-scope (2) wins
        code, out = run(self._args("api.example.com", "blog.example.com",
                                   "example.org"))
        self.assertEqual(code, 2)
        self.assertIn("Summary:", out)
        self.assertIn("1 in-scope", out)
        self.assertIn("1 out-of-scope", out)
        self.assertIn("1 not-listed", out)

    def test_batch_all_in_scope_exit_zero(self):
        code, _ = run(self._args("api.example.com", "www.example.com", "203.0.113.4"))
        self.assertEqual(code, 0)

    # -- input channels ------------------------------------------------- #
    def test_stdin(self):
        code, out = run(self._args("--stdin"),
                        stdin_text="api.example.com\n# comment\nblog.example.com\n")
        self.assertEqual(code, 2)
        self.assertIn("Summary:", out)

    def test_targets_file(self):
        tf = os.path.join(self.dir.name, "targets.txt")
        with open(tf, "w") as fh:
            fh.write("api.example.com\nexample.org\n")
        code, _ = run(self._args("--targets-file", tf))
        self.assertEqual(code, 3)

    # -- JSON ----------------------------------------------------------- #
    def test_json_output(self):
        code, out = run(self._args("--json", "blog.example.com"))
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["results"][0]["verdict"], "OUT_OF_SCOPE")
        self.assertEqual(payload["summary"]["out_of_scope"], 1)
        self.assertEqual(payload["exit_code"], 2)

    def test_quiet_has_no_stdout(self):
        code, out = run(self._args("--quiet", "blog.example.com"))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    # -- convert-scope -------------------------------------------------- #
    def test_convert_scope_yaml_roundtrip(self):
        src = os.path.join(self.dir.name, "pasted.txt")
        with open(src, "w") as fh:
            fh.write("In scope\n*.example.com\nOut of scope\nblog.example.com\n")
        code, out = run(["convert-scope", src])
        self.assertEqual(code, 0)
        self.assertIn("in_scope:", out)
        self.assertIn("*.example.com", out)
        self.assertIn("blog.example.com", out)

    # -- usage / errors ------------------------------------------------- #
    def test_missing_scope_is_usage_error(self):
        with self.assertRaises(SystemExit) as ctx:
            run(["check", "api.example.com"])   # no --scope
        self.assertEqual(ctx.exception.code, 64)

    def test_no_subcommand_is_usage_error(self):
        with self.assertRaises(SystemExit) as ctx:
            run([])
        self.assertEqual(ctx.exception.code, 64)

    def test_no_targets_is_runtime_error(self):
        code, _ = run(self._args())
        self.assertEqual(code, 1)

    def test_bad_scope_file_is_runtime_error(self):
        code, _ = run(["check", "--scope", "/no/such/file.yaml", "api.example.com"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()

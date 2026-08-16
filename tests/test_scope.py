import json
import os
import tempfile
import unittest

from scope_sentinel import (IN_SCOPE, NOT_LISTED, OUT_OF_SCOPE, Scope,
                             verdict_exit)
from scope_sentinel.errors import ScopeError
from scope_sentinel.scope import (EXIT_IN_SCOPE, EXIT_NOT_LISTED,
                                   EXIT_OUT_OF_SCOPE)

MAPPING = {
    "program": "Demo",
    "in_scope": [
        {"host": "*.example.com", "type": "web"},
        "api.example.com",
        "https://example.com/api/*",
        "203.0.113.0/24",
    ],
    "out_of_scope": [
        "blog.example.com",
        "*.internal.example.com",
        "https://example.com/api/legacy/*",
    ],
}


class VerdictTest(unittest.TestCase):
    def setUp(self):
        self.scope = Scope.from_mapping(MAPPING)

    def test_in_scope(self):
        self.assertEqual(self.scope.check("api.example.com").verdict, IN_SCOPE)
        self.assertEqual(self.scope.check("example.com").verdict, IN_SCOPE)
        self.assertEqual(
            self.scope.check("https://example.com/api/users").verdict, IN_SCOPE)
        self.assertEqual(self.scope.check("203.0.113.9").verdict, IN_SCOPE)

    def test_not_listed(self):
        self.assertEqual(self.scope.check("example.org").verdict, NOT_LISTED)
        self.assertEqual(self.scope.check("198.51.100.1").verdict, NOT_LISTED)

    def test_deny_beats_allow(self):
        # blog.example.com matches in-scope *.example.com AND out-of-scope exact.
        r = self.scope.check("blog.example.com")
        self.assertEqual(r.verdict, OUT_OF_SCOPE)
        self.assertTrue(r.in_matches)      # it did match an in-scope rule too
        self.assertTrue(r.out_matches)
        self.assertEqual(r.matched.pattern, "blog.example.com")

    def test_deny_subtree_beats_allow(self):
        r = self.scope.check("host.internal.example.com")
        self.assertEqual(r.verdict, OUT_OF_SCOPE)
        self.assertEqual(r.matched.pattern, "*.internal.example.com")

    def test_url_deny_beats_allow(self):
        self.assertEqual(
            self.scope.check("https://example.com/api/legacy/x").verdict,
            OUT_OF_SCOPE)

    def test_specific_rule_reported(self):
        # api.example.com matches both the wildcard and the exact rule;
        # the more specific exact rule should be reported.
        self.assertEqual(
            self.scope.check("api.example.com").matched.pattern, "api.example.com")

    def test_asset_type_preserved(self):
        r = self.scope.check("shop.example.com")
        self.assertEqual(r.matched.asset_type, "web")


class ExitCodeTest(unittest.TestCase):
    def test_verdict_exit(self):
        self.assertEqual(verdict_exit(IN_SCOPE), EXIT_IN_SCOPE)
        self.assertEqual(verdict_exit(OUT_OF_SCOPE), EXIT_OUT_OF_SCOPE)
        self.assertEqual(verdict_exit(NOT_LISTED), EXIT_NOT_LISTED)
        self.assertEqual(EXIT_IN_SCOPE, 0)


class LoadTest(unittest.TestCase):
    def test_from_json_and_yaml_equivalent(self):
        yaml_text = (
            "in_scope:\n"
            '  - host: "*.example.com"\n'
            "    type: web\n"
            "  - api.example.com\n"
            "out_of_scope:\n"
            "  - blog.example.com\n"
        )
        json_text = json.dumps({
            "in_scope": [{"host": "*.example.com", "type": "web"},
                         "api.example.com"],
            "out_of_scope": ["blog.example.com"],
        })
        y = Scope.from_text(yaml_text)
        j = Scope.from_text(json_text)
        for target in ("a.example.com", "blog.example.com", "example.org"):
            self.assertEqual(y.check(target).verdict, j.check(target).verdict)

    def test_from_file_by_extension(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            with open(path, "w") as fh:
                json.dump(MAPPING, fh)
            scope = Scope.from_file(path)
            self.assertEqual(scope.check("api.example.com").verdict, IN_SCOPE)

    def test_empty_scope_rejected(self):
        with self.assertRaises(ScopeError):
            Scope.from_mapping({"program": "x"})

    def test_result_to_dict(self):
        d = Scope.from_mapping(MAPPING).check("blog.example.com").to_dict()
        self.assertEqual(d["verdict"], OUT_OF_SCOPE)
        self.assertEqual(d["exit_code"], EXIT_OUT_OF_SCOPE)
        self.assertEqual(d["matched_rule"]["pattern"], "blog.example.com")


if __name__ == "__main__":
    unittest.main()

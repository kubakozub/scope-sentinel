import unittest

from scope_sentinel import yamllite
from scope_sentinel.errors import ScopeError


class YamlLiteTest(unittest.TestCase):
    def test_top_level_mapping(self):
        data = yamllite.load("program: Acme\nfoo: bar\n")
        self.assertEqual(data, {"program": "Acme", "foo": "bar"})

    def test_sequence_of_scalars_indented(self):
        data = yamllite.load("in_scope:\n  - a.com\n  - b.com\n")
        self.assertEqual(data, {"in_scope": ["a.com", "b.com"]})

    def test_sequence_same_indent_as_key(self):
        data = yamllite.load("in_scope:\n- a.com\n- b.com\nout_of_scope:\n- c.com\n")
        self.assertEqual(
            data, {"in_scope": ["a.com", "b.com"], "out_of_scope": ["c.com"]})

    def test_sequence_of_block_mappings(self):
        text = (
            "in_scope:\n"
            '  - host: "*.example.com"\n'
            "    type: web\n"
            "  - api.example.com\n"
        )
        self.assertEqual(
            yamllite.load(text),
            {"in_scope": [{"host": "*.example.com", "type": "web"},
                          "api.example.com"]})

    def test_quotes_comments_and_specials(self):
        text = (
            "# a comment line\n"
            'a: "hello world"   # trailing comment\n'
            "b: 'single'\n"
            "url: https://example.com/api/*  # not a comment before //\n"
            "flag: true\n"
            "none: null\n"
            "empty: []\n"
        )
        self.assertEqual(
            yamllite.load(text),
            {"a": "hello world", "b": "single",
             "url": "https://example.com/api/*",
             "flag": True, "none": None, "empty": []})

    def test_hash_inside_value_not_a_comment(self):
        # '#' without a preceding space is part of the value.
        self.assertEqual(yamllite.load("a: v#frag\n"), {"a": "v#frag"})

    def test_empty_key_with_no_children_is_none(self):
        self.assertEqual(
            yamllite.load("in_scope:\nout_of_scope:\n- x.com\n"),
            {"in_scope": None, "out_of_scope": ["x.com"]})

    def test_tabs_rejected(self):
        with self.assertRaises(ScopeError):
            yamllite.load("in_scope:\n\t- a.com\n")

    def test_bad_mapping_line_rejected(self):
        with self.assertRaises(ScopeError):
            yamllite.load("this is not valid\n")


if __name__ == "__main__":
    unittest.main()

import unittest

from scope_sentinel import IN_SCOPE, OUT_OF_SCOPE, Scope
from scope_sentinel import textscope


class ParseTextTest(unittest.TestCase):
    def test_sections_bullets_and_tokens(self):
        text = (
            "In scope\n"
            "  * *.example.com\n"
            "  - api.example.com\n"
            "  https://example.com/api/*\n"
            "  203.0.113.0/24\n"
            "\n"
            "Out of scope\n"
            "  - blog.example.com\n"
            "  - *.internal.example.com\n"
        )
        scope = textscope.parse_text(text)
        self.assertIn("*.example.com", scope["in_scope"])
        self.assertIn("api.example.com", scope["in_scope"])
        self.assertIn("https://example.com/api/*", scope["in_scope"])
        self.assertIn("203.0.113.0/24", scope["in_scope"])
        self.assertIn("blog.example.com", scope["out_of_scope"])
        self.assertIn("*.internal.example.com", scope["out_of_scope"])

    def test_markdown_link_and_backticks(self):
        text = "In scope\n- [API](https://api.example.com)\n- `db.example.com`\n"
        scope = textscope.parse_text(text)
        self.assertIn("https://api.example.com", scope["in_scope"])
        self.assertIn("db.example.com", scope["in_scope"])

    def test_default_section_is_in_scope(self):
        scope = textscope.parse_text("foo.example.com\nbar.example.com\n")
        self.assertEqual(scope["in_scope"], ["foo.example.com", "bar.example.com"])
        self.assertEqual(scope["out_of_scope"], [])

    def test_file_names_filtered_but_prose_ignored(self):
        text = "In scope\napi.example.com\nPlease read README.md and config.py first.\n"
        scope = textscope.parse_text(text)
        self.assertIn("api.example.com", scope["in_scope"])
        self.assertNotIn("README.md", scope["in_scope"])
        self.assertNotIn("config.py", scope["in_scope"])

    def test_email_domain_not_captured(self):
        scope = textscope.parse_text("In scope\napi.example.com\nContact security@corp.example\n")
        self.assertIn("api.example.com", scope["in_scope"])
        self.assertNotIn("corp.example", scope["in_scope"])

    def test_domain_line_not_treated_as_header(self):
        # 'in-scope.example.com' contains 'in-scope' but is a real host.
        scope = textscope.parse_text("Out of scope\nin-scope.example.com\n")
        self.assertIn("in-scope.example.com", scope["out_of_scope"])
        self.assertEqual(scope["in_scope"], [])

    def test_roundtrip_through_scope_yaml(self):
        text = "In scope\n*.example.com\nOut of scope\nblog.example.com\n"
        yaml_out = textscope.to_yaml(textscope.parse_text(text), program="Demo")
        scope = Scope.from_text(yaml_out)
        self.assertEqual(scope.program, "Demo")
        self.assertEqual(scope.check("a.example.com").verdict, IN_SCOPE)
        self.assertEqual(scope.check("blog.example.com").verdict, OUT_OF_SCOPE)

    def test_roundtrip_through_scope_json(self):
        text = "In scope\n*.example.com\nOut of scope\nblog.example.com\n"
        json_out = textscope.to_json(textscope.parse_text(text))
        scope = Scope.from_text(json_out)
        self.assertEqual(scope.check("blog.example.com").verdict, OUT_OF_SCOPE)


if __name__ == "__main__":
    unittest.main()

import unittest

from scope_sentinel.rules import (KIND_HOST, KIND_IP, KIND_URL, KIND_WILDCARD,
                                   Rule, parse_target)


def matches(pattern, target):
    return Rule.classify(pattern).matches(parse_target(target))


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(Rule.classify("api.example.com").kind, KIND_HOST)
        self.assertEqual(Rule.classify("*.example.com").kind, KIND_WILDCARD)
        self.assertEqual(Rule.classify("10.0.0.0/8").kind, KIND_IP)
        self.assertEqual(Rule.classify("203.0.113.7").kind, KIND_IP)
        self.assertEqual(Rule.classify("2001:db8::/32").kind, KIND_IP)
        self.assertEqual(Rule.classify("https://example.com/api/*").kind, KIND_URL)
        # scheme+host, no path -> host rule
        self.assertEqual(Rule.classify("https://example.com").kind, KIND_HOST)
        # scheme + wildcard host, no path -> wildcard rule
        self.assertEqual(Rule.classify("https://*.example.com").kind, KIND_WILDCARD)


class ExactHostTest(unittest.TestCase):
    def test_exact(self):
        self.assertTrue(matches("api.example.com", "api.example.com"))
        self.assertTrue(matches("api.example.com", "https://api.example.com/x"))
        self.assertTrue(matches("api.example.com", "API.EXAMPLE.COM:8443"))
        self.assertFalse(matches("api.example.com", "www.example.com"))
        self.assertFalse(matches("api.example.com", "xapi.example.com"))

    def test_trailing_fqdn_dot_normalized(self):
        self.assertTrue(matches("api.example.com", "api.example.com."))
        self.assertTrue(matches("*.example.com", "sub.example.com."))


class WildcardTest(unittest.TestCase):
    def test_apex_and_subdomains(self):
        self.assertTrue(matches("*.example.com", "example.com"))         # apex
        self.assertTrue(matches("*.example.com", "sub.example.com"))
        self.assertTrue(matches("*.example.com", "a.b.example.com"))     # deep
        self.assertTrue(matches("*.example.com", "https://a.example.com/p"))

    def test_wildcard_does_not_overmatch(self):
        self.assertFalse(matches("*.example.com", "notexample.com"))
        self.assertFalse(matches("*.example.com", "example.com.evil.com"))
        self.assertFalse(matches("*.example.com", "xexample.com"))


class IpCidrTest(unittest.TestCase):
    def test_v4_cidr(self):
        self.assertTrue(matches("203.0.113.0/24", "203.0.113.5"))
        self.assertTrue(matches("203.0.113.0/24", "https://203.0.113.5/x"))
        self.assertFalse(matches("203.0.113.0/24", "203.0.114.5"))

    def test_single_ip(self):
        self.assertTrue(matches("203.0.113.7", "203.0.113.7"))
        self.assertFalse(matches("203.0.113.7", "203.0.113.8"))

    def test_v6_cidr(self):
        self.assertTrue(matches("2001:db8::/32", "2001:db8::1"))
        self.assertTrue(matches("2001:db8::/32", "[2001:db8::1]:443"))
        self.assertFalse(matches("2001:db8::/32", "2001:dead::1"))

    def test_family_isolation(self):
        # An IPv4 target must never match an IPv6 range, and vice versa.
        self.assertFalse(matches("2001:db8::/32", "203.0.113.5"))
        self.assertFalse(matches("10.0.0.0/8", "2001:db8::1"))

    def test_hostnames_not_resolved(self):
        # No DNS: a hostname never matches an IP/CIDR rule.
        self.assertFalse(matches("203.0.113.0/24", "example.com"))


class UrlPrefixTest(unittest.TestCase):
    def test_glob_prefix(self):
        self.assertTrue(matches("https://example.com/api/*",
                                "https://example.com/api/users"))
        self.assertFalse(matches("https://example.com/api/*",
                                 "https://example.com/apidocs"))
        # scheme is ignored on both sides
        self.assertTrue(matches("example.com/api/*", "https://example.com/api/x"))
        self.assertTrue(matches("https://example.com/api/*", "example.com/api/x"))

    def test_boundary_prefix_without_star(self):
        self.assertTrue(matches("https://example.com/api", "https://example.com/api"))
        self.assertTrue(matches("https://example.com/api", "https://example.com/api/v1"))
        self.assertFalse(matches("https://example.com/api", "https://example.com/apidocs"))

    def test_host_must_match_too(self):
        self.assertFalse(matches("https://example.com/api/*",
                                 "https://other.com/api/users"))

    def test_wildcard_host_with_path(self):
        self.assertTrue(matches("https://*.example.com/api/*",
                                "https://a.example.com/api/x"))
        self.assertFalse(matches("https://*.example.com/api/*",
                                 "https://a.other.com/api/x"))


class SpecificityTest(unittest.TestCase):
    def test_exact_beats_wildcard(self):
        exact = Rule.classify("api.example.com")
        wild = Rule.classify("*.example.com")
        self.assertGreater(exact.specificity(), wild.specificity())


if __name__ == "__main__":
    unittest.main()

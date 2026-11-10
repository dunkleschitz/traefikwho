#!/usr/bin/env python3
"""Test suite for traefikwho 1.0.0.

Run:  python3 test_traefikwho.py        (from this directory)

Plain unittest, stdlib only, no pytest - the family standard.
Fixture configs are the only oracle: no `traefik` binary exists on
this box, so every expectation here is a design pin from
DESIGN-traefikwho.md (TR01-TR42), tagged [documented] /
[docs-inferred] / [hypothesized] there. Test groups mirror the
design's test plan BG1-BG12. Fixture files are chmod 0600 on write
(the kubewho lesson: treat every fixture as potentially
secret-bearing even though none here carries a secret).
"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
M = SourceFileLoader("traefikwho", os.path.join(HERE, "traefikwho")).load_module()


def svc(name="app", servers=("http://10.0.0.1:8080",), extra=""):
    lines = ["    %s:" % name, "      loadBalancer:", "        servers:"]
    for s in servers:
        lines.append('          - url: "%s"' % s)
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def http_conf(routers, services=None, middlewares=None, extra_top=""):
    out = ["http:", "  routers:"]
    out.extend(routers)
    if services is None:
        services = [svc()]
    out.append("  services:")
    out.extend(services)
    if middlewares:
        out.append("  middlewares:")
        out.extend(middlewares)
    if extra_top:
        out.append(extra_top)
    return "\n".join(out) + "\n"


def router(name, rule, service="app", extra=""):
    # Single-quoted YAML: backslashes in regexes stay literal (the
    # form real Traefik configs use); rules never contain "'".
    lines = ["    %s:" % name, "      rule: '%s'" % rule,
             "      service: %s" % service]
    if extra:
        lines.append(extra)
    return "\n".join(lines)


class TraefikCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="traefikwho-test-")

    def write(self, text, name="app.yml", subdir=None):
        d = os.path.join(self.dir, subdir) if subdir else self.dir
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(path, 0o600)
        return path

    def confdir(self, files):
        """files: {name: text} -> the directory path."""
        d = os.path.join(self.dir, "conf")
        os.makedirs(d, exist_ok=True)
        for name, text in files.items():
            path = os.path.join(d, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.chmod(path, 0o600)
        return d

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = M.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def run_http(self, conf, *args):
        return self.run_cli("http", "--conf", conf, *args)

    def conf_with(self, text, name="app.yml"):
        return self.confdir({name: text})


# ---------------------------------------------------------------- BG1

class TestBG1FilesLoading(TraefikCase):
    def test_yaml_and_toml_merge(self):
        yaml_cfg = http_conf([router("yaml-router",
                                     "Host(`yaml.example.com`)")])
        toml_cfg = (
            '[http.routers.toml-router]\n'
            '  rule = "Host(`toml.example.com`)"\n'
            '  service = "app"\n'
            '[http.services.app.loadBalancer]\n'
            '  [[http.services.app.loadBalancer.servers]]\n'
            '    url = "http://10.0.0.1:8080"\n')
        conf = self.confdir({"a.yml": yaml_cfg, "b.toml": toml_cfg})
        code, out, _ = self.run_http(conf, "--host", "toml.example.com")
        self.assertEqual(code, 0)
        self.assertIn("toml-router", out)
        code, out, _ = self.run_http(conf, "--host", "yaml.example.com")
        self.assertEqual(code, 0)
        self.assertIn("yaml-router", out)

    def test_router_cites_file_and_line(self):
        conf = self.conf_with(http_conf(
            [router("web", "Host(`example.com`)")]))
        code, out, _ = self.run_cli("--list-routers", "--conf", conf)
        self.assertEqual(code, 0)
        self.assertIn("app.yml:3", out)
        self.assertIn("web@file", out)

    def test_json_file_ignored_with_note(self):
        conf = self.confdir({
            "app.yml": http_conf([router("web", "Host(`example.com`)")]),
            "extra.json": '{"http": {"routers": {}}}',
        })
        code, out, _ = self.run_http(conf, "--host", "example.com")
        self.assertEqual(code, 0)
        self.assertIn("extra.json", out)
        self.assertIn("not a file-provider format", out)

    def test_subdirectory_not_read(self):
        conf = self.confdir({
            "app.yml": http_conf([router("web", "Host(`example.com`)")]),
            "sub/hidden.yml": http_conf(
                [router("hidden", "Host(`hidden.example.com`)")]),
        })
        code, out, _ = self.run_http(conf, "--host", "hidden.example.com")
        self.assertEqual(code, 1)  # NO-MATCH: hidden router not loaded
        self.assertIn("subdirectory not descended", out)

    def test_conf_single_file(self):
        path = self.write(http_conf(
            [router("web", "Host(`example.com`)")]))
        code, out, _ = self.run_http(path, "--host", "example.com")
        self.assertEqual(code, 0)
        self.assertIn("web@file", out)

    def test_missing_conf_is_usage_error(self):
        code, _out, err = self.run_cli("http", "--host", "example.com")
        self.assertEqual(code, 2)
        self.assertIn("--conf is required", err)

    def test_duplicate_keys_in_one_file_fatal(self):
        text = ("http:\n  routers:\n    web:\n"
                '      rule: "Host(`a.example.com`)"\n'
                "      service: app\n    web:\n"
                '      rule: "Host(`b.example.com`)"\n'
                "      service: app\n  services:\n" + svc() + "\n")
        conf = self.conf_with(text)
        code, _out, err = self.run_http(conf, "--host", "a.example.com")
        self.assertEqual(code, 2)
        self.assertIn("duplicate key", err)
        self.assertIn("app.yml", err)

    def test_go_template_file_routers_unknown_rest_decidable(self):
        clean = http_conf([router("clean", "Host(`clean.example.com`)")])
        templated = (
            "http:\n  routers:\n    tmpl:\n"
            '      rule: "Host(`{{ .Env.HOST }}`)"\n'
            "      service: app\n  services:\n" + svc() + "\n")
        conf = self.confdir({"a.yml": clean, "b.yml": templated})
        code, out, _ = self.run_http(conf, "--host", "clean.example.com")
        self.assertEqual(code, 0)
        self.assertIn("clean", out)
        self.assertIn("[go-template-not-evaluated]", out)
        code, out, _ = self.run_http(conf, "--host", "other.example.com")
        self.assertEqual(code, 2)
        self.assertIn("UNKNOWN", out)


# ---------------------------------------------------------------- BG2

class TestBG2RuleGrammar(TraefikCase):
    def test_and_binds_tighter_than_or(self):
        # Host(a) || Host(b) && Path(/x): host b + path /y must NOT match
        cfg = http_conf([router(
            "web", "Host(`a.example.com`) || Host(`b.example.com`) && "
                   "Path(`/x`)")])
        conf = self.conf_with(cfg)
        code, _o, _e = self.run_http(conf, "--host", "b.example.com",
                                     "--path", "/y")
        self.assertEqual(code, 1)
        code, out, _ = self.run_http(conf, "--host", "b.example.com",
                                     "--path", "/x")
        self.assertEqual(code, 0)
        self.assertIn("web@file", out)
        code, out, _ = self.run_http(conf, "--host", "a.example.com",
                                     "--path", "/y")
        self.assertEqual(code, 0)

    def test_parentheses_override(self):
        cfg = http_conf([router(
            "web", "(Host(`a.example.com`) || Host(`b.example.com`)) && "
                   "Path(`/x`)")])
        conf = self.conf_with(cfg)
        code, _o, _e = self.run_http(conf, "--host", "b.example.com",
                                     "--path", "/y")
        self.assertEqual(code, 1)
        code, out, _ = self.run_http(conf, "--host", "b.example.com",
                                     "--path", "/x")
        self.assertEqual(code, 0)

    def test_not_inverts_matcher(self):
        cfg = http_conf([router("web", "!Host(`a.example.com`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "b.example.com")
        self.assertEqual(code, 0)
        code, _o, _e = self.run_http(conf, "--host", "a.example.com")
        self.assertEqual(code, 1)

    def test_and_inside_quoted_regex_does_not_split(self):
        cfg = http_conf([router(
            "web", "HostRegexp(`^(a&&b)\\.example\\.com$`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a&&b.example.com")
        self.assertEqual(code, 0)
        self.assertIn("web@file", out)

    def test_single_quoted_matcher_value_fatal(self):
        cfg = http_conf([router("web", "Host('example.com')")])
        conf = self.conf_with(cfg)
        code, _o, err = self.run_http(conf, "--host", "example.com")
        self.assertEqual(code, 2)
        self.assertIn("single-quoted", err)

    def test_v2_router_parses_headers_multi_value_captures(self):
        cfg = http_conf([router(
            "v2web", "Headers(`X-Tenant`, `acme`) && "
                     "Host(`a.example.com`, `b.example.com`) && "
                     "PathPrefix(`/u/{id:[0-9]+}`)",
            extra="      ruleSyntax: v2")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(
            conf, "--host", "b.example.com", "--path", "/u/42",
            "--header", "X-Tenant=acme")
        self.assertEqual(code, 0)
        self.assertIn("v2web@file", out)
        code, _o, _e = self.run_http(
            conf, "--host", "b.example.com", "--path", "/u/abc",
            "--header", "X-Tenant=acme")
        self.assertEqual(code, 1)

    def test_v3_headers_is_fatal(self):
        cfg = http_conf([router("web", "Headers(`X-A`, `b`)")])
        conf = self.conf_with(cfg)
        code, _o, err = self.run_http(conf, "--host", "example.com")
        self.assertEqual(code, 2)
        self.assertIn("unknown matcher Headers", err)

    def test_v3_hostheader_is_fatal(self):
        cfg = http_conf([router("web", "HostHeader(`example.com`)")])
        conf = self.conf_with(cfg)
        code, _o, err = self.run_http(conf, "--host", "example.com")
        self.assertEqual(code, 2)
        self.assertIn("unknown matcher HostHeader", err)

    def test_default_rule_syntax_v2_from_static(self):
        static = ("core:\n  defaultRuleSyntax: v2\n"
                  "entryPoints:\n  web:\n    address: ':80'\n")
        cfg = http_conf([router(
            "v2web", "Headers(`X-Tenant`, `acme`)")])
        conf = self.confdir({"app.yml": cfg})
        spath = self.write(static, name="traefik.yml")
        code, out, _ = self.run_http(
            conf, "--host", "example.com", "--header", "X-Tenant=acme",
            "--static", spath)
        self.assertEqual(code, 0)
        self.assertIn("v2web@file", out)
        self.assertIn("[v2-rule-syntax-deprecated]", out)


# ---------------------------------------------------------------- BG3

class TestBG3Matchers(TraefikCase):
    def test_host_wildcards(self):
        cfg = http_conf([
            router("exact", "Host(`foo.example.com`)"),
            router("one", "Host(`*.example.com`)"),
            router("multi", "Host(`**.example.com`)"),
        ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "foo.example.com")
        self.assertEqual(code, 0)
        self.assertIn("exact@file", out)  # longest rule wins (23)
        code, out, _ = self.run_http(conf, "--host", "bar.example.com")
        self.assertEqual(code, 0)
        self.assertIn("one@file", out)  # 21 beats 20
        code, out, _ = self.run_http(conf, "--host", "a.b.example.com")
        self.assertEqual(code, 0)
        self.assertIn("multi@file", out)
        code, _o, _e = self.run_http(conf, "--host", "example.com")
        self.assertEqual(code, 1)  # neither wildcard matches bare domain

    def test_bare_star_matches_hostless(self):
        cfg = http_conf([router("catch", "Host(`*`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf)  # no --host at all
        self.assertEqual(code, 0)
        self.assertIn("catch@file", out)

    def test_hostregexp_case_insensitive_flag(self):
        cfg = http_conf([router(
            "web", "HostRegexp(`(?i)^EXAMPLE\\.COM$`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "example.com")
        self.assertEqual(code, 0)
        self.assertIn("web@file", out)

    def test_path_exact(self):
        cfg = http_conf([router("web", "Path(`/products`)")])
        conf = self.conf_with(cfg)
        code, _o, _e = self.run_http(conf, "--host", "example.com",
                                     "--path", "/products/shoes")
        self.assertEqual(code, 1)
        code, _o, _e = self.run_http(conf, "--host", "example.com",
                                     "--path", "/products/")
        self.assertEqual(code, 1)
        code, out, _ = self.run_http(conf, "--host", "example.com",
                                     "--path", "/products")
        self.assertEqual(code, 0)

    def test_pathprefix_is_string_prefix(self):
        cfg = http_conf([router("web", "PathPrefix(`/products`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "example.com",
                                     "--path", "/products-for-sale")
        self.assertEqual(code, 0)
        self.assertIn("web@file", out)

    def test_pathregexp_unanchored(self):
        cfg = http_conf([router(
            "web", "PathRegexp(`\\.(jpeg|jpg|png)$`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "example.com",
                                     "--path", "/img/photo.jpg")
        self.assertEqual(code, 0)

    def test_method_exact_and_unsupplied_unknown(self):
        cfg = http_conf([router("web", "Method(`POST`)")])
        conf = self.conf_with(cfg)
        code, _o, _e = self.run_http(conf, "--host", "example.com",
                                     "--method", "GET")
        self.assertEqual(code, 1)
        code, out, _ = self.run_http(conf, "--host", "example.com")
        self.assertEqual(code, 2)
        self.assertIn("UNKNOWN", out)
        self.assertIn("--method", out)
        code, out, _ = self.run_http(conf, "--host", "example.com",
                                     "--method", "POST")
        self.assertEqual(code, 0)

    def test_header_case_insensitive_name_unsupplied_unknown(self):
        cfg = http_conf([router(
            "web", "Header(`X-Tenant`, `acme`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(
            conf, "--host", "example.com", "--header", "x-tenant=acme")
        self.assertEqual(code, 0)
        code, out, _ = self.run_http(conf, "--host", "example.com")
        self.assertEqual(code, 2)
        self.assertIn("UNKNOWN", out)
        self.assertIn("--header", out)

    def test_query_one_arg_vs_two_arg(self):
        cfg = http_conf([
            router("valueless", "Query(`mobile`)"),
            router("valued", "Query(`mobile`, `true`)"),
        ])
        conf = self.conf_with(cfg)
        # ?mobile (no value): the one-arg router matches (present);
        # the two-arg router is FALSE ("" != "true"), so the
        # one-arg router wins outright.
        code, out, _ = self.run_http(conf, "--host", "example.com",
                                     "--path", "/search?mobile")
        self.assertEqual(code, 0)
        self.assertIn("valueless@file", out)
        code, out, _ = self.run_http(conf, "--host", "example.com",
                                     "--path", "/search?mobile=true")
        self.assertEqual(code, 0)
        self.assertIn("valued@file", out)

    def test_clientip_cidr_both_directions(self):
        cfg = http_conf([router("web", "ClientIP(`192.168.1.0/24`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "example.com",
                                     "--client-ip", "192.168.1.50")
        self.assertEqual(code, 0)
        code, _o, _e = self.run_http(conf, "--host", "example.com",
                                     "--client-ip", "192.168.2.50")
        self.assertEqual(code, 1)
        code, out, _ = self.run_http(conf, "--host", "example.com")
        self.assertEqual(code, 2)
        self.assertIn("UNKNOWN", out)
        self.assertIn("--client-ip", out)

    def test_or_with_unknown_disjunct(self):
        cfg = http_conf([router(
            "web", "Host(`a.example.com`) || Method(`POST`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "b.example.com")
        self.assertEqual(code, 2)  # UNKNOWN, not FALSE
        self.assertIn("UNKNOWN", out)
        code, out, _ = self.run_http(conf, "--host", "b.example.com",
                                     "--method", "POST")
        self.assertEqual(code, 0)


# ---------------------------------------------------------------- BG4

class TestBG4Priority(TraefikCase):
    def test_docs_34_vs_26(self):
        cfg = http_conf([
            router("router-1", "HostRegexp(`[a-z]+\\.traefik\\.com`)"),
            router("router-2", "Host(`foobar.traefik.com`)"),
        ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "foobar.traefik.com")
        self.assertEqual(code, 0)
        self.assertIn("router-1@file", out)
        self.assertIn("priority 34", out)

    def test_double_wildcard_priority_20(self):
        cfg = http_conf([
            router("exact", "Host(`foo.example.com`)"),
            router("one", "Host(`*.example.com`)"),
            router("multi", "Host(`**.example.com`)"),
        ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_cli("--list-routers", "--conf", conf)
        self.assertIn("exact@file", out)
        self.assertIn("(priority 23)", out)
        self.assertIn("(priority 21)", out)
        self.assertIn("(priority 20)", out)

    def test_explicit_priority_overrides_length(self):
        cfg = http_conf([
            router("short", "Host(`a.com`)",
                   extra="      priority: 100"),
            router("long", "Host(`averylonghostname.example.com`)"),
        ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("short@file", out)

    def test_priority_zero_falls_back_to_length(self):
        cfg = http_conf([
            router("short", "Host(`a.com`)",
                   extra="      priority: 0"),
            router("long", "Host(`averylonghostname.example.com`)"),
        ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_cli("--list-routers", "--conf", conf)
        self.assertIn("short@file", out)
        self.assertIn("(priority 13)", out)  # len("Host(`a.com`)") = 13

    def test_negative_priority_sinks(self):
        cfg = http_conf([
            router("neg", "Host(`a.com`)",
                   extra="      priority: -50"),
            router("plain", "Host(`a.com`)"),
        ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        # both match; the plain one (priority 13) outranks -50
        self.assertIn("plain@file", out)

    def test_whitespace_counts_toward_length(self):
        cfg = http_conf([
            router("spaced", "Host(`a.com`) && Path(`/x`)"),
            router("tight", "Host(`a.com`)&&Path(`/x`)"),
        ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_cli("--list-routers", "--conf", conf)
        # spaced rule is 2 chars longer (spaces around &&)
        self.assertIn("spaced@file", out)
        self.assertIn("(priority 27)", out)
        self.assertIn("(priority 25)", out)

    def test_same_priority_tie_by_name(self):
        cfg = http_conf([
            router("b-router", "Host(`a.com`)"),
            router("a-router", "Host(`b.com`)"),
        ])
        conf = self.conf_with(cfg)
        # both rules are length 13; query host b.com: only a-router TRUE
        code, out, _ = self.run_http(conf, "--host", "b.com")
        self.assertEqual(code, 0)
        self.assertIn("a-router@file", out)
        # identical rules, both TRUE: tie broken by name ascending
        cfg2 = http_conf([
            router("b-router", "Host(`a.com`)"),
            router("a-router", "Host(`a.com`)"),
        ])
        conf2 = self.conf_with(cfg2)
        code, out, _ = self.run_http(conf2, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("a-router@file", out)
        self.assertIn("[same-priority-tie-name-order]", out)

    def test_priority_above_max_is_fatal(self):
        cfg = http_conf([
            router("web", "Host(`a.com`)",
                   extra="      priority: 9223372036854775807"),
        ])
        conf = self.conf_with(cfg)
        code, _o, err = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 2)
        self.assertIn("exceeds the user maximum", err)


# ---------------------------------------------------------------- BG5

class TestBG5EntrypointsTLS(TraefikCase):
    STATIC_WEB = ("entryPoints:\n  web:\n    address: ':80'\n"
                  "  websecure:\n    address: ':443'\n")

    def test_router_on_web_does_not_match_websecure(self):
        cfg = http_conf([router("web", "Host(`a.com`)",
                                extra="      entryPoints:\n        - web")])
        conf = self.conf_with(cfg)
        code, _o, _e = self.run_http(conf, "--host", "a.com",
                                     "--entrypoint", "websecure")
        self.assertEqual(code, 1)

    def test_router_without_list_matches_any_entrypoint(self):
        cfg = http_conf([router("web", "Host(`a.com`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com",
                                     "--entrypoint", "websecure")
        self.assertEqual(code, 0)
        self.assertIn("web@file", out)

    def test_no_entrypoint_flag_listed_router_unknown(self):
        cfg = http_conf([router("web", "Host(`a.com`)",
                                extra="      entryPoints:\n        - web")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 2)
        self.assertIn("UNKNOWN", out)
        self.assertIn("--entrypoint", out)

    def test_tls_router_does_not_match_no_tls(self):
        cfg = http_conf([router("web", "Host(`a.com`)",
                                extra="      tls: {}")])
        conf = self.conf_with(cfg)
        code, _o, _e = self.run_http(conf, "--host", "a.com", "--no-tls")
        self.assertEqual(code, 1)
        code, out, _ = self.run_http(conf, "--host", "a.com", "--tls")
        self.assertEqual(code, 0)

    def test_entrypoint_tls_makes_router_https_only(self):
        static = ("entryPoints:\n  websecure:\n    address: ':443'\n"
                  "    http:\n      tls: {}\n")
        cfg = http_conf([router("web", "Host(`a.com`)",
                                extra="      entryPoints:\n        - websecure")])
        conf = self.confdir({"app.yml": cfg})
        spath = self.write(static, name="traefik.yml")
        code, _o, _e = self.run_http(conf, "--host", "a.com",
                                     "--entrypoint", "websecure",
                                     "--no-tls", "--static", spath)
        self.assertEqual(code, 1)
        code, out, _ = self.run_http(conf, "--host", "a.com",
                                     "--entrypoint", "websecure",
                                     "--tls", "--static", spath)
        self.assertEqual(code, 0)

    def test_router_tls_replaces_entrypoint_tls(self):
        # entrypoint websecure has http.tls with a certResolver; the
        # router defines its own tls (empty) which replaces it. The
        # router is still HTTPS-only, but the verdict must not claim
        # the entrypoint's certResolver applies.
        static = ("entryPoints:\n  websecure:\n    address: ':443'\n"
                  "    http:\n      tls:\n        certResolver: le\n")
        cfg = http_conf([router("web", "Host(`a.com`)",
                                extra="      entryPoints:\n        - websecure\n"
                                      "      tls: {}")])
        conf = self.confdir({"app.yml": cfg})
        spath = self.write(static, name="traefik.yml")
        code, out, _ = self.run_http(conf, "--host", "a.com",
                                     "--entrypoint", "websecure",
                                     "--tls", "--static", spath)
        self.assertEqual(code, 0)
        self.assertNotIn("certResolver `le`", out)
        self.assertIn("[default-cert-would-serve]", out)

    def test_entrypoint_redirection(self):
        static = ("entryPoints:\n  web:\n    address: ':80'\n"
                  "    http:\n      redirections:\n        entryPoint:\n"
                  "          to: websecure\n          scheme: https\n"
                  "          permanent: true\n"
                  "  websecure:\n    address: ':443'\n")
        cfg = http_conf([router("web", "Host(`a.com`)")])
        conf = self.confdir({"app.yml": cfg})
        spath = self.write(static, name="traefik.yml")
        code, out, _ = self.run_http(conf, "--host", "a.com",
                                     "--entrypoint", "web",
                                     "--static", spath)
        self.assertEqual(code, 0)
        self.assertIn("VERDICT REDIRECT", out)
        self.assertIn("websecure", out)
        self.assertIn("301", out)
        # ACME challenge path is exempt from the redirect
        code, out, _ = self.run_http(
            conf, "--host", "a.com", "--entrypoint", "web",
            "--path", "/.well-known/acme-challenge/token",
            "--static", spath)
        self.assertEqual(code, 0)
        self.assertIn("VERDICT MATCH", out)


# ---------------------------------------------------------------- BG6

class TestBG6TCP(TraefikCase):
    TCP_CONF = ("tcp:\n  routers:\n    db:\n"
                "      rule: \"HostSNI(`db.example.com`)\"\n"
                "      service: db-svc\n"
                "      entryPoints:\n        - websecure\n"
                "      tls:\n        passthrough: true\n"
                "  services:\n    db-svc:\n      loadBalancer:\n"
                "        servers:\n          - address: \"10.0.0.2:5432\"\n")

    def test_hostsni_matches(self):
        conf = self.conf_with(self.TCP_CONF, name="tcp.yml")
        code, out, _ = self.run_cli(
            "tcp", "--conf", conf, "--sni", "db.example.com",
            "--tls", "--entrypoint", "websecure")
        self.assertEqual(code, 0)
        self.assertIn("db@file", out)
        self.assertIn("tls=passthrough", out)

    def test_hostsni_star_matches_non_tls(self):
        cfg = ("tcp:\n  routers:\n    catch:\n"
               "      rule: \"HostSNI(`*`)\"\n"
               "      service: plain-svc\n"
               "  services:\n    plain-svc:\n      loadBalancer:\n"
               "        servers:\n          - address: \"10.0.0.3:80\"\n")
        conf = self.conf_with(cfg, name="tcp.yml")
        code, out, _ = self.run_cli("tcp", "--conf", conf, "--no-tls")
        self.assertEqual(code, 0)
        self.assertIn("catch@file", out)

    def test_hostsni_single_wildcard_one_label(self):
        cfg = ("tcp:\n  routers:\n    wild:\n"
               "      rule: \"HostSNI(`*.example.com`)\"\n"
               "      service: svc\n"
               "      tls: {}\n"
               "  services:\n    svc:\n      loadBalancer:\n"
               "        servers:\n          - address: \"10.0.0.3:443\"\n")
        conf = self.conf_with(cfg, name="tcp.yml")
        code, _o, _e = self.run_cli(
            "tcp", "--conf", conf, "--sni", "foo.bar.example.com",
            "--tls")
        self.assertEqual(code, 1)
        code, out, _ = self.run_cli(
            "tcp", "--conf", conf, "--sni", "foo.example.com", "--tls")
        self.assertEqual(code, 0)

    def test_alpn_matches(self):
        cfg = ("tcp:\n  routers:\n    h2:\n"
               "      rule: \"ALPN(`h2`)\"\n"
               "      service: svc\n"
               "  services:\n    svc:\n      loadBalancer:\n"
               "        servers:\n          - address: \"10.0.0.3:443\"\n")
        conf = self.conf_with(cfg, name="tcp.yml")
        code, out, _ = self.run_cli("tcp", "--conf", conf,
                                    "--alpn", "h2")
        self.assertEqual(code, 0)
        self.assertIn("h2@file", out)

    def test_alpn_acme_tls_fatal(self):
        cfg = ("tcp:\n  routers:\n    bad:\n"
               "      rule: \"ALPN(`ACME-TLS/1`)\"\n"
               "      service: svc\n"
               "  services:\n    svc:\n      loadBalancer:\n"
               "        servers:\n          - address: \"10.0.0.3:443\"\n")
        conf = self.conf_with(cfg, name="tcp.yml")
        code, _o, err = self.run_cli("tcp", "--conf", conf,
                                     "--alpn", "ACME-TLS/1")
        self.assertEqual(code, 2)
        self.assertIn("ACME-TLS/1", err)

    def test_tcp_router_blocks_http_verdict(self):
        cfg = self.TCP_CONF + http_conf(
            [router("web", "Host(`db.example.com`)",
                    extra="      entryPoints:\n        - websecure")])
        conf = self.conf_with(cfg, name="both.yml")
        code, out, _ = self.run_http(
            conf, "--host", "db.example.com", "--entrypoint", "websecure",
            "--tls")
        self.assertEqual(code, 2)
        self.assertIn("UNKNOWN", out)
        self.assertIn("[tcp-router-may-claim-connection]", out)
        # provably non-TLS: the TLS TCP router cannot claim it
        code, out, _ = self.run_http(
            conf, "--host", "db.example.com", "--entrypoint", "websecure",
            "--no-tls")
        self.assertEqual(code, 0)
        self.assertIn("web@file", out)

    def test_tcp_passthrough_reported(self):
        conf = self.conf_with(self.TCP_CONF, name="tcp.yml")
        code, out, _ = self.run_cli(
            "tcp", "--conf", conf, "--sni", "db.example.com",
            "--tls", "--entrypoint", "websecure")
        self.assertIn("tls=passthrough", out)
        self.assertIn("[passthrough-cert-backend]", out)


# ---------------------------------------------------------------- BG7

class TestBG7PathNormalization(TraefikCase):
    def test_dot_segments_cleaned(self):
        cfg = http_conf([router("web", "Path(`/a/b`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "example.com",
                                     "--path", "/a/./b")
        self.assertEqual(code, 0)
        self.assertIn("normalized from /a/./b", out)

    def test_dotdot_resolves(self):
        cfg = http_conf([router("web", "Path(`/b`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "example.com",
                                     "--path", "/a/../b")
        self.assertEqual(code, 0)

    def test_duplicate_slashes_collapse(self):
        cfg = http_conf([router("web", "Path(`/a/b`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "example.com",
                                     "--path", "//a//b")
        self.assertEqual(code, 0)

    def test_encoded_slash_does_not_match(self):
        cfg = http_conf([router("web", "PathPrefix(`/foo/bar`)")])
        conf = self.conf_with(cfg)
        code, _o, _e = self.run_http(conf, "--host", "example.com",
                                     "--path", "/foo%2Fbar")
        self.assertEqual(code, 1)

    def test_query_string_split_and_merged(self):
        cfg = http_conf([router("web",
                                "Host(`a.com`) && Query(`q`, `x`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com",
                                     "--path", "/search?q=x")
        self.assertEqual(code, 0)
        # explicit --query wins over the --path query string
        code, out, _ = self.run_http(conf, "--host", "a.com",
                                     "--path", "/search?q=y",
                                     "--query", "q=x")
        self.assertEqual(code, 0)


# ---------------------------------------------------------------- BG8

class TestBG8Middlewares(TraefikCase):
    MW_CONF = http_conf(
        [router("web", "Host(`a.com`) && PathPrefix(`/api`)",
                extra="      middlewares:\n        - auth-chain\n"
                      "        - strip-api")],
        middlewares=[
            "    strip-api:",
            "      stripPrefix:",
            "        prefixes:",
            "          - /api",
            "    auth-chain:",
            "      chain:",
            "        middlewares:",
            "          - basic",
            "          - add-hdr",
            "    basic:",
            "      basicAuth:",
            "        users:",
            '          - "user:hash"',
            "    add-hdr:",
            "      headers:",
            "        customRequestHeaders:",
            "          X-Added: yes",
        ])

    def test_chain_order_and_expansion(self):
        conf = self.conf_with(self.MW_CONF)
        code, out, _ = self.run_http(conf, "--host", "a.com",
                                     "--path", "/api/users")
        self.assertEqual(code, 0)
        self.assertIn("basic (BasicAuth)", out)
        self.assertIn("add-hdr (Headers)", out)
        self.assertIn("strip-api (StripPrefix)", out)
        # declaration order: chain members first, then strip-api
        self.assertLess(out.index("basic (BasicAuth)"),
                        out.index("strip-api (StripPrefix)"))

    def test_chain_cycle_is_fatal(self):
        cfg = http_conf(
            [router("web", "Host(`a.com`)",
                    extra="      middlewares:\n        - c1")],
            middlewares=[
                "    c1:",
                "      chain:",
                "        middlewares:",
                "          - c2",
                "    c2:",
                "      chain:",
                "        middlewares:",
                "          - c1",
            ])
        conf = self.conf_with(cfg)
        code, _o, err = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 2)
        self.assertIn("chain cycle", err)

    def test_stripprefix_rewrites_path(self):
        conf = self.conf_with(self.MW_CONF)
        code, out, _ = self.run_http(conf, "--host", "a.com",
                                     "--path", "/api/users")
        self.assertEqual(code, 0)
        self.assertIn("path rewrite: strip-api /api/users → /users", out)
        self.assertIn("service sees path: /users", out)

    def test_replacepathregex_rewrites(self):
        cfg = http_conf(
            [router("web", "Host(`a.com`)",
                    extra="      middlewares:\n        - repl")],
            middlewares=[
                "    repl:",
                "      replacePathRegex:",
                "        regex: \"^/old/(.*)\"",
                "        replacement: \"/new/$1\"",
            ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com",
                                     "--path", "/old/thing")
        self.assertEqual(code, 0)
        self.assertIn("service sees path: /new/thing", out)

    def test_redirectscheme_classified_and_flagged(self):
        cfg = http_conf(
            [router("web", "Host(`a.com`)",
                    extra="      middlewares:\n        - redir")],
            middlewares=[
                "    redir:",
                "      redirectScheme:",
                "        scheme: https",
                "        permanent: true",
            ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("redir (RedirectScheme)", out)
        self.assertIn("[outcome-changing]", out)
        self.assertIn("[redirect-middleware]", out)

    def test_ipallowlist_rejects_outside_ip(self):
        cfg = http_conf(
            [router("web", "Host(`a.com`)",
                    extra="      middlewares:\n        - allow")],
            middlewares=[
                "    allow:",
                "      ipAllowList:",
                "        sourceRange:",
                "          - 10.0.0.0/8",
            ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com",
                                     "--client-ip", "192.168.1.1")
        self.assertEqual(code, 0)  # router won; middleware would reject
        self.assertIn("[ipallowlist-would-reject]", out)
        code, out, _ = self.run_http(conf, "--host", "a.com",
                                     "--client-ip", "10.1.2.3")
        self.assertEqual(code, 0)
        self.assertNotIn("[ipallowlist-would-reject]", out)

    def test_service_middlewares_second_chain(self):
        services = [svc("app", extra="      middlewares:\n        - svc-mw")]
        cfg = http_conf(
            [router("web", "Host(`a.com`)")],
            services=services,
            middlewares=[
                "    svc-mw:",
                "      compress: {}",
            ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("service: svc-mw (Compress)", out)
        self.assertIn("[service-middlewares-require-3.7+]", out)

    def test_plugin_middleware_opaque(self):
        cfg = http_conf(
            [router("web", "Host(`a.com`)",
                    extra="      middlewares:\n        - plug")],
            middlewares=[
                "    plug:",
                "      myCustomPlugin:",
                "        setting: true",
            ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("[unknown-middleware-type]", out)
        self.assertIn("[response-only / opaque]", out)

    def test_undefined_middleware_fatal(self):
        cfg = http_conf(
            [router("web", "Host(`a.com`)",
                    extra="      middlewares:\n        - nope")])
        conf = self.conf_with(cfg)
        code, _o, err = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 2)
        self.assertIn("undefined middleware", err)


# ---------------------------------------------------------------- BG9

class TestBG9Services(TraefikCase):
    def test_service_lists_servers(self):
        conf = self.conf_with(http_conf(
            [router("web", "Host(`a.com`)")]))
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("http://10.0.0.1:8080", out)

    def test_no_servers_means_503_flag(self):
        services = ["    app:", "      loadBalancer:",
                    "        servers: []"]
        cfg = http_conf([router("web", "Host(`a.com`)")],
                        services=services)
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("[service-has-no-servers]", out)

    def test_undefined_service_fatal(self):
        cfg = http_conf([router("web", "Host(`a.com`)",
                                service="ghost")])
        conf = self.conf_with(cfg)
        code, _o, err = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 2)
        self.assertIn("undefined service", err)

    def test_weighted_reports_weights(self):
        services = [
            "    app:",
            "      weighted:",
            "        services:",
            "          - name: blue",
            "            weight: 3",
            "          - name: green",
            "            weight: 1",
            "    blue:",
            "      loadBalancer:",
            "        servers:",
            '          - url: "http://10.0.0.1:8080"',
            "    green:",
            "      loadBalancer:",
            "        servers:",
            '          - url: "http://10.0.0.2:8080"',
        ]
        cfg = http_conf([router("web", "Host(`a.com`)")],
                        services=services)
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("(weighted)", out)
        self.assertIn("blue (weight 3)", out)
        self.assertIn("green (weight 1)", out)
        self.assertIn("[weighted-routing-runtime]", out)

    def test_weighted_single_member_effective(self):
        services = [
            "    app:",
            "      weighted:",
            "        services:",
            "          - name: blue",
            "            weight: 1",
            "          - name: green",
            "            weight: 0",
            "    blue:",
            "      loadBalancer:",
            "        servers:",
            '          - url: "http://10.0.0.1:8080"',
            "    green:",
            "      loadBalancer:",
            "        servers:",
            '          - url: "http://10.0.0.2:8080"',
        ]
        cfg = http_conf([router("web", "Host(`a.com`)")],
                        services=services)
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("[weighted-single-member]", out)
        self.assertIn("effective service: blue", out)

    def test_mirroring_copy_banner(self):
        services = [
            "    app:",
            "      mirroring:",
            "        service: blue",
            "        mirrors:",
            "          - name: green",
            "            percent: 10",
            "    blue:",
            "      loadBalancer:",
            "        servers:",
            '          - url: "http://10.0.0.1:8080"',
            "    green:",
            "      loadBalancer:",
            "        servers:",
            '          - url: "http://10.0.0.2:8080"',
        ]
        cfg = http_conf([router("web", "Host(`a.com`)")],
                        services=services)
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("(mirroring)", out)
        self.assertIn("[mirroring-copy]", out)

    def test_failover_fallback_banner(self):
        services = [
            "    app:",
            "      failover:",
            "        service: blue",
            "        fallback: green",
            "    blue:",
            "      loadBalancer:",
            "        servers:",
            '          - url: "http://10.0.0.1:8080"',
            "    green:",
            "      loadBalancer:",
            "        servers:",
            '          - url: "http://10.0.0.2:8080"',
        ]
        cfg = http_conf([router("web", "Host(`a.com`)")],
                        services=services)
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("(failover)", out)
        self.assertIn("[failover-on-health-runtime]", out)


# --------------------------------------------------------------- BG10

class TestBG10NoMatchCatchAllMultiLayer(TraefikCase):
    def test_no_match_exit_1(self):
        conf = self.conf_with(http_conf(
            [router("web", "Host(`a.com`)")]))
        code, out, _ = self.run_http(conf, "--host", "z.com")
        self.assertEqual(code, 1)
        self.assertIn("NO-MATCH", out)
        self.assertIn("404", out)

    def test_catch_all_wins_only_when_nothing_else(self):
        cfg = http_conf([
            router("web", "Host(`a.com`)"),
            router("catch", "Host(`*`)",
                   extra="      priority: -100"),
        ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("web@file", out)
        code, out, _ = self.run_http(conf, "--host", "anything.else")
        self.assertEqual(code, 0)
        self.assertIn("catch@file", out)

    def test_catch_all_to_serverless_converts_404_to_503(self):
        services = [svc("app", servers=[])]
        cfg = http_conf([
            router("catch", "Host(`*`)",
                   extra="      priority: -100"),
        ], services=services)
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "anything.else")
        self.assertEqual(code, 0)
        self.assertIn("[catchall-converts-404-to-503]", out)

    def test_parentrefs_excluded_and_unknown_when_matching(self):
        cfg = http_conf([
            router("parent", "Host(`a.com`)"),
            router("child", "Host(`a.com`) && PathPrefix(`/kid`)",
                   extra="      parentRefs:\n        - parent"),
        ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com",
                                     "--path", "/kid/x")
        self.assertEqual(code, 2)
        self.assertIn("UNKNOWN", out)
        self.assertIn("[multi-layer-routing]", out)
        self.assertIn("[parentRefs-requires-3.6+]", out)
        # a request the child cannot match stays decidable
        code, out, _ = self.run_http(conf, "--host", "a.com",
                                     "--path", "/other")
        self.assertEqual(code, 0)
        self.assertIn("parent@file", out)

    def test_duplicate_router_last_file_wins(self):
        first = http_conf([router("web", "Host(`a.com`)")])
        second = http_conf([router("web", "Host(`b.com`)")])
        conf = self.confdir({"a.yml": first, "b.yml": second})
        code, out, _ = self.run_http(conf, "--host", "b.com")
        self.assertEqual(code, 0)
        self.assertIn("web@file", out)
        self.assertIn("[duplicate-router-shadowed]", out)
        code, _o, _e = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 1)

    def test_shadowed_router_finding(self):
        cfg = http_conf([
            router("narrow", "Host(`x.com`)"),
            router("broad", "Host(`x.com`) && PathPrefix(`/`)"),
        ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "x.com",
                                     "--path", "/anything")
        self.assertEqual(code, 0)
        self.assertIn("[shadowed-by]", out)
        self.assertIn("narrow", out)


# --------------------------------------------------------------- BG11

class TestBG11OutputInventoryExitCodes(TraefikCase):
    def test_text_json_agree(self):
        cfg = http_conf([router("web", "Host(`a.com`)")])
        conf = self.conf_with(cfg)
        for args, expect in (
                (("--host", "a.com"), "MATCH"),
                (("--host", "z.com"), "NO-MATCH"),
                (("--host", "a.com", "--method", "POST"), "MATCH")):
            code, tout, _ = self.run_http(conf, *args)
            code2, jout, _ = self.run_http(conf, "--json", *args)
            self.assertEqual(code, code2)
            doc = json.loads(jout)
            self.assertEqual(doc["verdict"], expect)
            self.assertIn("VERDICT %s" % expect, tout)
        # UNKNOWN fixture: Method term with no --method
        cfg2 = http_conf([router("web", "Method(`POST`)")])
        conf2 = self.conf_with(cfg2)
        code, tout, _ = self.run_http(conf2, "--host", "a.com")
        code2, jout, _ = self.run_http(conf2, "--json", "--host", "a.com")
        self.assertEqual(code, 2)
        self.assertEqual(code2, 2)
        self.assertEqual(json.loads(jout)["verdict"], "UNKNOWN")
        self.assertIn("VERDICT UNKNOWN", tout)

    def test_list_routers_priorities(self):
        cfg = http_conf([
            router("router-1", "HostRegexp(`[a-z]+\\.traefik\\.com`)"),
            router("router-2", "Host(`foobar.traefik.com`)"),
        ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_cli("--list-routers", "--conf", conf)
        self.assertEqual(code, 0)
        self.assertIn("(priority 34)", out)
        self.assertIn("(priority 26)", out)

    def test_list_services(self):
        conf = self.conf_with(http_conf(
            [router("web", "Host(`a.com`)")]))
        code, out, _ = self.run_cli("--list-services", "--conf", conf)
        self.assertEqual(code, 0)
        self.assertIn("app@file", out)
        self.assertIn("loadBalancer", out)
        self.assertIn("http://10.0.0.1:8080", out)

    def test_list_middlewares_refcounts(self):
        conf = self.conf_with(TestBG8Middlewares.MW_CONF)
        code, out, _ = self.run_cli("--list-middlewares", "--conf", conf)
        self.assertEqual(code, 0)
        self.assertIn("strip-api", out)
        self.assertIn("routers: web", out)
        self.assertIn("basic", out)

    def test_exit_codes(self):
        conf = self.conf_with(http_conf(
            [router("web", "Host(`a.com`)")]))
        code, _o, _e = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        code, _o, _e = self.run_http(conf, "--host", "z.com")
        self.assertEqual(code, 1)
        code, _o, _e = self.run_http(conf, "--host", "a.com",
                                     "--method", "POST")
        # Method is not in the rule; --method is harmless here
        self.assertEqual(code, 0)
        cfg2 = http_conf([router("web", "Method(`POST`)")])
        conf2 = self.conf_with(cfg2)
        code, _o, _e = self.run_http(conf2, "--host", "a.com")
        self.assertEqual(code, 2)


# --------------------------------------------------------------- BG12

class TestBG12VersionPin(TraefikCase):
    def test_tap_middleware_v38_only(self):
        cfg = http_conf(
            [router("web", "Host(`a.com`)",
                    extra="      middlewares:\n        - tapper")],
            middlewares=[
                "    tapper:",
                "      tap: {}",
            ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("[v3.8-only]", out)

    def test_responding_timeouts_misuse_fatal(self):
        cfg = http_conf([router(
            "web", "Host(`a.com`)",
            extra="      respondingTimeouts:\n"
                  "        readTimeout: 10s\n"
                  "        writeTimeout: 5s")])
        conf = self.conf_with(cfg)
        code, _o, err = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 2)
        self.assertIn("readTimeout", err)

    def test_v2_router_flagged(self):
        cfg = http_conf([router(
            "web", "Host(`a.com`)", extra="      ruleSyntax: v2")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 0)
        self.assertIn("[v2-rule-syntax-deprecated]", out)

    def test_parentrefs_flagged_in_coverage(self):
        cfg = http_conf([
            router("parent", "Host(`a.com`)"),
            router("child", "Host(`a.com`)",
                   extra="      parentRefs:\n        - parent"),
        ])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "z.com")
        self.assertEqual(code, 1)
        self.assertIn("[parentRefs-requires-3.6+]", out)


class TestCLI(TraefikCase):
    def test_version(self):
        code, out, _ = self.run_cli("--version")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "traefikwho 1.0.0")

    def test_help_exit_zero(self):
        code, out, _ = self.run_cli("--help")
        self.assertEqual(code, 0)
        self.assertIn("traefikwho", out)

    def test_no_args_exit_2(self):
        code, _o, _e = self.run_cli()
        self.assertEqual(code, 2)

    def test_unknown_verb_exit_2(self):
        code, _o, err = self.run_cli("bogus")
        self.assertEqual(code, 2)
        self.assertIn("unknown verb", err)

    def test_unknown_flag_exit_2(self):
        conf = self.conf_with(http_conf(
            [router("web", "Host(`a.com`)")]))
        code, _o, err = self.run_cli("http", "--conf", conf, "--nope", "x")
        self.assertEqual(code, 2)
        self.assertIn("unknown flag", err)

    def test_http_flag_on_tcp_verb_is_error(self):
        conf = self.conf_with(http_conf(
            [router("web", "Host(`a.com`)")]))
        code, _o, err = self.run_cli("tcp", "--conf", conf,
                                     "--host", "a.com")
        self.assertEqual(code, 2)
        self.assertIn("unknown flag", err)

    def test_quiet_prints_verdict_line_only(self):
        conf = self.conf_with(http_conf(
            [router("web", "Host(`a.com`)")]))
        code, out, _ = self.run_http(conf, "--host", "a.com", "--quiet")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip().count("\n"), 0)
        self.assertIn("VERDICT MATCH", out)

    def test_cross_provider_service_unknown(self):
        cfg = http_conf([router("web", "Host(`a.com`)",
                                service="api@docker")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com")
        self.assertEqual(code, 2)
        self.assertIn("UNKNOWN", out)
        self.assertIn("[cross-provider-reference]", out)

    def test_host_port_stripped_hypothesis(self):
        cfg = http_conf([router("web", "Host(`a.com`)")])
        conf = self.conf_with(cfg)
        code, out, _ = self.run_http(conf, "--host", "a.com:8080")
        self.assertEqual(code, 0)
        self.assertIn("[host-port-stripped-hypothesis]", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)

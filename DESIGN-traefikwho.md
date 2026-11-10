# traefikwho — hazard-first design review

**Status:** BUILD APPROVED (2026-11-10).
**Question:** for a described HTTP request (or, with the `tcp`
verb, a described TLS/TCP connection), (a) which Traefik
router handles it — the winning router with file:line
provenance, the service it forwards to, and the middleware
chain that will run — or no router at all, in which case
Traefik answers `404 Not Found`; and (b) for every router
that also matched, why it lost (lower priority, entrypoint
scope, TLS scope), with the full match chain, so "the wrong
router served my request" stops being a live-curl mystery.
**Shape:** two query verbs over the file provider (static
config + dynamic YAML/TOML), plus inventory modes:

```
traefikwho http --host H [--path P] [--method M]
    [--header K=V]... [--query K=V]... [--client-ip IP]
    [--entrypoint E] [--tls | --no-tls]
    [--conf DIR] [--static FILE] [--json] [--quiet] [--version]
traefikwho tcp [--sni NAME] [--alpn PROTO] [--client-ip IP]
    [--entrypoint E] [--tls | --no-tls]
    [--conf DIR] [--static FILE] [--json] [--quiet] [--version]
traefikwho --list-routers [--kind http|tcp|all] [--conf DIR]
traefikwho --list-services [--kind http|tcp] [--conf DIR]
traefikwho --list-middlewares [--conf DIR]
```

The request is described by flags, not by a live packet:
there is no `--packet-hex` in v1, so request fields the
flags cannot express are UNKNOWN terms (TR11). One binary,
one query per run. Flags (who-family standard): `--json`,
`--quiet`, `--version`. `--conf` is the file-provider
dynamic directory (TR01); `--static` is the optional
static-configuration file (`traefik.yml`, entrypoints /
`defaultRuleSyntax` / `providers.precedence` — TR01/TR04/
TR14). A router's `rule` is evaluated as a three-valued
expression — TRUE / FALSE / UNKNOWN — because a flag the
user did not supply (no `--method`, no `--entrypoint`) is
not a fact about the request, and a rule that *could*
match on a fact not supplied must not be silently counted
as a non-match (TR12/TR13). The winner is the highest-
priority TRUE router; an UNKNOWN router that could
outrank every TRUE router makes the verdict UNKNOWN,
citing it (TR13).

**Pinned from:** Traefik reference documentation,
`doc.traefik.io`, read 2026-11-10 — HTTP Routers Rules &
Priority (master branch, rendered against the v3.7 line;
the same page is served versioned as v3.8 and v3.0 with
identical matcher/priority text), TCP Routers Rules &
Priority (master), HTTP Router reference (v3.8, which
adds `parentRefs` and per-router `respondingTimeouts` to
the v3.7 field set), TCP Router reference, EntryPoints
reference (master), File provider install + routing
references (master), v2-to-v3 migration details
(`doc.traefik.io/traefik/migrate/v2-to-v3-details/` and
v3.0), v3.4 migration notes (path normalization, rule-
syntax deprecation), Traefik Proxy 3.7 release notes
("Langres", traefik.io blog), Traefik Proxy 3.6 release
notes and multi-layer routing tutorial (traefik.io blog),
Getting Started FAQ (v2.8, the 404/503 section — the
wording is unchanged in v3), API reference (v2.5, the
endpoint table — unchanged in v3), HTTP Middleware
overview (v2.8/v2.11, the built-in table), Traefik CLI
`--help` command list (gist of `docker run traefik
--help`, corroborated by the v1.6/v1.7 Basics pages),
`traefik-config-validator` (otto-de, pkg.go.dev /
GitHub README), and the Traefik community forum threads
on TCP-before-HTTP ordering and on 404-on-`web`-only.
No `traefik` binary exists on this box (checked
2026-11-10) and no live experiments were run, so every
claim below is `[documented]` (Traefik docs / release
notes / forum text), `[docs-inferred]` (follows from a
documented rule), or `[hypothesized]` (best-supported
guess, flippable) — never `[observed]`. Fixture trees
are the only oracle, exactly as the documentation text
is the only authority. A claim that turns out wrong
must flip the design, not get quietly absorbed.

**Version pin and drift note.** Traefik is alive and
fast-moving, unlike the frozen tools on this bench:
the latest stable at read time is **v3.7.17** (Oct 31,
2026; v3.7 "Langres" went GA in May 2026), **v3.8.0-rc.1**
shipped Oct 30, 2026 and is a release candidate, not
stable; v3.0–v3.6 are end of life and v2.11 receives
security fixes only (v2.11.60, Oct 20, 2026). The
semantics below are pinned to the **v3.7 stable line**,
with v3.8-only additions (`tap` middleware, per-router
`respondingTimeouts`) noted where they land and
excluded from v1's inventory. Two recent changes
matter and are pinned where they land: v3.6 added
multi-layer routing (`parentRefs`, TR24) and v3.7
added middlewares on services (TR23) — both change
what "the middleware chain" means. The build must
treat the Traefik version as a first-class input: the
README names the pinned version, and any Traefik
release that changes a pinned rule is a design-flip
event, not silent drift. A `--traefik-version` flag is
deliberately *not* in v1: v1 pins v3.7 and refuses
configs that declare v2 syntax (TR04) rather than
trying to be a multi-version simulator.

## Thinness verdict: APPROVED, and no native holder answers the question

1. **The `traefik` CLI has no request test, in any
   version.** Its subcommands are `version`,
   `healthcheck` (calls `/ping` on a running instance),
   `storeconfig` (stores static config into a KV
   store; "Traefik will not start"), and `bug`
   [documented — v1.6/v1.7 Basics "Commands"; the same
   four commands appear in the `docker run traefik
   --help` gist]. The v3 CLI flags reference documents
   flags only. There is no `traefik test request`, no
   `--dry-run`, no config-check subcommand, no
   hypothetical-request query. `--log.level=DEBUG` makes
   a *running* Traefik narrate live routing decisions;
   it answers nothing about a config file on disk.
   The exact v3 command list is [docs-inferred] from
   the v1-era lists (open question 12) — but the
   negative claim, that no simulation subcommand
   exists, is corroborated by every version of the
   CLI reference and by the absence of any such
   command in the v3 docs.
2. **The dashboard and API are runtime-only.** The API
   "exposes a number of information through an API
   handler, such as the configuration of all routers,
   services, middlewares, etc." [documented — API
   reference, v2.5, endpoint table unchanged in v3]:
   `GET /api/http/routers` lists all HTTP routers,
   `/api/http/routers/{name}` one router,
   `/api/tcp/routers` the TCP routers — all of them
   read the *running* instance's aggregated
   configuration. None of them takes a described
   request and answers which router would handle it.
   The dashboard is the same data with a UI. Both
   require Traefik running, with the API enabled (and
   the docs warn against enabling it in production,
   since it "will expose all configuration elements").
   A file on disk is not a running instance.
3. **The only third-party validator is syntax-only.**
   `traefik-config-validator` (otto-de) is "a CLI tool
   to (syntactically) validate your Traefik
   configuration files", pre-release software, validated
   "against the following JSON schemas hosted on
   schemastore: `traefik-v2.json`,
   `traefik-v2-file-provider.json`" [documented —
   pkg.go.dev / GitHub README]. It validates YAML
   only ("Currently, only YAML configuration is
   supported"), cannot recursively scan files for
   file-provider configurations, and validates
   against the **v2** schemas. It answers "is this
   file well-formed" and nothing about which router
   a request hits. The gap holds in full, not
   narrowed to file:line.
4. **Diagnosis today is live curl + a 404.** The
   official FAQ's answer to "why is Traefik answering
   404" is a list of situations in which no router
   matched [documented — Getting Started FAQ, v2.8]:
   "A request reaching an EntryPoint that has no
   Routers", "an HTTP request reaching an EntryPoint
   that has no HTTP Router", "an HTTPS request reaching
   an EntryPoint that has no HTTPS Router", "a request
   reaching an EntryPoint that has HTTP/HTTPS Routers
   that cannot be matched". The operator's only
   diagnostic is to send the request and read the
   status code — which cannot distinguish "no router
   matched" from "the wrong router matched and its
   service 404'd", and cannot name the router that
   did match. Forum threads on 404s (e.g. "404
   responses to everything on HTTP (web)") are
   resolved by staring at rules and curling variants.
   There is no offline oracle.
5. **No plugin answers the question either.** The
   plugin catalog holds request/response middlewares
   (header validation, auth, rewriting) that run
   *inside* a matched route. A plugin cannot answer
   "which router would match" because plugins execute
   after routing, and no plugin in the catalog is a
   routing simulator. Traefik Hub (the commercial
   API gateway) adds governance, portals, and AI
   controls on top of the same router model; its
   Rules & Priority reference restates the same
   matcher/priority semantics and adds no offline
   simulator.
6. **The routing model is fully static over the file
   provider — the one provider whose input is a file.**
   Routers, services, middlewares, and TLS options
   declared in the file provider are plain data
   (TR01). The evaluation — entrypoint filter, rule
   evaluation, priority sort — is a deterministic
   function of that data plus the request (TR12/TR13/
   TR15). Nothing about the file-provider answer
   requires a running process, a network, or a
   backend. The tool is therefore a faithful
   re-implementation, not a heuristic: the same
   discipline as nginxwho/caddy who, for the proxy
   that has no `nginx -T`-style test at all.
7. **The sibling tools already cover Traefik's
   neighbours, and Traefik is the missing one.**
   nginxwho, apachewho, and caddy who answer the same
   question for the other three mainstream reverse
   proxies. Traefik is the default ingress for Docker
   / homelab / self-hosted stacks, where the config
   is split across a static file and a dynamic
   directory and routers are routinely created by
   labels and files together — the exact setting in
   which "the wrong router served my request" is the
   daily pain and the live-curl loop is the only
   diagnostic. The file-provider scope (TR01) is the
   honest v1: it answers the question for the
   configs that live in files, and banners the rest
   instead of pretending Docker labels were read.
8. **The priority rule is a trap the docs themselves
   warn about, in the docs' own example.** "In this
   case, all requests with host `foobar.traefik.com`
   will be routed through `Router-1` instead of
   `Router-2`" — because `HostRegexp(...)` (34 chars)
   outranks `Host(...)` (26 chars) [documented —
   Rules & Priority, Priority Calculation]. The
   specific host loses to the regex. That is the
   canonical traefikwho finding: the decider is the
   *longest rule*, not the most specific match, and
   only a tool that computes the lengths can show
   it. A human reading two rules does not compute
   34 vs 26.
9. **The v2→v3 syntax break makes the file unreadable
   by eye.** v3 renamed `Headers` → `Header`,
   removed `HostHeader`, made every matcher
   single-valued, stripped regexes and `{name:pattern}`
   placeholders out of `Path`/`PathPrefix`, and added
   `QueryRegexp` and `PathRegexp` [documented —
   v2-to-v3 migration details]. A config that mixes
   v2 and v3 syntax (legal, per-router, via the
   deprecated `ruleSyntax` option) cannot be read
   correctly without knowing which syntax each router
   uses — and the v2 syntax is deprecated with removal
   in the next major version. The tool pins the
   syntax per router (TR04) instead of guessing.
10. **The scope is deliberately narrow, and the narrow
    scope is the whole answer.** traefikwho does not
    run Traefik, does not talk to Docker, Kubernetes,
    Consul, or etcd, does not resolve ACME, and does
    not pick a backend server. It reads files, parses
    rules, sorts by priority, and names the winner.
    Everything it cannot decide it banners (banner
    list below). That is the same contract the
    who-family has kept everywhere else: a verdict
    with provenance, or an honest UNKNOWN.

## Pinned semantics

### Files and lines

- **Two configuration layers, and they live in
  different places.** Traefik distinguishes *static*
  (install) configuration — entrypoints, providers,
  certificate resolvers, API, log level; "Traefik
  reads it only at startup. Changes need a restart"
  — from *dynamic* (routing) configuration —
  routers, middlewares, services, TLS certificates;
  "Traefik reads it continuously and applies changes
  immediately" [documented — File provider install
  reference; corroborated by the deployn.de Traefik 3
  guide]. In the canonical file-based setup the
  static file is `traefik.yml` and the dynamic files
  live in a directory (conventionally `rules/` or
  `dynamic/`) watched by the file provider.
  v1's input is therefore two things, and the CLI
  keeps them separate: `--conf DIR` (dynamic
  directory, required) and `--static FILE` (static
  file, optional). A run with no `--static` still
  works: entrypoint names, `defaultRuleSyntax`, and
  `providers.precedence` are then UNKNOWN-or-default
  per TR01/TR04/TR14, and the coverage section says
  so on every run.
- **Static file discovery.** Traefik accepts the
  static file via `--configfile`, or by discovery:
  `traefik.yml` / `traefik.yaml` / `traefik.toml` in
  `/etc/traefik/` and the working directory
  [docs-inferred — the file provider is "the default
  format used throughout the documentation"; the
  exact discovery order is an open question, OQ-11].
  v1 does **not** auto-discover: `--static` must be
  named, or `--conf` must contain a file literally
  named `traefik.yml`/`traefik.yaml`/`traefik.toml`
  at its top level, which v1 then reads as the
  static file and excludes from the dynamic set.
  Auto-discovery of `/etc/traefik/traefik.yml` is
  deliberately refused: a tool that silently reads
  a live proxy's config while the user meant a
  staging tree is a footgun, and the family rule is
  "never a silent guess at another tree" (pfwho
  precedent).
- **Dynamic file discovery.** `providers.file.directory`
  "defines the path to the directory that contains
  the configuration files. The `filename` and
  `directory` options are mutually exclusive. It is
  recommended to use `directory`" [documented — File
  provider install reference]. `providers.file.filename`
  loads "dynamic configuration from a file";
  `providers.file.watch` (default `true`) hot-reloads
  on change [documented — install options list].
  v1 reads **every** `.yml`, `.yaml`, and `.toml`
  file in `--conf DIR`, non-recursively, in
  alphabetical (byte) order, and merges them into
  one dynamic configuration. Whether `.yaml` is
  accepted by Traefik itself is an open question
  (OQ-10): the options list says ".yml or .toml",
  but `.yaml` is near-universally used in the wild.
  v1 accepts `.yaml` and notes the acceptance in
  coverage, so a file Traefik would ignore is never
  silently treated as live — the reverse (v1
  ignoring a file Traefik reads) is the error that
  must not happen, and `.yaml` acceptance guards it.
  Subdirectories are **not** descended: Traefik's
  file provider watches the directory itself, and
  the docs describe a flat directory of files.
  A `--conf` that names a single file (not a
  directory) is accepted as the `filename` form.
- **Static file may also carry dynamic config — no,
  it may not.** Whether an `http:` section inside
  `traefik.yml` is loaded without the file provider
  pointing at the same file is unresolved in the
  docs read (OQ-11). v1's rule: the static file's
  `http:`/`tcp:`/`udp:`/`tls:` sections are
  **ignored** unless `--conf` (directory or file)
  names the same file, in which case they are read
  as dynamic config. The coverage section states
  which reading was applied. This is the one place
  v1 guesses, and it guesses in the direction that
  keeps a router visible rather than invisible.
- **YAML and TOML, both, with file:line.** Dynamic
  files are YAML or TOML; the same router may be
  declared in either. v1 parses both into one model
  and records, for every router/service/middleware/
  TLS object, the file and the line of its first key
  (YAML: the line of the mapping key; TOML: the line
  of the `[table]` header or the key line for inline
  tables). JSON is **not** a file-provider format:
  Traefik's static config accepts JSON, but the
  file provider loads `.yml`/`.toml` only
  [documented — install options list]. A `.json`
  file in `--conf DIR` is ignored with a coverage
  note, not an error — it is not a config file
  Traefik would read.
- **Duplicate keys inside one file are a config-fatal
  (exit 2).** YAML forbids duplicate mapping keys
  and TOML forbids duplicate table definitions;
  Traefik rejects such files at load. v1's parsers
  must detect duplicates (a plain `yaml.Unmarshal`
  into a map silently keeps the last — the parser
  must use a node-preserving YAML parse and reject
  duplicates explicitly). The fatal names the file
  and both lines. Duplicate *router names across
  different files* are TR25, not this finding.
- **Go templating in dynamic files.** "Go Templating
  only works with dedicated dynamic configuration
  files. Templating does not work in the Traefik main
  static configuration file" [documented — File
  routing reference]. Dynamic files may contain Go
  templates (sprig functions) evaluated at load.
  v1 does **not** evaluate templates: a file whose
  content contains `{{` outside a quoted string is
  reported as `[go-template-not-evaluated]` and any
  router whose rule (or name) depends on template
  output is UNKNOWN citing it. Evaluating templates
  would require executing user template code at
  design time; the honest answer is to refuse the
  affected routers, not to half-evaluate them.
  (A template that produces only constant text is
  still refused — v1 cannot know it is constant
  without evaluating it.)
- **What counts as a line for provenance.** A router
  is cited as `file:line` where line is the line of
  the router's name key (`my-router:` in YAML,
  `[http.routers.my-router]` in TOML). A rule's
  provenance is the router's line plus the rule's
  own line when the rule is on its own line; the
  verdict line always cites the router line, and
  the match chain cites the rule line where it
  differs. Middlewares and services cite their own
  definition lines the same way. This matches the
  family convention (keawho JSON lines, pfwho
  first-token lines) adapted to YAML/TOML mappings.
- **Comments and quoting.** YAML `#` comments and
  TOML `#` comments are stripped by the parsers and
  never shift line numbers. A rule value in YAML
  may be plain, single-quoted, or double-quoted;
  Traefik's rule grammar additionally requires
  backticks or escaped double-quotes *inside* the
  rule string for matcher arguments (TR03) — the
  YAML quoting and the rule quoting are two
  different layers, and the parser must not
  confuse them (a YAML single-quoted rule containing
  backticks is the common case).

### TR01 — Verdict scope: the file provider, and only the file provider

v1 answers the question over the merged dynamic
configuration from `--conf DIR` (plus `--static FILE`
for entrypoint names, `defaultRuleSyntax`, and
`providers.precedence`). Routers, services, middlewares,
and TLS options from any other provider — Docker
labels, Kubernetes CRD/Ingress, Gateway API, Consul,
etcd, ZooKeeper, Rancher, Nomad, ECS, HTTP provider —
are **out of scope, not approximated**: their
configuration does not exist in the files v1 reads,
and a router that exists only in Docker labels is
invisible to v1 by construction. The coverage section
of every run states the provider set consulted
(`file` only) and names the out-of-scope providers
that the static file enables, if `--static` was given
and enables any (e.g. `providers.docker: {}` in the
static file → `[docker-provider-enabled-not-read]` on
every verdict). If `--static` was not given, the run
cannot know other providers are enabled, and coverage
says so in one line: `[static-config-not-supplied]`.
This is the exact analogue of pfwho's "the file is
not the whole firewall" (PF38): the file-provider
config may not be the whole routing table, and the
tool checks for that instead of assuming it. A router
referenced with an explicit `@<provider>` suffix naming
a non-file provider (e.g. `service: api@docker`) is
UNKNOWN with `[cross-provider-reference]`; a reference
with `@file` or no suffix is resolved in the file
model (TR23). The internal provider (`@internal`:
`api@internal`, `dashboard@internal`, `ping@internal`,
`noop@internal`, `acme-http@internal`) is inventoried,
not routed (TR35).

### TR02 — Two questions, not one: HTTP requests and TCP connections

Traefik routes two different things. An **HTTP router**
matches a *request* (host, path, method, headers,
query, client IP) and forwards through middlewares to
an HTTP service. A **TCP router** matches a
*connection* (SNI, ALPN, client IP) and forwards to a
TCP service, with optional TLS termination or
passthrough. The verbs are therefore separate —
`traefikwho http ...` and `traefikwho tcp ...` — and
share nothing but the config loader and the priority
machinery. A UDP router has no rule at all (TR33):
there is no `traefikwho udp` verb in v1; a UDP router
in the config is inventoried by `--list-routers` and
bannered. The `http` verb takes `--host`, `--path`
(default `/`), `--method`, `--header K=V` (repeatable),
`--query K=V` (repeatable), `--client-ip`, `--entrypoint`,
`--tls`/`--no-tls`. The `tcp` verb takes `--sni`,
`--alpn`, `--client-ip`, `--entrypoint`, `--tls`/`--no-tls`.
Supplying an HTTP-only flag to the `tcp` verb (or vice
versa) is a usage error, not a silent ignore — the
family rule that a flag the tool cannot honour must
fail loudly. `--host` on the `http` verb is the request
`Host` header value; an IP-address host is legal and
matches `Host` rules against the IP string (TR06).

### TR03 — The rule grammar needs a real parser, not a regex

A rule is an expression over matchers joined by `&&`,
`||`, `!`, and parentheses, "with the expected
precedence rules" [documented — Rules & Priority, both
HTTP and TCP pages]. Concretely: `!` binds tightest,
then `&&`, then `||`; parentheses override. The
precedence is [documented] as "expected" but the docs
never spell out the operator table; the table above is
[docs-inferred] from the standard reading plus the
docs' own example `Host(`example.com`) || (Host(`example.org`)
&& !ALPN(`h2`))` [documented — TCP Rules & Priority],
which is only unambiguous under `&&` > `||`. v1 must
implement a tokenizer + recursive-descent parser over
the rule string, producing an AST with a node per
matcher and per operator, each node carrying the
character offset of its source span (for error
messages) — never a regex that "mostly" splits on
`&&`. The grammar hazards that force this:

- Matcher arguments are Go string literals: backtick
  (`` ` ``) or escaped double-quote (`\"`); "Single
  quotes `'` are not accepted since the values are
  Go's String Literals" [documented — Rules &
  Priority]. A rule containing a literal backtick
  inside a double-quoted argument, or a `&&` inside
  a quoted regex, must not split the expression.
- Regex matchers (`HostRegexp`, `PathRegexp`,
  `HeaderRegexp`, `QueryRegexp`, `HostSNIRegexp`)
  take Go-flavored regexps [documented]. A regex may
  contain `(`, `)`, `&&`, `||`, `!`, backticks
  (escaped), and character classes containing all of
  those. Only a tokenizer that knows it is inside a
  quoted literal can survive them.
- v2 syntax (TR04) allows `{name:pattern}` captures
  inside `HostRegexp`/`Path`/`PathPrefix` arguments
  and multi-value matchers separated by commas;
  the parser must know which syntax it is parsing
  before it tokenizes, because `{subdomain:[a-z]+}`
  is a capture in v2 and a syntax error in v3.
- Whitespace is insignificant between tokens but
  significant inside quoted literals, and it counts
  toward rule length (TR12): the parser must retain
  the raw rule string verbatim for the priority
  computation even while the AST ignores whitespace.

A rule that fails to parse is a config-fatal (exit 2)
naming the router, file:line, and the parser's error
with offset — Traefik would disable that router with
an error at load, and v1 must not silently drop it
and answer from the remaining routers. (Traefik
disables the broken router and keeps the rest; v1
is stricter — a fatal — because a dropped router
changes the winner silently, and the family rule is
that a config Traefik would partly reject must not
produce a confident verdict. This strictness is a
deliberate design choice, flagged as OQ-2.)

### TR04 — v3 syntax is the default; v2 syntax is deprecated, per-router, and dying

"In Traefik v3 a new rule syntax has been introduced
(migration guide). The `ruleSyntax` option allows
configuring the rule syntax to be used for parsing
the rule on a per-router basis" [documented — Rules &
Priority]. "The default value of the `ruleSyntax`
option is inherited from the `core.defaultRuleSyntax`
option in the install configuration (formerly known as
static configuration). By default, the `core.defaultRuleSyntax`
static option is v3, meaning that the default rule
syntax is also v3" [documented]. And: "RuleSyntax
option is deprecated and will be removed in the next
major version. Please do not use this field and
rewrite the router rules to use the v3 syntax"
[documented — Rules & Priority, warning box]. The
v3.4 migration notes repeat: "rule syntax configuration
options will be removed in the next major version.
Deprecated Options: `core.defaultRuleSyntax` (static
configuration), `ruleSyntax` (router option)"
[documented — v3.4 migration guide]. v1's syntax
resolution, in order:

1. The router's own `ruleSyntax` field, if present
   (`v2` or `v3`).
2. Else `core.defaultRuleSyntax` from `--static FILE`,
   if given.
3. Else `v3`.

A router whose resolved syntax is `v2` is parsed with
the v2 grammar and flagged `[v2-rule-syntax-deprecated]`
on every verdict it participates in; a config whose
static file sets `defaultRuleSyntax: v2` gets the same
banner once in coverage. v1 does **not** refuse v2
syntax — it is still legal in v3.7 — but it refuses
to guess: a router with no `ruleSyntax` and no static
file is v3, full stop. The v3 notable changes, all
[documented — v2-to-v3 migration details]:

- `Headers` and `HeadersRegexp` renamed to `Header`
  and `HeaderRegexp`. **Correction to the IDEA
  record:** the IDEA listed the matcher set as
  "Host/HostRegexp/Path/PathPrefix/PathRegexp/Method/
  Headers/HeadersRegexp/Query/QueryRegexp/ClientIP".
  `Headers`/`HeadersRegexp` do not exist in v3; the
  v3 names are singular. Any design or fixture using
  the plural names under v3 syntax is a config-fatal.
- `PathPrefix` no longer uses regular expressions to
  match path prefixes. `Path` and `PathPrefix` no
  longer support path parameter placeholders (e.g.
  `{id}`, `{name}`): "Routes using placeholders like
  ``Path(`/route/{id}`)`` will not match in v3
  syntax. Use `PathRegexp` instead for dynamic path
  segments."
- `QueryRegexp` has been introduced. `HeaderRegexp`,
  `HostRegexp`, `PathRegexp`, `QueryRegexp`, and
  `HostSNIRegexp` matchers now use the Go regexp
  syntax.
- All matchers now take a single value (except
  `Header`, `HeaderRegexp`, `Query`, and `QueryRegexp`
  which take two) and "should be explicitly combined
  using logical operators to mimic previous
  behavior". `Query` can take a single value, to match
  a query parameter that has no value (e.g.
  `/search?mobile`).
- `HostHeader` has been removed, use `Host` instead.
- **Correction to the IDEA record:** the IDEA's
  hazard "quoted regexes with `{name:pattern}`
  captures" describes the **v2** grammar. In v3
  there are no `{name:pattern}` captures anywhere:
  regex matchers take plain Go regexps, in which a
  named group is written `(?P<name>...)` if the
  author wants one, and `Path`/`PathPrefix` take
  literal paths only. The parser hazard in v3 is
  different — nested combinators, quoted literals
  containing operators, and `**` wildcards (TR03/
  TR06) — and the design pins that instead. A v2
  rule containing `{name:pattern}` is parsed by the
  v2 grammar, where the capture is a *match-time*
  variable binding that v1 evaluates as a plain
  regexp (the binding is never used for routing;
  only the match matters).

### TR05 — The HTTP matcher set is closed: eleven matchers, no more

[documented — Rules & Priority, matcher table]:

| Matcher | Matches |
|---|---|
| `Header(`key`, `value`)` | request contains header `key` set to `value` |
| `HeaderRegexp(`key`, `regexp`)` | header `key` matches Go `regexp` |
| `Host(`domain`)` | request host equals `domain`; `*`/`**` wildcards (TR06) |
| `HostRegexp(`regexp`)` | request host matches Go `regexp` |
| `Method(`method`)` | request method equals `method` |
| `Path(`path`)` | request path equals `path` |
| `PathPrefix(`prefix`)` | request path starts with `prefix` (TR07) |
| `PathRegexp(`regexp`)` | request path matches Go `regexp` |
| `Query(`key`, `value`)` | query parameter `key` equals `value`; one-arg form matches a valueless parameter |
| `QueryRegexp(`key`, `regexp`)` | query parameter `key` matches Go `regexp` |
| `ClientIP(`ip`)` | client IP equals `ip`; IPv4, IPv6, CIDR (TR11) |

That is the complete set for v3.7 HTTP routers. There
is no `HostHeader`, no `Headers`, no `PathStrip`
matcher (stripping is a middleware, TR22), no `Scheme`
matcher, no `Port` matcher. An unknown matcher name
in a v3 rule is a config-fatal (Traefik rejects the
router); an unknown matcher name in a v2 rule is
parsed against the v2 set (`Headers`, `HeadersRegexp`,
`HostHeader`, multi-value forms) and otherwise fatal.
Matcher names are case-sensitive: `host(`...`)` is
not `Host(`...`)` [docs-inferred — the docs use exact
PascalCase names throughout and the parser is
generated from them; flippable, OQ-3].

### TR06 — Host and HostRegexp: lowercase, punycode, wildcards, and the bare-`*` catch-all

- "These matchers do not support non-ASCII characters,
  use punycode encoded values (rfc 3492) to match such
  domains" [documented]. A `Host` value containing
  non-ASCII is a config-fatal naming the router: v1
  does not punycode-encode on the user's behalf, because
  silently rewriting the matcher's value would change
  what the router matches.
- "If no `Host` is set in the request URL (for example,
  it's an IP address), these matchers will look at the
  `Host` header" [documented]. v1's `--host` is the
  Host header value; there is no separate URL-host
  flag, and an IP host is matched as a literal string
  against `Host`/`HostRegexp` values.
- "These matchers will match the request's host in
  lowercase" [documented]. v1 lowercases `--host`
  before matching, and lowercases `Host` matcher
  values at parse time. A `HostRegexp` is **not**
  lowercased: the regexp is applied to the lowercased
  host as written, so `HostRegexp(`^EXAMPLE\.COM$`)`
  never matches and v1 emits a finding
  `[hostregexp-case-never-matches]` when a `HostRegexp`
  contains an uppercase literal outside a character
  class — a likely authoring error, not a fatal.
- Wildcards, v3 only: "A single wildcard matches
  exactly one subdomain label, a double wildcard one
  or more: `*.example.com` matches `foo.example.com`
  but not `foo.bar.example.com`, while
  `**.example.com` matches both. Neither matches
  `example.com` itself. This is only available with
  the **v3 rule syntax** (the default)"
  [documented]. A `*`/`**` wildcard in a v2-syntax
  rule is a config-fatal (v2 has no wildcard Host;
  multi-host was expressed as a comma list).
  "It should be preferred over the `HostRegexp`
  matcher as it allows attaching a TLS option and is
  more efficient" [documented] — which is why the
  wildcard form matters for TR18: a `Host` wildcard
  attaches TLS options; a `HostRegexp` does not.
- The bare-`*` exception: "As an exception to the
  rules above, a bare `*` is not treated as a subdomain
  wildcard but as a catch-all: ``Host(`*`)`` matches
  every request regardless of its host, including
  requests with no host at all. This mirrors the
  behaviour of the TCP ``HostSNI(`*`)`` matcher, so
  both stay consistent" [documented]. A bare `*` is
  therefore the catch-all router, and any rule
  containing it has the priority consequences of
  TR12 (its length is 9: `Host(`*`)`).
- Whether `Host(`example.com`)` matches a request
  whose Host header carries a port (`example.com:8080`)
  is **not stated in the docs read** and is an open
  question (OQ-4). v1's rule: the port is stripped
  before matching — `example.com:8080` matches
  `Host(`example.com`)` — [hypothesized], flagged
  `[host-port-stripped-hypothesis]` on any verdict
  where the strip changed the outcome. The hypothesis
  is isolated in one function (host normalization)
  and flips cleanly if the source says otherwise.
  A trailing dot (`example.com.`) is likewise
  [hypothesized] to be stripped; same banner, same
  function, OQ-4.
- A request with **no** host at all: only `Host(`*`)`
  matches; every other `Host`/`HostRegexp` term is
  FALSE, not UNKNOWN [documented — the bare-`*`
  exception exists precisely because other Host
  matchers need a host]. v1 has no `--no-host` flag
  in v1; the absence of `--host` means "host not
  supplied" (UNKNOWN), which is different from "no
  host" and must not be conflated (TR11).

### TR07 — Path, PathPrefix, PathRegexp: exact, prefix, and the normalization trap

- "For exact matches, use `Path` and its prefixed
  alternative `PathPrefix`, for regexp matches, use
  `PathRegexp`. Path are always starting with a `/`,
  except for `PathRegexp`" [documented]. A `Path` or
  `PathPrefix` value not starting with `/` is a
  config-fatal.
- `Path(`/products`)` matches `/products` "but neither
  `/products/shoes` nor `/products/`" [documented].
  `PathPrefix(`/products`)` matches `/products` "as
  well as everything under `/products`, such as
  `/products/shoes`, `/products/` but also
  `/products-for-sale`" [documented]. Note the last
  case: `PathPrefix` is a *string* prefix, not a
  segment prefix — `/products-for-sale` matches.
  This is the single most common authoring error in
  the wild, and the match chain (TR13) shows it.
- **Path normalization happens before matching, and
  it changed in v3.4.1.** "Starting with v3.4.1,
  incoming request paths are now automatically cleaned
  before processing" / "request paths are now
  normalized according to RFC 3986 standards" and
  "reserved characters (per RFC 3986) remain encoded
  during router rule matching to prevent routing
  ambiguity": `/foo%2Fbar` against
  ``PathPrefix(`/foo/bar`)`` matched in v3.4.0 and
  does **not** match from v3.4.1 [documented — v3.4
  migration guide, with the before/after table].
  v1 therefore normalizes `--path` before evaluation
  exactly as documented: collapse `.`/`..`
  segments and duplicate slashes per RFC 3986
  (`/a/./b` → `/a/b`, `/a/../b` → `/b`, `//` → `/`),
  and keep `%2F` (and other reserved characters)
  encoded so they never match a literal `/` in a
  `Path`/`PathPrefix` value. The normalized path is
  printed in the verdict (`path /a/b (normalized from
  /a/./b)`), so the user sees the transformation.
  Normalization details beyond the documented cases
  (e.g. `%2e` decoding, trailing-slash handling of
  the root) are [hypothesized] to follow Go's
  `path.Clean` plus the RFC 3986 reservation rule,
  OQ-5. A `--path` that is empty normalizes to `/`.
  The query string is never part of the path: v1
  splits `--path` at the first `?` and treats the
  rest as query parameters merged with `--query`
  flags (explicit `--query` wins on conflict, and
  the merge is stated in coverage).
- `PathRegexp` matches against the normalized path
  with a Go regexp, unanchored unless the author
  anchors it: ``PathRegexp(`\.(jpeg|jpg|png)$`)``
  matches any path ending in an image extension
  [documented]. Case-insensitivity is the author's
  job (`(?i)` prefix) [documented].

### TR08 — Header and HeaderRegexp: names are case-insensitive, values are not

HTTP header names are case-insensitive by RFC, and
Go's `textproto` canonicalization is what Traefik
runs on; v1 therefore matches header *names*
case-insensitively (`content-type` finds
`Content-Type`) [docs-inferred — the docs never
state it, but the implementation language (Go) and
the HTTP specification leave no other reading;
flippable, OQ-6]. Header *values* match exactly
for `Header` and by Go regexp for `HeaderRegexp`;
"Match headers case-insensitively" is shown in the
docs only via ``HeaderRegexp(`Content-Type`,
`(?i)^application/(json|yaml)$`)`` [documented] —
i.e. the author opts in with `(?i)`. v1's `--header`
flags are parsed as `K=V` on the first `=`; a flag
without `=` is a usage error. Multiple values for
the same header name (repeated `--header`) are kept
as a list; `Header(`K`, `V`)` is TRUE if **any**
value equals `V` [docs-inferred — HTTP allows
repeated headers and the docs say "containing a
header named `key` set to `value`"; OQ-6]. A `Header`
term for a header the user did not supply is
UNKNOWN, not FALSE (TR11) — unless the term is
negated (`!Header(...)`), in which case an
unsupplied header makes the negation UNKNOWN too:
three-valued logic does not let `!UNKNOWN` become
TRUE. This is the one place three-valued logic
surprises newcomers, and the test plan (BG3)
covers it explicitly.

### TR09 — Method: exact, uppercase, and unsupplied means UNKNOWN

"The `Method` matchers allows matching requests sent
based on their HTTP method" [documented], e.g.
``Method(`OPTIONS`)``. v1 compares the method
exactly as given, case-sensitively: `Method(`get`)`
does not match `GET` [hypothesized — the docs show
only uppercase methods and Go's `http.Request.Method`
preserves the wire case; OQ-7]. If `--method` is not
supplied, every `Method` term is UNKNOWN (TR11):
v1 does **not** default to `GET`, because a config
whose routers split on method (GET vs POST to
different services is common) would otherwise produce
a confident wrong answer. The `--method` default is
therefore "unsupplied", and the coverage section
says so. A `Method` value that is not a valid HTTP
token is a config-fatal.

### TR10 — Query and QueryRegexp: the parameter, its value, and its absence

- ``Query(`mobile`, `true`)`` matches
  `/search?mobile=true`; ``Query(`mobile`)`` (one
  argument) matches `/search?mobile`, "a query
  parameter `mobile` that has no value"
  [documented]. ``QueryRegexp(`mobile`, `^(true|yes)$`)``
  matches either value; ``QueryRegexp(`mobile`, `^.*$`)``
  matches "any value (including the empty value)"
  [documented].
- v1 parses `--query K=V` flags and the query string
  of `--path` into a multi-map (a key may repeat:
  `?a=1&a=2`). `Query(`k`, `v`)` is TRUE if any value
  of `k` equals `v`; `Query(`k`)` is TRUE if `k` is
  present (with or without a value — including
  `?mobile=` with an empty value, which is present
  but valueless, and therefore matches the one-arg
  form and does **not** match ``Query(`mobile`, ``)``
  unless the two-arg form with an empty value is
  given [docs-inferred, OQ-8]). Whether Traefik
  URL-decodes query values before matching, and how
  `+` is treated (`%20` vs literal `+`), is not
  stated in the docs read: v1 URL-decodes both keys
  and values (`%20` → space, `+` → space in the
  query component, per `application/x-www-form-
  urlencoded` rules) [hypothesized, OQ-8], and the
  decoded pair is printed in coverage when it
  differs from the raw input.
- A `Query` term for a key the user did not supply
  is UNKNOWN (TR11), not FALSE: the request *might*
  have had the parameter. This is what makes
  `--query` a load-bearing flag rather than a
  nicety.

### TR11 — ClientIP: the direct connection IP, never X-Forwarded-For

"It only matches the request client IP and does not
use the `X-Forwarded-For` header for matching"
[documented — Rules & Priority, ClientIP section].
v1's `--client-ip` is therefore the TCP peer address
as Traefik would see it — the address of the client,
or of the last untrusted proxy. Two consequences,
both pinned:

- If Traefik sits behind a trusted proxy, the
  *effective* client IP is what the entrypoint's
  `forwardedHeaders.trustedIPs` (or `proxyProtocol`)
  configuration produces — but the `ClientIP`
  matcher itself still does not read `X-Forwarded-For`
  [documented]. v1 takes `--client-ip` at face value
  as the already-resolved client IP and does not
  apply `trustedIPs` rewriting; if `--static` shows
  `forwardedHeaders.trustedIPs` set on the entrypoint,
  the verdict carries `[forwarded-headers-trusted]`
  and the coverage section explains that the user
  must pass the post-trust IP. PROXY protocol is
  the same: if the entrypoint enables it with
  `trustedIPs`, the peer address Traefik uses is the
  PROXY header's address, and `--client-ip` must be
  that address [docs-inferred, OQ-9].
- CIDR matching is exact network arithmetic on
  IPv4 and IPv6 (`ClientIP(`192.168.1.0/24`)`,
  `ClientIP(`fe80::/10`)` [documented]). A bare IP
  is a /32 (IPv4) or /128 (IPv6). An IPv4-mapped
  IPv6 address (`::ffff:192.168.1.1`) matches an
  IPv4 `ClientIP` term [hypothesized, OQ-9].
  A malformed IP or CIDR in a rule is a
  config-fatal. If `--client-ip` is not supplied,
  every `ClientIP` term is UNKNOWN (TR11/TR13).
- The same matcher exists for TCP routers (TR16/
  TR17) with the same semantics: the connection's
  client IP.

### TR12 — Priority: the rule length, exactly, with the `**` refinement

"To avoid path overlap, routes are sorted, by default,
in descending order using rules length. The priority
is directly equal to the length of the rule, and so
the longest length has the highest priority"
[documented — Rules & Priority, both HTTP and TCP].
The worked examples pin the arithmetic:

- ``HostRegexp(`[a-z]+\.traefik\.com`)`` → 34;
  ``Host(`foobar.traefik.com`)`` → 26 — so the
  regex router wins for `foobar.traefik.com`
  [documented].
- ``Host(`foo.example.com`)`` → 23,
  ``Host(`*.example.com`)`` → 21, and
  ``Host(`**.example.com`)`` → 20 — "The stars of a
  double wildcard host do not count toward this
  length, so that it always ranks below the single
  wildcard and the exact hosts it covers"
  [documented].

Counting the first example by hand confirms the
unit: `Host(`foo.example.com`)` is 4 (`Host`) + 1
(`(`) + 1 (backtick) + 15 (`foo.example.com`) + 1
(backtick) + 1 (`)`) = 23. The length is therefore
the length of the rule string **as written in the
config file**, in characters (bytes — the rules are
ASCII by the punycode rule, TR06), including
parentheses, backticks, quotes, operators, and
whitespace, with exactly one adjustment: each `**`
inside a `Host`/`HostSNI` wildcard contributes 0
instead of 2, i.e. subtract 2 per `**` occurrence
[documented by the 23/21/20 example]. Whitespace
counts: `Host(`a`) && Path(`/b`)` is longer than
`Host(`a`)&&Path(`/b`)` by 2, and the two rules
therefore have different priorities [docs-inferred
from "directly equal to the length of the rule";
the docs never discuss whitespace, OQ-3]. A
`priority: 0` is ignored ("`priority: 0` means that
the default rules length sorting is used")
[documented]; a negative priority "is allowed and
can be used to push a route below the default
computed priority" [documented]. Explicit `priority`
overrides the computed length entirely. The maximum
user-defined priority is `(MaxInt32 - 1000)` =
`2147482647` on 32-bit platforms and
`(MaxInt64 - 1000)` = `9223372036854774807` on
64-bit [documented]; a larger value is a
config-fatal. Traefik "reserves a range of
priorities for its internal routers" [documented]
(TR35). v1 prints the computed priority for every
router in `--list-routers` and in the match chain,
so the 34-vs-26 trap is visible without arithmetic.

### TR13 — Evaluation: three-valued logic, then the sort, then the winner

The evaluation order is: (1) entrypoint filter
(TR15) and TLS scope (TR17) as three-valued terms;
(2) rule evaluation to TRUE / FALSE / UNKNOWN;
(3) sort the TRUE routers by priority descending;
(4) the first TRUE router wins. The UNKNOWN
handling is the design's core honesty rule:

- A rule evaluates TRUE only if every term needed
  for its value is known and the boolean combination
  yields true. It evaluates FALSE only if the known
  terms already force false (e.g. `Host(`a.com`)`
  with `--host b.com` is FALSE regardless of any
  other term, by `&&`-short-circuit over known
  falsity — but `Host(`a.com`) || Method(`POST`)`
  with `--host b.com` and no `--method` is UNKNOWN,
  because the second disjunct could still be true).
  Otherwise it is UNKNOWN. Negation follows
  Kleene logic: `!TRUE` = FALSE, `!FALSE` = TRUE,
  `!UNKNOWN` = UNKNOWN.
- Let U be the set of UNKNOWN routers and T the set
  of TRUE routers. If T is non-empty and the
  highest-priority member of T has a strictly
  greater priority than every member of U, that
  router wins — no UNKNOWN router could outrank it.
  Otherwise the verdict is UNKNOWN, citing every
  UNKNOWN router whose priority is >= the best TRUE
  router's priority (or all of U if T is empty),
  and naming the exact flag that would resolve each
  one (`--method`, `--header X`, `--entrypoint`,
  `--client-ip`, `--query`). The output tells the
  user what to supply; it never guesses.
- Priority ties among TRUE routers are TR14's
  problem; ties involving UNKNOWN routers are
  UNKNOWN, never resolved by the tie-break, because
  the tie-break is itself [hypothesized] (TR14).
- The match chain lists every router in priority
  order with its evaluated value, its priority, and
  the term-level reason (which matcher was FALSE, or
  which term was UNKNOWN). A FALSE router's chain
  entry names the deciding term; an UNKNOWN router's
  entry names the missing flag. This is the whole
  diagnostic: the user sees not only the winner but
  every router that could have won and why it did
  not.

### TR14 — Priority ties: cross-provider is documented, same-provider is not

"When two routes from **different providers** share
the same numeric priority, Traefik uses the
`providers.precedence` install configuration option
to determine which route takes precedence. The
provider listed first in `precedence` wins the tie"
[documented — Rules & Priority, both HTTP and TCP].
Within the file provider alone there is only one
provider, so `providers.precedence` never fires in
v1's model — but it is read from `--static` when
present and recorded in coverage, because a future
multi-provider v2 will need it, and because a
static file that lists `file` after another provider
is a signal the file may not be the whole table
(TR01). What the docs do **not** state is what
happens when two routers from the *same* provider
share the same numeric priority — the common case
of two identical rules, or two different rules of
equal length (e.g. `Host(`a.com`)` and
`Host(`b.com`)` are both length 13). This is an
open question (OQ-1) and the design's largest
[hypothesized] pin: **v1 breaks same-provider ties
by router name, ascending byte order**, on the
reasoning that Traefik's router store is a map
keyed by name and the sort must be deterministic
across reloads, and that name order is the only
deterministic order available from the config
alone. Every verdict decided by this tie-break
carries `[same-priority-tie-name-order]` and names
both routers and their equal priority. If the
source (or a live experiment) shows the tie-break
is instead declaration order, insertion order, or
nondeterministic, the hypothesis flips and the
verdict for tied routers becomes AMBIGUOUS — the
flip is isolated in one comparator function, and
the test plan (BG4) has fixtures ready for either
outcome. v1 does **not** emit AMBIGUOUS for ties
today, because a tool that answers AMBIGUOUS on
every duplicated rule would be useless on the
copy-paste configs that dominate homelab setups;
the banner is the honest compromise, and OQ-1
records that it is a compromise.

### TR15 — Entrypoint scoping: a router only matches on its entrypoints

"The list of entry points to which the router is
attached. If not specified, HTTP routers are
attached to all entry points" [documented — HTTP
Router reference, `entryPoints` field, default "All
entry points"]. The same holds for TCP routers
("If not specified, TCP routers will accept requests
from all defined entry points" [documented — v2.3
Routers, unchanged in v3]). Entrypoint scoping is
therefore a filter applied *before* rule evaluation:
a router whose `entryPoints` list does not contain
the request's entrypoint cannot win, whatever its
rule says. Three-valued treatment: if `--entrypoint`
is supplied and the router lists it → TRUE; if
supplied and the router lists other entrypoints →
FALSE (the router is out, cited in the chain as
`[entrypoint-excluded]`); if `--entrypoint` is not
supplied and the router lists entrypoints → UNKNOWN
(the request might have arrived there). A router
with no `entryPoints` list is TRUE on this term
always. A router naming an entrypoint that does not
exist in `--static` (or that is not defined anywhere
v1 can see) is a config-fatal naming the router and
the entrypoint [docs-inferred — Traefik errors on
unknown entrypoint references at load; flippable,
OQ-11]. Entrypoint *names* are arbitrary strings
(`web`/`websecure` are conventions, not built-ins;
the Helm chart also creates `traefik` and `metrics`
by default [documented — EntryPoints reference]):
v1 never assumes `web` exists. If `--static` is
absent, entrypoint names in routers are opaque
labels: scoping still works by name equality, but
v1 cannot know whether an entrypoint has TLS or
redirections, and says so (`[entrypoint-properties-
unknown]`).

### TR16 — TCP before HTTP on a shared entrypoint

"If both HTTP routers and TCP routers listen to the
same EntryPoint, the TCP routers will apply before
the HTTP routers. If no matching route is found for
the TCP routers, then the HTTP routers will take
over" [documented — TCP Router reference and TCP
Rules & Priority, General note]. This is load-bearing
for the `tcp` verb and for the `http` verb alike:
a `traefikwho http` query on an entrypoint that also
has TCP routers must first ask whether a TCP router
would claim the connection — and the answer depends
on facts the HTTP query does not carry (SNI, ALPN).
v1's rule: the `http` verb evaluates TCP routers on
the same entrypoint with the connection facts it has
(`--tls` implies a TLS ClientHello exists, so SNI
*may* be present but its value is UNKNOWN unless
`--sni` is also given — there is no `--sni` flag on
the `http` verb, so it is always UNKNOWN). If any
TCP router on the entrypoint evaluates TRUE or
UNKNOWN on the available facts, the HTTP verdict is
UNKNOWN citing `[tcp-router-may-claim-connection]`
and naming the TCP router — unless the TCP router
is provably FALSE (e.g. its rule is
`HostSNI(`db.example.com`)` and the request is
`--no-tls`, which makes SNI impossible and the
rule FALSE). Conversely the `tcp` verb never
consults HTTP routers: if no TCP router matches,
the connection falls through to HTTP routing, and
the `tcp` verdict is NO-MATCH with a note that HTTP
routers may still claim it (`[http-routers-may-
claim]`). This asymmetry is [documented] behaviour,
not a v1 invention. A TCP router with
``HostSNI(`*`)`` on the entrypoint claims every
connection (TR17) and therefore makes every HTTP
verdict on that entrypoint UNKNOWN unless the
connection is provably non-TLS — which is exactly
the failure mode of the forum thread "HTTP router
applied before TCP router?" (May 2023), where a
TLS-enabled TCP router silently swallowed traffic
meant for HTTP routers.

### TR17 — TCP matchers: HostSNI, HostSNIRegexp, ClientIP, ALPN

[documented — TCP Rules & Priority, matcher table]:

| Matcher | Matches |
|---|---|
| `HostSNI(`domain`)` | connection's TLS SNI equals `domain`; `*` wildcard (single-level only — no `**` for SNI) |
| `HostSNIRegexp(`regexp`)` | SNI matches Go `regexp` |
| `ClientIP(`ip`)` | client IP; IPv4, IPv6, CIDR (TR11) |
| `ALPN(`protocol`)` | connection's ALPN protocol equals `protocol` |

- "It is important to note that the Server Name
  Indication is an extension of the TLS protocol.
  Hence, only TLS routers will be able to specify a
  domain name with that rule. However, there is one
  special use case for `HostSNI` with non-TLS
  routers: when one wants a non-TLS router that
  matches all (non-TLS) requests, one should use the
  specific ``HostSNI(`*`)`` syntax" [documented].
  A `HostSNI` term on a non-TLS connection is
  therefore FALSE for any value except `*`, for
  which it is TRUE (it matches all non-TLS
  requests). A `HostSNIRegexp` term on a non-TLS
  connection is FALSE. v1's `--tls`/`--no-tls`
  flags pin this; if neither is given, a `HostSNI`
  term is UNKNOWN (the connection might be TLS)
  except `HostSNI(`*`)`, which is TRUE either way.
- "The `HostSNI` matcher supports a single-level
  wildcard prefix (`*.example.com`) to match any
  direct subdomain of `example.com`. … A wildcard
  matches exactly one subdomain label:
  `*.example.com` matches `foo.example.com` but
  not `foo.bar.example.com` or `example.com` itself.
  This is only available with the **v3 rule syntax**
  (the default)" [documented]. Note the asymmetry
  with HTTP `Host`: TCP `HostSNI` has **no `**`
  multi-level wildcard** — `**.example.com` as a
  `HostSNI` value is a config-fatal in v3 syntax
  [docs-inferred from the single-level-only text;
  OQ-3]. The priority-length `**` adjustment
  (TR12) therefore never applies to TCP rules.
- "`ALPN` … It would be a security issue to let a
  user-defined router catch the response to an ACME
  TLS challenge previously initiated by Traefik. For
  this reason, the `ALPN` matcher is not allowed to
  match the `ACME-TLS/1` protocol, and Traefik
  returns an error if this is attempted" [documented].
  v1 makes ``ALPN(`ACME-TLS/1`)`` a config-fatal.
- TCP priority is the same rule-length computation
  as HTTP (TR12), including `priority: 0` ignored
  and negative priorities allowed, and the same
  cross-provider precedence (TR14). TCP and HTTP
  priorities are **not** comparable across the two
  router kinds: "priorities only applicable for TCP
  rules with other TCP rules and http rules with
  other http rules but not mixed TCP/HTTP"
  [documented — community forum, corroborated by
  the TCP-before-HTTP ordering of TR16]. v1 never
  sorts a TCP router against an HTTP router.
- A TCP router's `tls` block has three modes, and
  the mode changes the question: no `tls` → plain
  TCP; `tls: {}` (or with options) → Traefik
  terminates TLS; `tls.passthrough: true` → Traefik
  reads SNI and forwards the still-encrypted stream.
  With passthrough, the backend — not Traefik —
  terminates TLS, and the `HostSNI` match is the
  only TLS fact Traefik uses. v1 reports the mode
  on the verdict line (`tls=terminate` /
  `tls=passthrough` / `tls=none`).

### TR18 — TLS and SNI vs Host: the router's TLS block, the entrypoint's TLS, and cert selection

- "TLS configuration for the router. When specified,
  the router will only handle HTTPS requests"
  [documented — HTTP Router reference, `tls` field].
  A router with a `tls` block therefore cannot match
  a `--no-tls` request: its TLS term is FALSE. A
  router without a `tls` block matches both HTTP and
  HTTPS requests on its entrypoints — unless the
  *entrypoint* has `http.tls` set, which enables TLS
  "on every router attached to the `entryPoint`"
  [documented — EntryPoints reference]. If the
  entrypoint has TLS and the router has no `tls`
  block, the router is HTTPS-only by inheritance
  [docs-inferred]. If the router *does* define a
  `tls` section, "Defining a router `tls` section
  (even empty, or with any field such as
  `certResolver`) replaces the entrypoint TLS
  configuration for that router (no merge)"
  [documented — EntryPoints reference]. There is no
  partial merge to model: router-`tls` replaces
  entrypoint-`tls` wholesale.
- The HTTP `Host` matcher matches the **Host header**,
  not the TLS SNI (TR06). SNI matters for HTTP
  routing in exactly two ways: (1) certificate
  selection — "the `Host()` part of the rule is used
  to pick the appropriate certificate" (community
  answer, corroborated by the TLS docs: `tls.options`
  "are mapped to the host names of the router rule,
  and not to the router itself, so all the routers
  serving the same host name on the same entry point
  must reference the same TLS options" [documented
  — HTTP Router reference]); and (2) ACME — "If
  `certResolver` is defined, Traefik will try to
  generate certificates based on routers `Host` &
  `HostSNI` rules" [documented — v2.3 Routers, TLS
  section, unchanged in v3]. Neither changes which
  router wins: cert selection happens after routing,
  and a router whose certificate is missing or
  invalid still wins the route (the client gets a
  TLS error or the default cert, not a different
  router). v1 therefore reports TLS facts as
  annotations on the verdict, never as deciders —
  except the HTTPS-only scope above, which *is* a
  decider.
- **Conflicting TLS options.** If two routers serve
  the same hostname on the same entrypoint with
  different `tls.options`, a conflict occurs
  [documented — v2.3 Routers, "Conflicting TLS
  Options", unchanged in v3]. From v3.7.11 the
  unsafe fallback to default TLS options on conflict
  is disabled (GHSA-g55h-rg46-x9c5, noted in the
  Helm chart values: "Disables the unsafe fallback
  to default TLS options on conflict, mitigating
  GHSA-g55h-rg46-x9c5. Requires traefik v3.7.11+").
  v1's rule: conflicting `tls.options` for one
  hostname+entrypoint is a config-fatal naming both
  routers [docs-inferred — the docs describe the
  conflict but not the exact failure mode in v3.7;
  OQ-11]. A `tls.options` reference naming an
  options object that is not defined in the config
  is likewise a config-fatal.
- `tls.domains` ("List of domains and Subject
  Alternative Names (SANs) for explicit certificate
  domain specification. When using ACME certificate
  resolvers, domains are automatically extracted from
  router rules, making this option optional"
  [documented]) does not affect routing: it is
  inventoried and printed, never evaluated.
- The default certificate: "If no certificate are
  set, a default self-signed certificate is generated
  by Traefik" [documented — EntryPoints reference,
  `http.tls`]. A router that matches but whose
  hostname has no certificate still serves, with
  `CN=TRAEFIK DEFAULT CERT` — the subject of the
  May 2026 blog post "The case of the self-signed
  cert". v1 notes `[default-cert-would-serve]` when
  a winning TLS router has no certificate source in
  the config (no `tls.certificates` entry, no
  `certResolver`, no entrypoint cert) — an
  annotation, not a verdict change.

### TR19 — No match is a 404; a match with no servers is a 503

"Traefik returns a `404` response code in the
following situations: A request reaching an
EntryPoint that has no Routers; An HTTP request
reaching an EntryPoint that has no HTTP Router; An
HTTPS request reaching an EntryPoint that has no
HTTPS Router; A request reaching an EntryPoint that
has HTTP/HTTPS Routers that cannot be matched. From
Traefik's point of view, every time a request cannot
be matched with a router the correct response code
is a `404 Not found`" [documented — Getting Started
FAQ, v2.8]. And: "Traefik returns a `503 Service
Unavailable` response code when a Router has been
matched but there are no servers ready to handle
the request" [documented — same FAQ]. The verdict
vocabulary follows directly: **NO-MATCH** (exit 1)
means the live answer would be 404; **MATCH**
(exit 0) names the router and service, and if the
service has no servers (or no healthy servers —
TR32) the verdict adds `[service-has-no-servers]`
and notes the live answer would be 503. The FAQ
also documents the catch-all workaround: "a simple
catchall router, with the lowest possible priority
and routing to a service without servers, can handle
all the requests when no other router has been
matched" — i.e. a catch-all that *converts* 404s
into 503s. v1 models that exactly: a catch-all
router (e.g. `Host(`*`)` with a very negative
priority) wins NO-MATCH queries and reports its
service, with `[catchall-converts-404-to-503]`
when its service has no servers.

### TR20 — Entrypoint redirections happen before routing

`entryPoints.<name>.http.redirections.entryPoint`
redirects "all incoming requests on an entry point
to another one", with `to` (entrypoint name or
port), `scheme` (default `https`), and `permanent`
(default `true`) [documented — EntryPoints
reference]. A request arriving on a redirecting
entrypoint never reaches any router: it gets a 301
(permanent) or 302/308 redirect to the target
entrypoint. v1 models this as a pre-routing verdict:
if `--entrypoint` names an entrypoint with a
redirection configured in `--static`, the verdict is
**REDIRECT** (exit 0 — the request is decided, just
not by a router), naming the entrypoint, the target,
and the status code, and no router is evaluated.
"Entrypoint-level redirects automatically pass
through `/.well-known/acme-challenge/` paths for
Let's Encrypt HTTP-01 challenges" [documented —
bitdoze guide, corroborated by Traefik behaviour]:
a `--path` under `/.well-known/acme-challenge/`
is exempt from the redirect and proceeds to routing
[docs-inferred — the exemption is documented in
guides, not in the reference; OQ-11]. If `--static`
is absent, redirections are unknown and the run
carries `[entrypoint-redirections-unknown]`; a
router verdict on an entrypoint that might redirect
is still reported, because the redirect is a
property of the *entrypoint*, not the router, and
the coverage section says the redirect check could
not be performed. The per-router `RedirectScheme` /
`RedirectRegex` middlewares are different: they run
*after* the router matches (TR22) and do not change
the winner.

### TR21 — Middlewares: declared order, chain expansion, and the built-in inventory

"The list of middlewares that are applied to the
router. Middlewares are applied in the order they
are declared" [documented — HTTP Router reference,
`middlewares` field]. A middleware is referenced by
name, with an optional `@<provider>` suffix; the
default provider is the router's own. A `chain`
middleware "combines multiple pieces of middleware"
[documented — Middleware overview] and is expanded
in place, in its declared order, recursively (a
chain containing a chain is legal; a chain cycle is
a config-fatal). The built-in HTTP middlewares in
v3.7, from the overview table [documented — HTTP
Middleware overview, v2.8/v2.11; the v3.7 set is
the same table plus the additions noted]:

AddPrefix, BasicAuth, Buffering, Chain,
CircuitBreaker, Compress, ContentType, DigestAuth,
Errors, ForwardAuth, GrpcWeb, Headers, IPAllowList,
InFlightReq, PassTLSClientCert, RateLimit,
RedirectRegex, RedirectScheme, ReplacePath,
ReplacePathRegex, Retry, StripPort, StripPrefix,
StripPrefixRegex. Plus, in v3.8 only (excluded from
v1's inventory, flagged `[v3.8-only]` if seen):
Tap. TCP middlewares: InFlightConn, IPAllowList
[documented — TCP middleware references]. There are
no built-in UDP middlewares. A middleware name
whose type is not in the inventory is a
**plugin middleware** (community plugin, loaded via
`experimental.plugins` in the static config) or an
unknown type: v1 inventories it by name and type
as written, and if the type is unknown to v1 it
emits `[unknown-middleware-type]` and treats the
middleware as opaque (TR22) rather than failing —
plugin middlewares are legitimate config, and
refusing the whole file over one would be wrong.
A middleware reference naming a middleware that is
not defined anywhere in the config is a config-fatal
[docs-inferred — Traefik errors on unknown
middleware references; OQ-11]. A middleware defined
but never referenced is inventoried by
`--list-middlewares` and otherwise inert.

### TR22 — Which middlewares change the answer, and which only change the forwarded request

This is the finding the IDEA record got right and
the design keeps: middlewares run **after** the
router matches, so no middleware changes *which
router won*. What they change is what happens next,
and v1 classifies each middleware in the winning
chain into one of three classes, printed on the
verdict:

- **Outcome-changing (the response is not the
  service's response).** `RedirectScheme` /
  `RedirectRegex` ("Redirects based on regex" /
  redirect to another scheme — the client gets a
  3xx and never reaches the service);
  `BasicAuth` / `DigestAuth` / `ForwardAuth` (a
  failed check returns 401/403 before the service
  is called — but the check depends on the
  request's credentials, which v1 cannot evaluate
  without `--header Authorization`, so the verdict
  is MATCH with `[auth-may-reject]` unless the
  credentials are supplied and fail); `IPAllowList`
  (a client IP outside `sourceRange` gets 403 —
  decidable when `--client-ip` is given, so v1
  evaluates it: if the IP is outside the range, the
  verdict is MATCH with `[ipallowlist-would-reject]`
  and exit code stays 0, because the router *did*
  win; the rejection is a second-stage fact);
  `RateLimit` / `InFlightReq` (capacity-dependent,
  never decidable from the file — `[rate-limit-
  runtime]`); `CircuitBreaker` (health-dependent —
  `[circuit-breaker-runtime]`); `Errors` (rewrites
  error responses — annotation only); `Retry`
  (replays the request on failure — annotation only,
  and from v3.7 retry-by-status-code is configured
  in the middleware [documented — 3.7 release notes]).
- **Request-rewriting (the service sees a different
  request than the router matched).** `StripPrefix` /
  `StripPrefixRegex` ("Remove the specified prefixes
  from the URL path"; "store the matching path prefix
  in a `X-Forwarded-Prefix` header" [documented]);
  `ReplacePath` / `ReplacePathRegex` ("Changes the
  path of the request"); `AddPrefix` ("Adds a Path
  Prefix"); `StripPort` (strips the port from the
  Host header before forwarding); `Headers` (adds/
  updates/removes headers); `PassTLSClientCert`
  (injects client-cert info as headers); `GrpcWeb`
  (translates gRPC-Web to gRPC). v1 computes and
  prints the rewritten path for the path-modifying
  middlewares in chain order (`/api/users` →
  StripPrefix(`/api`) → `/users` → service sees
  `/users`), because "the service 404'd" is very
  often a strip/replace surprise, not a routing
  surprise. The rewritten path is [docs-inferred]
  from each middleware's documented semantics; the
  computation is deterministic given the request
  path, so it is pinned, not hypothesized — except
  `StripPrefixRegex` with a regex that can match in
  more than one way, which is still deterministic
  (first match wins, Go regexp leftmost match).
- **Response-only / opaque.** `Compress` (encoding
  negotiation), `Buffering` (request/response
  buffering), `ContentType` (auto-detect override),
  `ForwardAuth`'s `authResponseHeaders` (adds headers
  from the auth response), plugin middlewares
  (opaque by definition). These are listed, never
  evaluated.

The chain is printed in full, in order, with each
middleware's file:line and its class. A chain that
contains a redirect or an auth middleware is flagged
in the verdict summary line, because those are the
two cases where "the router matched but the user
still didn't reach the service" — the second most
common traefikwho question after the wrong-router
one.

### TR23 — Service resolution: names, providers, types, and v3.7 service middlewares

- "The name of the service that will handle the
  matched requests. Services can be load balancer
  services, weighted round robin, mirroring, or
  failover services" [documented — HTTP Router
  reference, `service` field, marked Required:
  **Yes**]. In the file provider there is no
  auto-creation: "The file provider does not discover
  services automatically. Define every router,
  service, middleware, and TLS resource explicitly"
  [documented — File routing reference]. A router
  whose `service` names a service not defined in the
  file config is a config-fatal [docs-inferred —
  Traefik disables such a router with an error;
  OQ-11]. (Contrast the Docker provider, where "If
  a label defines a router but no service is defined,
  then a service is automatically created and
  assigned to the router" [documented — Docker
  routing reference] — that auto-creation is a
  Docker-provider behaviour and does not apply to
  files. **Correction to the IDEA record:** the
  IDEA's shape implies the service is always
  resolvable from the files; the design pins that
  this holds only because the file provider requires
  explicit services, and a missing service is a
  fatal, not a silent default.) A router with no
  `service` field at all is likewise a config-fatal
  in v1's file model — the router table marks the
  field required, and v1 follows the table rather
  than guessing a same-name service.
- Service references use the `name@provider` form:
  `service: api@file`, or bare `api` (same provider
  as the router). A reference to a service in another
  provider (`api@docker`) is UNKNOWN with
  `[cross-provider-reference]` (TR01). The
  `@internal` services (`api@internal`,
  `dashboard@internal`, `ping@internal`,
  `noop@internal`) are inventoried (TR35).
- Service types: `loadBalancer` (with `servers`
  — `url` or `address` — plus `healthCheck`,
  `sticky`, `serversTransport`), `weighted` (a
  list of named services with weights),
  `mirroring` (a main service plus `mirrors` that
  receive a copy), `failover` (a main service plus
  a `fallback`). v1 reports the service type and,
  for `loadBalancer`, the server list with
  file:line. Which *server* handles the request
  (round-robin, weighted, sticky cookie, least-
  connections) is runtime and is never adjudicated:
  the verdict names the service, and the server list
  is printed as inventory with
  `[server-selection-runtime]`. A `weighted` service
  is reported with its weights and a note that the
  request goes to one of them by weight
  (`[weighted-routing-runtime]`); a `mirroring`
  service is reported with its mirrors and a note
  that mirrors receive a copy (`[mirroring-copy]`);
  a `failover` service is reported with its fallback
  and `[failover-on-health-runtime]`. A service with
  an empty server list (or a `weighted` service whose
  members are all empty) is the TR19 503 case.
- **Middlewares on services (v3.7).** "You can now
  attach middlewares directly to a service
  definition, and they apply to every router that
  targets that service" [documented — Traefik Proxy
  3.7 release notes, "Middlewares on Services"].
  The effective chain is therefore router
  middlewares first, then service middlewares, in
  their declared orders [docs-inferred — the release
  notes say service middlewares "apply to every
  router that targets that service"; the ordering
  relative to router middlewares (router first) is
  the natural pipeline order and is marked OQ-13].
  v1 prints both chains, labelled `router:` and
  `service:`, and classifies service middlewares
  with the same TR22 classes. A service middleware
  that would reject (IPAllowList, auth) is flagged
  the same way. This is a v3.7 feature: a config
  that uses service middlewares under an older
  Traefik is invalid, and v1 notes the version
  requirement in coverage (`[service-middlewares-
  require-3.7+]`).

### TR24 — Multi-layer routing: parentRefs makes the question a hierarchy, and v1 refuses it

"Multi-layer routing enables you to create
hierarchical relationships between routers, where
parent routers can process requests through
middleware before child routers make final routing
decisions" [documented — Traefik Hub multi-layer
routing reference; Traefik Proxy 3.6 release notes].
Three router types: **root routers** (no
`parentRefs`, attached to `entryPoints`, define
`tls` and `observability`, can have children or
route to a service); **intermediate routers**
(reference parents via `parentRefs`, have children,
"cannot define a `service` and inherit
`entryPoints`, `tls`, and `observability` from their
root"); **leaf routers** (reference parents via
`parentRefs`, "must define a `service`", inherit
from their root) [documented — traefik.io multi-layer
routing tutorial]. "Child routers cannot be called
directly — requests must flow through their parent"
[documented — 3.6 release notes], and the child's
rule "can key off things the middleware added, like
a header from a forward-auth check" — i.e. the
child's match inputs include headers the parent's
middlewares *created*, which do not exist in the
incoming request. Multi-layer routing "only works
with Kubernetes IngressRoute CRD, File providers
(YAML/TOML), and KV stores" [documented — tutorial],
so it is squarely inside v1's file scope — and v1
still refuses it: evaluating a child router
requires evaluating the parent's rule, then the
parent's middlewares' *effects* on the request
(forward-auth injecting `X-User`, a headers
middleware adding a header), then the child's rule
against the enriched request. That is a second
evaluation pass over middleware semantics that v1
does not implement (TR22 classifies middlewares;
it does not simulate them). v1's rule: any router
with a `parentRefs` field is excluded from the
walk and listed in coverage as
`[multi-layer-router-excluded]`; if such a router
would have been a candidate (its rule evaluates
TRUE against the raw request and its parent chain
is present), the verdict is UNKNOWN citing
`[multi-layer-routing]` and naming the router and
its parents. A config with no `parentRefs` anywhere
is unaffected. This is a deliberate v1 limitation,
not a gap in the design: the alternative (treating
a child's rule as if it matched the raw request)
would produce confident wrong answers whenever a
parent middleware enriches the request, which is
the entire point of the feature. A v2 design
question is a `--simulate-parent-middleware` mode;
it is not in v1. Note also the version hazard
documented by a Sep 2026 field report: on Traefik
< 3.6, "a single `parentRefs` field anywhere in the
file will take down routing on the older version
entirely" (`field not found, node: parentRefs` —
every router stops being served, not just the
multi-layer ones). v1 flags any `parentRefs` use
with `[parentRefs-requires-3.6+]` in coverage.

### TR25 — Duplicate router/service/middleware names across files

Within one file, duplicate keys are a config-fatal
(Files and lines). Across files in `--conf DIR`,
Traefik merges the dynamic configurations, and the
docs do not state what happens when two files define
the same router name. v1's rule is [hypothesized]:
**the last file in alphabetical order wins**, and
the losing definition is reported as a finding
(`[duplicate-router-shadowed]`, naming both files
and lines) — the merge is a map merge, and map
merges in Traefik's config assembly are
last-write-wins in load order. The hypothesis is
flippable (OQ-10): if the merge is first-wins or an
error, the finding changes to a fatal or the winner
flips. The same rule applies to duplicate service
and middleware names. A duplicate *within* the
same provider but across the static file's dynamic
section and the directory is handled the same way
(the directory wins, [hypothesized]). What v1 never
does is silently merge two routers with the same
name into one: a router is one definition, and the
shadowed one is named out loud.

### TR26 — Router and service naming: `@` is forbidden, names are case-sensitive

"The character `@` is not authorized in the router
name" [documented — HTTP Router reference, Router
Naming; same for TCP routers and for services in
the File routing reference]. A router or service
name containing `@` is a config-fatal. Names are
case-sensitive and are compared byte-wise
[docs-inferred — the docs never state case rules
for names, and every example uses lowercase;
OQ-3]. The `@provider` suffix is syntax, not part
of the name: `api@file` is service `api` from
provider `file`, and a bare `api` in a file-provider
router is `api@file`. A reference with an unknown
provider suffix (`api@nosuchprovider`) is a
config-fatal naming the reference [docs-inferred].
Internal names (`api@internal` etc.) are reserved:
a user-defined router named `api` in the file
provider does not collide with `api@internal`
because the provider suffix differs — but a
router *referencing* `api@internal` as its service
is legal and is how the dashboard is exposed, so
v1 resolves it as the internal service (TR35).

### TR27 — TLS options, certificates, and stores: inventoried, never evaluated for routing

`tls.options` (cipher suites, min/max TLS version,
client auth), `tls.certificates` (static cert/key
pairs), `tls.stores` (default certificate and
store selection), and `tls.ca`/`clientAuth` are
all inventoried by `--list-*` modes and printed in
coverage when present. None of them changes which
router wins, with the two exceptions already pinned:
conflicting `tls.options` for one hostname (TR18,
config-fatal) and the HTTPS-only scope of a router
with a `tls` block (TR18). Client-certificate
requirements (`clientAuth`) do not change routing:
a router still wins and the handshake then fails —
v1 annotates `[client-auth-required]` when the
winning router's TLS options demand a client cert,
because "the router matched but the handshake
failed" is a distinct diagnostic from "no router
matched". ACME state (which certificates have been
issued, stored in `acme.json`) is runtime and never
read: a `certResolver` on a router is reported as
`[acme-cert-runtime]` and the router is still
evaluable. The `tls.certificates` entries are
checked only for file existence when the paths are
local and absolute [hypothesized — Traefik fails
to load a missing cert file at startup; OQ-11];
a missing cert file is a config-fatal.

### TR28 — Observability, timeouts, and the fields that never change the winner

`observability` (per-router metrics/accessLogs/
tracing, `traceVerbosity`), `respondingTimeouts`
(per-router `readTimeout`/`writeTimeout` — added
in v3.8, [documented — 3.8.0-rc.1 release notes,
"Add per router responding timeouts"]; in v3.7
these are entrypoint-level only), and the
entrypoint-level `transport`/`http2`/`http3`
settings are inventoried and never evaluated: they
cannot change which router wins. Two exceptions
are pinned because they look like routing and are
not: (1) "Only one router per branch of a
multi-layer routing tree can define
`respondingTimeouts`, otherwise the router is
disabled with an error" [documented — HTTP Router
reference] — v1 enforces this as a config-fatal
when `parentRefs` trees are present, even though
the tree itself is excluded (TR24); (2) a
`respondingTimeouts.readTimeout` longer than
`writeTimeout` disables the router with an error
[documented — same reference] — v1 enforces this
as a config-fatal too, because a disabled router
must not be in the walk. Everything else in this
finding is annotation: the verdict prints the
winning router's observability/timeout settings in
one line, and moves on.

### TR29 — Health checks and server readiness: matched is not served

A router can win and the request can still fail,
and the two failures have different status codes
(TR19). v1 distinguishes three service states, all
reported on a MATCH verdict: (a) the service has
servers listed and no health check configured —
the live answer is the service's response, and v1
says `[servers-present-no-healthcheck]`; (b) the
service has a `healthCheck` configured — whether
any server is currently healthy is runtime, so v1
says `[server-health-runtime]` and the verdict
stands; (c) the service has no servers at all (or
a `weighted` service whose members are all empty,
or a `failover` service with no main and no
fallback) — the live answer would be 503, flagged
`[service-has-no-servers]`. Load-balancer
`healthCheck` configuration (path, interval,
timeout, hostname) is inventoried; the *result*
of a health check is never in the files. Sticky
sessions (`sticky.cookie`) mean the *same* client
may be pinned to one server, but the router and
service are unchanged — annotation only. The
`serversTransport` (custom TLS to backends,
`insecureSkipVerify`, root CAs) likewise does not
change routing; it is inventoried, and
`insecureSkipVerify: true` earns a finding
(`[backend-tls-insecure]`) because it is a
security fact the operator should see next to the
routing answer, not because it changes the winner.

### TR30 — Weighted, mirroring, and failover services: the verdict is the service, the split is runtime

A `weighted` service names services with weights
("weighted round robin" [documented — HTTP Router
reference]); a `mirroring` service names a main
service and mirrors that receive a copy of the
request; a `failover` service names a main service
and a fallback used when the main is unhealthy.
v1's verdict names the top-level service and its
type, lists the members with weights, and stops:
which member receives *this* request is decided by
weight (randomized), by mirroring (a copy, the
response still comes from the main), or by health
(runtime). The verdict is therefore MATCH with the
service named and the appropriate banner
(`[weighted-routing-runtime]`, `[mirroring-copy]`,
`[failover-on-health-runtime]`). Nested services
(a weighted service whose member is itself a
weighted service) are expanded recursively for
inventory, with a depth cap of 8 and a cycle
check — a service cycle is a config-fatal naming
the cycle. A member naming a service that does not
exist is a config-fatal (TR23). The one case where
the split *is* decidable: a `weighted` service
with exactly one member at weight > 0 and all
others at weight 0 — v1 reports that member as the
effective service, with `[weighted-single-member]`.

### TR31 — EntryPoint HTTP settings that change the request before routing

Three entrypoint settings rewrite the request
before any router sees it, and all three are
static-config facts, hence `[entrypoint-properties-
unknown]` when `--static` is absent:

- `http.redirections` (TR20) — the request never
  reaches a router.
- `http.tls` (TR18) — every router on the
  entrypoint becomes HTTPS-only.
- `forwardedHeaders` / `proxyProtocol` (TR11) —
  they change which IP `ClientIP` sees and which
  scheme/host the request appears to have. In
  particular, `forwardedHeaders.trustedIPs` makes
  Traefik trust `X-Forwarded-Proto` /
  `X-Forwarded-Host` / `X-Forwarded-For` from the
  listed sources, which can change the *effective*
  Host header a `Host` matcher sees. v1 does not
  apply this rewriting: `--host` is taken as the
  Host header Traefik sees after trust processing,
  and the coverage section says so. If the user
  passes the *external* Host while Traefik sits
  behind a trusted proxy that rewrites it, the
  verdict is wrong — and the design says that out
  loud rather than pretending to model it.
- `http2` / `http3` settings, `maxHeaderBytes`,
  `transport` timeouts: no routing effect, inventoried.

### TR32 — TCP services and TLS passthrough: the backend sees what the router does not decrypt

A TCP service is a `loadBalancer` with `servers`
(`address: host:port`), optionally with `tls`
(`terminationProxy` etc.), `proxyProtocol`
(version 1/2 — "If PROXY protocol header parsing
is enabled for the entry point, this entry point
can accept connections with or without PROXY
protocol headers" [documented — EntryPoints
reference]), and `healthCheck` (TCP-level). With
`tls.passthrough: true` on the router, Traefik
forwards the encrypted stream untouched: the SNI
match is the only inspection, and the backend must
hold the certificate. v1 reports passthrough on
the verdict line (TR17) and never claims to know
whether the backend's certificate matches the SNI
— that is a backend fact, bannered
`[passthrough-cert-backend]`. A TCP `weighted` /
`mirroring` service does not exist in the same form
as HTTP (TCP services are loadBalancer only, plus
failover via the HTTP-style `failover` service in
newer versions — [hypothesized], OQ-13); v1
accepts whatever the file declares and inventories
it, refusing only unknown service *keys*.

### TR33 — UDP routers: no rule, no verb, no verdict

"Similarly to TCP, as UDP is the transport layer,
there is no concept of a request, so there is no
notion of an URL path prefix to match an incoming
UDP packet with. Furthermore, as there is no good
TLS support at the moment for multiple hosts, there
is no Host SNI notion to match" [documented — v2.3
Routers, UDP section, unchanged in v3]. A UDP
router has an entrypoint and a service and nothing
to match on: every packet on the entrypoint goes to
the service (first UDP router on the entrypoint
wins by declaration order, [hypothesized]).
There is no `traefikwho udp` verb in v1. UDP
routers are listed by `--list-routers --kind all`
with `[udp-no-rule]` and are otherwise ignored; a
`--kind udp` query is a usage error telling the
user there is nothing to adjudicate. If a future
version adds UDP, the verb will need a
`--datagram` description, not a request — a
separate design question.

### TR34 — The `traefik` entrypoint and the internal routers

Traefik's own API/dashboard/ping are served by
internal routers on the `traefik` entrypoint
(conventionally `:8080`), via the `api@internal`
service. Internal routers have reserved priorities
(TR12) and reserved names. A user router that
shadows the dashboard path (e.g. `Host(`traefik.
example.com`) && PathPrefix(`/dashboard`)` with a
higher priority than the internal router) wins the
request in Traefik's model, because user routers
and internal routers are sorted in the same table
[docs-inferred — the dashboard is "just a router
pointing at the built-in `api@internal` service",
per the svenvg.com Traefik explainer, and the API
docs describe `api@internal` as a service like any
other; OQ-13]. v1 models internal routers as
ordinary routers with their documented rules
(`PathPrefix(`/api`)` and `PathPrefix(`/dashboard`)`
on the API entrypoint, when the API is enabled in
`--static`) and their reserved priorities, so a
shadowing finding (`[shadows-internal-router]`)
can be emitted. When `--static` is absent, the
internal routers are unknown and coverage says so.
`ping@internal` (`/ping`) and `acme-http@internal`
(the HTTP-01 challenge handler, which claims
`/.well-known/acme-challenge/` on the `web`
entrypoint before user routers) are modelled the
same way: the ACME challenge path is a reserved
internal route, and a user router matching it loses
to the internal one [docs-inferred, OQ-13].

### TR35 — Reserved priorities and internal routers: the table's top end

"Traefik reserves a range of priorities for its
internal routers, the maximum user-defined router
priority value is: `(MaxInt32 - 1000)` for 32-bit
platforms, `(MaxInt64 - 1000)` for 64-bit platforms"
[documented — Rules & Priority]. The reserved band
is therefore (MaxInt-1000, MaxInt]. v1 rejects a
user priority inside the reserved band as a
config-fatal [docs-inferred — the docs state the
maximum, and exceeding it is an error; OQ-11],
and assigns the internal routers (TR34) priorities
inside the band, in their documented relative order
(ACME challenge highest, then API/dashboard, then
ping — [hypothesized], OQ-13). The practical
consequence: a user router can never outrank an
internal router by priority alone, only by not
overlapping its rule — which is why shadowing
(TR34) is a rule-overlap question, not a priority
question.

### TR36 — Rule length is measured on the configured string, per router, per syntax

TR12 pins the unit; this finding pins the edge
cases. The length is measured on the rule string as
it appears in the config file — after YAML/TOML
unquoting, before any evaluation, including all
whitespace and operators as written. For a v2-syntax
router, the length is measured on the v2 rule string
as written (including `{name:pattern}` captures and
commas); the v2→v3 *rewritten* length is irrelevant
because Traefik sorts on the configured rule
[docs-inferred — "directly equal to the length of
the rule" with no normalization step described;
OQ-3]. For a rule split across YAML lines (a YAML
folded/block scalar), the length is measured on the
value after YAML scalar processing (folded newlines
become spaces) [hypothesized, OQ-3]. Two routers
with textually identical rules have identical
priorities and are therefore a TR14 tie. The
computed priority is shown for every router in
`--list-routers` and in every match-chain entry, so
a user can verify the arithmetic without trusting
the tool.

### TR37 — What v1 refuses: the config is not the whole Traefik

The banner list below is the contract. The headline
refusals, each with its reason:

- **Other providers (TR01).** Docker labels,
  Kubernetes CRD/Ingress, Gateway API, Consul,
  etcd, ZooKeeper, HTTP provider, Rancher, Nomad,
  ECS, Ingress NGINX provider. Their routers do
  not exist in the files. If `--static` enables
  one, every verdict carries the banner; if
  `--static` is absent, coverage says the provider
  set is unknown.
- **ACME runtime state (TR27).** Which certificates
  exist, whether a challenge is in flight, whether
  a renewal failed. `certResolver` is a name, not
  a certificate.
- **Backend health and server selection (TR29/
  TR30).** Health checks run live; load-balancer
  picks are per-request.
- **Plugin middlewares (TR21).** Inventoried by
  name, opaque in effect. A plugin that rewrites
  the request (like a custom auth plugin) can
  change the outcome in ways v1 cannot see; the
  banner says so.
- **Multi-layer routing (TR24).** Excluded routers,
  UNKNOWN when they could win.
- **Go templates (Files and lines).** Unevaluated
  files make their routers UNKNOWN.
- **Live traffic facts.** Rate limits, circuit
  breakers, in-flight counts, retries — all
  runtime, all bannered, none decidable.
- **The dashboard/API as an input.** v1 never
  contacts a running Traefik. A `--api URL` flag is
  deliberately absent: the tool answers from
  files, and a mode that fetched live state would
  be a different tool (and would need the API
  enabled, which the docs warn against in
  production).

### TR38 — Duplicate and shadowed routers: loud, classified, never silently absorbed

Three distinct situations, three different
treatments: (a) the same router name defined twice
(TR25 — last file wins, finding); (b) two routers
with identical rules and equal priority (TR14 —
name-order tie-break, banner); (c) a router that
can never win because a higher-priority router's
rule is a superset of its rule (shadowing). For
(c), v1 computes a *conservative* shadow analysis
over `Host`/`PathPrefix` literals only: if router
A's rule is a single `Host(`x`)` and router B's
rule is `Host(`x`) && PathPrefix(`/`)` with higher
priority, B shadows A for every request A could
match — A is reported as `[shadowed-by]` with B
named, on every run, in coverage (not only when
queried). The analysis is deliberately
conservative: it fires only when the shadowing is
provable from literal matchers (same Host value,
prefix containment), never from regexps, and it
never changes a verdict — it is a finding. Full
shadow analysis (regexp containment, multi-matcher
set solving) is a v1.1 design question (pfwho OQ-12
precedent). A router shadowed by a *catch-all*
(`Host(`*`)` with higher priority) is the extreme
case and gets the same finding with the catch-all
named.

### TR39 — Config errors are fatal, and the fatal names the file and line

The config-fatal set (exit 2): unparseable YAML/
TOML; duplicate keys in one file; a rule that fails
to parse (TR03); an unknown matcher in the resolved
syntax (TR05); a `Host`/`HostSNI` value with
non-ASCII (TR06); a `Path`/`PathPrefix` not starting
with `/` (TR07); a malformed IP/CIDR in `ClientIP`
(TR11); ``ALPN(`ACME-TLS/1`)`` (TR17); a `**`
wildcard in a `HostSNI` (TR17); a priority above
the user maximum or inside the reserved band (TR12/
TR35); a router naming an unknown entrypoint, an
unknown middleware, an unknown service, or an
unknown provider suffix (TR15/TR21/TR23/TR26); a
router with no `service` in the file model (TR23);
conflicting `tls.options` for one hostname (TR18);
a chain cycle (TR21); a service cycle (TR30);
`respondingTimeouts` misuse (TR28); a missing
`tls.certificates` file (TR27); a Go-template file
is **not** a fatal — it makes routers UNKNOWN
(Files and lines), because the file may still be
valid Traefik config. Every fatal prints `file:line`,
the offending value, and the rule it violates, and
exits before any verdict is computed. Warnings
(findings) never change the exit code. This is the
family rule: a config Traefik would reject must not
produce a confident verdict, and a config Traefik
would partly reject must not produce a verdict from
the surviving part without saying so.

### TR40 — The `--conf` default: there is none, and that is deliberate

Unlike pfwho (`/etc/pf.conf`) and keawho (a
conventional path), traefikwho has **no default
`--conf`**. Traefik's own config locations vary by
deployment (Docker volume mounts, `/etc/traefik/`,
a Helm chart's mounted directory, a repo checkout),
and any default would guess wrong more often than
right — and a wrong guess here means answering
from the wrong routing table, silently. `--conf`
is therefore required (usage error, exit 2, naming
the flag). `--static` is optional, with the
consequences pinned in TR01/TR15/TR20. `--list-*`
modes require `--conf` too. This is the one
deliberate break with the family default-discovery
convention, and it is documented in `--help` in one
line: "no default: Traefik configs live in too many
places to guess".

### TR41 — Exit-code and verdict vocabulary: MATCH is 0, NO-MATCH is 1, everything else is 2

Verdicts: **MATCH** (winner named, exit 0),
**REDIRECT** (entrypoint redirection, TR20, exit 0 —
the request is decided), **NO-MATCH** (no router
matched; live answer 404, exit 1), **UNKNOWN**
(exit 2, blocker cited), **AMBIGUOUS** (exit 2 —
reserved for the day OQ-1 flips the tie-break to
ambiguous; v1 never emits it). A MATCH whose
service has no servers is still exit 0 with
`[service-has-no-servers]` (the router *did* win;
the 503 is a service fact). A MATCH whose winning
chain contains a would-reject middleware
(IPAllowList outside range, auth with supplied
failing credentials) is still exit 0 with the
rejection flagged (TR22) — the router won; the
middleware refused. The asymmetry with pfwho (1 =
BLOCK) is deliberate and follows keawho (1 =
NO-LEASE): 1 is the decided-negative for the
question asked, and a script testing "does this
request route" wants `traefikwho http … && echo
routed` to work.

### TR42 — The v3.8 line: pinned out, not in

v3.8.0-rc.1 (Oct 30, 2026) adds: the `tap`
middleware ("triples request latency even with an
instant local receiver" — dev.to, Nov 9, 2026, on
the RC), per-router `respondingTimeouts`
[documented — 3.8.0-rc.1 release notes], and
`reusePrivateKey` for ACME. None of it is in v1's
pinned version (v3.7 stable). v1's parser accepts
`tap` as a middleware type and `respondingTimeouts`
as a router field (they parse), but flags them
`[v3.8-only]` in coverage and, for `tap`, treats
the middleware as opaque (TR21) — because v1
cannot verify the RC's final semantics from a
release candidate. When v3.8 goes stable, the pin
moves by a design update, not by silently
accepting RC behaviour. The README will name v3.7
until that update lands.

## Unmodeled / dynamism — the honest banner list

Every run's coverage section names which of these were
present in the consulted material; a blocker that decided
the verdict is cited on the verdict line itself, not
buried in coverage:

| Dynamism | Where pinned | Effect |
|---|---|---|
| providers other than `file` enabled (Docker, K8s, Consul, etcd, …) | TR01 | routers from those providers invisible; verdict is file-only |
| static config not supplied (`--static` absent) | TR01/TR15/TR20 | entrypoint TLS/redirections/`defaultRuleSyntax`/`providers.precedence` unknown |
| cross-provider service/middleware reference (`@docker`, …) | TR01/TR23 | reference UNKNOWN |
| Go templates in dynamic files | Files and lines | affected routers UNKNOWN |
| v2 rule syntax on a router (`ruleSyntax: v2` or `defaultRuleSyntax: v2`) | TR04 | parsed as v2; deprecated, removal in next major |
| multi-layer routing (`parentRefs`) present | TR24 | those routers excluded; UNKNOWN if one could win |
| plugin middleware in the winning chain | TR21 | middleware opaque; outcome UNKNOWN in its effect |
| service middlewares (v3.7) present | TR23 | chain printed as router+service; order [hypothesized] |
| weighted / mirroring / failover service | TR30 | member selection runtime |
| load-balancer server selection (round-robin, sticky, …) | TR23/TR29 | service named; exact server UNKNOWN |
| server health (healthCheck configured) | TR29 | health runtime; 503 possible |
| rate limit / in-flight / circuit breaker | TR22 | capacity runtime; rejection possible |
| auth middleware without supplied credentials | TR22 | rejection possible, not decidable |
| TCP router may claim the connection before HTTP | TR16 | HTTP verdict UNKNOWN if a TCP router could claim it |
| entrypoint redirection (static known) | TR20 | REDIRECT verdict, no router evaluated |
| entrypoint redirection (static unknown) | TR20 | redirect check not performed |
| same-priority tie broken by name order | TR14 | `[same-priority-tie-name-order]` on the verdict |
| Host port/trailing-dot stripping | TR06 | `[host-port-stripped-hypothesis]` when it changed the outcome |
| `ClientIP` behind trusted proxies / PROXY protocol | TR11 | `--client-ip` taken as post-trust IP |
| default cert would serve (no cert source) | TR18 | `[default-cert-would-serve]` annotation |
| duplicate router/service/middleware across files | TR25 | last file wins, loser named |
| shadowed router (literal containment) | TR38 | `[shadowed-by]` finding in coverage |
| internal router shadowed by a user router | TR34 | `[shadows-internal-router]` finding |
| v3.8-only fields (`tap`, per-router `respondingTimeouts`) | TR42 | flagged, treated as opaque/annotated |
| UDP routers present | TR33 | listed, never routed |

Banners used on verdicts: `[file-provider-only]`,
`[static-config-not-supplied]`,
`[docker-provider-enabled-not-read]`,
`[cross-provider-reference]`,
`[go-template-not-evaluated]`,
`[v2-rule-syntax-deprecated]`,
`[hostregexp-case-never-matches]`,
`[host-port-stripped-hypothesis]`,
`[forwarded-headers-trusted]`,
`[same-priority-tie-name-order]`,
`[tcp-router-may-claim-connection]`,
`[http-routers-may-claim]`,
`[service-has-no-servers]`,
`[catchall-converts-404-to-503]`,
`[auth-may-reject]`, `[ipallowlist-would-reject]`,
`[rate-limit-runtime]`, `[circuit-breaker-runtime]`,
`[default-cert-would-serve]`, `[client-auth-required]`,
`[acme-cert-runtime]`, `[backend-tls-insecure]`,
`[server-health-runtime]`,
`[servers-present-no-healthcheck]`,
`[weighted-routing-runtime]`, `[mirroring-copy]`,
`[failover-on-health-runtime]`,
`[weighted-single-member]`,
`[multi-layer-routing]`,
`[multi-layer-router-excluded]`,
`[parentRefs-requires-3.6+]`,
`[service-middlewares-require-3.7+]`,
`[duplicate-router-shadowed]`,
`[shadowed-by]`, `[shadows-internal-router]`,
`[unknown-middleware-type]`,
`[entrypoint-properties-unknown]`,
`[entrypoint-redirections-unknown]`,
`[server-selection-runtime]`,
`[passthrough-cert-backend]`,
`[udp-no-rule]`, `[v3.8-only]`.

## Output, verdicts, exit codes

Verdict vocabulary: **MATCH** (winner: router
file:line, priority, service + file:line, middleware
chain in order with classes, rewritten path where
applicable), **REDIRECT** (entrypoint, target,
status — TR20), **NO-MATCH** (no router matched;
live answer 404 — TR19), **UNKNOWN** (blocker
cited), **AMBIGUOUS** (reserved, never emitted in
v1 — TR41).

Text output leads with the verdict line (`VERDICT
MATCH — router web@file dynamic/app.yml:12
(priority 34) → service app@file`), then the
service line (type, servers or members, health
state), then the middleware chain (each: name,
type, file:line, class, and the rewritten path
after each path-modifying middleware), then the
match chain (every router in priority order with
TRUE/FALSE/UNKNOWN and the deciding term or the
missing flag), then findings, then coverage (files
read in load order, routers/services/middlewares/
TLS objects inventoried, banners that fired).
`--json` mirrors the same fields; JSON and text
verdicts must agree on every fixture (BG11). The
winner's rule is printed verbatim, and its computed
priority is printed next to it, so the 34-vs-26
trap is checkable by eye.

Exit codes (family standard, TR41): **0** = MATCH
or REDIRECT; **1** = NO-MATCH; **2** = UNKNOWN /
AMBIGUOUS / config-fatal / usage error.

`--list-routers` prints every router with file:line,
entrypoints, rule verbatim, computed priority,
explicit priority if set, service, middleware
names, TLS mode, and `parentRefs` if present
(exit 0). `--list-services` prints services with
file:line, type, servers/members, and middlewares.
`--list-middlewares` prints middlewares with
file:line, type, and reference counts (which
routers and services use them). They are the tool's
answer to "show me what this file contains" without
a request.

## The hazards, distilled (why this tool earns its keep)

1. **The longest rule wins, not the most specific
   match (TR12).** The docs' own example routes
   `foobar.traefik.com` to the regex router (34)
   instead of the exact-host router (26). Every
   "why did the wrong router serve my request"
   question is, at root, a length computation the
   operator did not do. The tool does it, and prints
   it next to the winner.
2. **The default when nothing matches is a 404 with
   no name attached (TR19).** Traefik's 404 tells
   you nothing matched; it cannot tell you whether
   a router *almost* matched, or which router was
   one flag away. The match chain is the diagnostic
   the status code cannot be: every router, its
   value, and the term that excluded it.
3. **TCP claims the connection before HTTP ever sees
   it (TR16).** A `HostSNI(`*`)` TCP router on
   `websecure` swallows every TLS connection,
   including the ones meant for HTTP routers, and
   the symptom is an HTTP router that "never
   matches" for no visible reason. The tool checks
   the TCP table first, because Traefik does.
4. **Entrypoint scoping and TLS scoping are silent
   filters (TR15/TR18).** A router on `websecure`
   never sees a `web` request; a router with a
   `tls` block never sees plain HTTP; a router whose
   `tls` block *replaces* the entrypoint's TLS
   config inherits nothing from it. All three are
   properties of the config, not the rule, and all
   three are invisible in the rule string. The tool
   evaluates them as terms, not footnotes.
5. **The v2→v3 syntax break is a live landmine
   (TR04).** The same characters mean different
   things under the two syntaxes — `Headers` is a
   matcher in v2 and a config-fatal in v3,
   `{id}` is a placeholder in v2 and a dead literal
   in v3, `PathPrefix` takes a regex in v2 and a
   literal in v3 — and the syntax is chosen
   per-router by a deprecated option. A tool that
   assumed one syntax would misread half the
   configs in the wild.
6. **Path normalization moved under operators' feet
   in v3.4.1 (TR07).** `/foo%2Fbar` matched a
   `/foo/bar` prefix before v3.4.1 and does not
   after; `.`/`..`/duplicate slashes are cleaned
   before matching. A static evaluator that matched
   the raw `--path` would disagree with the live
   proxy on exactly the requests attackers send.
7. **Middlewares do not change the winner, and that
   is precisely why they confuse people (TR22).**
   The router matched; then `stripPrefix` changed
   the path, `redirectScheme` sent the client
   elsewhere, `forwardAuth` rejected the request,
   or a service-level middleware (v3.7) rejected it
   after the router's chain. The verdict must show
   the whole chain, in order, with the rewritten
   path — otherwise the operator fixes the router
   when the middleware is the fault.
8. **Multi-layer routing makes the request a
   hierarchy, not a flat match (TR24).** A child
   router matches on headers the parent's middleware
   created. Any tool that evaluated the child's rule
   against the raw request would produce confident
   wrong answers on exactly the configs the feature
   was built for. v1 refuses those routers out loud
   instead.
9. **The file may not be the whole routing table
   (TR01/TR37).** Docker labels, Kubernetes CRDs,
   Consul, and etcd all feed the same router table,
   and a file-only answer that did not say so would
   be wrong on the most common Traefik deployment
   in existence. The tool states its provider set
   on every run and banners every cross-provider
   reference.
10. **There is no native oracle to check against
    (thinness verdict).** No `traefik test`, no
    dry-run, no simulation endpoint, no third-party
    validator that goes past schema syntax. The
    operator's only alternative is live traffic.
    A static evaluator is not a convenience here;
    it is the only way to answer the question
    without serving the request.

## Test plan (hermetic fixture configs; stdlib-only runner)

~83 tests, plain `python3` (no pytest — the aptpinswho
lesson). Every fixture is a file-provider tree on disk
(tempdir): a dynamic directory of YAML/TOML files plus
an optional static `traefik.yml`. No `traefik` binary
is required or invoked. Each test names its fixture
and expected verdict. Fixture configs use literal
hosts, paths, and IPs wherever the test is not about
name handling, so the matcher semantics are exercised
by their own tests.

- **BG1 (files, loading, provenance — Files and
  lines/TR01/TR40) — 8:** YAML and TOML routers in
  the same directory merge into one table; a router
  cites its own file:line (YAML key line, TOML table
  line); `.json` in the directory is ignored with a
  coverage note; subdirectory files are not read;
  `--conf` naming a single file works (the `filename`
  form); missing `--conf` → usage error exit 2;
  duplicate keys in one file → config-fatal naming
  both lines; a Go-template file (`{{` in a rule)
  makes its routers UNKNOWN with
  `[go-template-not-evaluated]` and leaves the rest
  decidable.
- **BG2 (rule grammar — TR03/TR04) — 8:** `&&` binds
  tighter than `||` (the docs' own
  `Host(`a`) || Host(`b`) && Path(`/x`)` case);
  parentheses override; `!` inverts a matcher and
  `!` on a compound needs parens; a `&&` inside a
  quoted regex does not split the rule; single-quoted
  matcher values are a config-fatal; a v2-syntax
  router (`ruleSyntax: v2`) parses `Headers(...)`,
  multi-value `Host(`a`,`b`)`, and `{id}` captures
  in `PathPrefix`; a v3-syntax router with
  `Headers(`...`)` is a config-fatal; `HostHeader`
  under v3 is a config-fatal; `defaultRuleSyntax: v2`
  in `--static` makes unmarked routers v2.
- **BG3 (matchers and three-valued logic — TR05–
  TR11/TR13) — 10:** `Host` exact, `*` one label,
  `**` multi-label, neither matching the bare domain,
  bare `*` matching a hostless request; `HostRegexp`
  with `(?i)`; `Path` exact (no `/products/shoes`,
  no `/products/`); `PathPrefix` string-prefix
  (`/products-for-sale` matches); `PathRegexp`
  unanchored; `Method` exact and unsupplied →
  UNKNOWN; `Header` case-insensitive name, exact
  value, unsupplied → UNKNOWN; `Query` one-arg
  (valueless) vs two-arg; `ClientIP` CIDR both
  directions; a rule `Host(`a`) || Method(`POST`)`
  with host `b` and no `--method` → UNKNOWN (not
  FALSE), and with `--method POST` → TRUE.
- **BG4 (priority and ties — TR12/TR14/TR36) — 8:**
  the docs' own 34-vs-26 case (regex beats exact
  host); `Host(`**.example.com`)` computes 20, below
  `*.example.com` at 21 and the exact host at 23;
  explicit `priority` overrides length; `priority: 0`
  falls back to length; negative priority sinks below
  a default; whitespace in the rule counts toward
  length (two rules differing only by spaces have
  different priorities); a same-priority tie is
  broken by router name ascending with
  `[same-priority-tie-name-order]`; a priority above
  `MaxInt64 - 1000` is a config-fatal.
- **BG5 (entrypoints and TLS scope — TR15/TR18/
  TR20/TR31) — 7:** router with `entryPoints: [web]`
  does not match `--entrypoint websecure`; router
  with no list matches any `--entrypoint`; no
  `--entrypoint` + a router that lists entrypoints →
  UNKNOWN naming the flag; router with `tls:` does
  not match `--no-tls`; entrypoint `http.tls` in
  `--static` makes a `tls`-less router HTTPS-only;
  router `tls` replaces (not merges) entrypoint TLS;
  entrypoint redirection in `--static` yields
  REDIRECT and no router evaluation, except the
  `/.well-known/acme-challenge/` path which proceeds
  to routing.
- **BG6 (TCP before HTTP, and the TCP verb —
  TR16/TR17/TR32) — 7:** `HostSNI(`db.example.com`)`
  matches `--sni db.example.com --tls`; `HostSNI(`*`)`
  on a non-TLS connection matches (catch-all);
  `HostSNI(`*.example.com`)` does not match
  `foo.bar.example.com`; `ALPN(`h2`)` matches;
  ``ALPN(`ACME-TLS/1`)`` is a config-fatal; a TCP
  router on `websecure` makes an `http` verdict on
  `websecure` UNKNOWN with
  `[tcp-router-may-claim-connection]`; a
  `tls.passthrough: true` router reports
  `tls=passthrough` on the verdict.
- **BG7 (path normalization — TR07) — 5:** `/a/./b`
  normalizes to `/a/b` and matches `Path(`/a/b`)`;
  `/a/../b` normalizes to `/b`; `//` collapses;
  `/foo%2Fbar` does **not** match
  ``PathPrefix(`/foo/bar`)`` (v3.4.1 behaviour);
  the query string in `--path` is split off and
  merged with `--query` flags.
- **BG8 (middlewares — TR21/TR22/TR23) — 8:**
  chain order is declaration order; a `chain`
  middleware expands in place; a chain cycle is a
  config-fatal; `StripPrefix(`/api`)` rewrites
  `/api/users` → `/users` and the rewritten path is
  printed; `ReplacePathRegex` rewrites per its
  regex; `RedirectScheme` is classified
  outcome-changing and flagged on the verdict;
  `IPAllowList` with `--client-ip` outside
  `sourceRange` yields MATCH +
  `[ipallowlist-would-reject]`; service middlewares
  (v3.7) print as a second `service:` chain after
  the router chain; a plugin middleware type is
  inventoried as opaque with
  `[unknown-middleware-type]`; a reference to an
  undefined middleware is a config-fatal.
- **BG9 (services — TR23/TR29/TR30) — 7:** service
  with servers lists them; service with no servers
  → MATCH + `[service-has-no-servers]` (live 503);
  router with an undefined service → config-fatal;
  `weighted` service reports weights and
  `[weighted-routing-runtime]`; single-member
  weighted reports the effective member;
  `mirroring` reports the copy banner;
  `failover` reports the fallback banner.
- **BG10 (no-match, catch-all, multi-layer, duplicates
  — TR19/TR24/TR25/TR38) — 6:** no router matches →
  NO-MATCH exit 1 (live 404); a `Host(`*`)`
  catch-all with the lowest priority wins only when
  nothing else does; a catch-all to a serverless
  service carries `[catchall-converts-404-to-503]`;
  a router with `parentRefs` is excluded and, when
  its rule would match, the verdict is UNKNOWN
  `[multi-layer-routing]`; a duplicate router name
  across two files resolves last-file-wins with
  `[duplicate-router-shadowed]`; a literally
  shadowed router (`Host(`x`)` under a higher
  priority `Host(`x`) && PathPrefix(`/`)`) gets a
  `[shadowed-by]` finding in coverage.
- **BG11 (output, inventory, exit codes — Output/
  TR41) — 5:** text and `--json` verdicts agree on
  a MATCH, a NO-MATCH, and an UNKNOWN fixture;
  `--list-routers` prints computed priorities (34
  and 26 for the docs' example); `--list-services`
  prints types and servers; `--list-middlewares`
  prints reference counts; exit codes 0/1/2 match
  MATCH / NO-MATCH / UNKNOWN+config-fatal across
  the suite.
- **BG12 (version pin and drift — TR42/TR04) — 4:**
  a `tap` middleware parses and is flagged
  `[v3.8-only]`; per-router `respondingTimeouts`
  with `readTimeout` > `writeTimeout` is a
  config-fatal; a v2-syntax router is flagged
  `[v2-rule-syntax-deprecated]`; a config with
  `parentRefs` carries `[parentRefs-requires-3.6+]`
  in coverage.

## Build order

1. Config loader (Files and lines/TR01): directory
   scan (`.yml`/`.yaml`/`.toml`, alphabetical,
   non-recursive), YAML node-preserving parse with
   duplicate-key detection, TOML parse, static-file
   read (`--static` or top-level `traefik.yml` in
   `--conf`), merge with TR25 last-wins, provenance
   (file:line) on every object, Go-template
   detection, `--conf`-required enforcement (TR40).
2. Rule parser (TR03/TR04): tokenizer over Go string
   literals, recursive-descent AST with precedence
   `!` > `&&` > `||`, per-router syntax resolution
   (router `ruleSyntax` → `defaultRuleSyntax` →
   `v3`), v2 grammar (multi-value matchers,
   `{name:pattern}` captures, `Headers`/`HostHeader`)
   behind the syntax flag, config-fatals with
   offsets (TR39).
3. Matcher evaluation (TR05–TR11): three-valued
   Kleene logic; Host lowercasing/punycode/wildcard
   rules; path normalization (TR07); header name
   case-insensitivity; query multi-map; ClientIP CIDR
   arithmetic; SNI/ALPN for TCP.
4. The walk (TR12–TR20): entrypoint filter, TLS
   scope, entrypoint redirection pre-check, TCP-
   before-HTTP gate for the `http` verb, priority
   computation (rule length minus `**` stars),
   sort, TR14 name-order tie-break with banner,
   UNKNOWN propagation per TR13, NO-MATCH → 404,
   MATCH → service resolution.
5. Services and middlewares (TR21–TR24/TR29/TR30/
   TR32/TR35): service type handling (loadBalancer/
   weighted/mirroring/failover), chain expansion
   (recursive, cycle = fatal), TR22 classification,
   path rewriting computation, service middlewares
   (v3.7), multi-layer exclusion (TR24), internal
   routers and reserved priorities (TR34/TR35),
   shadow analysis (TR38, literal containment only).
6. Renderers (text/JSON/coverage) + inventory modes
   + findings/banners + dogfood and gates above.

## Open questions / flippable hypotheses

1. **Same-provider priority tie-break (TR14).**
   The docs state only the cross-provider rule
   (`providers.precedence`). v1 breaks same-provider
   ties by router name ascending, [hypothesized],
   bannered on every affected verdict. If the
   Traefik source (or a live experiment) shows the
   tie-break is declaration order, insertion order,
   or nondeterministic (map iteration), the
   comparator flips — and if it is nondeterministic,
   tied verdicts become AMBIGUOUS. The flip is
   isolated in one comparator; BG4 has the fixture.
2. **Strictness on a broken router (TR03/TR39).**
   v1 makes any unparseable rule a config-fatal for
   the whole run; Traefik disables only that router
   and keeps serving the rest. If a real deployment
   needs partial answers from a config with one
   broken router, the honest shape is a
   `--tolerate-broken-routers` flag that excludes
   the broken router, banners it, and answers from
   the rest — a v1.1 flag, not a silent default.
3. **Unstated details of the matcher semantics
   (TR05/TR06/TR12/TR36).** Four small pins that
   the docs never state: matcher names are
   case-sensitive; a `**` wildcard in `HostSNI` is
   a config-fatal; whitespace counts toward rule
   length; v2 rule length is measured on the v2
   string as written. Each is [hypothesized] or
   [docs-inferred] and flips with a one-line change
   plus a fixture. A source read of Traefik's
   `rules` package would settle all four at once.
4. **Host header with a port, and trailing dots
   (TR06).** v1 strips `:port` and a trailing dot
   before `Host` matching, [hypothesized], bannered
   when it changes an outcome. If Traefik matches
   the raw Host header (port included), the
   normalization function flips and the banner
   becomes a finding that the rule can never match
   a port-carrying Host.
5. **Path normalization beyond the documented cases
   (TR07).** The v3.4.1 notes pin `.`/`..`/duplicate
   slashes and `%2F` staying encoded. Whether `%2e`
   decodes, whether a trailing slash on the root is
   preserved, and whether normalization applies
   before or after percent-decoding of unreserved
   characters are [hypothesized] to follow Go's
   `path.Clean` plus the RFC 3986 reservation rule.
   A live probe (or a source read of the v3.4.1
   change) flips the normalizer.
6. **Header matching details (TR08).** Header-name
   case-insensitivity is [docs-inferred]; repeated
   headers matching if *any* value matches is
   [docs-inferred]; both are standard HTTP/Go
   behaviour but neither is stated in the Traefik
   docs. If Traefik compares header names
   case-sensitively (it should not — Go
   canonicalizes), the matcher flips.
7. **Method case (TR09).** v1 compares methods
   case-sensitively (`Method(`get`)` never matches
   `GET`), [hypothesized]. If Traefik uppercases
   methods before matching, the comparison flips to
   case-insensitive.
8. **Query decoding (TR10).** v1 URL-decodes query
   keys/values (`+` → space), [hypothesized], and
   treats `?mobile=` (empty value) as present-but-
   valueless. If Traefik matches raw (encoded) query
   strings, the query parser flips to raw comparison
   and the one-arg/two-arg distinction is rechecked.
9. **ClientIP behind proxies (TR11).** v1 takes
   `--client-ip` as the already-resolved client IP
   and does not apply `forwardedHeaders.trustedIPs`
   or PROXY-protocol rewriting. If a deployment
   needs the tool to compute the effective IP from a
   `--peer-ip` plus a trusted-proxy list, the honest
   shape is explicit flags (`--peer-ip`,
   `--xff-chain`) — never a live lookup. IPv4-mapped
   IPv6 matching is [hypothesized].
10. **File-provider merge details (TR25, Files and
    lines).** Three small pins: duplicate router
    names across files resolve last-file-wins
    [hypothesized]; `.yaml` is accepted alongside
    `.yml`/`.toml` [hypothesized — the options list
    says ".yml or .toml"]; subdirectories are not
    descended [docs-inferred]. If the provider
    errors on duplicates, or ignores `.yaml`, or
    descends, the loader flips.
11. **Failure modes the docs describe but do not
    pin (TR15/TR18/TR21/TR23/TR27/TR28/TR34).**
    A batch of [docs-inferred] config-fatals to
    verify against the source at build time: unknown
    entrypoint reference, unknown middleware/service
    reference, unknown provider suffix, conflicting
    `tls.options` for one hostname, missing
    `tls.certificates` file, `respondingTimeouts`
    misuse, and whether an `http:` section in the
    static file is loaded without the file provider.
    Each is a one-line acceptance change with a
    fixture. The static-file discovery order is in
    this batch too.
12. **The exact v3 CLI command list (thinness
    verdict, point 1).** The four commands
    (`version`, `healthcheck`, `storeconfig`, `bug`)
    are documented for v1.6/v1.7 and appear in the
    `--help` gist; the v3 CLI flags reference lists
    flags only. If v3 added a command (it has not,
    in any release notes read), the thinness
    verdict's first point is rechecked — but no
    v3 command is a request simulator, so the
    verdict stands either way.
13. **Service-middleware order, internal-router
    priorities, TCP failover (TR23/TR34/TR35).**
    Whether service middlewares run after router
    middlewares (v1's [docs-inferred] order); the
    relative priorities of the internal routers
    (ACME > API > ping, [hypothesized]); whether a
    user router can shadow the ACME challenge path
    (v1 says no — the internal router wins); and
    whether TCP `failover` services exist in v3.7.
    All four are source-checkable at build time.

## Sources (read 2026-11-10)

- Traefik, HTTP Routers Rules & Priority (master,
  doc.traefik.io/traefik/master/reference/routing-
  configuration/http/routing/rules-and-priority/) —
  matcher table, `&&`/`||`/`!` and precedence,
  backticks/escaped quotes, Go regexp, Host
  wildcards (`*`/`**`/bare `*`), Host lowercasing
  and punycode, Path/PathPrefix/PathRegexp table,
  Query one-arg form, ClientIP (no X-Forwarded-For),
  RuleSyntax deprecation and default v3, priority
  = rule length, `**` stars not counted (23/21/20),
  `priority: 0` ignored, negative priorities,
  user maximums, providers precedence.
- Traefik, TCP Routers Rules & Priority (master,
  doc.traefik.io/traefik/reference/routing-
  configuration/tcp/routing/rules-and-priority/) —
  TCP-before-HTTP, HostSNI/HostSNIRegexp/ClientIP/
  ALPN table, `HostSNI(`*`)` non-TLS catch-all,
  single-level SNI wildcard, `ALPN(`ACME-TLS/1`)`
  forbidden, TCP priority (same rule).
- Traefik, HTTP Router reference (v3.8,
  doc.traefik.io/traefik/v3.8/reference/routing-
  configuration/http/routing/router/) — field table:
  `entryPoints` default all, `rule` required,
  `priority` default rule length, `middlewares`
  applied in declared order, `tls` = HTTPS-only,
  `tls.options` mapped to hostnames, `tls.domains`,
  `observability`, `respondingTimeouts` (v3.8),
  `parentRefs`, `service` required, router naming
  (`@` forbidden).
- Traefik, TCP Router reference (doc.traefik.io/
  traefik/reference/routing-configuration/tcp/routing/
  router/) — TCP field table, same priority text.
- Traefik, EntryPoints reference (master,
  doc.traefik.io/traefik/master/reference/install-
  configuration/entrypoints/) — `http.redirections`,
  `http.tls` (default self-signed cert, router
  `tls` replaces entrypoint TLS with no merge),
  `forwardedHeaders.trustedIPs`/`insecure`,
  `proxyProtocol`, HTTP/3, default entrypoints
  in the Helm chart.
- Traefik, File provider install reference
  (doc.traefik.io/traefik/reference/install-
  configuration/providers/others/file/) and File
  routing reference (master, doc.traefik.io/
  traefik/master/reference/routing-configuration/
  other-providers/file/) — `directory` vs
  `filename` mutually exclusive, `watch` default
  true, "does not discover services automatically",
  Go templating only in dynamic files, `@file`
  suffix for cross-provider references.
- Traefik, Install configuration options list
  (doc.traefik.io/traefik/reference/install-
  configuration/configuration-options/) —
  `core.defaultRuleSyntax` default v3,
  `providers.file.directory` (".yml or .toml").
- Traefik, v2-to-v3 migration details
  (doc.traefik.io/traefik/migrate/v2-to-v3-details/
  and v3.0) — `Headers`→`Header` rename,
  `PathPrefix` loses regexes, `Path`/`PathPrefix`
  lose `{name}` placeholders, `QueryRegexp` new,
  single-value matchers, `HostHeader` removed,
  v2 syntax deprecated, removal in next major.
- Traefik, v3.4 migration notes (doc.traefik.io/
  traefik/v3.4/migrate/v3/) — rule-syntax options
  deprecated, path normalization from v3.4.1
  (`/foo%2Fbar` no longer matches
  ``PathPrefix(`/foo/bar`)``).
- Traefik, Getting Started FAQ (v2.8,
  doc.traefik.io/traefik/v2.8/getting-started/faq/)
  — 404 situations, 404 vs 503, catch-all router
  converting 404 to 503.
- Traefik, API reference (v2.5, doc.traefik.io/
  traefik/v2.5/operations/api/) — `/api/http/routers`,
  `/api/http/routers/{name}`, `/api/tcp/routers`,
  `/api/udp/routers`, `api@internal`, dashboard
  warning.
- Traefik, HTTP Middleware overview (v2.8/v2.11,
  doc.traefik.io/traefik/v2.8/middlewares/http/
  overview/) — built-in table (AddPrefix … StripPrefix
  Regex); StripPrefix doc (`X-Forwarded-Prefix`,
  `forceSlash`).
- Traefik, Docker routing reference (doc.traefik.io/
  traefik/reference/routing-configuration/other-
  providers/docker/) — automatic service creation/
  assignment (Docker-only), `defaultRule`.
- Traefik, CLI reference (v3.0 CLI flags;
  doc.traefik.io/traefik/v3.0/reference/static-
  configuration/cli/) — flags only; command list
  from v1.6/v1.7 Basics ("Commands": version,
  storeconfig, bug, healthcheck) and the
  `docker run traefik --help` gist (PrplHaz4).
- Traefik Proxy 3.7 release notes, "Langres"
  (traefik.io/blog/traefik-proxy-3-7-is-available,
  May 2026) — middlewares on services, retries and
  failover by status code, Gateway API v1.5.1,
  Ingress NGINX provider GA, certificates view.
- Traefik Proxy 3.6 release notes and multi-layer
  routing tutorial (traefik.io/blog/traefik-proxy-
  3-6-ramequin, traefik.io/blog/multi-layer-routing-
  in-traefik) — `parentRefs`, root/intermediate/
  leaf, file-provider support, "child routers cannot
  be called directly".
- Traefik Hub, Rules & Priority and Multi-Layer
  Routing references (doc.traefik.io/traefik-hub/) —
  same matcher/priority semantics, multi-layer
  provider list.
- traefik-config-validator, otto-de (pkg.go.dev/
  github.com/otto-de/traefik-config-validator) —
  "(syntactically) validate", schemastore
  `traefik-v2.json`, YAML only, no recursive scan,
  pre-release.
- Traefik 3.8.0-rc.1 release notes (newreleases.io,
  Oct 30, 2026) and "Traefik 3.8's tap middleware
  triples request latency" (dev.to, Nov 9, 2026) —
  `tap` middleware, per-router responding timeouts,
  RC status; latest stable v3.7.17 (Oct 31, 2026,
  FreshPorts; Docker Hub `latest` = v3.7.17).
- Traefik community forum: "How to route TCP after
  matching HTTP rules?" (Oct 2024, TCP-before-HTTP
  confirmation); "HTTP router applied before TCP
  router?" (May 2023, TLS TCP router swallowing
  HTTP traffic); "404 responses to everything on
  HTTP (web)" (Dec 2025); "Its not clear how the
  pieces are interconnected" (Dec 2024, cert
  selection via `Host()`).
- ssdnodes.com, "Traefik v2 to v3 migration: what
  breaks" — independent corroboration of the v3
  syntax changes (single-value matchers,
  `PathPrefix` regex loss, `Headers` rename).
- svenvg.com, "Traefik Reverse Proxy Explained" —
  entrypoint/router/middleware/service pipeline,
  dashboard as a router to `api@internal`.

## Verdict

**BUILD APPROVED.** The gap is real and was
re-verified with fresh searches on 2026-11-10: no
native Traefik command simulates a request, the
dashboard/API only list a running instance's
routers, the only third-party validator checks
schema syntax against v2 schemas, and no plugin
answers "which router handles this request"
offline. The semantics are pinnable from primary
sources to an unusual degree for this bench: the
matcher set is a closed table, the priority rule
is arithmetic with worked examples in the docs,
the v2/v3 break is documented matcher by matcher,
and the failure modes (404 vs 503, TCP-before-HTTP,
entrypoint redirection, multi-layer routing) are
all stated in the reference. The design corrects
the IDEA record in five places: (1) the matcher
names are `Header`/`HeaderRegexp`, not
`Headers`/`HeadersRegexp`, in v3; (2)
`{name:pattern}` captures are a v2-syntax feature,
absent from v3; (3) default priority is rule
length *with* the `**` non-counting refinement
(20, not 22); (4) v3.7 adds middlewares on
services, a second chain the IDEA did not mention;
(5) v3.6 multi-layer routing (`parentRefs`) is a
new hazard the IDEA did not list, and v1 refuses
it rather than modelling it. The two genuine
risks are flagged, not hidden: the same-provider
priority tie-break is undocumented and pinned as
a [hypothesized] name-order rule (OQ-1), and the
file provider is only part of the routing table on
any deployment that also runs Docker or Kubernetes
(TR01/TR37) — the tool says so on every run.
Build in the order given, dogfood against the
docs' own examples first (BG4's 34-vs-26 case is
the acceptance test), and treat any Traefik
release that changes a pinned rule as a
design-flip event.

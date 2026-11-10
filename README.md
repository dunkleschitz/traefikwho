# traefikwho

Which Traefik router handles this request — and why did the others lose?

`traefik` has no request test: no `traefik test request`, no dry-run,
no simulation endpoint. The dashboard and API list a *running*
instance's routers; they take no described request. The only
third-party validator checks schema syntax against v2 schemas. So
today the diagnostic is live curl + a bare 404, which cannot tell
you whether a router *almost* matched, or which router was one flag
away — and it cannot tell you that the regex router (priority 34)
beat the exact-host router (priority 26) because the decider is the
longest rule, not the most specific match.

`traefikwho` is a static model of Traefik v3.7's documented
file-provider routing rules. It reads the static config and the
dynamic directory, parses the rules with a real parser, sorts by
priority, and names the winner with file:line provenance, the
service it forwards to, and the middleware chain that will run —
or NO-MATCH (live answer: 404), or UNKNOWN naming the flag that
would resolve it. No `traefik` binary is run, ever.

## Usage

```
traefikwho http --host HOST [--path PATH] [--method METHOD]
    [--header K=V]... [--query K=V]... [--client-ip IP]
    [--entrypoint NAME] [--tls | --no-tls]
    [--conf DIR] [--static FILE] [--json] [--quiet]
traefikwho tcp [--sni NAME] [--alpn PROTO] [--client-ip IP]
    [--entrypoint NAME] [--tls | --no-tls]
    [--conf DIR] [--static FILE] [--json] [--quiet]
traefikwho --list-routers [--kind http|tcp|all] [--conf DIR]
traefikwho --list-services [--kind http|tcp] [--conf DIR]
traefikwho --list-middlewares [--conf DIR]
traefikwho --version
```

`--conf` is required and has **no default**: Traefik configs live in
too many places to guess (Docker volume mounts, `/etc/traefik/`, a
repo checkout), and a wrong guess means answering from the wrong
routing table. It names the file-provider dynamic directory — every
`.yml`, `.yaml`, and `.toml` file in it, non-recursively, in
alphabetical order — or a single dynamic file (the `filename` form).
`--static` names the static config file (`traefik.yml`); if omitted,
a file literally named `traefik.yml` / `traefik.yaml` / `traefik.toml`
at the top of `--conf` is read as the static file instead. There is
no auto-discovery of `/etc/traefik/traefik.yml`: a tool that silently
reads a live proxy's config while the user meant a staging tree is a
footgun.

A request field the flags cannot express is **UNKNOWN, not absent**:
omit `--method` and a `Method(...)` term is UNKNOWN, not FALSE. The
verdict names the flag that would resolve it (`--method`,
`--header X`, `--entrypoint`, `--client-ip`, `--query`).

Verdicts and exit codes: **MATCH 0, REDIRECT 0, NO-MATCH 1** (live
answer: 404), **UNKNOWN 2**, config-fatal 2, usage error 2. A MATCH
whose service has no servers is still exit 0 with
`[service-has-no-servers]` — the router *did* win; the live answer
would be 503.

## Examples

The docs' own trap, answered (priority 34 beats 26):

```
$ traefikwho http --host foobar.traefik.com --conf ./dynamic
VERDICT MATCH — router router-1@file dynamic/app.yml:3 (priority 34) → service app@file
  rule: HostRegexp(`[a-z]+\.traefik\.com`)
  ...
  match chain (priority order):
    TRUE router-1@file dynamic/app.yml:3 (priority 34) — HostRegexp(`[a-z]+\.traefik\.com`) matches host foobar.traefik.com
    TRUE router-2@file dynamic/app.yml:6 (priority 26) — Host(`foobar.traefik.com`) matches host foobar.traefik.com
```

Why a request 404s — the chain names the deciding term per router:

```
$ traefikwho http --host example.com --path /admin --conf ./dynamic
VERDICT NO-MATCH — no router matched (live answer: 404 Not Found)
  match chain (priority order):
    FALSE admin@file dynamic/app.yml:12 (priority 41) — PathPrefix(`/admin`) does not match path /admin
    ...
```

A question the flags cannot answer yet:

```
$ traefikwho http --host example.com --conf ./dynamic
VERDICT UNKNOWN — the answer is not statically decidable
  blocker: api@file (dynamic/app.yml:9) — Method UNKNOWN (no --method supplied)
    resolve with: --method
```

TCP first, because Traefik checks TCP routers before HTTP routers
on a shared entrypoint:

```
$ traefikwho tcp --sni db.example.com --tls --entrypoint websecure --conf ./dynamic
VERDICT MATCH — router db@file dynamic/tcp.yml:3 (priority 25) → service db-svc@file
  rule: HostSNI(`db.example.com`)
  tls=passthrough
```

Inventory without a request:

```
$ traefikwho --list-routers --conf ./dynamic
$ traefikwho --list-services --conf ./dynamic
$ traefikwho --list-middlewares --conf ./dynamic
```

## What it models

- **File provider only (TR01).** Routers, services, middlewares, and
  TLS objects from the dynamic directory, plus entrypoints,
  `defaultRuleSyntax`, and `providers.precedence` from `--static`.
  Docker labels, Kubernetes CRD/Ingress, Consul, etcd, and every
  other provider are out of scope and bannered, never approximated.
- **Real rule parser (TR03/TR04).** Tokenizer + recursive descent
  over Go string literals, precedence `!` > `&&` > `||`. v3 syntax
  by default; v2 per-router via `ruleSyntax` (or
  `core.defaultRuleSyntax`), deprecated and flagged.
  `Headers`/`HostHeader` do not exist in v3 — they are config-fatals
  there, as Traefik rejects them.
- **Priority is rule length (TR12), with the `**` refinement.**
  `Host(`**.example.com`)` computes 20, below `*.example.com` at 21
  and the exact host at 23. Explicit `priority` overrides;
  `priority: 0` falls back to length; negative priorities sink.
  Same-provider ties break by router name ascending
  [hypothesized], bannered `[same-priority-tie-name-order]`.
- **Three-valued evaluation (TR13).** TRUE / FALSE / UNKNOWN, Kleene
  logic. An UNKNOWN router that could outrank the best TRUE router
  makes the verdict UNKNOWN.
- **Entrypoint and TLS scope (TR15/TR18).** Filters before rule
  evaluation. A router with a `tls` block (or on an entrypoint with
  `http.tls`) is HTTPS-only; router `tls` replaces entrypoint TLS
  wholesale, no merge.
- **TCP before HTTP (TR16).** An `http` query on an entrypoint with
  a TCP router that could claim the connection is UNKNOWN with
  `[tcp-router-may-claim-connection]`, unless the connection is
  provably non-TLS.
- **Entrypoint redirections before routing (TR20).** REDIRECT, exit
  0, except `/.well-known/acme-challenge/`, which proceeds to
  routing.
- **Middlewares (TR21/TR22).** Declared order, chains expand in
  place (a cycle is a config-fatal), classified outcome-changing /
  request-rewriting / response-only-or-opaque. Path-modifying
  middlewares print the rewritten path (`/api/users` → StripPrefix
  → `/users`). Service middlewares (v3.7) print as a second
  `service:` chain. `IPAllowList` is evaluated when `--client-ip`
  is given; auth middlewares are flagged `[auth-may-reject]`
  (credentials are not verified — see Limitations).
- **Services (TR23/TR29/TR30).** `loadBalancer` (servers listed,
  health-check state bannered), `weighted` (weights listed;
  single-member weighted names the effective service), `mirroring`
  (copy banner), `failover` (fallback banner). A service with no
  servers is MATCH + `[service-has-no-servers]` (live 503). A router
  with no service, or a service that is not defined, is a
  config-fatal — the file provider does not auto-create services.
- **Multi-layer routing refused (TR24).** Routers with `parentRefs`
  are excluded; if one's rule would match the raw request, the
  verdict is UNKNOWN with `[multi-layer-routing]`.
- **Duplicates and shadowing, out loud (TR25/TR38).** A router name
  defined in two files resolves last-file-wins with
  `[duplicate-router-shadowed]`; a router provably shadowed by a
  higher-priority literal superset gets `[shadowed-by]` in coverage.
- **Internal routers (TR34/TR35).** When `--static` enables the API,
  `api@internal` (`PathPrefix(`/api`)`), `dashboard@internal`, and
  `ping@internal` are modelled with reserved-band priorities, and
  the ACME challenge handler claims
  `/.well-known/acme-challenge/` on `web` when a `certResolver` is
  in play.

## Limitations — the honest banner list

Every run's coverage section names which of these were present; a
blocker that decided the verdict is cited on the verdict line.

- **Other providers are invisible (TR01/TR37).** A file-only answer
  on a deployment that also runs Docker or Kubernetes is a partial
  answer. If `--static` enables another provider, every verdict
  carries the banner; without `--static`, coverage says the provider
  set is unknown. Cross-provider references (`api@docker`) are
  UNKNOWN with `[cross-provider-reference]`.
- **Go templates are not evaluated.** A file containing `{{` has
  its routers excluded as UNKNOWN (`[go-template-not-evaluated]`);
  a query no clean router matches is UNKNOWN, not NO-MATCH.
- **v2 rule syntax is parsed, not embraced.** It is deprecated and
  will be removed in the next Traefik major; v1 parses it and flags
  every v2 router.
- **Auth middlewares are flagged, not decided.**
  `[auth-may-reject]` means an auth middleware is in the winning
  chain; whether *this* request's credentials pass is not evaluated
  (BasicAuth password-hash verification is out of scope for a
  stdlib-only static tool).
- **Server selection and health are runtime (TR29/TR30).** Which
  server a load balancer picks, whether a health-checked server is
  currently healthy, which weighted member receives this request —
  all bannered, none decided.
- **Rate limits, circuit breakers, in-flight counts, retries are
  runtime (TR22).** Bannered, never decidable from files.
- **Plugin middlewares are opaque (TR21).** Inventoried by name and
  type; their effect on the request is unknown.
- **ACME state is runtime (TR27).** `certResolver` is a name, not a
  certificate. A winning TLS router with no certificate source in
  the config is annotated `[default-cert-would-serve]`.
- **UDP routers have no verdict (TR33).** Listed by
  `--list-routers`, never routed; there is no `traefikwho udp` verb.
- **v3.8-only fields are flagged, not modelled (TR42).** The `tap`
  middleware and per-router `respondingTimeouts` parse and are
  flagged `[v3.8-only]`; the pin is v3.7 stable.
- **Templated TCP routers are ignored by the TCP-before-HTTP gate.**
  A Go-template file's TCP routers cannot be evaluated, so the gate
  cannot ask whether they would claim the connection; the HTTP
  verdict proceeds from the clean routers and the templated file is
  bannered in coverage.

## Open questions that affect verdicts

Pinned as [hypothesized] or [docs-inferred] in DESIGN-traefikwho.md;
each flips mechanically if the Traefik source or a live experiment
says otherwise. The ones most likely to matter:

- **OQ-1 — same-provider priority ties.** v1 breaks ties by router
  name ascending. If the real tie-break is declaration order,
  insertion order, or nondeterministic, the comparator flips — and
  if nondeterministic, tied verdicts become AMBIGUOUS.
- **OQ-4 — Host header with a port / trailing dot.** v1 strips
  `:port` and a trailing dot before `Host` matching, bannered
  `[host-port-stripped-hypothesis]` when it changes an outcome.
- **OQ-5 — path normalization beyond the documented cases.** `.` /
  `..` / duplicate slashes are cleaned and `%2F` stays encoded (both
  documented for v3.4.1); the rest follows Go's `path.Clean` plus
  the RFC 3986 reservation rule. A trailing slash is preserved:
  `Path(`/products`)` does not match `/products/`, as documented.
- **OQ-8 — query decoding.** Keys and values are URL-decoded
  (`+` → space); `?mobile=` (empty value) is present-but-valueless.
- **OQ-13 — service-middleware order, internal-router priorities,
  TCP failover.** Service middlewares run after router middlewares
  (the natural pipeline order); internal routers are ordered ACME >
  API > dashboard > ping; a TCP `failover` service is accepted and
  inventoried.
- **OQ-2 — strictness on a broken router.** Any unparseable rule is
  a config-fatal for the whole run; Traefik disables only that
  router and keeps serving the rest. A future `tolerate-broken-
  routers` flag is the honest shape for partial answers, not a
  silent default.
- **OQ-10 — file-provider merge details.** Duplicate names across
  files resolve last-file-wins; `.yaml` is accepted alongside
  `.yml`/`.toml` (the options list says ".yml or .toml");
  subdirectories are not descended.
- **OQ-11 — failure modes the docs describe but do not pin.**
  Unknown entrypoint/middleware/service references, unknown
  provider suffixes, conflicting `tls.options` for one hostname,
  missing `tls.certificates` files, and `respondingTimeouts`
  misuse are all config-fatals in v1; each is a one-line acceptance
  change with a fixture if the source says otherwise.

No `traefik` binary exists on the build machine, so no claim in v1
is [observed] — the fixture suite is the oracle, exactly as the
documentation text is the only authority.

## Pre-publish checklist

- [x] `python3 test_traefikwho.py` green (95 tests, 0.07s), also
      green under umask 022
- [x] Design review BUILD APPROVED (DESIGN-traefikwho.md, 2026-11-10)
- [x] Publish approved by Sam Nov 10, 2026 ("Concur on all projects")
- [x] `doccover` clean over README vs `--help` (20/20, 0 gaps, 0 stale)
- [x] `clicheck` (strict mode) clean (16/16)
- [x] `prepublish-check` clean (stdlib-only, no secret-like literals)
- [x] `bench-audit` clean (map entry added for traefikwho)
- [x] MIT LICENSE, copyright holder `dunkleschitz`
- [x] CI workflow `.github/workflows/tests.yml` (Python 3.12,
      runs `python3 test_traefikwho.py`)

## License

MIT — see LICENSE.

# Changelog — traefikwho

## v1.0.0 — 2026-11-10

Initial release. Build approved 2026-11-10 (DESIGN-traefikwho.md);
publish approved by Sam Nov 10, 2026 ("Concur on all projects").

- `http` and `tcp` verbs over the file provider (static config +
  dynamic YAML/TOML directory), with `--list-routers`,
  `--list-services`, and `--list-middlewares` inventory modes.
- Real rule parser (tokenizer + recursive descent, `!` > `&&` >
  `||`, Go string literals) with per-router v3/v2 syntax resolution;
  v2 syntax parsed and flagged `[v2-rule-syntax-deprecated]`.
- Three-valued (Kleene) rule evaluation; UNKNOWN routers that could
  outrank the best TRUE router make the verdict UNKNOWN, naming the
  resolving flag.
- Priority = rule length as written, with the `**` non-counting
  refinement (23/21/20); explicit `priority` overrides,
  `priority: 0` falls back to length; same-provider ties break by
  router name ascending [hypothesized], bannered.
- Entrypoint scoping, TLS scope (router `tls` replaces entrypoint
  TLS), entrypoint redirections (REDIRECT, exit 0; ACME challenge
  path exempt), and the TCP-before-HTTP gate.
- Path normalization per v3.4.1 (`.`/`..`/duplicate slashes cleaned,
  `%2F` stays encoded, trailing slash preserved).
- Middleware chains (declared order, chain expansion, cycle =
  fatal), TR22 classification, path-rewrite computation, and v3.7
  service middlewares as a second chain.
- Services: loadBalancer / weighted / mirroring / failover, with
  server lists, health banners, and the 404-vs-503 distinction
  (NO-MATCH exit 1; MATCH with no servers exit 0 +
  `[service-has-no-servers]`).
- Multi-layer routing (`parentRefs`) refused out loud; Go-template
  files unevaluated; duplicate names across files last-wins with
  findings; conservative literal shadow analysis.
- Internal routers (`api`/`dashboard`/`ping`/`acme-http`) modelled
  with reserved-band priorities when `--static` enables them.
- v3.8-only fields (`tap`, per-router `respondingTimeouts`) parse
  and are flagged, not modelled; the pin is Traefik v3.7 stable.
- 95-test stdlib-only suite (BG1–BG12), green under the default
  umask and under umask 022.

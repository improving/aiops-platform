# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository ("Security" tab, "Report a vulnerability").
Do not open a public issue, and do not post details in a discussion.

Include what you can: the affected route, chart or component, the version or
commit, and the steps to reproduce.
We will acknowledge the report, tell you what we think, and keep you informed
until it is fixed.

## Supported versions

The `main` branch and the most recent chart release are supported.
Older image tags and chart versions receive no fixes.

## Scope

This project deploys workloads into a Kubernetes cluster and hands out
credentials to them.
Reports in these areas are especially useful:

- The authentication and authorization path: the Keycloak token check, the
  `ext-authz` route decision, organization and owner scoping, personal tokens.
- The gateway objects the controllers create, and the per-instance workload
  credentials.
- The MCP endpoint and the relay to the LiteLLM proxy.
- Helm templates that render a credential into a manifest, a log or an
  annotation.
- The container images built from `backend/` and `frontend/`.

## Known and intended behaviour

These are documented design decisions, not vulnerabilities:

- `AUTH_MODE=disabled` turns authentication off.
  The backend refuses it unless `TEST_MODE=true` is also set, and it exists for
  the test suites only.
  A deployment that sets both is misconfigured, and we treat that as a
  configuration problem rather than a vulnerability in this project.
- The development stack under `infra/local/` carries literal development
  secrets (`dev-gateway-secret`, `postgres`, the `alice`/`bob`/`admin` users).
  They are for a local kind cluster and are never valid anywhere else.
- Deployed MCP servers on the `cluster` egress setting can reach every private
  address. This is recorded in ADR 0011 and accepted for version 1.

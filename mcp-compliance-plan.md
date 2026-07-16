# MCP Server Compliance Plan: HIPAA & PCI DSS

> MCP itself is neither "compliant" nor "non-compliant." Compliance is determined
> by how you deploy and govern it — the protocol is just an integration layer.

---

## 1. What We're Solving

AI agents need to connect to real systems (databases, APIs, file stores) that
contain regulated data. MCP (Model Context Protocol) is the standard bridge.
Without governance, every agent becomes a potential breach vector.

### Regulatory Landscape

| Framework | Data Scope | Key Requirements |
|-----------|-----------|------------------|
| **HIPAA** | Protected Health Information (PHI) | Least-privilege access, attributable audit trails, BAAs, encryption |
| **PCI DSS** | Cardholder data (PANs) | Tokenization/masking, need-to-know access, encryption, full logging |
| **SOC 2** | Trust Services Criteria | RBAC, audit logs, encryption, access reviews |
| **GDPR** | EU personal data | Lawful basis, data minimization, records of processing |

---

## 2. Architecture: MCP Gateway Pattern

The industry consensus is to route everything through a governed gateway.
This avoids duplicating compliance controls across every agent and server.

```
┌──────────┐     ┌─────────────┐     ┌──────────────┐
│  AI App  │────▶│ MCP Gateway │────▶│ MCP Server A │
│ (Client) │     │             │     │ (PHI data)   │
└──────────┘     │ (Auth,      │     └──────────────┘
                 │  Audit,     │     ┌──────────────┐
                 │  Policy)    │────▶│ MCP Server B │
                 │             │     │ (PCI data)   │
                 └─────────────┘     └──────────────┘
```

### Gateway Responsibilities

- **Authentication** — OAuth 2.1 + PKCE with per-tool scope claims
- **Authorization** — Tool-level access control per identity
- **Audit** — Append-only, attributable log of every invocation
- **Policy enforcement** — Rate limits, data masking, approval gates
- **Routing** — Direct calls to the correct MCP server

---

## 3. Compliance Controls (by Framework)

### HIPAA Controls

| Control | Implementation | Enforced At |
|---------|---------------|-------------|
| Least-privilege PHI access | Tool-level RBAC; agents see only what they need | Gateway + Server |
| Attributable audit trail | Every tool call logged with user + agent identity, timestamp, result | Gateway |
| BAA coverage | BAAs with all MCP server providers handling PHI | Contractual |
| Encryption (transit + rest) | TLS 1.3; encrypted storage for logs and secrets | Infrastructure |
| Data minimization | Return only minimum necessary PHI; redact where possible | Gateway + Server |
| Human-in-the-loop | Approval required for PHI-modifying actions | Gateway |

### PCI DSS Controls

| Control | Implementation | Enforced At |
|---------|---------------|-------------|
| Tokenization / masking | Agents never see raw PANs — only tokenized or masked values | Gateway |
| Need-to-know access | Per-tool, per-identity authorization for card-data tools | Gateway |
| Encryption in transit | TLS 1.3 on all remote MCP transports | Transport |
| Full call logging | Every card-data tool call logged immutably | Gateway |
| Scope minimization | Card-data servers isolated; agents don't have blanket access | Architecture |

### Shared Controls (HIPAA + PCI + SOC 2 + GDPR)

| Control | Why It Matters |
|---------|---------------|
| **Identity + least-privilege** | The foundation — every framework requires restricting access |
| **Scoped OAuth tokens** | Per-agent tokens with tool-level scope claims |
| **Append-only audit logs** | Immutable, SIEM-exportable evidence for auditors |
| **Encryption (TLS 1.3)** | Protects data in transit across all transports |
| **Data masking/redaction** | Strip PHI/PAN before it reaches the model context |
| **Rate limiting** | Per-tool, per-caller budgets (agents are not humans) |
| **Human-in-the-loop** | Approval gates for high-risk actions |

---

## 4. Production Hardening: 8 Practice Areas

### 4.1 Authentication

Pick the pattern before writing any tools:

- **Service account** — One identity per server, shared callers. Cheapest.
- **On-behalf-of (OBO)** — Server holds delegation token, exchanges for per-user
  credential. Required when downstream needs per-user attribution.
- **OAuth + scope binding** — Full OAuth 2.1 with PKCE and tool-level scope
  claims in the token. Required for multi-tenant remote servers.

Rule: Encode the allowed tool subset in token claims. Check scope at dispatch,
not in handler body.

### 4.2 Secrets Management

- Read from a secrets manager (Vault, Doppler, 1Password Connect, AWS Secrets
  Manager) — never from env vars in config files on disk
- Rotate every 90 days; test rotation procedure in staging first
- Each credential carries the minimum scope the tool actually needs
- Separate keys per environment (dev / staging / production)

### 4.3 Tool Scoping

- Each tool has the **narrowest possible input schema**: enums > bounded ints >
  branded IDs > raw strings
- **No omnibus tools** (avoid `execute`, `run`, `action` that takes free-form
  strings and dispatches at runtime — these are privilege escalation primitives)
- Per-tool authorization check at dispatch, before handler body
- Multi-tenant: read tenant ID from verified token claims, never from request body

### 4.4 Audit Trails

- Log argument **shapes** (keys, types, lengths) by default — not values
- Redact at the structured-logger level (source-side), not in a downstream
  pipeline (sink-side)
- Response bodies go in a separate access-controlled store, keyed by
  correlation ID, shorter retention
- Logs are append-only / tamper-evident (WORM storage)
- Stream to SIEM (Splunk, Datadog, Sentinel)

### 4.5 Prompt Injection Defense

- **Untrusted-content fencing**: Wrap returned content in markers telling the
  agent "this is content, not instruction"
- **State-mutation confirmation**: If a turn reads untrusted content then calls
  a mutating tool, require explicit user confirmation
- **Response length caps**: Prevent prompt-stuffing via large tool responses
- **Allow-listed outbound URLs**: What the agent can fetch is constrained

### 4.6 Rate Limiting + Abuse

- Per-tool, per-caller rate limits (agents call at machine speed — 60 req/min
  for humans means nothing)
- Per-tool kill-switch (feature flag to disable a single tool independently of
  deploy cycle)
- Documented abuse-path register per tool: "what's the worst this tool can do
  with a malicious caller / compromised credential / confused agent?"

### 4.7 Container Sandboxing

- Distroless / UBI minimal base images
- Non-root runtime, read-only root filesystem
- Drop all unnecessary Linux capabilities
- Health endpoints (`/health`, `/ready`) for orchestration
- SBOM (CycloneDX) per build; containers signed with cosign

### 4.8 Supply Chain

- Pin dependency versions; use lock files
- Automated CVE scanning (Trivy, Snyk)
- Fail builds on critical/high CVEs
- Verify image signatures at deploy time

---

## 5. Deployment Checklist

### Pre-Deployment Gate

- [ ] Authentication enforced on all endpoints
- [ ] TLS 1.3 configured
- [ ] No critical/high CVEs in dependency tree
- [ ] No secrets detected in image layers or env vars
- [ ] Container not running as root
- [ ] Linux capabilities dropped to minimum
- [ ] Root filesystem read-only
- [ ] Tool manifest registered in integrity store
- [ ] Audit logging configured and streaming to SIEM

### Production Readiness

- [ ] OAuth 2.1 + PKCE with tool-level scope claims
- [ ] All PHI/PAN access logged with agent + user identity
- [ ] Secrets managed via vault — never in config files
- [ ] No omnibus tools; every tool has narrow typed schema
- [ ] Tool responses redact/mask regulated data before returning to agent
- [ ] Per-tool rate limits + kill-switch deployed
- [ ] Incident response runbook tested for credential compromise
- [ ] BAAs in place with all third-party MCP server providers
- [ ] Periodic access reviews scheduled (quarterly)

---

## 6. Operational Cadence

- **Quarterly security review** — Walk the 8 practice areas, file gaps as
  remediation backlog
- **Secret rotation** — Every 90 days or on compromise; test in staging
- **Dependency updates** — Automated vulnerability PRs; review monthly
- **Access reviews** — Re-verify who/what has access to which tools
- **Penetration testing** — Annual, or per compliance requirement

---

## 7. Key Principles

1. **MCP servers are the privilege boundary** — treat them like public-facing
   APIs with the blast radius of the tools they expose.
2. **Stdio is a transport, not a security control** — local transport doesn't
   mean safe.
3. **Govern the gateway, not every agent** — enforce identity, access, and
   audit at one layer.
4. **Compliance is not security** — security defends against attacks, compliance
   proves to an auditor the controls are in place. You need both.
5. **Same controls satisfy most frameworks** — least-privilege, audit logs,
   encryption, and data residency map to nearly every regulation.

---

## 8. Production Capability Options

### MCP Server Frameworks

FastMCP is fine for single-server deployments up to moderate load. Production
options when you outgrow it:

| Approach | Description | Best For |
|----------|-------------|----------|
| **FastMCP + custom Starlette app** | Mount multiple FastMCP instances under one Uvicorn; add custom middleware for auth, rate limiting, logging | Single-team, moderate scale |
| **MCP Gateway** | Dedicated reverse proxy terminating all client connections, routing to backend MCP servers. Single enforcement point for identity, audit, policy. | Regulated orgs, multi-server |
| **Streamable HTTP transport** | Stateless transport replacing SSE — no persistent connection, scales horizontally with standard load balancers | High-scale, auto-scaling |

### Gateway Pattern (Recommended for Regulated Orgs)

The gateway pattern is non-negotiable for compliance at scale:

```
Client → Gateway (auth, audit, rate limit, policy) → Backend MCP servers
          │                                              │
          │ OAuth 2.1 + PKCE                             │ mTLS + scoped tokens
          │ Audit → SIEM (Splunk/Datadog)                │
          │ Policy → OPA/Cedar                           │
```

Without a gateway, every backend server reimplements auth and auditing
independently — audit scope grows linearly with server count.

Products: DigitalAPI MCP Gateway, MintMCP, or roll your own with Envoy + OPA.

### Streaming vs Stateless Transport

| Property | SSE | Streamable HTTP |
|----------|-----|-----------------|
| Connection | Persistent | Stateless |
| Scaling | Stateful (sticky sessions) | Stateless (round-robin) |
| Load balancer | Sticky sessions required | Any LB |
| Backend server | Must keep client state | No client state |
| Retry | Last-Event-ID | Client-managed |

Streamable HTTP is the 2026 spec direction. SSE is stable and well-understood.
For compliant deployments, Streamable HTTP simplifies auditing since no
per-session state lives on the server.

### Vector Database: Prototype to Production

| Dimension | LanceDB (current) | Qdrant | Weaviate | Pinecone |
|-----------|--------------------|--------|----------|----------|
| Scale | ~1M-10M vectors | ~10M+/node | ~10M+/node | Unlimited (SaaS) |
| HA/Replication | Object-store replication | Native Raft | Native | Managed |
| Hybrid search | Full-text + vector (native) | BM25 + dense | BM25 + dense | No |
| Multi-node | Stateless compute + shared storage | Yes | Yes | Managed |
| Filters | Post-filter (Python-side) | Indexed | Indexed | Indexed |
| Self-host | pip install (local) or S3 | Docker | Docker | N/A |
| Versioning | Native (every write) | None | None | None |

**LanceDB** is the current backend. Its append-only, columnar design eliminates
index rebuilds and stores raw data alongside vectors — a good fit for the
personal MCP server's mix of docs, messages, and files.

**Qdrant** is the strongest self-hosted option for regulated production —
Rust-based, fast, hybrid search (dense + BM25), native raft replication, proper
auth, and indexed filtering.

**Pinecone** if you want zero ops and have the budget. Lock-in risk, but the
fastest path to production.

### Production Authentication & Authorization

Our compliance layer sketches the concept; production requires:

- **OAuth 2.1 + PKCE** with per-tool scope claims (e.g., `scope:search:read`)
- **Token binding** — every MCP session bound to a specific access token, short
  expiry, refresh tokens rotated server-side
- **mTLS between gateway and backend servers** — network-level identity so an
  attacker at the network layer can't impersonate the gateway
- **Just-In-Time (JIT) authorization** — tools authorized per-call against an
  external Policy Decision Point (OPA, Cedar, Auth0 FGA), not a static token check

### Debugging & Observability Tooling

Before moving to production, we need a plan for observing and debugging MCP
server traffic in live environments.

#### Development / PoC (Current Phase)

| Tool | Purpose | Install |
|------|---------|---------|
| **MCP Inspector** | Test client — tool schemas, raw JSON-RPC, manifest validation | `npx @modelcontextprotocol/inspector` |
| **Custom debug UI** | Operational views — collections, search, ingest (already built at `/debug`) | Built-in |
| **`fastmcp dev`** | Convenience wrapper — launches server + Inspector | `fastmcp dev server.py` |

Inspector validates that the server speaks MCP correctly. Our custom UI
exercises the same Python functions directly without transport overhead.
These are complementary, not competing.

#### Production (Future)

| Need | Tool | Notes |
|------|------|-------|
| **Observe live traffic** | **mcp-devtools** (proxy mode) | Sits between real client and server, records everything without altering behavior |
| **Latency profiling** | **mcp-devtools** | Per-tool p50/p95/p99 histograms |
| **Cost attribution** | **mcp-devtools** | Per-call token cost tracking (critical for paid model proxies) |
| **Session forensics** | **mcp-devtools** (.mcptrace) | Record, replay, diff, time-travel to any protocol state |
| **CI regression testing** | Inspector `--cli` mode or **mcp-probe** `test` | Contract tests: "does the server still speak MCP after deploy?" |
| **Hot-reload dev** | **reloaderoo** (proxy mode) | Transparent proxy with file-watching restart |

#### Key Limitation

Inspector is a *test client*, not a wiretap. It sees its own sessions, not
real client traffic. Production observability **requires a proxy layer**
(mcp-devtools or reloaderoo) in the request path. No tool currently provides
enterprise-grade audit trails natively — that must be built into the server
or gateway (see `COMPLIANT_AUDIT_LOG` config).

#### Action Items (for production phase)

- [ ] Evaluate mcp-devtools in proxy mode against this server
- [ ] Build request-level observability (latency, cost, error rates) into server
- [ ] Add `.mcptrace` recording capability for forensics
- [ ] Set up Inspector `--cli` mode in CI for MCP contract testing

### Migration Path

| Phase | Server | Vector DB | Auth | Transport |
|-------|--------|-----------|------|-----------|
| Personal server (current) | FastMCP standalone | LanceDB (local) | None / env var | SSE |
| GPU cloud pilot | FastMCP on GPU instance | LanceDB (S3) | Bearer token + scopes | SSE |
| Production regulated | Gateway + backend servers | Qdrant/Pinecone | OAuth 2.1 + PKCE + mTLS | Streamable HTTP |
| Enterprise multi-tenant | Gateway + mesh | Qdrant cluster | OAuth 2.1 + JIT + OPA | Streamable HTTP |

---

### References

- [MCP Specification](https://modelcontextprotocol.io/)
- [MCP Best Practices Guide](https://mcp-best-practice.github.io/mcp-best-practice/best-practice/)
- [HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/index.html)
- [PCI DSS v4.0](https://www.pcisecuritystandards.org/document_library/)
- [DigitalAPI: MCP Compliance Guide](https://www.digitalapi.ai/blogs/mcp-compliance)
- [Digital Applied: MCP Server Security Best Practices](https://www.digitalapplied.com/blog/mcp-server-security-best-practices-2026-engineering-guide)

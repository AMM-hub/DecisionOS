# Ruflo × DecisionOS Integration

Ruflo (v3.42.0) is an enterprise agent orchestration meta-harness — 100+ specialized
agents, coordinated swarms, self-learning memory, federation, and MCP integration.
This document maps Ruflo's capabilities onto DecisionOS's architecture.

## Why Ruflo?

DecisionOS needs an **AI Gateway** (spec §20) that routes user queries to the right
analytical engine, manages provider abstraction, tracks cost, and enforces data
privacy. Ruflo provides battle-tested patterns for exactly this kind of
agent routing and orchestration.

## Integration Points

### 1. Multi-Agent Swarms → DecisionOS AI Gateway

Ruflo's `ruflo-swarm` plugin coordinates hierarchical agent teams with
anti-drift topology. This maps directly to DecisionOS's AI Gateway:

| Ruflo Concept | DecisionOS Mapping |
|---------------|-------------------|
| Swarm router | Query planner that routes to NL2SQL, forecasting, or scenario engine |
| Agent spawn | Spawn analytical workers per query type |
| Task lifecycle | Query → plan → execute → evidence → explanation |
| Hooks system | Pre/post query validation, audit logging |
| Memory retrieval | Cache frequent queries, learn from corrections |

### 2. RAG Memory → DecisionOS Semantic Layer

Ruflo's `ruflo-rag-memory` (HNSW vector search + hybrid SQLite/AgentDB) maps
to DecisionOS's Business Definitions Layer (spec §5):

- Store metric definitions as semantic vectors
- Retrieve relevant definitions for ambiguous queries
- Cache golden answers for regression detection
- Learn from user corrections to improve future answers

### 3. Workflows → DecisionOS Scenario Studio

Ruflo's `ruflo-workflows` provides reusable multi-step pipelines that map
to DecisionOS's Scenario & Decision Studio (spec §13):

- Define scenario templates as workflows
- Compare "what-if" alternatives as parallel branches
- Track decision outcomes as workflow completions

### 4. Federation → Multi-Tenant Deployment

Ruflo's `ruflo-federation` enables secure cross-machine agent collaboration,
mapping to DecisionOS's multi-tenant architecture:

- Per-tenant isolated agent pools
- Cross-tenant data never crosses agent boundaries
- Federated audit logs

## Getting Started

### Install Ruflo in DecisionOS

```bash
cd C:\Users\AMD\Desktop\DecisionOS
npm install ruflo
npx ruflo init     # creates .claude/, MCP config, hooks
npx ruflo doctor    # verify health
```

### Plugins for DecisionOS

```bash
# Core + Swarm (agent routing)
npx ruflo plugin install ruflo-core
npx ruflo plugin install ruflo-swarm

# Memory (semantic definitions cache)
npx ruflo plugin install ruflo-rag-memory

# Workflows (scenario templates)
npx ruflo plugin install ruflo-workflows

# Cost tracking (AI spend budgets)
npx ruflo plugin install ruflo-cost-tracker
```

## Architecture Integration

```
User Query
    |
    v
DecisionOS Nuxt Frontend  ──→  DecisionOS Python API (:8100)
    |                                |
    v                                v
Ruflo Swarm Router ──────────→  Analytical Engine
    |                                |
    v                                v
Ruflo Memory ←──── Cache ────→  Evidence Store
    |
    v
DecisionOS Laravel API (:8000)
    |
    v
PostgreSQL / SQLite
```

## Key Files

| Path | Description |
|------|-------------|
| `ref-ruflo/README.md` | Ruflo full documentation |
| `ref-ruflo/AGENTS.md` | All 100+ agent definitions |
| `ref-ruflo/SKILL.md` | Skill integration guide |
| `ref-ruflo/ruflo-explained.md` | 14-chapter conceptual guide |
| `ref-ruflo/plugins/` | All 35+ plugin configurations |
| `ref-ruflo/CLAUDE.md` | Claude Code agent harness instructions |
# salary_demo

A small demo of grounding an LLM's answer in a knowledge graph instead of letting it reason
freely over raw numbers.

It answers one question — "why is my salary less than last month?" — for a single employee,
by building a *verified context block* from payroll data + an OWL ontology, then handing
that block (and only that block) to Claude. The model can explain the numbers, but it can't
invent a change that isn't explicitly listed.

## Pipeline

```
SQL (schema.sql) -> knowledge graph (typed by ontology.ttl) -> graph query -> diff -> verified-context string -> Claude
```

The knowledge graph step has two interchangeable backends — an in-memory RDF graph queried
with SPARQL (`rdflib`, default, no external service needed), and Neo4j queried with Cypher
(opt-in, requires Docker). Both produce identical output; everything downstream of the graph
query doesn't know or care which one ran.

## Install

```bash
python3 -m venv .venv        # if .venv doesn't already exist
.venv/bin/pip install rdflib anthropic neo4j
export ANTHROPIC_API_KEY=sk-ant-...
```

`rdflib` and `anthropic` are required no matter which graph backend you use. `neo4j` (the
Python driver) is only needed if you plan to run the Neo4j option below — skip it if you're
only using the default.

## Test / run

Pick one of the two graph backends. Both walk the exact same SQL → graph → diff → Claude
pipeline and produce identical output — only the middle step (how the knowledge graph is
stored and queried) differs.

### Option A — default (in-memory RDF graph + SPARQL)

No external service required:

```bash
.venv/bin/python agent.py
```

Expected output starts with:

```
[graph backend: rdflib]

<verified_context>
QUESTION : "Why is my salary less than last month?"
...
```

### Option B — Neo4j + Cypher

Requires Docker.

```bash
docker compose up -d                              # starts Neo4j (bolt://localhost:7687)
GRAPH_BACKEND=neo4j .venv/bin/python agent.py
```

Neo4j takes a few seconds to finish booting after `docker compose up -d`; if the run fails
to connect, wait a moment and retry. Expected output starts with:

```
[graph backend: neo4j]

<verified_context>
QUESTION : "Why is my salary less than last month?"
...
```

The `<verified_context>` block (and everything below it) should be byte-for-byte identical
between Option A and Option B — that's the point of having two backends share one pipeline.
Connection defaults (`bolt://localhost:7687`, `neo4j` / `salarydemo123`) match
`docker-compose.yml`; override with `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` if you're
pointing at a different instance. When you're done, `docker compose down` stops the
container.

## Files

| File | Role |
|---|---|
| `agent.py` | The whole pipeline, both graph backends, and the Claude API call |
| `schema.sql` | SQLite schema + seed payroll data for one employee, two months |
| `ontology.ttl` | OWL class hierarchy (`Earning`/`Deduction` -> `Gross`/`Bonus`/`Tax`/`Insurance`/`Pension`) |
| `query.rq` | SPARQL query used by the rdflib backend |
| `query.cypher` | Cypher equivalent used by the Neo4j backend |
| `docker-compose.yml` | Local Neo4j instance for the Neo4j backend |
| `glossary.json` | Plain-English term definitions (not yet wired into `agent.py`) |

See `CLAUDE.md` for a deeper architectural walkthrough.

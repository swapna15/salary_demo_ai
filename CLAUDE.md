# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small, single-file demo of grounding an LLM's answer in a knowledge graph instead of raw
SQL. It answers "why is my salary less than last month?" for one employee by building a
*verified context block* from SQL data + an OWL ontology, then handing that block to Claude
instead of letting the model reason freely over numbers.

The point of the demo is the pipeline, not the LLM call: **SQL → knowledge graph (typed by
ontology) → graph query → diff → verified-context string → prompt**. The graph step has two
interchangeable backends (see `GRAPH_BACKEND` below) — both produce identical output, since
`diff_months` onward is backend-agnostic.

## Setup & running

No `requirements.txt` exists yet; the checked-in `.venv` has no packages installed. Before
running:

```bash
.venv/bin/pip install rdflib anthropic neo4j
export ANTHROPIC_API_KEY=sk-ant-...   # simple_llm() calls the real Claude API
.venv/bin/python agent.py
```

Everything through `build_context()` (SQL → graph → query → diff) runs with no credentials;
only the final `simple_llm()` call needs `ANTHROPIC_API_KEY`.

**Graph backend** is selected via `GRAPH_BACKEND` (default `rdflib`, no external service
needed):

```bash
docker compose up -d                          # starts Neo4j (bolt://localhost:7687)
GRAPH_BACKEND=neo4j .venv/bin/python agent.py
```

Connection defaults (`bolt://localhost:7687`, `neo4j` / `salarydemo123`) match
`docker-compose.yml` and can be overridden via `NEO4J_URI` / `NEO4J_USER` /
`NEO4J_PASSWORD`.

There is no test suite, linter, or build step in this repo.

## Architecture

Everything lives in `agent.py`, run top-to-bottom from `__main__`. Each stage feeds the next:

1. **`build_db()`** — loads `schema.sql` into an in-memory SQLite DB. `schema.sql` defines
   `employees` and a flat `payroll(emp_id, month, component, amount)` table, with component
   one of `GROSS / BONUS / TAX / INSURANCE / PENSION`. Seed data hardcodes one employee
   (`E-102`, Priya) across `2026-06` and `2026-07`.

2. **`sql_to_graph(con)`** — parses `ontology.ttl` (the OWL class hierarchy) into an
   `rdflib.Graph`, then walks every `payroll` row and asserts triples typing each pay item by
   its ontology class via the `CLASS_OF` dict (SQL component string → `pay:` RDF class, e.g.
   `"BONUS" -> PAY.Bonus`). This is the join point between raw data and semantics — a
   component only shows up correctly downstream if it's both in `CLASS_OF` here *and*
   declared in `ontology.ttl`.

3. **`ontology.ttl`** — the class hierarchy: `PayItem` → `Earning`/`Deduction` →
   concrete classes (`Gross`, `Bonus` under `Earning`; `Tax`, `Insurance`, `Pension` under
   `Deduction`). `pay:Bonus` carries an `rdfs:comment` flagging it as one-time/non-recurring —
   this annotation is what lets `build_context()` add the "(one-time, per ontology)" caveat
   instead of that being hardcoded logic.

4. **`query.rq`** — the SPARQL query run against the graph. Pulls `(month, kind, class,
   amount)` for `pay:E-102` where `kind` is `Earning` or `Deduction`, derived via
   `rdfs:subClassOf`. Adding a new component only requires it to be a subclass of `Earning` or
   `Deduction`; the query itself doesn't need to change.

5. **`fetch_pay_items(g)`** — executes `query.rq`, groups results into `{month: [(kind,
   class, amount), ...]}`.

### Alternative graph backend: Neo4j

`sql_to_neo4j(con, driver)` / `fetch_pay_items_neo4j(driver)` are a parallel implementation
of steps 2–5 against Neo4j instead of rdflib, selected by `GRAPH_BACKEND=neo4j` in
`__main__`. Both backends return the exact same `{month: [(kind, class, amount), ...]}`
shape, so everything from `diff_months` onward doesn't know or care which backend produced
it.

- **`parse_ontology_classes()`** reads `ontology.ttl` once (via a throwaway `rdflib.Graph`)
  and returns `(class, superclass)` pairs — `ontology.ttl` stays the single source of truth
  for the class hierarchy even though Neo4j has no native RDFS/OWL reasoner.
- **`sql_to_neo4j`** wipes the graph (fine for this single-employee demo dataset — don't
  reuse that `DETACH DELETE` against a real dataset), writes the ontology as
  `(:OntClass)-[:SUBCLASS_OF]->(:OntClass)` chains, then writes each payroll row as a
  `(:PayItem)-[:TYPE]->(:OntClass)` edge — `:TYPE` is the Cypher analog of RDF's `rdf:type`.
- **`query.cypher`** mirrors `query.rq` exactly: it walks `[:SUBCLASS_OF*1..]` at query time
  to resolve each item's `kind` (`Earning`/`Deduction`), rather than precomputing it at write
  time. This is deliberate — it's what preserves the "adding a new component needs no query
  change" property from the rdflib path (see Extending, below).
- `docker-compose.yml` runs `neo4j:5-community` with browser UI on `:7474` and bolt on
  `:7687`.

6. **`diff_months(months, prev, cur)`** — the only place with actual business logic. Computes
   net pay per month as `sum(Earnings) - sum(Deductions)` and produces a signed per-class
   delta list. This is what encodes `netPay = Earnings - Deductions` — the ontology's `kind`
   (Earning/Deduction) determines the sign, not a hardcoded per-component rule.

7. **`build_context(...)`** — renders a `<verified_context>...</verified_context>` block:
   the question, a semantic note, net-pay figures, and one `CHANGE:` line per differing
   component, each showing direction and magnitude. This string is the only thing the LLM
   stage is allowed to reason over.

8. **`simple_llm(context)`** — calls the Claude API (`claude-opus-4-8` via the `anthropic`
   SDK) with the context block plus a one-line task instruction ("explain this kindly.
   Invent nothing."). The `<verified_context>` block is the only source of numbers the model
   is given — it can't invent a change that isn't listed in `CHANGE:` lines.

`glossary.json` is a separate, currently-unused semantic layer — plain-English definitions
(e.g. "salary" = net take-home pay, not gross) intended to disambiguate user terminology
before it hits the pipeline. Nothing in `agent.py` reads it yet.

### Extending with a new pay component

To add a component (e.g. the `PENSION` exercise already reflected in `schema.sql`), three
places must stay in sync: the `INSERT INTO payroll` row (SQL), the class + `subClassOf`
declaration in `ontology.ttl`, and the `CLASS_OF` mapping in `agent.py`. Neither `query.rq`
nor `query.cypher` nor `diff_months` need changes — that's the design point of routing
everything through the ontology's `Earning`/`Deduction` hierarchy instead of switching on
component name, and it holds for both graph backends.

import json, os, sqlite3
import anthropic
from rdflib import Graph, Literal, Namespace, RDF
from rdflib.namespace import RDFS

PAY = Namespace("https://hr.example/pay#")

CLASS_OF = {
    "GROSS": PAY.Gross,
    "BONUS": PAY.Bonus,
    "TAX": PAY.Tax,
    "INSURANCE": PAY.Insurance,
    "PENSION": PAY.Pension  # Added Pension to the ontology mapping
}


def build_db():
    con = sqlite3.connect(":memory:")
    con.executescript(open("schema.sql").read())
    return con


def sql_to_graph(con):
    g = Graph()
    g.parse("ontology.ttl", format="turtle")

    for emp, month, comp, amount in con.execute("SELECT * FROM payroll"):
        item = PAY[f"item-{emp}-{month}-{comp}"]
        g.add((item, RDF.type, CLASS_OF[comp]))  # typed by the ontology!
        g.add((item, PAY.ofEmployee, PAY[emp]))
        g.add((item, PAY.inMonth, Literal(month)))
        g.add((item, PAY.amount, Literal(amount)))

    return g

def fetch_pay_items(g):
    months = {}
    for row in g.query(open("query.rq").read()):
        month = str(row.month)
        kind = str(row.kind).split("#")[-1]  # Earning / Deduction
        cls = str(row["class"]).split("#")[-1]  # Gross / Bonus / Tax ...
        months.setdefault(month, []).append((kind, cls, float(row.amount)))
    return months


def parse_ontology_classes():
    """(class_name, superclass_name) pairs from ontology.ttl's rdfs:subClassOf edges."""
    onto = Graph()
    onto.parse("ontology.ttl", format="turtle")
    return [
        (str(cls).split("#")[-1], str(sup).split("#")[-1])
        for cls, _, sup in onto.triples((None, RDFS.subClassOf, None))
    ]


def sql_to_neo4j(con, driver):
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")  # demo reset — single-employee dataset

        for cls, sup in parse_ontology_classes():
            session.run(
                "MERGE (c:OntClass {name: $cls}) "
                "MERGE (s:OntClass {name: $sup}) "
                "MERGE (c)-[:SUBCLASS_OF]->(s)",
                cls=cls, sup=sup,
            )

        for emp, month, comp, amount in con.execute("SELECT * FROM payroll"):
            cls_name = str(CLASS_OF[comp]).split("#")[-1]
            session.run(
                "MERGE (item:PayItem {id: $id}) "
                "SET item.ofEmployee = $emp, item.inMonth = $month, item.amount = $amount "
                "MERGE (cls:OntClass {name: $cls}) "
                "MERGE (item)-[:TYPE]->(cls)",
                id=f"item-{emp}-{month}-{comp}", emp=emp, month=month, amount=amount, cls=cls_name,
            )


def fetch_pay_items_neo4j(driver, emp="E-102"):
    cypher = open("query.cypher").read()
    months = {}
    with driver.session() as session:
        for record in session.run(cypher, emp=emp):
            months.setdefault(record["month"], []).append(
                (record["kind"], record["class"], float(record["amount"]))
            )
    return months


def diff_months(months, prev="2026-06", cur="2026-07"):
    def net(items):
        return sum(a if k == "Earning" else -a for k, _, a in items)

    def by_class(items):
        return {c: (k, a) for k, c, a in items}

    p, c = by_class(months[prev]), by_class(months[cur])
    changes = []
    for cls in sorted(set(p) | set(c)):
        pk, pa = p.get(cls, (None, 0.0))
        ck, ca = c.get(cls, (None, 0.0))
        kind = pk or ck
        if pa != ca:
            delta = (ca - pa) if kind == "Earning" else -(ca - pa)
            changes.append((cls, kind, pa, ca, delta))
    return net(months[prev]), net(months[cur]), changes

def build_context(question, net_prev, net_cur, changes):
    lines = [
        f'QUESTION : "{question}"',
        "SEMANTIC : salary = net take-home pay ; last month = 2026-06",
        f"NET PAY : 2026-06 = ${net_prev:,.0f} 2026-07 = ${net_cur:,.0f}"
        f" difference = ${net_cur - net_prev:,.0f}",
    ]
    for cls, kind, pa, ca, delta in changes:
        note = " (one-time, per ontology)" if cls == "Bonus" else ""
        lines.append(
            f"CHANGE : {cls} ({kind}) ${pa:,.0f} -> ${ca:,.0f}"
            f" = {'-' if delta < 0 else '+'}${abs(delta):,.0f} on net{note}"
        )
    lines.append("RULE : netPay = Earnings - Deductions (ontology.ttl)")
    return "<verified_context>\n" + "\n".join(lines) + "\n</verified_context>"

def simple_llm(context):
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": context + "\nTASK: explain this kindly. Invent nothing.",
        }],
    )
    return next(block.text for block in response.content if block.type == "text")


if __name__ == "__main__":
    question = "Why is my salary less than last month?"
    con = build_db()

    backend = os.environ.get("GRAPH_BACKEND", "rdflib")  # rdflib | neo4j
    if backend == "neo4j":
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            auth=(
                os.environ.get("NEO4J_USER", "neo4j"),
                os.environ.get("NEO4J_PASSWORD", "salarydemo123"),
            ),
        )
        sql_to_neo4j(con, driver)  # DATA -> KG
        months = fetch_pay_items_neo4j(driver)  # KG + ONTOLOGY
        driver.close()
    else:
        g = sql_to_graph(con)  # DATA -> KG
        months = fetch_pay_items(g)  # KG + ONTOLOGY

    print(f"[graph backend: {backend}]\n")
    net_prev, net_cur, changes = diff_months(months)  # DECISION
    ctx = build_context(question, net_prev, net_cur, changes)
    print(ctx)
    print()
    print(simple_llm(ctx))


// Cypher equivalent of query.rq — walks the ontology's SUBCLASS_OF chain at query
// time, the same way SPARQL's `?class rdfs:subClassOf ?kind` does. Adding a new pay
// component still requires no change here, same as query.rq.
MATCH (item:PayItem {ofEmployee: $emp})-[:TYPE]->(cls:OntClass)-[:SUBCLASS_OF*1..]->(kind:OntClass)
WHERE kind.name IN ["Earning", "Deduction"]
RETURN item.inMonth AS month, kind.name AS kind, cls.name AS class, item.amount AS amount
ORDER BY month, kind

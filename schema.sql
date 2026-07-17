CREATE TABLE employees (
emp_id TEXT PRIMARY KEY,
name TEXT,
grade TEXT
);

CREATE TABLE payroll (
emp_id TEXT,
month TEXT, -- '2026-06' or '2026-07'
component TEXT, -- TAX / INSURANCE / GROSS / BONUS
amount REAL);

INSERT INTO employees VALUES ('E-102', 'Priya', 'L4'); -- June: 5000 + 500 bonus - 900 tax - 200 insurance = 4400 net
INSERT INTO payroll VALUES ('E-102','2026-06','GROSS',5000);
INSERT INTO payroll VALUES ('E-102','2026-06','BONUS',500);
INSERT INTO payroll VALUES ('E-102','2026-06','TAX',900);
INSERT INTO payroll VALUES ('E-102','2026-06','INSURANCE',200); -- July: 5000 - 950 tax - 250 insurance =3800 net (no bonus!)
INSERT INTO payroll VALUES ('E-102','2026-07','GROSS',5000);
INSERT INTO payroll VALUES ('E-102','2026-07','TAX',950);
INSERT INTO payroll VALUES ('E-102','2026-07','INSURANCE',250);


-- Exercise 1:
-- Add a PENSION component ($100, July only) to schema.sql, 
-- add pay:Pension as a Deduction in ontology.ttl, 
-- and add it to CLASS_OF . Re-run. The diff should now show four changes without touching the query or the math.
INSERT INTO payroll VALUES ('E-102','2026-07','PENSION',100);
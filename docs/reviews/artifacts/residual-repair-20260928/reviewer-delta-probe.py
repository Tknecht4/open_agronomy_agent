"""Independent bounded contrasts; no model or network access."""
import hashlib
import json
from pathlib import Path

from agronomy_agent.answer_verifier import assess_claim_risk, _looks_incomplete
from agronomy_agent.method_context import requested_methods
from agronomy_agent.quantity_claims import unsupported_quantities

root = Path(__file__).resolve().parents[2]
manifest = json.loads((root / 'docs/reviews/artifacts/residual-repair-20260928/review-candidate.json').read_text())
assert all(hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
           for row in manifest['runtime_and_tests'])
rows = []


def record(kind, inputs, expected, actual):
    rows.append(dict(kind=kind, inputs=inputs, expected=expected, actual=actual, passed=expected == actual))


for evidence, answer, unsupported in [
    ('Mass: 120 kg.', 'Mass: 20 kg.', True),
    ('Mass: 1,200 kilograms.', 'Mass: 1200 kg.', False),
    ('Temperature: -5 C.', 'Temperature: 5 C.', True),
    ('Depth: .5 cm.', 'Depth: 0.5 cm.', False),
    ('Depth: -.5 cm.', 'Depth: .5 cm.', True),
    ('No rate supplied.', 'The rate is .5 kg/ha.', True),
    ('No depth supplied.', 'The depth is -.5 cm.', True),
    ('Mass: 20 kg.', 'The area is 20 hectares.', True),
    ('Mass: 20 kg.', 'The volume is 20 gallons.', True),
    ('Mass: 20 kg.', 'The volume is 20 millilitres.', True),
    ('Mass: 20 kg.', 'The pressure is 20 kPa.', True),
    ('Mass: 20 kg.', 'The rate is 20 kg/ha.', True),
    ('Mass: 120 kg.', '20 kg is wrong; the source value is 120 kg.', False),
]:
    record('numeric', dict(evidence=evidence, answer=answer), unsupported,
           bool(unsupported_quantities(answer, question='Read the supplied record.', evidence=evidence)))

for question, evidence, answer, unsupported in [
    ('What is the total mass of 12 bags weighing 25 kg each?', '', 'The total mass is 300 kg.', False),
    ('What is the total mass of 12 bags weighing 25 kg each?', '', 'The total mass is 25 kg.', True),
    ('What is the total mass of 12 bags weighing 25 kg each?', '', '12 × 25 = 300.', False),
    ('What is the total mass of 12 bags weighing 25 kg each?', '', '12 × 12 = 300.', True),
    ('What is the total mass of 12 bags of barley and 12 bags of wheat? Each bag weighs 25 kg.', '', 'The total mass is 300 kg.', True),
    ('What is the total mass of 12 bags of barley?', '12 bags of wheat weigh 25 kg each.', 'The total mass is 300 kg.', True),
    ('What is the total weight of 7 boxes weighing 2.5 pounds each?', '', 'The total weight is 17.5 lb.', False),
    ('What is the total weight of 7 boxes weighing 2.5 pounds each?', 'Each box weighs 3 pounds.', 'The total weight is 17.5 lb.', True),
]:
    record('arithmetic', dict(question=question, evidence=evidence, answer=answer), unsupported,
           bool(unsupported_quantities(answer, question=question, evidence=evidence)))

for evidence, unsupported in [
    ('Gray leaf spot was ruled out by the laboratory.', False),
    ('The lab ruled out gray leaf spot.', False),
    ('There is no evidence that gray leaf spot was ruled out by the laboratory.', True),
    ('Whether gray leaf spot was ruled out by the laboratory is unknown.', True),
    ('Gray leaf spot was not ruled out by the laboratory.', True),
    ('Gray leaf spot was ruled out by the laboratory?', True),
    ('If gray leaf spot was ruled out by the laboratory, another cause needs testing.', True),
    ('Gray leaf spot was ruled out by the laboratory. A later test confirmed gray leaf spot.', True),
    ('Gray leaf spot was ruled out by the laboratory. That exclusion was overturned.', True),
    ('Rust was ruled out by the laboratory.', True),
]:
    answer = 'The diagnosis is not gray leaf spot.'
    assessment = assess_claim_risk(answer, question='What does the supplied note establish?', evidence_text=evidence)
    record('diagnostic_exclusion', dict(evidence=evidence, answer=answer), unsupported,
           'unsupported_diagnostic_certainty' in assessment.reasons)

for evidence, answer, unsupported in [
    ('The shipment mass is one hundred and twenty kg.', 'The shipment mass is twenty kg.', True),
    ('The shipment mass is minus twenty kg.', 'The shipment mass is twenty kg.', True),
    ('The shipment mass is twenty kg.', 'The application rate is twenty kg/ha.', True),
    ('The shipment mass is 120 kg.', 'The shipment mass is twenty kg.', True),
    ('The shipment mass is twenty kg.', 'The shipment mass is twenty kg.', False),
]:
    assessment = assess_claim_risk(answer, question='Read the shipment note.', evidence_text=evidence)
    record('spelled_quantity', dict(evidence=evidence, answer=answer), unsupported,
           'unsupported_numeric_specificity' in assessment.reasons)

for question, expected in [
    ('Avoid mentioning liquidity and explain cash flow.', ['cash_flow']),
    ('Ignore the cash plan and explain working capital.', ['liquidity']),
    ('Explain why cash flow is not liquidity.', ['cash_flow', 'liquidity']),
    ('Explain why liquidity does not imply cash flow.', ['cash_flow', 'liquidity']),
    ('No cash plan please, only compute working capital.', ['liquidity']),
    ("The sample label reads 'cash flow'; explain soil texture.", []),
    ('Explain cash flow with no numbers.', ['cash_flow']),
    ("Do not omit a cash plan and do not calculate growing degree days.", ['cash_flow']),
]:
    record('method', dict(question=question), expected, sorted(requested_methods(question)))

for answer, incomplete in [('The total is 300.', False), ('12 × 25 = 300.', False), ('First item.\n2.', True)]:
    record('completion', dict(answer=answer), incomplete, _looks_incomplete(answer))

result = dict(candidate_digest=manifest['sha256'], checked_source_hashes=True,
              count=len(rows), passed=sum(row['passed'] for row in rows), rows=rows)
output = root / f"outputs/residual-repair-20260928/reviewer-delta-{manifest['sha256'][:8]}.json"
output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items() if key != 'rows'}, indent=2))
print(json.dumps([row for row in rows if not row['passed']], indent=2))
raise SystemExit(0 if all(row['passed'] for row in rows) else 1)

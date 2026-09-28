import importlib.util, json, sys, hashlib, subprocess
from pathlib import Path
root=Path.cwd(); out=root/'outputs/residual-repair-20260928'
base=out/'baseline_answer_verifier.py'; base.write_bytes(subprocess.check_output(['git','show','8380b8b:src/agronomy_agent/answer_verifier.py']))
spec=importlib.util.spec_from_file_location('baseline_verifier',base); old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
from agronomy_agent import answer_verifier as new
fixture=root/'docs/reviews/artifacts/portable-residual-20260928/verifier-contrasts.json'
rows=[]
for case in json.loads(fixture.read_text())['cases']:
 args={k:case[k] for k in ['question','evidence_text','question_type','risk_level']}
 rows.append({'id':case['id'],'normative_expected_review':case['expected_review'],'baseline':old.assess_claim_risk(case['answer'],**args).as_record(),'candidate':new.assess_claim_risk(case['answer'],**args).as_record()})
result={'schema':'verifier_repair_contrast.v1','claim_eligible':False,'status':'exposed_engineering_regression_not_efficacy','baseline_commit':'8380b8b','fixture_sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'source_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [root/'src/agronomy_agent/answer_verifier.py',root/'src/agronomy_agent/quantity_claims.py']},'cases':rows}
(out/'verifier-contrast.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps([{'id':r['id'],'before':r['baseline']['reasons'],'after':r['candidate']['reasons']} for r in rows],indent=2))

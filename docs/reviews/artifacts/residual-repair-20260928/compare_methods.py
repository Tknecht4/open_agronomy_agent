import importlib.util, json, sys, hashlib, subprocess
from pathlib import Path
from agronomy_agent.method_context import method_task_frame, requested_methods
from dataclasses import asdict
root=Path.cwd();out=root/'outputs/residual-repair-20260928';base=out/'baseline_method_context.py'
base.write_bytes(subprocess.check_output(['git','show','8380b8b:src/agronomy_agent/method_context.py']))
spec=importlib.util.spec_from_file_location('baseline_methods',base);old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
f=root/'docs/reviews/artifacts/portable-residual-20260928/method-contrasts.json';fixture=json.loads(f.read_text())
rows=[]
for case in fixture['cases']:
 before=list(old.requested_methods(case['question']));after=list(requested_methods(case['question']))
 rows.append({'id':case['id'],'expected':case['expected'],'baseline':before,'candidate':after,'candidate_frame':[asdict(t) for t in method_task_frame(case['question'])]})
result={'schema':'method_repair_contrast.v1','claim_eligible':False,'status':'exposed_engineering_regression_not_efficacy','baseline_commit':'8380b8b','fixture_sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'source_sha256':hashlib.sha256((root/'src/agronomy_agent/method_context.py').read_bytes()).hexdigest(),'summary':{'cases':len(rows),'baseline_exact':sum(set(r['baseline'])==set(r['expected']) for r in rows),'candidate_exact':sum(set(r['candidate'])==set(r['expected']) for r in rows)},'cases':rows}
(out/'method-contrast.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result['summary']))

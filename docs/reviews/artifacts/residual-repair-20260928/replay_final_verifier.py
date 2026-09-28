"""Exact fixed-output decision replay after the complete spelled-quantity fix."""
import hashlib, importlib.util, json, sys, zipfile
from pathlib import Path
from agronomy_agent import answer_verifier as current
root=Path.cwd();out=root/'outputs/residual-repair-20260928'
archive=out/'capsule-final.zip';run_path=out/'benchmark-final.json'
run=json.loads(run_path.read_text());assert run['status']=='completed'
with zipfile.ZipFile(archive) as z:
 prior_path=out/'previous_candidate_verifier.py';prior_path.write_bytes(z.read('src/agronomy_agent/answer_verifier.py'))
 manifest=json.loads(z.read('manifest.json'))
 # All other runtime source is unchanged from the real-model run.
 other_differences=[r['path'] for r in manifest['files'] if r['path'].startswith('src/') and r['path']!='src/agronomy_agent/answer_verifier.py' and hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()!=r['sha256']]
 assert not other_differences,other_differences
spec=importlib.util.spec_from_file_location('prior_candidate_verifier',prior_path);prior=importlib.util.module_from_spec(spec);sys.modules[spec.name]=prior;spec.loader.exec_module(prior)
cases={r['id']:r for r in json.loads((root/'docs/reviews/artifacts/portable-residual-20260928/verifier-contrasts.json').read_text())['cases']}
rows=[]
class CapturedEditor:
 max_tokens=220
 def __init__(self,record):self.record=record;self.prompts=[]
 def count_prompt_tokens(self,messages):
  return self.record['editor_context_budget']['input_tokens']
 def generate(self,messages):
  assert self.record['editor_output'] is not None
  self.prompts.append(messages)
  return self.record['editor_output']
for cell in run['verifier']:
 if cell['arm']!='candidate':continue
 case=cases[cell['case_id']];saved=cell['result'];records=[];prompts=[]
 for module in (prior,current):
  editor=CapturedEditor(saved)
  result=module.verify_answer(case['answer'],**{k:case[k] for k in ['question','evidence_text','question_type','risk_level']},editor=editor,review_mode='risk_conditioned_selective_v3')
  records.append(result.as_record());prompts.append(editor.prompts)
 assert records[0]==saved,(case['id'],'prior replay drift')
 assert records[1]==saved,(case['id'],'current decision drift')
 assert prompts[0]==prompts[1],(case['id'],'editor prompt drift')
 rows.append({'case_id':case['id'],'prior_record_matches_retained':True,'current_record_matches_retained':True,'editor_prompts_identical':True,'editor_calls':len(prompts[0]),'editor_prompts_sha256':hashlib.sha256(json.dumps(prompts[0],sort_keys=True).encode()).hexdigest()})
r={'schema':'fixed_editor_output_replay.v1','scope':'Final deterministic decision and prompt-byte equivalence using captured model outputs; not a new generation or tokenizer measurement','source_run_sha256':hashlib.sha256(run_path.read_bytes()).hexdigest(),'prior_capsule_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'final_verifier_sha256':hashlib.sha256(Path(current.__file__).read_bytes()).hexdigest(),'other_runtime_source_matches_capsule':True,'cases':rows}
(out/'final-decision-replay.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({'cases':len(rows),'all_records_and_prompts_equal':True}))

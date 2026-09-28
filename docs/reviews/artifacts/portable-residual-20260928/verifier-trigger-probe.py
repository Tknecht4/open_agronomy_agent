"""Post-hoc lexical trigger ablation, not repaired-answer quality evaluation."""
import gzip,hashlib,itertools,json,subprocess
from pathlib import Path
from agronomy_agent.agent import build_context
from agronomy_agent.answer_verifier import assess_claim_risk,context_evidence_text
root=Path(__file__).resolve().parents[4]
ledger=root/'docs/reviews/artifacts/portable-agronomy-20260928/qwen27b-v4-cells.jsonl.gz'
with gzip.open(ledger,'rt') as f: turn=next(r for r in map(json.loads,f) if r['unit_id']=='main/active/PFMH3-12')['turns'][0]
original=turn['answer_stages']['draft']['text']
# These transformations are fixed before the assessment calls below. They test
# lexical rules, not truth, safety or whether the remaining prose is warranted.
operations=[('drop_unfinished_tail',' This adjustment immediately reduces',''),('drop_depth_parenthetical',' (typically 2 to 4 inches deep)',''),('rot_synonym','rot','decay')]
assert all(old in original for _,old,_ in operations)
context=build_context(turn['question'],rag_config='configs/rag.yaml',use_context_cache=False,use_search_cache=False)
evidence=context_evidence_text(context)
results=[]
for bits in itertools.product((False,True),repeat=3):
 text=original;applied=[]
 for enabled,(name,old,new) in zip(bits,operations):
  if enabled:text=text.replace(old,new);applied.append(name)
 assessment=assess_claim_risk(text,question=turn['question'],evidence_text=evidence,question_type=context.route.question_type,risk_level=context.route.risk_level,evidence_docs=context.retrieved_docs,preserve_entities=context.evidence_handshake.preserve_entities if context.evidence_handshake else (),required_entities=context.evidence_handshake.required_entities if context.evidence_handshake else ()).as_record()
 results.append({'transformations':applied,'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'assessment':assessment})
assert results[0]['assessment']==turn['verification']['draft_assessment']
output={'schema':'verifier_trigger_ablation.v1','status':'posthoc_exposed_lexical_sensitivity_not_truth_or_answer_quality','source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'source_sha256':hashlib.sha256((root/'src/agronomy_agent/answer_verifier.py').read_bytes()).hexdigest(),'ledger_sha256':hashlib.sha256(ledger.read_bytes()).hexdigest(),'original_draft_sha256':hashlib.sha256(original.encode()).hexdigest(),'reconstructed_evidence_text_sha256':hashlib.sha256(evidence.encode()).hexdigest(),'operations':operations,'historical_full_evidence_available':False,'results':results,'boundary':'Replacing rot with decay preserves much of the meaning; disappearance of a rule is not evidence the remaining claim is supported. No model/editor or final selection ran.'}
Path(__file__).with_name('verifier-trigger-results.json').write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps([{'transformations':r['transformations'],'reasons':r['assessment']['reasons']} for r in results],indent=2))

"""Summarize output ceilings and reassess tree drafts; never grade efficacy."""
import gzip,hashlib,json
from pathlib import Path
from agronomy_agent.agent import build_context
from agronomy_agent.answer_verifier import assess_claim_risk,context_evidence_text
here=Path(__file__).resolve().parent;root=here.parents[3]
result={'schema':'output_budget_analysis.v1','scope':'exposed fixed prompts; completion mechanism and reconstructed draft assessment, not product quality','models':{}}
for model in ('gemma','qwen'):
 path=here/f'budget-{model}.json.gz'
 with gzip.open(path,'rt') as f:receipt=json.load(f)
 rows=[]
 for unit in receipt['units_fixed_before_generation']:
  cells=[c for c in receipt['conditions'] if c['unit']==unit]
  context=None
  if unit.startswith('main/active/'):
   context=build_context(cells[0]['question'],rag_config='configs/rag.yaml',use_context_cache=False,use_search_cache=False)
   evidence=context_evidence_text(context)
  for i,c in enumerate(cells):
   r={k:c[k] for k in ('unit','max_tokens','finish_reason','generation_tokens','equals_historical_draft','text_sha256','prompt_token_ids_sha256','mlx_peak_memory_bytes')}
   r['text_prefix_of_next_allowance']=cells[i+1]['text'].startswith(c['text']) if i+1<len(cells) else None
   r['last_160_characters']=c['text'][-160:]
   if context is not None:
    r['reconstructed_draft_assessment']=assess_claim_risk(c['text'],question=c['question'],evidence_text=evidence,question_type=context.route.question_type,risk_level=context.route.risk_level,evidence_docs=context.retrieved_docs,preserve_entities=context.evidence_handshake.preserve_entities if context.evidence_handshake else (),required_entities=context.evidence_handshake.required_entities if context.evidence_handshake else ()).as_record()
    r['reconstructed_evidence_sha256']=hashlib.sha256(evidence.encode()).hexdigest()
   rows.append(r)
 result['models'][model]={'receipt_gzip_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'cells':rows}
result['source_sha256']={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in ['src/agronomy_agent/answer_verifier.py','src/agronomy_agent/agent.py','configs/rag.yaml']}
(here/'budget-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({m:[{k:c[k] for k in ('unit','max_tokens','finish_reason','generation_tokens')} for c in d['cells']] for m,d in result['models'].items()},indent=2))

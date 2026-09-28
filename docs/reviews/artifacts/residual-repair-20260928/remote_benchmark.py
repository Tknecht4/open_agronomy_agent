"""Public synthetic verifier regression and model-pair switching; no quality claim."""
import os
os.environ.update(HF_HOME='/content/oa-hf', HF_HUB_CACHE='/content/oa-hf/hub', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1')
import gc, hashlib, importlib.util, importlib.metadata, json, sys, time, weakref
from pathlib import Path
root=Path('/content/oa-repair'); capsule=root/'capsule'; sys.path.insert(0,str(capsule/'src'))
import mlx.core as mx
import mlx_lm
load_calls=[]
original_load=mlx_lm.load
def observed_load(path, *args, **kwargs):
 value=original_load(path,*args,**kwargs);load_calls.append(str(path));return value
mlx_lm.load=observed_load
from agronomy_agent import agent, answer_verifier as candidate
spec=importlib.util.spec_from_file_location('baseline_verifier',capsule/'baseline_answer_verifier.py'); baseline=importlib.util.module_from_spec(spec); sys.modules[spec.name]=baseline; spec.loader.exec_module(baseline)
setup=json.loads((root/'setup.json').read_text())
receipt={'schema':'residual_repair_gpu_regression.v1','claim_eligible':False,'scope':'synthetic exposed fixed drafts; real editor and adapter lifecycle; no full product retrieval or efficacy claim','start_unix':time.time(),'capsule_sha256':hashlib.sha256(Path('/content/oa-repair-capsule.zip').read_bytes()).hexdigest(),'setup':setup,'lifecycle':[],'verifier':[]}
def save(): (root/'benchmark.json').write_text(json.dumps(receipt,indent=2))
def released(g): return all(getattr(g,k) is None for k in ('_model','_tokenizer','_draft_model'))
def keys(): return [list(k) for k in agent._MLX_MODEL_CACHE]
def generator(i,max_tokens):
 m=setup['models'][i]
 return agent.MLXGenerator(m['repo'],model_revision=m['revision'],max_tokens=max_tokens,temperature=0,seed=42,prompt_cache_enabled=False)
gemma=generator(0,48); qwen=generator(1,48)
messages=[{'role':'user','content':'Explain what crop rotation means in one sentence.'}]
try:
 for name,g in [('gemma_first',gemma),('qwen',qwen),('gemma_reused',gemma)]:
  mx.reset_peak_memory(); started=time.perf_counter(); count=g.count_prompt_tokens(messages); after_count=released(g); text=g.generate(messages)
  row={'name':name,'tokens':count,'text':text,'seconds':time.perf_counter()-started,'stats':g.last_generation_stats,'resident_pair_keys':keys(),'released_after_count':after_count,'released_after_generate':released(g),'active_model_uses':agent._MLX_ACTIVE_MODEL_USES,'load_calls':list(load_calls),'mlx_peak_memory_bytes':mx.get_peak_memory()}
  receipt['lifecycle'].append(row); save()
  assert row['released_after_count'] and row['released_after_generate'] and len(keys())==1 and agent._MLX_ACTIVE_MODEL_USES==0 and text and count>0
 assert len(load_calls)==3, load_calls
 receipt['lifecycle_same_gemma_text']=receipt['lifecycle'][0]['text']==receipt['lifecycle'][2]['text']
 editor=generator(0,220)
 for case in json.loads((capsule/'verifier-contrasts.json').read_text())['cases']:
  for name,module in [('baseline',baseline),('candidate',candidate)]:
   started=time.perf_counter()
   try:
    result=module.verify_answer(case['answer'],**{k:case[k] for k in ['question','evidence_text','question_type','risk_level']},editor=editor,review_mode='risk_conditioned_selective_v3')
    row={'case_id':case['id'],'arm':name,'seconds':time.perf_counter()-started,'result':result.as_record(),'answer':result.answer,'resident_pair_keys':keys(),'released_after_verify':released(editor)}
   except Exception as exc:
    row={'case_id':case['id'],'arm':name,'error_type':type(exc).__name__,'error':str(exc),'seconds':time.perf_counter()-started}
   receipt['verifier'].append(row); save(); print(json.dumps({'case':case['id'],'arm':name,'error':row.get('error_type'),'seconds':row['seconds']}),flush=True)
 receipt['status']='completed'; receipt['end_unix']=time.time(); save()
except BaseException as exc:
 receipt['status']='failed';receipt['error_type']=type(exc).__name__;receipt['error']=str(exc);receipt['end_unix']=time.time();save();raise

"""Exposed fixed-prompt output-budget diagnostic; no editor or efficacy claim."""
import argparse, gzip, hashlib, importlib.metadata, json, os, platform, time
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
p=argparse.ArgumentParser(); p.add_argument('--ledger',required=True);p.add_argument('--snapshot',required=True);p.add_argument('--output',required=True);a=p.parse_args()
out=Path(a.output);out.mkdir(exist_ok=False,parents=True)
import mlx.core as mx
from mlx_lm import load, stream_generate
from mlx_lm.sample_utils import make_sampler
def sha(x):return hashlib.sha256(x).hexdigest()
with gzip.open(a.ledger,'rt') as f: rows={r['unit_id']:r for r in map(json.loads,f)}
units=['main/active/PFMH3-12','direct_reference/PFMH3-06']
receipt={'schema':'exposed_output_budget_probe.v1','claim_eligible':False,'units_fixed_before_generation':units,'allowances':[320,640,1024],'source_ledger_sha256':sha(Path(a.ledger).read_bytes()),'script_sha256':sha(Path(__file__).read_bytes()),'platform':platform.platform(),'device':str(mx.default_device()),'packages':{n:importlib.metadata.version(n) for n in ('mlx','mlx-lm','mlx-vlm','transformers','huggingface-hub')},'conditions':[]}
assert receipt['packages']['mlx']=='0.32.2' and receipt['packages']['mlx-lm']=='0.31.3'
assert mx.device_count(mx.gpu)>0
start=time.perf_counter();model,tok=load(a.snapshot);receipt['load_seconds']=time.perf_counter()-start
for unit in units:
 t=rows[unit]['turns'][0];stats=t['generation_stats'];identity=t['model_identity'];revision=identity['configured_model_revision']
 assert Path(a.snapshot).name==revision
 messages=t['prompt_messages'];prompt=list(tok.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,enable_thinking=False));assert len(prompt)==stats['prompt_tokens']
 historical=t.get('answer_stages',{}).get('draft',{}).get('text',t['answer'])
 seed=stats['seed_application']['applied_seed'];settings=stats['seed_application']['sampler'];assert settings['temperature']==0
 for limit in receipt['allowances']:
  mx.random.seed(seed);mx.clear_cache();mx.reset_peak_memory();begin=time.perf_counter();first=None;chunks=[];tokens=[];final=None
  for r in stream_generate(model,tok,prompt=prompt,max_tokens=limit,sampler=make_sampler(temp=0,top_p=settings['top_p'],top_k=settings['top_k']),prefill_step_size=stats['prefill_step_size'],prompt_cache=None,max_kv_size=None,kv_bits=None):
   if first is None:first=time.perf_counter()-begin
   chunks.append(r.text or '');tokens.append(int(r.token));final=r
  text=''.join(chunks).strip()
  row={'unit':unit,'question':t['question'],'max_tokens':limit,'seed':seed,'sampler':settings,'prefill_step_size':stats['prefill_step_size'],'model_id':identity['configured_model_id'],'model_revision':revision,'prompt_tokens':len(prompt),'prompt_token_ids_sha256':sha(json.dumps(prompt,separators=(',',':')).encode()),'prompt_messages':messages,'generated_token_ids':tokens,'text':text,'text_sha256':sha(text.encode()),'historical_draft_sha256':sha(historical.encode()),'equals_historical_draft':text==historical,'seconds':time.perf_counter()-begin,'time_to_first_response_seconds':first,'finish_reason':final.finish_reason,'generation_tokens':final.generation_tokens,'generation_tps':final.generation_tps,'prompt_tps':final.prompt_tps,'mlx_peak_memory_bytes':mx.get_peak_memory(),'memory_scope':'MLX allocator process peak reset immediately before generation; not total device/OS memory'}
  receipt['conditions'].append(row);(out/'budget.json').write_text(json.dumps(receipt,indent=2));print(json.dumps({k:row[k] for k in ('unit','max_tokens','finish_reason','generation_tokens','seconds','equals_historical_draft')}),flush=True)

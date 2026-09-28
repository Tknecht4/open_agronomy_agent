#!/usr/bin/env python3
"""Narrow opt-in causal probe: 3 prefix repeats, then shared-origin clone/LRU arms.
Requires an existing cache_probe.py runtime receipt and revision-pinned local
snapshot. No downloads, product edits, training, or answer-quality claims.
"""
from __future__ import annotations
import argparse
import copy
import faulthandler
import hashlib
import importlib.metadata as metadata
import json
import os
import platform
import signal
import sys
import time
import traceback
from pathlib import Path


def sha(data): return hashlib.sha256(data).hexdigest()
def canonical(value): return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()


def changed_paths(a,b,path=""):
    if type(a)!=type(b): return [path]
    if isinstance(a,dict):
        return sum((changed_paths(a.get(k),b.get(k),path+"/"+str(k)) for k in sorted(set(a)|set(b))),[])
    if isinstance(a,list):
        if len(a)!=len(b): return [path+"/length"]
        return sum((changed_paths(x,y,path+"/"+str(i)) for i,(x,y) in enumerate(zip(a,b))),[])
    return [] if a==b else [path]


def run(args,out,progress,save):
    if {n:metadata.version(n) for n in ("mlx","mlx-lm")}!={"mlx":"0.32.2","mlx-lm":"0.31.3"}:
        raise ValueError("requires historical mlx0.32.2 / mlx-lm0.31.3")
    source=json.loads(args.receipt.read_text())
    tokens=source["prompt_token_ids"]; prefix=source["prefix_token_ids"]
    settings=source["settings"]; revision=source["model_revision"]
    snapshot=args.snapshot.resolve()
    if not snapshot.is_dir() or snapshot.name!=revision:
        raise ValueError("existing local snapshot must be named by retained revision")
    if not prefix or tokens[:len(prefix)]!=prefix or len(prefix)>=len(tokens):
        raise ValueError("invalid exact prefix IDs")
    if settings["temperature"]!=0 or settings.get("kv_bits") is not None or settings.get("max_kv_size") is not None:
        raise ValueError("narrow probe requires retained argmax/no explicit KV quantization/truncation")
    os.environ["HF_HUB_OFFLINE"]="1"; os.environ["TRANSFORMERS_OFFLINE"]="1"
    progress("import_start")
    import mlx.core as mx
    import numpy as np
    from mlx_lm import load
    from mlx_lm.generate import generate_step,generation_stream
    from mlx_lm.models.cache import make_prompt_cache,LRUPromptCache
    root=Path(metadata.distribution("mlx-lm").locate_file("mlx_lm"))
    out.update(packages={n:metadata.version(n) for n in ("mlx","mlx-lm")},device=str(mx.default_device()),
               model_revision=revision,snapshot=str(snapshot),prompt_token_ids=tokens,prefix_token_ids=prefix,
               prompt_messages=source["prompt_messages"],prompt_token_ids_sha256=sha(canonical(tokens)),
               settings={**settings,"max_tokens":args.max_tokens},
               source_sha256={n:sha((root/n).read_bytes()) for n in ("generate.py","models/cache.py","models/gemma4_text.py")})
    expected=source.get("snapshot_small_file_sha256",{})
    observed={name:sha((snapshot/name).read_bytes()) for name in expected}
    if observed!=expected: raise ValueError("snapshot metadata differs from source receipt")
    out["snapshot_small_file_sha256"]=observed
    progress("load_start")
    model,tokenizer=load(str(snapshot))
    eos_ids=getattr(tokenizer,"eos_token_ids",None)
    eos_id=getattr(tokenizer,"eos_token_id",None)
    out["tokenizer_eos"]={"eos_token_ids":sorted(int(x) for x in eos_ids) if eos_ids is not None else None,
                          "eos_token_id":eos_id}
    actual=list(tokenizer.apply_chat_template(source["prompt_messages"],tokenize=True,add_generation_prompt=True,enable_thinking=False))
    if actual!=tokens: raise ValueError("tokenizer no longer reproduces exact input IDs")
    progress("load_complete")
    def host(value):
        mx.eval(value)
        return np.array(value.astype(mx.float32) if value.dtype==mx.bfloat16 else value,copy=True)
    def leaves(value,path=""):
        if isinstance(value,mx.array):
            return [{"path":path,"shape":list(value.shape),"dtype":str(value.dtype),"sha256":sha(host(value).tobytes())}]
        if isinstance(value,(tuple,list)):
            return sum((leaves(x,path+"/"+str(i)) for i,x in enumerate(value)),[])
        if isinstance(value,dict):
            return sum((leaves(x,path+"/"+str(k)) for k,x in sorted(value.items())),[])
        return [{"path":path,"scalar":str(value)}]
    def state(cache):
        result=[]
        for item in cache:
            record={"class":type(item).__name__,"offset":str(getattr(item,"offset",None)),
                    "meta":str(getattr(item,"meta_state",None)),"arrays":leaves(item.state),
                    "padding":leaves(getattr(item,"left_padding",None)),"lengths":leaves(getattr(item,"lengths",None))}
            if type(item).__name__=="RotatingKVCache":
                record["temporal"]=leaves((item._temporal_order(item.keys),item._temporal_order(item.values)))
            result.append(record)
        return result
    def offsets(cache):return [str(getattr(x,"offset",None)) for x in cache]
    prefix_states=[]; last_values=[]; origin=None
    for index in range(3):
        progress("prefix_start",index=index)
        mx.random.seed(settings["seed"])
        cache=make_prompt_cache(model)
        list(generate_step(mx.array(prefix),model,max_tokens=0,prompt_cache=cache,
                           prefill_step_size=settings["prefill_step_size"],sampler=lambda x:mx.argmax(x,axis=-1)))
        mx.synchronize(generation_stream)
        progress("prefix_hash_start",index=index)
        prefix_states.append(state(cache))
        # Retain raw last-owned-layer V only for this localized Gemma question.
        value=cache[-1].state[1]
        if isinstance(value,mx.array):
            raw=host(value);last_values.append(raw)
            np.savez_compressed(args.output/f"prefix-{index}-last-value.npz",value=raw)
        else:last_values.append(None)
        out["prefix_states"]=prefix_states
        if index==0:origin=cache
        else:del cache
        save();progress("prefix_complete",index=index)
    out["prefix_comparisons"]=[]
    for index in (1,2):
        a,b=last_values[0],last_values[index]
        numeric=None
        if a is not None and b is not None and a.shape==b.shape:
            delta=np.abs(a.astype(np.float64)-b.astype(np.float64))
            changed=np.argwhere(a!=b)
            numeric={"max_abs_difference":float(delta.max()),"changed_elements":int(len(changed)),
                     "changed_token_positions":np.unique(changed[:,-2]).tolist() if len(changed) else []}
        out["prefix_comparisons"].append({"left":0,"right":index,"changed_state_paths":changed_paths(prefix_states[0],prefix_states[index]),
                                          "last_value_difference":numeric})
    del last_values
    origin_state=state(origin)
    namespace="same-origin:"+out["script_sha256"]+":"+out["prompt_token_ids_sha256"]
    lru=LRUPromptCache(max_size=1)
    lru.insert_cache(namespace,prefix,origin,cache_type="system")
    out["namespace"]=namespace;out["arms"]={};vectors={}
    class Trace:
        def __init__(self):self.n=len(prefix);self.calls=[];self.raw=[];self.full_state=None
        def __getattr__(self,name):return getattr(model,name)
        def __call__(self,ids,cache):
            before=offsets(cache);result=model(ids,cache=cache);self.n+=int(ids.shape[1])
            self.calls.append({"length":int(ids.shape[1]),"consumed":self.n,"before":before,"after":offsets(cache)})
            if self.n>=len(tokens):
                if not self.raw:progress("first_logits_copy_start",arm=arm)
                self.raw.append(host(result[0,-1,:].astype(mx.float32)))
                if self.full_state is None:
                    progress("full_prompt_hash_start",arm=arm)
                    self.full_state=state(cache)
            return result
    for arm in ("direct_a","lru_a","direct_b","lru_b"):
        progress("arm_start",arm=arm)
        mx.random.seed(settings["seed"])
        before_origin=state(origin)
        if arm.startswith("direct"):
            cache=copy.deepcopy(origin);rest=tokens[len(prefix):]
        else:cache,rest=lru.fetch_nearest_cache(namespace,tokens)
        if rest!=tokens[len(prefix):]:raise ValueError("LRU returned wrong remaining token IDs")
        start=state(cache)
        if start!=origin_state or before_origin!=origin_state:
            raise ValueError("origin changed or branch state differs before generation")
        trace=Trace();generated=[];tops=[]
        for token,logprobs in generate_step(mx.array(rest),trace,max_tokens=args.max_tokens,prompt_cache=cache,
                                            prefill_step_size=settings["prefill_step_size"],sampler=lambda x:mx.argmax(x,axis=-1)):
            generated.append(token);raw=trace.raw[len(generated)-1];ix=np.argsort(raw)[-10:][::-1]
            tops.append({"token":token,"top_ids":ix.tolist(),"top_raw_logits":raw[ix].tolist(),
                         "top_two_margin":float(raw[ix[0]]-raw[ix[1]])})
        mx.synchronize(generation_stream)
        after_origin=state(origin)
        ref,_=lru.fetch_nearest_cache(namespace,tokens);stored=state(ref);del ref
        out["arms"][arm]={"initial_state":start,"full_prompt_state":trace.full_state,"calls":trace.calls,
                          "tokens":generated,"top_logits":tops,
                          "origin_unchanged":origin_state==after_origin,"stored_unchanged":origin_state==stored}
        vectors[arm]=trace.raw[:len(generated)]
        np.savez_compressed(args.output/f"{arm}-logits.npz",logits=np.stack(vectors[arm]))
        save();progress("arm_complete",arm=arm)
        del trace,cache
        mx.clear_cache()
    out["comparisons"]=[]
    for left,right in (("direct_a","lru_a"),("direct_a","direct_b"),("lru_a","lru_b"),("direct_b","lru_b")):
        a,b=out["arms"][left],out["arms"][right]
        first=next((i for i,(x,y) in enumerate(zip(a["tokens"],b["tokens"])) if x!=y),None)
        horizon=args.max_tokens if first is None else first+1
        out["comparisons"].append({"left":left,"right":right,"first_divergent_token_index":first,
                                  "max_abs_logits_on_common_history":[float(np.max(np.abs(vectors[left][i]-vectors[right][i]))) for i in range(horizon)],
                                  "changed_full_state_paths":changed_paths(a["full_prompt_state"],b["full_prompt_state"]),
                                  "calls_equal":a["calls"]==b["calls"]})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--receipt",type=Path,required=True);p.add_argument("--snapshot",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True);p.add_argument("--execute",action="store_true")
    p.add_argument("--max-tokens",type=int,default=8);p.add_argument("--timeout-seconds",type=int,default=180)
    a=p.parse_args()
    if not a.execute:p.error("explicit --execute required")
    if not 1<=a.max_tokens<=16 or not 30<=a.timeout_seconds<=240:p.error("tokens1..16 / timeout30..240 required")
    a.output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    out={"schema":"cache_same_origin.v1","claim_eligible":False,"status":"running",
         "script_sha256":sha(Path(__file__).read_bytes()),"input_receipt_sha256":sha(a.receipt.read_bytes()),
         "platform":platform.platform(),"python":sys.version,"timeout_seconds":a.timeout_seconds,
         "stage_history":[],"limits":"Instrumented fixed-token horizon including EOS; no performance/quality claim"}
    def save():
        out["elapsed_seconds"]=round(time.monotonic()-started,3)
        (a.output/"same-origin.json").write_text(json.dumps(out,indent=2))
    def progress(stage,**kw):
        row={"stage":stage,"elapsed_seconds":round(time.monotonic()-started,3),**kw}
        out["stage_history"].append(row);print(json.dumps(row),flush=True);save()
    def timeout(*_):raise TimeoutError("bounded same-origin probe wall-time expired")
    signal.signal(signal.SIGALRM,timeout);signal.alarm(a.timeout_seconds)
    faulthandler.enable();faulthandler.dump_traceback_later(30,repeat=True)
    try:
        progress("start");run(a,out,progress,save);out["status"]="completed";progress("completed")
    except BaseException as exc:
        out.update(status="failed",error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc());save();raise
    finally:
        signal.alarm(0);faulthandler.cancel_dump_traceback_later();save()


if __name__=="__main__":main()

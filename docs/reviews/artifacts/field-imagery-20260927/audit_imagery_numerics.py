#!/usr/bin/env python3
"""Research-only reproduction of the retained numerical diagnostic.

Explicit execution refits the frozen small readouts; no model inference,
network, tuning or automatic metric acceptance. Existing outputs are refused.
See numerical-audit-reproduction.md and numerical-audit-source-lineage.json.
"""
import argparse
from pathlib import Path

ORIGINAL_EXECUTED_SCRIPT_SHA256 = '5f4b0480f4ae6f9bbe1d3ca75716441ceccd55f3b99cc4bf10734e6b241b42a6'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'protocol', 'spectral', 'encoder', 'original-result', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; historical evidence is never overwritten')
    if not args.output.parent.is_dir():
        parser.error('Output parent directory must already exist')
    import json,math,warnings,hashlib
    import numpy as np
    from sklearn.linear_model import LogisticRegression,Ridge
    from agronomy_agent.imagery_assessment import compare_features,load_source
    checks=[]
    original_predict={cls:cls.predict for cls in [LogisticRegression,Ridge]}
    original_fit=Ridge.fit
    ridge_residuals=[]
    def ridge_fit(self,X,y,*a,**kw):
     out=original_fit(self,X,y,*a,**kw)
     xx=np.asarray(X).tolist();yy=np.asarray(y).tolist();coef=np.asarray(self.coef_).tolist();n=len(yy);p=len(coef)
     means=[math.fsum(row[j] for row in xx)/n for j in range(p)];my=math.fsum(yy)/n
     centered=[[row[j]-means[j] for j in range(p)] for row in xx]
     residuals=[math.fsum(z*c for z,c in zip(row,coef))-(v-my) for row,v in zip(centered,yy)]
     equations=[math.fsum(row[j]*res for row,res in zip(centered,residuals))+float(self.alpha)*coef[j] for j in range(p)]
     rhs=[math.fsum(row[j]*(v-my) for row,v in zip(centered,yy)) for j in range(p)]
     ridge_residuals.append({'shape':[n,p],'normal_equation_max_absolute_residual':max(map(abs,equations)),'normal_equation_relative_residual':max(map(abs,equations))/max(1,max(map(abs,rhs)))})
     return out
    Ridge.fit=ridge_fit
    for cls in [LogisticRegression,Ridge]:
     old=original_predict[cls]
     def predict(self,X,*a,_old=old,_cls=cls,**kw):
      observed=_old(self,X,*a,**kw); xx=np.asarray(X).tolist()
      co=np.atleast_2d(self.coef_).tolist();inter=np.atleast_1d(self.intercept_).tolist()
      decisions=[[math.fsum([b]+[v*c for v,c in zip(row,coef)]) for coef,b in zip(co,inter)] for row in xx]
      if _cls is LogisticRegression:
       raw=np.asarray(self.decision_function(X)).reshape(len(xx),-1)
       predicted=[self.classes_[int(d[0]>0)] if len(co)==1 else self.classes_[max(range(len(d)),key=lambda j:d[j])] for d in decisions]
       class_equal=list(observed)==predicted
      else:
       raw=np.asarray(observed).reshape(len(xx),-1);class_equal=None
      expected=np.asarray(decisions)
      delta=abs(raw-expected)
      checks.append({'model':_cls.__name__,'shape':list(np.shape(X)),'inputs_finite':bool(np.isfinite(X).all()),'coef_finite':bool(np.isfinite(self.coef_).all()),'intercept_finite':bool(np.isfinite(self.intercept_).all()),'outputs_finite':bool(np.isfinite(raw).all()),'input_absmax':float(np.max(np.abs(X))),'decision_absmax':float(np.max(np.abs(raw))),'fsum_max_absolute_difference':float(np.max(delta)),'fsum_max_scaled_difference':float(np.max(delta/(1+abs(expected)))),'class_exact_match':class_equal})
      return observed
     cls.predict=predict
    with warnings.catch_warnings(record=True) as ws:
     warnings.simplefilter('always')
     result=compare_features(load_source(args.source),json.loads(args.protocol.read_text()),json.loads(args.spectral.read_text()),json.loads(args.encoder.read_text()))
    original=json.loads(args.original_result.read_text())
    metrics_equal=all(result['lanes'][a][s]['common_case_metrics']==original['lanes'][a][s]['common_case_metrics'] for a in result['lanes'] for s in result['lanes'][a])
    summary={'prediction_checks':len(checks),'ridge_fit_checks':len(ridge_residuals),'all_finite':all(all(c[k] for k in ['inputs_finite','coef_finite','intercept_finite','outputs_finite']) for c in checks),'all_classes_exact':all(c['class_exact_match'] is not False for c in checks),'max_fsum_absolute_difference':max(c['fsum_max_absolute_difference'] for c in checks),'max_fsum_scaled_difference':max(c['fsum_max_scaled_difference'] for c in checks),'max_ridge_relative_residual':max(c['normal_equation_relative_residual'] for c in ridge_residuals),'all_metrics_exact_replay':metrics_equal,'warnings_count':len(ws)}
    audit={'status':'numerical_outputs_verified_warning_cause_unresolved','summary':summary,'method':'Independent Python math.fsum for every fitted linear/logistic prediction and Ridge normal equation; no hyperparameter/input changes; warnings retained. Does not independently reproduce optimizer trajectory.','checks':checks,'ridge_residuals':ridge_residuals,'warnings':[{'message':str(w.message),'file':Path(w.filename).name,'line':w.lineno} for w in ws],'audit_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    audit['original_executed_script_sha256']=ORIGINAL_EXECUTED_SCRIPT_SHA256
    audit['original_status']=audit['status']
    audit['status']='analysis_only_reproduction_requires_review'
    with args.output.open('x') as f:json.dump(audit,f,indent=2)
    print(json.dumps(summary))


if __name__ == '__main__':
    main()

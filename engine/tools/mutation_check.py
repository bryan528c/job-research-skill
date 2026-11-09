"""Verify regression tests actually reject deliberately broken engine behavior."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args()
mutations=[
 ('drop_prior_candidates','store.py','WHERE r.profile_id=? AND','WHERE 0 AND r.profile_id=? AND','test_engine.CoreTests.test_three_run_candidate_survives'),
 ('close_missing_jobs','store.py','for m in missing:\n                    self._enqueue','for m in missing:\n                    self.db.execute("UPDATE jobs SET recruiting_status=\'closed\' WHERE id=?",(m[0],))\n                    self._enqueue','test_engine.CoreTests.test_absence_never_closes_job'),
 ('disable_report_reconciliation','store.py','if expected != shown:','if False:','test_engine.CoreTests.test_report_omission_is_error'),
 ('ignore_total_mismatch','store.py','if page.terminal and page.expected_total is not None and observed_count != page.expected_total:','if False:','test_engine.CoreTests.test_truncated_inventory_not_complete')]
results=[]
for name,file,old,new,test in mutations:
    with tempfile.TemporaryDirectory() as td:
        folder=Path(td);shutil.copytree(root/'job_research_engine',folder/'job_research_engine');shutil.copytree(root/'tests',folder/'tests')
        path=folder/'job_research_engine'/file;text=path.read_text();assert text.count(old)==1,(name,text.count(old));path.write_text(text.replace(old,new))
        compile(path.read_text(),str(path),'exec')
        env={**os.environ,'PYTHONPATH':str(folder)+os.pathsep+str(folder/'tests')}
        proc=subprocess.run([sys.executable,'-m','unittest',test,'-v'],cwd=folder,env=env,text=True,capture_output=True)
        output=proc.stdout+proc.stderr
        detected=proc.returncode!=0 and ('FAIL:' in output or 'ERROR:' in output) and 'ImportError' not in output
        results.append({'mutation':name,'detected':detected,'returncode':proc.returncode,'test':test,'tail':output[-1500:]})
if a.output:a.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))
raise SystemExit(0 if all(r['detected'] for r in results) else 1)

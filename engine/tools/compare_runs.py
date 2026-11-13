"""Compare private host exports against a separately authored private cohort."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from job_research_engine.comparison import compare

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('cohort',type=Path);p.add_argument('run',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result=compare(json.loads(args.cohort.read_text(encoding='utf8')),json.loads(args.run.read_text(encoding='utf8')))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'mode':result['mode'],'individual_sample_roles':result['individual_sample_roles'],'counts':result['counts']}))

if __name__=='__main__':main()

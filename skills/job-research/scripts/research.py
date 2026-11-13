#!/usr/bin/env python3
"""Agent entry point, in a checkout or native upload. Ordinary users speak naturally."""
from pathlib import Path
import os
import sys

here=Path(__file__).resolve().parent
runtime=here/'runtime'
checkout=here.parents[2]/'engine'
base=runtime if (runtime/'job_research_engine').is_dir() else checkout
if not (base/'job_research_engine').is_dir():
    raise SystemExit('Runtime not bundled in this instruction-only copy; use the complete native package or authorized checkout.')
sys.path.insert(0,str(base))
from job_research_engine.cli import main

args=sys.argv[1:]
if '--db' not in args:
    database=os.environ.get('JOB_RESEARCH_DB')
    if not database:
        raise SystemExit('Host must bind an authorized private DB with JOB_RESEARCH_DB or --db. Do not ask the user to write JSON.')
    args=['--db',database,*args]
raise SystemExit(main(args))

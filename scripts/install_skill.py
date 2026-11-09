#!/usr/bin/env python3
"""Optional local installer. Default: print a plan; --apply copies one chosen host skill.
No network, login, privilege escalation, config replacement or automatic host launch.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
PREFIX={'codex':'.agents','claude-code':'.claude','gemini-cli':'.gemini'}

def linked(path:Path)->bool:
    return path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction())


def install(host:str,base:Path,apply:bool=False,source:Path|None=None)->Path:
    source=source or ROOT/'skills/job-research'
    if host not in PREFIX: raise ValueError('choose codex, claude-code or gemini-cli')
    if not (source/'SKILL.md').is_file(): raise ValueError('source SKILL.md missing')
    if linked(source) or any(linked(p) for p in source.rglob('*')):
        raise ValueError('source symlinks not accepted')
    base=base.expanduser().absolute()
    target=base/PREFIX[host]/'skills'/'job-research'
    # Do not follow an installation path symlink into an unexpected directory.
    for parent in [target,*target.parents]:
        if linked(parent): raise ValueError('target or parent symlink/junction; review destination manually')
    if target.exists(): raise FileExistsError(f'{target} already exists; compare versions, do not overwrite')
    if apply:
        target.parent.mkdir(parents=True,exist_ok=True)
        temp=Path(tempfile.mkdtemp(prefix='.job-research-install-',dir=target.parent))
        try:
            shutil.copytree(source,temp/'payload',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            engine=source.parents[1]/'engine/job_research_engine'
            if engine.is_dir():
                if linked(engine) or any(linked(p) for p in engine.rglob('*')):raise ValueError('engine symlink/junction not accepted')
                shutil.copytree(engine,temp/'payload/scripts/runtime/job_research_engine',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            if target.exists(): raise FileExistsError('destination appeared during installation')
            (temp/'payload').rename(target)
        finally:
            shutil.rmtree(temp,ignore_errors=True)
    return target


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',choices=PREFIX,required=True)
    p.add_argument('--scope',choices=['project','user'],default='project')
    p.add_argument('--project',type=Path,default=Path.cwd())
    p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    try:
        target=install(a.host,Path.home() if a.scope=='user' else a.project,a.apply)
        print(('Copied files to ' if a.apply else 'Plan only; add --apply to copy: ')+str(target))
        print('File copy is not runtime validation. Load the skill in the actual host and confirm the version.')
        return 0
    except (OSError,ValueError) as exc:
        print(f'Installation not performed: {exc}',file=sys.stderr);return 2

if __name__=='__main__': raise SystemExit(main())

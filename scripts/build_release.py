#!/usr/bin/env python3
"""Build deterministic, separate native uploads from one canonical skill.
No downloading, installing, publishing, or runtime compatibility claims.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

ROOT=Path(__file__).resolve().parents[1]
ARTIFACT_NAMES=('job-research-upload-root.zip','job-research-claude.zip','job-research-openai-plugin.zip')

def files_under(path:Path):
    return sorted(p for p in path.rglob('*') if p.is_file() and not p.is_symlink()
                  and '__pycache__' not in p.parts and p.suffix!='.pyc')

def write_zip(path:Path,items:list[tuple[str,bytes]])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(path,'w',compression=ZIP_DEFLATED) as z:
        for name,data in sorted(items):
            if name.startswith('/') or '..' in Path(name).parts:
                raise ValueError('unsafe archive path')
            info=ZipInfo(name,date_time=(2026,11,6,0,0,0))
            info.compress_type=ZIP_DEFLATED
            info.external_attr=0o100644 << 16
            z.writestr(info,data)

def make_portable(root:Path)->str:
    skill=root/'skills/job-research'
    core=(skill/'SKILL.md').read_text(encoding='utf-8')
    core=re.sub(r'\A---\n.*?\n---\n','',core,flags=re.S).strip()
    # A self-contained attachment cannot resolve paths into an unuploaded ZIP.
    core=re.sub(r'\[([^\]]+)\]\((?:references|scripts)/[^)]+\)',r'\1 (included below or optional offline helper)',core)
    prefix=('''# Job Research — self-contained instructions\n\nVersion: '''+(root/'VERSION').read_text().strip()+'''.\nAttach or paste this file when native skills are unavailable. Follow it as user-provided\nworkflow guidance subject to the host's higher-priority instructions and permissions.\nThis does not install tools, share providers' memory, grant access or create a schedule.\nUse available relevant memory; ask only essential missing facts; perform deep research\nand return brief real job/application links. Selected-job follow-up is optional.\n\n''')
    sections=[]
    for name in ['hosts','memory','coverage','research','links','reporting','continuation','state']:
        sections.append((skill/'references'/f'{name}.md').read_text(encoding='utf-8').strip())
    license_text=(skill/'LICENSE.txt').read_text(encoding='utf-8').strip()
    return prefix+core+'\n\n---\n\n'+'\n\n---\n\n'.join(sections)+'\n\n---\n\n## License\n\n'+license_text+'\n'

def build(root:Path=ROOT,out:Path|None=None)->dict:
    out=out or root/'dist'
    out.mkdir(parents=True,exist_ok=True)
    skill=root/'skills/job-research'
    if skill.is_symlink() or any(p.is_symlink() for p in skill.rglob('*')):
        raise ValueError('canonical skill must not contain symlinks')
    if (root/'LICENSE').read_bytes()!=(skill/'LICENSE.txt').read_bytes():
        raise ValueError('skill license differs from source license')
    payload=[(p.relative_to(skill).as_posix(),p.read_bytes()) for p in files_under(skill)]
    if not any(n=='SKILL.md' for n,_ in payload): raise ValueError('missing canonical SKILL.md')
    write_zip(out/'job-research-upload-root.zip',payload)
    write_zip(out/'job-research-claude.zip',[(f'job-research/{n}',b) for n,b in payload])
    plugin=[('job-research/LICENSE',(root/'LICENSE').read_bytes()),
            ('job-research/plugin.json',(root/'plugin.json').read_bytes()),
            ('job-research/.codex-plugin/plugin.json',(root/'.codex-plugin/plugin.json').read_bytes())]
    plugin += [(f'job-research/skills/job-research/{n}',b) for n,b in payload]
    write_zip(out/'job-research-openai-plugin.zip',plugin)
    portable=root/'portable/JOB_RESEARCH.md'
    portable.parent.mkdir(parents=True,exist_ok=True)
    portable.write_text(make_portable(root),encoding='utf-8')
    manifest={'version':(root/'VERSION').read_text().strip(),
              'kind':'packaging_checks_not_runtime_validation',
              'canonical_skill_sha256':hashlib.sha256((skill/'SKILL.md').read_bytes()).hexdigest(),
              'artifacts':{name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in sorted(ARTIFACT_NAMES)},
              'portable_sha256':hashlib.sha256(portable.read_bytes()).hexdigest(),
              'payload':{n:hashlib.sha256(b).hexdigest() for n,b in payload}}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest

def write_package_manifest(root:Path=ROOT)->dict:
    """Inventory only distributable source, never private run folders or git data."""
    root_files=['.gitignore','CHANGELOG.md','LICENSE','LICENSE-CHOICE.md','PRIVACY.md','QUICKSTART.en.md',
                'README.md','SECURITY.md','START_HERE.ko.md','VERSION','WORK_HANDOFF.ko.txt','plugin.json']
    paths=[root/name for name in root_files if (root/name).is_file()]
    for directory in ['.codex-plugin','docs','portable','scripts','skills','tests','.github']:
        paths.extend(files_under(root/directory))
    paths.extend(root/'dist'/name for name in [*ARTIFACT_NAMES,'manifest.json'])
    payload={'version':(root/'VERSION').read_text().strip(),
             'files':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(paths) if p.is_file()}}
    (root/'PACKAGE_MANIFEST.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    return payload

if __name__=='__main__':
    result=build();write_package_manifest()
    print(json.dumps({'version':result['version'],'artifacts':list(result['artifacts'])},indent=2))

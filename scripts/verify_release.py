#!/usr/bin/env python3
"""Verify source/ZIP/version bytes; never claim a host was installed or executed."""
from pathlib import Path
import hashlib,json,re
from zipfile import ZipFile
from build_release import ROOT,ARTIFACT_NAMES,make_portable,payload_sources

def digest(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def verify(root:Path=ROOT)->dict:
    version=(root/'VERSION').read_text().strip()
    manifest=json.loads((root/'dist/manifest.json').read_text())
    source=json.loads((root/'PACKAGE_MANIFEST.json').read_text())
    if manifest['version']!=version or source['version']!=version:
        raise ValueError('manifest version mismatch')
    core=(root/'skills/job-research/SKILL.md').read_bytes()
    if f'version: "{version}"' not in core.decode():
        raise ValueError('skill version mismatch')
    helper=(root/'skills/job-research/scripts/job_research.py').read_text()
    if f"VERSION = '{version}'" not in helper:
        raise ValueError('helper version mismatch')
    for name in ['plugin.json','.codex-plugin/plugin.json']:
        if json.loads((root/name).read_text())['version']!=version:
            raise ValueError('plugin version mismatch')
    if manifest['canonical_skill_sha256']!=digest(core):
        raise ValueError('canonical skill hash mismatch')
    license_bytes=(root/'LICENSE').read_bytes()
    if license_bytes!=(root/'skills/job-research/LICENSE.txt').read_bytes():
        raise ValueError('skill license differs from source license')
    portable=(root/'portable/JOB_RESEARCH.md').read_bytes()
    if portable.decode()!=make_portable(root) or manifest['portable_sha256']!=digest(portable):
        raise ValueError('portable instructions stale')
    if set(manifest['artifacts'])!=set(ARTIFACT_NAMES):
        raise ValueError('unexpected release artifact inventory')
    prefixes={'job-research-upload-root.zip':'','job-research-claude.zip':'job-research/',
              'job-research-openai-plugin.zip':'job-research/skills/job-research/'}
    payload=payload_sources(root)
    if set(payload)!=set(manifest['payload']):raise ValueError('source/runtime payload inventory mismatch')
    for name,prefix in prefixes.items():
        archive=root/'dist'/name
        if digest(archive.read_bytes())!=manifest['artifacts'][name]:
            raise ValueError('archive hash mismatch: '+name)
        with ZipFile(archive) as z:
            expected={prefix+n for n in manifest['payload']}
            if name=='job-research-openai-plugin.zip':
                expected|={'job-research/LICENSE','job-research/plugin.json','job-research/.codex-plugin/plugin.json'}
                for f in ['LICENSE','plugin.json','.codex-plugin/plugin.json']:
                    if z.read('job-research/'+f)!=(root/f).read_bytes():
                        raise ValueError('plugin archive bytes mismatch')
            if set(z.namelist())!=expected or len(z.namelist())!=len(expected):
                raise ValueError('archive payload inventory mismatch')
            for rel,sha in manifest['payload'].items():
                data=payload[rel].read_bytes()
                if digest(data)!=sha or z.read(prefix+rel)!=data:
                    raise ValueError('payload bytes mismatch: '+rel)
    for rel,sha in source['files'].items():
        path=root/rel
        if Path(rel).is_absolute() or '..' in Path(rel).parts or path.is_symlink():
            raise ValueError('unsafe source manifest path')
        if not path.is_file() or digest(path.read_bytes())!=sha:
            raise ValueError('source manifest stale: '+rel)
    return {'version':version,'status':'pass','source_files':len(source['files']),
            'upload_archives':len(prefixes),'scope':'source and packaging integrity only'}

if __name__=='__main__':
    print(json.dumps(verify(),ensure_ascii=False,indent=2))

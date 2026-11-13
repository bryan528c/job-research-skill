import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('runtime_builder',ROOT/'scripts/build_release.py')
B=importlib.util.module_from_spec(spec);spec.loader.exec_module(B)

class RuntimePackageTests(unittest.TestCase):
    def test_zip_metadata_does_not_depend_on_build_os(self):
        with tempfile.TemporaryDirectory() as name:
            B.build(ROOT,Path(name))
            with ZipFile(Path(name)/'job-research-upload-root.zip') as archive:
                self.assertTrue(all(info.create_system==3 for info in archive.infolist()))
                self.assertTrue(all(info.external_attr>>16==0o100644 for info in archive.infolist()))

    def test_source_manifest_uses_case_sensitive_portable_order(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'VERSION').write_text('synthetic')
            (root/'README.md').write_text('Synthetic');(root/'LICENSE').write_text('Synthetic')
            (root/'docs').mkdir();(root/'docs/Z.md').write_text('Synthetic');(root/'docs/a.md').write_text('Synthetic')
            result=B.write_package_manifest(root)
            self.assertEqual(list(result['files']),sorted(result['files']))

    def test_native_zip_runs_engine_without_checkout(self):
        with tempfile.TemporaryDirectory() as name:
            temp=Path(name);B.build(ROOT,temp/'archives')
            with ZipFile(temp/'archives/job-research-upload-root.zip') as archive:
                archive.extractall(temp/'isolated')
            db=temp/'private/research.sqlite'
            result=subprocess.run([sys.executable,str(temp/'isolated/scripts/research.py'),'--db',str(db),'init'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['schema'],3)
            self.assertTrue(db.is_file())

    def test_runtime_bytes_are_built_from_canonical_engine_only(self):
        with tempfile.TemporaryDirectory() as name:
            manifest=B.build(ROOT,Path(name))
            key='scripts/runtime/job_research_engine/store.py'
            self.assertIn(key,manifest['payload'])
            with ZipFile(Path(name)/'job-research-upload-root.zip') as archive:
                self.assertEqual(archive.read(key),(ROOT/'engine/job_research_engine/store.py').read_bytes())
                self.assertFalse(any('private' in p.lower() or p.endswith(('.db','.sqlite')) for p in archive.namelist()))

if __name__=='__main__':unittest.main()

import sqlite3,tempfile,unittest
from pathlib import Path
from job_research_engine.store import Store
from job_research_engine.model import Job,Page

class ObservationURLTests(unittest.TestCase):
    def test_same_bytes_and_clock_at_two_actual_urls_produce_two_real_observations(self):
        with Store(':memory:') as s:
            s.set_profile('p',{})
            s.import_companies('fixture',[{'external_id':'1','name':'Example'}],source_url='https://registry.example',scope='fixture',raw_sha256='a'*64,provenance='fixture')
            sid=s.add_source('host-json','https://jobs.example/list',company_id=None,policy='host_only',evidence_ref='fixture')
            run=s.plan_run('p',scope_note='fixture');s.attach_source(run,sid);t=s.claim(run,source_ids=[sid])
            args=dict(media_type='text/plain',origin='fixture',tool_ref=None,observed_at='2026-01-01T00:00:00+00:00')
            one=s._observe(t,'https://jobs.example/one',b'same bytes',**args)
            two=s._observe(t,'https://jobs.example/two',b'same bytes',**args)
            self.assertNotEqual(one,two);self.assertEqual(s.row('observations',two)['source_url'],'https://jobs.example/two')
            self.assertEqual(s._observe(t,'https://jobs.example/two',b'same bytes',**args),two)
    def test_schema2_migration_keeps_all_observation_ids_payloads_and_references(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'private.sqlite'
            with Store(path) as s:
                s.set_profile('p',{})
                s.import_companies('fixture',[{'external_id':'1','name':'Example'}],source_url='https://registry.example',scope='fixture',raw_sha256='a'*64,provenance='fixture')
                sid=s.add_source('host-json','https://jobs.example/list',company_id=None,policy='host_only',evidence_ref='fixture')
                run=s.plan_run('p',scope_note='fixture');s.attach_source(run,sid);t=s.claim(run,source_ids=[sid])
                result=s.commit_page(t['id'],t['lease_token'],Page([Job('1','Planning','Example','https://jobs.example/1')],True),source_url='https://jobs.example/list',payload=b'fixture bytes',origin='fixture')
                oid=result['observation_id'];before=s.row('observations',oid);original_job=s.row('jobs',result['job_ids'][0])
            db=sqlite3.connect(path);db.execute('PRAGMA foreign_keys=OFF')
            sql=db.execute("SELECT sql FROM sqlite_master WHERE name='observations'").fetchone()[0]
            db.executescript(sql.replace('observations(','old_observations(').replace('UNIQUE(source_id,source_url,sha256,observed_at)','UNIQUE(source_id,sha256,observed_at)')+'; INSERT INTO old_observations SELECT * FROM observations; DROP TABLE observations; ALTER TABLE old_observations RENAME TO observations; UPDATE meta SET value=\'2\' WHERE key=\'schema_version\';')
            db.close()
            with Store(path) as s:
                self.assertEqual(s.row('observations',oid),before);self.assertEqual(s.row('jobs',result['job_ids'][0]),original_job)
                self.assertFalse(s.db.execute('PRAGMA foreign_key_check').fetchall())
                self.assertEqual(s.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],'3')
            self.assertEqual(len(list(Path(td).glob('*.schema2-*.bak.sqlite'))),1)
            with Store(path) as s:self.assertEqual(s.row('observations',oid),before)
            self.assertEqual(len(list(Path(td).glob('*.schema2-*.bak.sqlite'))),1)

if __name__=='__main__':unittest.main()

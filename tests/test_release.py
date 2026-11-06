from __future__ import annotations
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

Q=module('quality',ROOT/'skills/job-research/scripts/job_research.py')
I=module('installer',ROOT/'scripts/install_skill.py')
B=module('builder',ROOT/'scripts/build_release.py')
G=module('grader',ROOT/'tests/evaluate_capture.py')
F=module('fixture_browser',ROOT/'tests/fixture_browser.py')

def load(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
def job():return copy.deepcopy(load('tests/fixtures/report.json')['jobs'][0])
def receipt():return copy.deepcopy(load('tests/fixtures/receipt.json'))

class PackageTests(unittest.TestCase):
    def test_frontmatter(self):
        s=(ROOT/'skills/job-research/SKILL.md').read_text()
        f=re.match(r'\A---\n(.*?)\n---\n',s,re.S).group(1)
        self.assertIn('name: job-research',f)
        for key,limit in [('description',1024),('compatibility',500)]:
            value=re.search(key+r': "([^\n]+)"',f).group(1)
            self.assertTrue(0<len(value)<=limit)
    def test_core_version(self):
        self.assertIn(f'version: "{Q.VERSION}"',(ROOT/'skills/job-research/SKILL.md').read_text())
        self.assertEqual((ROOT/'VERSION').read_text().strip(),Q.VERSION)
    def test_skill_local_links(self):
        d=ROOT/'skills/job-research'
        for p in d.rglob('*.md'):
            for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
                if '://' in link or link.startswith('#') or link=='observed URL':continue
                target=(p.parent/link.split('#')[0]).resolve()
                self.assertTrue(target.is_relative_to(d.resolve()),str(p)+link)
                self.assertTrue(target.is_file(),str(p)+link)
    def test_core_not_tool_whitelist(self):
        s=(ROOT/'skills/job-research/SKILL.md').read_text()
        self.assertNotIn('allowed-tools:',s)
        self.assertLess(len(s.splitlines()),500)
    def test_coverage_required_for_broad(self):
        s=(ROOT/'skills/job-research/SKILL.md').read_text()
        self.assertIn('read [coverage safeguards]',s)
        self.assertIn('single-job review',s)
        self.assertIn('counter-search',s)
    def test_selected_job_branch_present(self):
        s=(ROOT/'skills/job-research/SKILL.md').read_text()
        self.assertIn('Continue only for user-selected jobs',s)
        self.assertIn('새 채팅용 프롬프트',s)
        self.assertIn('references/links.md',s)
    def test_scenario_definitions_not_results(self):
        s=load('tests/scenarios.json');self.assertEqual(s['status'],'not_executed_against_a_model')
        self.assertEqual(s['version'],Q.VERSION)
        ids=[c['id'] for c in s['cases']];self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(len(ids),64)
        for c in s['cases']:
            self.assertEqual(c['evaluation_status'],'not_run');self.assertTrue(c['expected']);self.assertTrue(c['forbidden'])
    def test_minimal_plugins(self):
        p=load('plugin.json');c=load('.codex-plugin/plugin.json')
        self.assertEqual(p['version'],Q.VERSION);self.assertEqual(c['version'],Q.VERSION)
        self.assertEqual(c['skills'],'./skills/');self.assertEqual(p['name'],'job-research')
        self.assertNotIn('mcpServers',p)
    def test_offline_helper_has_no_network_client(self):
        tree=ast.parse((ROOT/'skills/job-research/scripts/job_research.py').read_text())
        imported=[]
        for n in ast.walk(tree):
            if isinstance(n,ast.Import):imported += [x.name for x in n.names]
            elif isinstance(n,ast.ImportFrom):imported += [n.module or '']
        self.assertFalse(set(imported)&{'requests','httpx','urllib.request','socket','http.client','subprocess'})
    def test_source_docs_record_runtime_limits(self):
        s=(ROOT/'docs/compatibility.ko.md').read_text()
        self.assertIn('not_run',s);self.assertIn('메모리',s);self.assertIn('공식',s)
    def test_portable_no_relative_reference_dependencies(self):
        s=B.make_portable(ROOT)
        self.assertNotRegex(s,r'\]\((?:references|scripts|assets)/')
        for name in ['# Coverage safeguards','# Optional application continuation','# Direct links users can act on']:
            self.assertIn(name,s)
    def test_plugin_zip_has_no_tests_or_oracles(self):
        with tempfile.TemporaryDirectory() as d:
            B.build(ROOT,Path(d))
            with ZipFile(Path(d)/'job-research-openai-plugin.zip') as z:
                self.assertIn('job-research/plugin.json',z.namelist())
                self.assertIn('job-research/skills/job-research/SKILL.md',z.namelist())
                self.assertFalse(any('oracles' in n or '/tests/' in n for n in z.namelist()))
    def test_upload_root_layout_and_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            m=B.build(ROOT,Path(d))
            with ZipFile(Path(d)/'job-research-upload-root.zip') as z:
                self.assertIn('SKILL.md',z.namelist());self.assertIn('references/continuation.md',z.namelist())
                self.assertEqual(z.read('SKILL.md'),(ROOT/'skills/job-research/SKILL.md').read_bytes())
                self.assertFalse(any(n.endswith('.pyc') for n in z.namelist()))
    def test_claude_folder_layout(self):
        with tempfile.TemporaryDirectory() as d:
            B.build(ROOT,Path(d))
            with ZipFile(Path(d)/'job-research-claude.zip') as z:
                self.assertIn('job-research/SKILL.md',z.namelist())
                self.assertTrue(all(n.startswith('job-research/') for n in z.namelist()))
    def test_reproducible_artifacts(self):
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            one=B.build(ROOT,Path(a));two=B.build(ROOT,Path(b))
            self.assertEqual(one['artifacts'],two['artifacts'])
            self.assertEqual(one['payload'],two['payload'])
    def test_build_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):B.write_zip(Path(d)/'x.zip',[('../escape',b'x')])

class LinkAndDeadlineTests(unittest.TestCase):
    def test_accept_real_shaped_job_query(self):
        u='https://careers.example.org/job?postingId=123&jobCode=PM'
        self.assertEqual(Q.public_url(u),u)
    def test_reject_executable_scheme(self):
        for u in ['javascript:alert(1)','file:///etc/passwd','data:text/html,x']:
            with self.subTest(u=u),self.assertRaises(Q.ValidationError):Q.public_url(u)
    def test_reject_private_addresses(self):
        for u in ['http://127.0.0.1/x','http://10.0.0.1/x','http://[::1]/x','http://localhost/x','http://host.internal/x']:
            with self.subTest(u=u),self.assertRaises(Q.ValidationError):Q.public_url(u)
    def test_reject_embedded_credentials(self):
        with self.assertRaises(Q.ValidationError):Q.public_url('https://user:secret@example.org/job')
    def test_reject_query_secrets(self):
        for key in ['access_token','api_key','sessionid','token','X-Amz-Signature']:
            with self.subTest(key=key),self.assertRaises(Q.ValidationError):Q.public_url(f'https://example.org/job?{key}=x')
    def test_reject_control_delimiters(self):
        for u in ['https://example.org/job\nsecret','https://example.org/ a','https://example.org/<x>']:
            with self.subTest(u=u),self.assertRaises(Q.ValidationError):Q.public_url(u)
    def test_reject_token_fragment(self):
        with self.assertRaises(Q.ValidationError):Q.public_url('https://example.org/job#access_token=secret')
    def test_date_only_not_2359(self):
        label=Q.deadline_label({'kind':'date','date':'2030-04-09'})
        self.assertIn('미기재',label);self.assertNotIn('23:59',label)
    def test_date_only_hidden_time_rejected(self):
        with self.assertRaises(Q.ValidationError):Q.deadline_label({'kind':'date','date':'2030-04-09','time':'23:59'})
    def test_midday_preserved(self):
        label=Q.deadline_label({'kind':'datetime','at':'2030-04-09T11:59:00+09:00'})
        self.assertIn('11:59',label);self.assertNotIn('23:59',label)
    def test_naive_datetime_rejected(self):
        with self.assertRaises(Q.ValidationError):Q.deadline_label({'kind':'datetime','at':'2030-04-09T11:59:00'})
    def test_invalid_date_rejected(self):
        with self.assertRaises(Q.ValidationError):Q.deadline_label({'kind':'date','date':'2030-02-30'})
    def test_recommend_blocker_rejected(self):
        j=job();j['blocking_unknowns']=['필수 출근일 확인']
        with self.assertRaises(Q.ValidationError):Q.validate_job(j)
    def test_recommend_closed_rejected(self):
        j=job();j['recruiting_status']='closed'
        with self.assertRaises(Q.ValidationError):Q.validate_job(j)
    def test_homepage_not_verified_job(self):
        j=job();j['links']=[{'url':'https://example.org','kind':'homepage','status':'verified','checked_at':j['checked_at']}]
        with self.assertRaises(Q.ValidationError):Q.validate_job(j)
    def test_verified_link_requires_observation_time(self):
        j=job();del j['links'][0]['checked_at']
        with self.assertRaises(Q.ValidationError):Q.validate_job(j)
    def test_check_unverified_allowed_labeled(self):
        j=job();j['decision']='check'
        for l in j['links']:l['status']='unverified'
        Q.validate_job(j);self.assertIn('직접 확인 미완료',Q.link_line(j))
    def test_distinct_apply_url_and_login_label(self):
        out=Q.link_line(job());self.assertIn('공식 공고',out);self.assertIn('지원하기·로그인 필요',out)
        self.assertIn('https://apply.example.org/',out)
    def test_duplicate_links_collapsed(self):
        j=job();j['links'].append(copy.deepcopy(j['links'][0]))
        self.assertEqual(Q.link_line(j).count('https://careers.example.org/'),1)

class ReportAndHandoffTests(unittest.TestCase):
    def test_report_preserves_seven_jobs(self):
        r=load('tests/fixtures/report.json');out=Q.render_report(r)
        for j in r['jobs']:self.assertIn(j['employer'],out)
        self.assertEqual(out.count('공식 공고'),7)
    def test_no_mandatory_followup_prompt(self):
        out=Q.render_report(load('tests/fixtures/report.json'))
        self.assertNotIn('새 채팅용 프롬프트',out)
        self.assertNotIn('[선택 공고]',out)
    def test_followup_single_optional_line(self):
        r=load('tests/fixtures/report.json');r['offer_followup']=True
        self.assertEqual(Q.render_report(r).count('새 채팅용 프롬프트'),1)
    def test_duplicate_report_numbers_rejected(self):
        r=load('tests/fixtures/report.json');r['jobs'][1]['report_number']=1
        with self.assertRaises(Q.ValidationError):Q.render_report(r)
    def test_check_separate(self):
        r=load('tests/fixtures/report.json');r['jobs'][0]['decision']='check'
        self.assertIn('확인 필요',Q.render_report(r))
    def test_excluded_not_new_suggestion(self):
        r=load('tests/fixtures/report.json');r['jobs'][0]['decision']='exclude'
        self.assertNotIn(r['jobs'][0]['employer'],Q.render_report(r))
    def test_submitted_not_new_suggestion(self):
        r=load('tests/fixtures/report.json');r['jobs'][0]['application_stage']='submitted'
        self.assertNotIn(r['jobs'][0]['employer'],Q.render_report(r))
    def test_archived_closed_submission_not_recommended_again(self):
        r=load('tests/fixtures/report.json');r['jobs'][0]['application_stage']='submitted';r['jobs'][0]['recruiting_status']='closed'
        self.assertNotIn(r['jobs'][0]['employer'],Q.render_report(r))
    def test_display_compaction_does_not_drop_jobs(self):
        r=load('tests/fixtures/report.json');r['expanded_job_ids']=[]
        out=Q.render_report(r)
        self.assertEqual(out.count('공식 공고'),7)
        self.assertLess(len(out.splitlines()),30)
    def test_known_application_stage_in_handoff(self):
        j=job();j['application_stage']='submitted'
        self.assertIn('현재 지원 단계: submitted',Q.make_handoff(j,[],'면접 준비'))
    def test_material_limitation_visible(self):
        r=load('tests/fixtures/report.json');r['limitation']='일부 상세페이지 확인 미완료'
        self.assertIn(r['limitation'],Q.render_report(r))
    def test_selection_ambiguous_number_rejected(self):
        r=load('tests/fixtures/report.json');r2=copy.deepcopy(r);r2['report_id']='other'
        with self.assertRaises(Q.ValidationError):Q.resolve_selection([r,r2],'2')
    def test_selection_bound_to_report(self):
        r=load('tests/fixtures/report.json');r2=copy.deepcopy(r);r2['report_id']='other';r2['jobs'][1]['id']='new-job'
        self.assertEqual(Q.resolve_selection([r,r2],'2',r['report_id'])['id'],'job-2')
    def test_unknown_selection_no_guess(self):
        with self.assertRaises(Q.ValidationError):Q.resolve_selection([load('tests/fixtures/report.json')],'999')
    def test_handoff_self_contained(self):
        j=job();out=Q.make_handoff(j,['사용자 자기보고: 요구사항 작성 경험'],'지원 계획부터 정리해줘.')
        for s in [j['employer'],j['role'],j['round'],j['checked_at'],j['links'][0]['url'],'현재 지원 단계: 미확인']:
            self.assertIn(s,out)
        self.assertIn('최신 공식 자료로 재확인',out)
    def test_handoff_only_selected_job(self):
        r=load('tests/fixtures/report.json');out=Q.make_handoff(r['jobs'][0],[],'계획')
        self.assertNotIn(r['jobs'][1]['employer'],out)
    def test_handoff_no_fake_chat_launch(self):
        out=Q.make_handoff(job(),[],'계획')
        self.assertNotIn('chatgpt.com/?',out);self.assertNotIn('claude.ai/new',out)
    def test_handoff_rejects_full_memory_object(self):
        with self.assertRaises(Q.ValidationError):Q.make_handoff(job(),{'private':'data'},'계획')
    def test_handoff_rejects_contact_data(self):
        with self.assertRaises(Q.ValidationError):Q.make_handoff(job(),['email: user@example.org'],'계획')
    def test_handoff_rejects_credentials(self):
        with self.assertRaises(Q.ValidationError):Q.make_handoff(job(),['api_key=not-a-real-secret'],'계획')
    def test_handoff_respects_decline(self):
        j=job();j['user_decision']='declined'
        with self.assertRaises(Q.ValidationError):Q.make_handoff(j,[],'계획')

class CoverageTests(unittest.TestCase):
    def test_consistent_fixture(self):
        out=Q.audit_receipt(receipt());self.assertEqual(out['status'],'pass');self.assertTrue(out['warnings'])
    def test_missing_branches(self):
        r=receipt();r['branches']=[];self.assertIn('broad_scope_without_branches',Q.audit_receipt(r)['errors'])
    def test_missing_evidence(self):
        r=receipt();r['branches'][0]['evidence_refs']=[]
        self.assertIn('checked_branch_without_evidence',Q.audit_receipt(r)['errors'])
    def test_unobserved_evidence_id(self):
        r=receipt();r['branches'][0]['evidence_refs']=['invented']
        self.assertEqual(Q.audit_receipt(r)['status'],'fail')
    def test_material_gap_cannot_be_complete(self):
        r=receipt();r['branches'][0].update(status='gap',first_gap_at='2030-03-01',revisit_trigger='next run')
        self.assertIn('unsupported_scope_complete',Q.audit_receipt(r)['errors'])
    def test_partial_result_permitted(self):
        r=receipt();r['scope_status']='partial';r['branches'][0].update(status='gap',first_gap_at='2030-03-01',revisit_trigger='next run')
        out=Q.audit_receipt(r);self.assertEqual(out['status'],'pass');self.assertIn('service',out['material_gaps'])
    def test_gap_age_required(self):
        r=receipt();r['scope_status']='partial';r['branches'][0]['status']='deferred'
        self.assertIn('gap_without_age_or_revisit',Q.audit_receipt(r)['errors'])
    def test_new_fit_requires_expansion(self):
        r=receipt();r['counter_searches'][0].pop('followthrough_refs')
        self.assertIn('new_fit_branch_unexpanded',Q.audit_receipt(r)['material_gaps'])
    def test_counter_without_distinct_route(self):
        r=receipt();r['counter_searches'][0].pop('different_route_reason')
        self.assertIn('counter_search_not_distinct',Q.audit_receipt(r)['errors'])
    def test_old_open_not_skipped(self):
        r=receipt();r.pop('older_open')
        self.assertIn('older_open',Q.audit_receipt(r)['material_gaps'])
    def test_false_exclusion_needs_evidence(self):
        r=receipt();r['candidates'][2].pop('evidence_refs')
        self.assertIn('exclusion_without_evidence',Q.audit_receipt(r)['errors'])
    def test_report_loss_caught(self):
        r=receipt();r['displayed_job_ids']=['job-1']
        self.assertIn('recommended_candidate_lost_from_report',Q.audit_receipt(r)['errors'])
    def test_fake_full_list_caught(self):
        r=receipt();r['displayed_job_ids']=['job-1'];r['retained_job_ids']=['job-2']
        self.assertIn('retained_list_not_proven_accessible',Q.audit_receipt(r)['errors'])
    def test_unknown_recommendation_caught(self):
        r=receipt();r['displayed_job_ids'].append('fabricated')
        self.assertIn('report_contains_unknown_candidate',Q.audit_receipt(r)['errors'])
    def test_version_mismatch(self):
        r=receipt();r['skill_version']='old'
        self.assertIn('loaded_skill_version_mismatch_or_unknown',Q.audit_receipt(r)['errors'])
    def test_self_receipt_not_trace_proof(self):
        r=receipt();r['evidence_assurance']='trace_verified'
        self.assertIn('unsupported_trace_verified_claim',Q.audit_receipt(r)['errors'])
    def test_single_job_not_forced_market_audit(self):
        r=receipt();r['scope']='single';r['branches']=[];r['counter_searches']=[]
        r.pop('older_open');r.pop('uncertain_exclusions')
        self.assertEqual(Q.audit_receipt(r)['status'],'pass')

class InstallerAndGraderTests(unittest.TestCase):
    def test_installer_dry_run_no_writes(self):
        with tempfile.TemporaryDirectory() as d:
            target=I.install('codex',Path(d));self.assertFalse(target.exists());self.assertEqual(list(Path(d).iterdir()),[])
    def test_installer_each_host_copy(self):
        for host,prefix in I.PREFIX.items():
            with self.subTest(host=host),tempfile.TemporaryDirectory() as d:
                target=I.install(host,Path(d),True)
                self.assertEqual(target,Path(d)/prefix/'skills/job-research')
                self.assertEqual((target/'SKILL.md').read_bytes(),(ROOT/'skills/job-research/SKILL.md').read_bytes())
                self.assertTrue((target/'references/links.md').exists())
    def test_installer_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            target=I.install('codex',Path(d),True)
            before=(target/'SKILL.md').read_bytes()
            with self.assertRaises(FileExistsError):I.install('codex',Path(d),True)
            self.assertEqual((target/'SKILL.md').read_bytes(),before)
    def test_installer_rejects_unknown_host(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):I.install('made-up',Path(d))
    def test_installer_rejects_symlink_destination(self):
        with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as other:
            (Path(d)/'.agents').symlink_to(Path(other),target_is_directory=True)
            with self.assertRaises(ValueError):I.install('codex',Path(d),True)
    def test_grader_detects_miss_and_report_loss(self):
        o=load('tests/oracles/discovery.expected.json');one=o['recommend'][0]
        capture={'observed_job_ids':[one],'recommended_job_ids':[one],'check_job_ids':[],
                 'excluded_job_ids':[o['recommend'][1]],'report_job_ids':[]}
        result=G.grade(capture,o)
        self.assertEqual(result['lost_in_report_job_ids'],[one])
        self.assertEqual(result['false_exclusion_job_ids'],[o['recommend'][1]])
        self.assertLess(result['observed_recall'],1)
    def test_grader_rejects_fabricated_job(self):
        o=load('tests/oracles/discovery.expected.json')
        c={k:[] for k in ['observed_job_ids','recommended_job_ids','check_job_ids','excluded_job_ids','report_job_ids']}
        c['recommended_job_ids']=['unknown']
        with self.assertRaises(ValueError):G.grade(c,o)
    def test_fixture_search_does_not_return_oracle(self):
        pages=load('tests/fixtures/discovery/pages.json')['pages']
        result=F.search(pages,'서비스')
        self.assertTrue(result)
        for row in result:self.assertEqual(set(row),{'page_id','title','employer','url'})
    def test_fixture_old_open_and_duplicate_present(self):
        pages=load('tests/fixtures/discovery/pages.json')['pages']
        self.assertEqual(sum(p['job_id']=='j01' for p in pages),2)
        self.assertIn('2030-02-01',next(p['body'] for p in pages if p['job_id']=='j03'))

if __name__=='__main__':unittest.main(verbosity=2)

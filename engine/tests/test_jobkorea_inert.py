import json,unittest
from job_research_engine.jobkorea import observed_iframe,description_body,public_records
from job_research_engine.model import EngineError

def script(text):return ('<script>self.__next_f.push('+json.dumps([1,text])+');</script>').encode()

class InertHTMLTests(unittest.TestCase):
    def test_actual_src_contract_checks_id_host_and_path(self):
        payload=script('1:'+json.dumps({'data-sentry-element':'IframeViewer','src':'/Recruit/GI_Read_Comt_Ifrm?Gno=123'})+'\n')
        self.assertEqual(observed_iframe(payload,'https://www.jobkorea.co.kr/Recruit/GI_Read/123','123'),'https://www.jobkorea.co.kr/Recruit/GI_Read_Comt_Ifrm?Gno=123')
        with self.assertRaises(EngineError):observed_iframe(payload,'https://www.jobkorea.co.kr/Recruit/GI_Read/456','456')
        with self.assertRaises(EngineError):observed_iframe(payload,'https://unrelated.example/123','123')
    def test_korean_byte_framing_adjacent_json_and_split_scripts(self):
        body='<div>합성 직무 본문\n5:{"not":"a record"}</div>'
        stream='1e:T'+format(len(body.encode()),'x')+','+body+'5:'+json.dumps({'data-sentry-element':'GIReadDetailContentIframeClient','jobId':123,'htmlContent':'$1e'})+'\n'
        payload=script(stream[:30])+script(stream[30:])
        self.assertIn('합성 직무 본문',description_body(payload,'https://m.jobkorea.co.kr/Recruit/GIReadDetailContentIframe/123','123')['description'])
        with self.assertRaises(EngineError):description_body(payload,'https://m.jobkorea.co.kr/Recruit/GIReadDetailContentIframe/123','999')
    def test_malformed_lengths_and_active_js_are_not_executed(self):
        with self.assertRaises(EngineError):public_records(script('1:Tff,too short'))
        payload=b'<script>self.__next_f.push(alert("never"));</script>'
        with self.assertRaises(EngineError):public_records(payload)
    def test_image_body_does_not_become_verified_duties(self):
        body='<div>'+('Synthetic common terms '*8)+'<img src="https://images.example/poster.png"></div>'
        result=description_body(body.encode(),'https://www.jobkorea.co.kr/Recruit/GI_Read_Comt_Ifrm?Gno=123','123')
        self.assertFalse(result['detail_verified']);self.assertEqual(len(result['media_urls']),1)

if __name__=='__main__':unittest.main()

import json
import unittest
from unittest.mock import patch
from job_research_engine.transport import PublicHTTP,Response,FetchError
from job_research_engine.model import EngineError

URL='https://talent.hyundai.com/apply/applyView.hc?nfGubnC=&recuYy=2026&recuType=N5&recuCls=255'


class HyundaiPublicTests(unittest.TestCase):
    def gate(self,flag):return Response('https://talent.hyundai.com/api/rec/AP-HM-FO-02900',200,{},json.dumps({'data':{'applySecret':{'recuNoticeSecretYn':flag}}}).encode())

    def test_only_explicit_nonsecret_opens_detail_read(self):
        client=PublicHTTP(enabled=True)
        with patch.object(client,'permitted_by_robots',return_value=True),patch.object(client,'_one',side_effect=[self.gate('N'),Response('https://talent.hyundai.com/api/rec/AP-HM-FO-02800',200,{},b'{}')]) as read:
            gate,detail=client.get_hyundai_detail(URL)
            self.assertEqual(read.call_count,2)
            self.assertIn('02900?',read.call_args_list[0].args[0]);self.assertIn('02800?',read.call_args_list[1].args[0])
            self.assertEqual(read.call_args_list[1].kwargs,{'hyundai_public_read':True})

    def test_secret_or_missing_flag_never_calls_body_password_or_application(self):
        for flag in ('Y',None,''):
            with self.subTest(flag=flag):
                client=PublicHTTP(enabled=True)
                with patch.object(client,'permitted_by_robots',return_value=True),patch.object(client,'_one',return_value=self.gate(flag)) as read:
                    with self.assertRaises(FetchError) as error:client.get_hyundai_detail(URL)
                    self.assertEqual(error.exception.code,'nonpublic_or_unknown_notice');self.assertEqual(read.call_count,1)

    def test_unobserved_identity_params_and_write_routes_refused(self):
        client=PublicHTTP(enabled=True)
        for url in (URL+'&password=x',URL+'&recuCls=7',URL.replace('nfGubnC=','nfGubnC=queue'),URL.replace('applyView.hc','applySave.hc'),URL.replace('talent.hyundai.com','example.com'),URL.replace('recuCls=255','recuCls=0')):
            with patch.object(client,'_one') as read:
                with self.assertRaises(EngineError):client.get_hyundai_detail(url)
                read.assert_not_called()


if __name__=='__main__':unittest.main()

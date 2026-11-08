from datetime import datetime,timezone
import contextlib
import io
import os
import smtplib
import unittest
from unittest.mock import patch, Mock
import cloud_run
from cloud_run import current_slot,send_once,delivery_key

class Ledger:
    def __init__(self):self.data={'deliveries':{}};self.saved=[]
    def save(self):self.saved.append([r['status'] for r in self.data['deliveries'].values()])

class SMTP:
    calls=0;failure=None
    def __init__(self,*a,**k):pass
    def login(self,*a):pass
    def send_message(self,message,**kw):
        SMTP.calls+=1
        assert message.get_content_type()=='text/plain' and not list(message.iter_attachments())
        if SMTP.failure:raise SMTP.failure
        return {}
    def quit(self):pass
    def close(self):pass

class Tests(unittest.TestCase):
    def setUp(self):
        SMTP.calls=0;SMTP.failure=None
        finisher=patch.object(cloud_run,'finish');self.finish=finisher.start();self.addCleanup(finisher.stop)
    def test_singapore_slots(self):
        self.assertEqual(current_slot(datetime(2026,11,5,2,tzinfo=timezone.utc)).isoformat(),'2026-11-05T10:00:00+08:00')
        self.assertEqual(current_slot(datetime(2026,11,5,12,tzinfo=timezone.utc)).isoformat(),'2026-11-05T20:00:00+08:00')
        self.assertEqual(current_slot(datetime(2026,11,5,1,59,tzinfo=timezone.utc)).hour,20)
    def test_acceptance_is_recorded_and_not_sent_twice(self):
        ledger=Ledger()
        for _ in range(2):send_once(ledger,'slot','reader@example.com','dummy','金融重点：关注通胀与融资成本。',SMTP)
        self.assertEqual(SMTP.calls,1);self.assertEqual(ledger.saved,[['sending'],['sent']])
    def test_uncertain_delivery_is_not_retried(self):
        ledger=Ledger();SMTP.failure=smtplib.SMTPServerDisconnected('test')
        with self.assertRaises(RuntimeError):send_once(ledger,'slot','reader@example.com','dummy','金融重点。',SMTP)
        result=send_once(ledger,'slot','reader@example.com','dummy','金融重点。',SMTP)
        self.assertEqual(result['status'],'uncertain');self.assertEqual(SMTP.calls,1)
    def test_explicit_rejection_can_retry(self):
        ledger=Ledger();SMTP.failure=smtplib.SMTPDataError(451,b'test')
        with self.assertRaises(RuntimeError):send_once(ledger,'slot','reader@example.com','dummy','金融重点。',SMTP)
        SMTP.failure=None
        self.assertEqual(send_once(ledger,'slot','reader@example.com','dummy','金融重点。',SMTP)['status'],'sent')
    def test_failed_ledger_write_prevents_smtp_data(self):
        ledger=Ledger();ledger.save=lambda:(_ for _ in ()).throw(RuntimeError('storage'))
        with self.assertRaises(RuntimeError):send_once(ledger,'slot','reader@example.com','dummy','金融重点。',SMTP)
        self.assertEqual(SMTP.calls,0)
    def test_security_recommendation_is_blocked(self):
        with self.assertRaises(ValueError):send_once(Ledger(),'slot','reader@example.com','dummy','短线关注NVDA。',SMTP)
        self.assertEqual(SMTP.calls,0)

    def test_manual_recovery_and_delayed_schedule_share_delivery(self):
        ledger=Ledger();now=datetime(2026,11,5,12,35,tzinfo=timezone.utc)
        slot=current_slot(now).isoformat()
        env={'GITHUB_ACTIONS':'true','QQ_EMAIL':'reader@example.com','QQ_SMTP_AUTH_CODE':'dummy'}
        with patch.dict(os.environ,env),patch.object(cloud_run,'GitHubLedger',return_value=ledger), \
             patch.object(cloud_run,'datetime') as clock,patch('sys.argv',['cloud_run.py']), \
             patch.object(cloud_run,'collect_brief',return_value=('金融重点。',{})) as collect, \
             patch.object(cloud_run.smtplib,'SMTP_SSL',SMTP),contextlib.redirect_stdout(io.StringIO()):
            clock.now.return_value=now
            with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ID':'manual'}):cloud_run.main()
            with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'schedule','GITHUB_RUN_ID':'timer'}):cloud_run.main()
        self.assertEqual(SMTP.calls,1);collect.assert_called_once()
        self.assertEqual(ledger.data['deliveries'][delivery_key(slot,'reader@example.com')]['slot'],slot)

    def test_manual_recovery_does_not_send_previous_slot_after_window(self):
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch',
                                  'QQ_EMAIL':'reader@example.com','QQ_SMTP_AUTH_CODE':'dummy'}), \
             patch.object(cloud_run,'GitHubLedger',return_value=Ledger()), \
             patch.object(cloud_run,'datetime') as clock,patch('sys.argv',['cloud_run.py']), \
             patch.object(cloud_run,'collect_brief') as collect,contextlib.redirect_stdout(io.StringIO()):
            clock.now.return_value=datetime(2026,11,5,7,tzinfo=timezone.utc)
            with self.assertRaises(RuntimeError):cloud_run.main()
        collect.assert_not_called();self.assertEqual(SMTP.calls,0)

    def test_failed_ack_is_repaired_without_sending_again(self):
        ledger=Ledger();now=datetime(2026,11,6,2,0,tzinfo=timezone.utc)
        env={'GITHUB_ACTIONS':'true','QQ_EMAIL':'reader@example.com','QQ_SMTP_AUTH_CODE':'dummy'}
        with patch.dict(os.environ,env),patch.object(cloud_run,'GitHubLedger',return_value=ledger), \
             patch.object(cloud_run,'datetime') as clock,patch('sys.argv',['cloud_run.py']), \
             patch.object(cloud_run,'collect_brief',return_value=('金融重点。',{})) as collect, \
             patch.object(cloud_run.smtplib,'SMTP_SSL',SMTP), \
             patch.object(cloud_run,'report_delivery',side_effect=[RuntimeError('ack failed'),None]) as ack, \
             contextlib.redirect_stdout(io.StringIO()):
            clock.now.return_value=now
            with self.assertRaises(RuntimeError):cloud_run.main()
            cloud_run.main()
        self.assertEqual(SMTP.calls,1);self.assertEqual(ack.call_count,2);collect.assert_called_once()

    def test_cloud_preview_never_loads_secrets_or_sends(self):
        with patch.dict(os.environ,{'DIGEST_PREVIEW':'true'},clear=True),patch('sys.argv',['cloud_run.py']), \
             patch.object(cloud_run,'GitHubLedger') as ledger,patch.object(cloud_run,'send_once') as sender, \
             patch.object(cloud_run,'report_delivery') as report, \
             patch.object(cloud_run,'collect_brief',return_value=('金融重点。',{'points':1})):
            cloud_run.main()
        ledger.assert_not_called();sender.assert_not_called();report.assert_not_called()
        self.assertEqual(self.finish.call_args.args[0],{'status':'preview','sent':False,'points':1})

    def test_public_repository_cannot_store_mail_ledger(self):
        response=Mock();response.json.return_value={'private':False}
        with patch.dict(os.environ,{'GITHUB_REPOSITORY':'example/public','GITHUB_TOKEN':'dummy'}), \
             patch.object(cloud_run.requests,'Session') as session:
            session.return_value.get.return_value=response
            with self.assertRaisesRegex(RuntimeError,'私有仓库'):
                cloud_run.GitHubLedger()
            self.assertEqual(session.return_value.get.call_count,1)
            session.return_value.put.assert_not_called()

    def test_preview_routes_custom_paths_without_delivery(self):
        from pathlib import Path
        with patch('sys.argv',['cloud_run.py','--preview','--config','custom.json','--output','custom-output']), \
             patch.object(cloud_run,'collect_brief',return_value=('金融重点。',{})) as collect, \
             patch.object(cloud_run,'GitHubLedger') as ledger:
            cloud_run.main()
        self.assertEqual(collect.call_args.kwargs['config_path'],Path('custom.json'))
        self.assertEqual(collect.call_args.kwargs['output_dir'],Path('custom-output').resolve())
        ledger.assert_not_called()

if __name__=='__main__':unittest.main(verbosity=2)

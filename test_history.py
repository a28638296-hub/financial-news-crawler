from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import smtplib
import unittest
from unittest.mock import patch

import cloud_run
from cloud_run import delivery_key, send_once
from finance_brief import local_news_brief
from finance_history import identity, select_new_content, delivered_items, sent_history, trim_history, source_record
from test_cloud import Ledger, SMTP

NOW=datetime(2026,11,14,12,tzinfo=timezone.utc)


def news(title='美国通胀率回落至3.2%', content=None, id='item'):
    return {'id':id,'title':title,'summary':content or title+'。','url':'https://example.com/'+id,
            'published_at':(NOW-timedelta(hours=1)).isoformat(),'time_kind':'published',
            'sources':[],'tickers':[],'topics':[],'first_seen':NOW.isoformat()}


def record(item, content=None):
    return {**identity(item),'content':content or item['summary'],'published_at':item['published_at'],**source_record(item['summary'])}


class HistoryTests(unittest.TestCase):
    def setUp(self):SMTP.calls=0;SMTP.failure=None

    def test_reprint_new_url_and_prefix_are_not_sent_again(self):
        old=news()
        changed=news('快讯：美国通胀率回落至3.2%',id='other')
        changed['summary']=old['summary']
        kept,stats=select_new_content([changed],[record(old)])
        self.assertEqual(kept,[]);self.assertEqual(stats['suppressed_news'],1)

    def test_new_numbers_and_countries_are_retained(self):
        old=news()
        for new in [news('美国通胀率回落至3.1%',id='next'),news('英国通胀率回落至3.2%',id='uk')]:
            kept,_=select_new_content([new],[record(old)])
            self.assertEqual(len(kept),1)

    def test_only_unsent_tail_survives_updated_article(self):
        old=news('美联储官员谈通胀','美联储官员表示，当前通胀压力仍然较高。')
        new={**old,'summary':old['summary']+'最新公布的就业数据进一步走弱。'}
        kept,_=select_new_content([new],[record(old)])
        self.assertEqual(kept[0]['summary'],'最新公布的就业数据进一步走弱。')
        self.assertTrue(kept[0]['is_update'])

    def test_unquoted_tail_of_unchanged_article_is_not_a_new_update(self):
        old=news(content='美国通胀率回落至3.2%。就业市场仍然放缓，后续数据还需观察。')
        kept,_=select_new_content([old],[record(old,'美国通胀率回落至3.2%。')])
        self.assertEqual(kept,[])

    def test_history_does_not_include_candidates_not_sent(self):
        packet={'facts':[{'id':'news_a','kind':'news','title':'美国通胀消息','category':'macro'},
                         {'id':'news_b','kind':'news','title':'英国就业消息','category':'macro'}]}
        brief={'points':[{'fact':'11月14日 10:00，公开来源：美国通胀率回落。','evidence_ids':['news_a']}]}
        rows=delivered_items(brief,packet,{'news_a':'https://example.com/a'})
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['id'],'a')
        self.assertEqual(rows[0]['content'],'美国通胀率回落。')

    def test_smtp_rejection_remains_eligible_but_ambiguity_blocks_content(self):
        for error,expected in [(smtplib.SMTPDataError(451,b'rejected'),0),(smtplib.SMTPServerDisconnected('unclear'),1)]:
            with self.subTest(error=type(error).__name__):
                ledger=Ledger();SMTP.failure=error;item=record(news())
                with self.assertRaises(RuntimeError):send_once(ledger,'slot','reader@example.com','dummy','金融重点。',SMTP,news_items=[item])
                self.assertEqual(len(sent_history(ledger.data,'reader@example.com',NOW)),expected)
                self.assertEqual(sent_history(ledger.data,'other@example.com',NOW),[])

    def test_persistent_history_survives_restart_and_preserves_audit(self):
        ledger=Ledger();item=record(news())
        send_once(ledger,'slot','reader@example.com','dummy','金融重点。',SMTP,news_items=[item])
        restored=json.loads(json.dumps(ledger.data))
        self.assertEqual(sent_history(restored,'reader@example.com',NOW),[item])
        trim_history(restored,datetime.now(timezone.utc)+timedelta(days=31))
        self.assertEqual(len(restored['deliveries']),1)
        self.assertNotIn('news_items',next(iter(restored['deliveries'].values())))

    def test_all_repeat_content_returns_no_mail_but_source_failure_is_error(self):
        item=news();source={'id':'test','name':'Test','kind':'媒体报道','url':'https://example.com/feed'}
        with TemporaryDirectory() as directory:
            config=Path(directory)/'config.json';config.write_text(json.dumps({'feeds':[source]}))
            for rows,status in [([item],{'id':'test','name':'Test','status':'可用','in_window':1}),
                                ([],{'id':'test','name':'Test','status':'读取失败','in_window':0})]:
                with patch.object(cloud_run,'fetch_feed',return_value=(rows,status)):
                    if rows:
                        text,details=cloud_run.collect_brief(NOW,config,Path(directory)/'out',[record(item)])
                        self.assertIsNone(text);self.assertEqual(details['suppressed_news'],1)
                    else:
                        with self.assertRaises(RuntimeError):cloud_run.collect_brief(NOW,config,Path(directory)/'out',[record(item)])

    def test_no_updates_slot_is_saved_and_ack_retry_does_not_send(self):
        ledger=Ledger();env={'GITHUB_ACTIONS':'true','QQ_EMAIL':'reader@example.com','QQ_SMTP_AUTH_CODE':'dummy','GITHUB_RUN_ID':'123'}
        with patch.dict(os.environ,env),patch('sys.argv',['cloud_run.py']), \
             patch.object(cloud_run,'datetime') as clock,patch.object(cloud_run,'GitHubLedger',return_value=ledger), \
             patch.object(cloud_run,'collect_brief',return_value=(None,{'points':0,'suppressed_news':6,'news_items':[]})) as collect, \
             patch.object(cloud_run,'report_delivery',side_effect=[RuntimeError('ack'),None]) as ack, \
             patch.object(cloud_run,'send_once') as sender,patch.object(cloud_run,'finish'):
            clock.now.return_value=NOW
            with self.assertRaises(RuntimeError):cloud_run.main()
            cloud_run.main()
        self.assertEqual(next(iter(ledger.data['deliveries'].values()))['status'],'no_updates')
        sender.assert_not_called();collect.assert_called_once();self.assertEqual(ack.call_count,2)

    def test_history_preview_reads_but_never_writes_or_sends(self):
        ledger=Ledger()
        with patch.dict(os.environ,{'QQ_EMAIL':'reader@example.com','GITHUB_RUN_ID':'123'}), \
             patch('sys.argv',['cloud_run.py','--preview','--use-delivery-history']), \
             patch.object(cloud_run,'GitHubLedger',return_value=ledger), \
             patch.object(cloud_run,'collect_brief',return_value=(None,{'points':0,'news_items':[]})), \
             patch.object(cloud_run,'send_once') as sender,patch.object(cloud_run,'report_delivery') as ack, \
             patch.object(cloud_run,'finish'):
            cloud_run.main()
        self.assertEqual(ledger.saved,[]);sender.assert_not_called();ack.assert_not_called()

    def test_morning_send_and_evening_repeat_produce_only_one_email(self):
        ledger=Ledger();item=news();saved=record(item)
        def collect(now, **kwargs):
            remaining,stats=select_new_content([item],kwargs['history'])
            return ('金融重点。' if remaining else None),{'points':len(remaining),'news_items':[saved] if remaining else [],**stats}
        env={'GITHUB_ACTIONS':'true','QQ_EMAIL':'reader@example.com','QQ_SMTP_AUTH_CODE':'dummy','GITHUB_RUN_ID':'123'}
        with patch.dict(os.environ,env),patch('sys.argv',['cloud_run.py']), \
             patch.object(cloud_run,'datetime') as clock,patch.object(cloud_run,'GitHubLedger',return_value=ledger), \
             patch.object(cloud_run,'collect_brief',side_effect=collect),patch.object(cloud_run.smtplib,'SMTP_SSL',SMTP), \
             patch.object(cloud_run,'report_delivery'),patch.object(cloud_run,'finish'):
            clock.now.return_value=NOW.replace(hour=2);cloud_run.main()
            clock.now.return_value=NOW;cloud_run.main()
        self.assertEqual(SMTP.calls,1)
        self.assertEqual([r['status'] for r in ledger.data['deliveries'].values()],['sent','no_updates'])

if __name__=='__main__':unittest.main()

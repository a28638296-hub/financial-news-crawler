from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock
import feedparser
from finance_feeds import fetch_feed
from finance_focus import same_financial_event,select_focus_news,persist_focus_views,focus_excerpt,relevant_financial_news,focus_category
from finance_brief import local_news_brief
from finance_core import news_importance,canonical_url

NOW=datetime(2026,11,6,10,tzinfo=timezone.utc)

def fact(title,minutes=30):
    return {'id':title,'kind':'news','title':title,'excerpt':title+'。相关数据已由统计机构公布，仍需结合后续数据判断持续性。',
            'published_at':(NOW-timedelta(minutes=minutes)).isoformat(),'time_kind':'published','category':'macro',
            'sources':['公开财经来源'],'selection_priority':5}

class QualityTests(unittest.TestCase):
    def test_invalid_record_does_not_drop_good_feed_and_window_is_24h(self):
        source={'id':'test','name':'Test','kind':'媒体报道','url':'https://example.com/feed'}
        config={'mode':'financial_news','watchlist':[],'news_days':30,'request_timeout':1}
        def entry(hours):return {'title':'美国通胀数据公布','link':'https://example.com/'+str(hours),
            'published_parsed':(NOW-timedelta(hours=hours)).utctimetuple(),'importance':'bad'}
        entries=[entry(1),entry(48),{'links':42}]
        response=SimpleNamespace(content=b'<rss/>',status_code=200,finance_route='direct')
        with TemporaryDirectory() as directory,patch('finance_feeds.NetworkClient') as client, \
             patch('finance_feeds.feedparser.parse',return_value=feedparser.FeedParserDict(version='rss20',entries=entries)):
            client.return_value.get.return_value=response
            rows,status=fetch_feed(source,config,NOW,Path(directory))
        self.assertEqual(len(rows),2);self.assertEqual(status['in_window'],1)
        self.assertEqual(status['rejected_entries'],1);self.assertEqual(rows[0]['importance'],0)

    def test_similar_events_preserve_changed_numbers_and_negation(self):
        a=fact('美国10月通胀率回落至3.2%，符合市场预期')
        self.assertTrue(same_financial_event(a,fact('最新：美国10月通胀率回落至3.2%，符合市场预期')))
        self.assertFalse(same_financial_event(a,fact('美国10月通胀率回落至3.5%，符合市场预期')))
        self.assertFalse(same_financial_event(a,fact('美国10月通胀率回落至3.2%，不符合市场预期')))
        self.assertFalse(same_financial_event(a,fact(a['title'],minutes=500)))
        self.assertFalse(same_financial_event(fact('通胀率1.5%'),fact('通胀率15%')))
        self.assertFalse(same_financial_event(fact('经济增速-0.2%'),fact('经济增速0.2%')))
        self.assertFalse(same_financial_event(fact('同比变化2%'),fact('同比变化2')))
        self.assertFalse(same_financial_event(fact(''),fact('')))

    def test_similar_headlines_keep_different_countries_and_speakers(self):
        self.assertFalse(same_financial_event(fact('美国10月通胀率回落至3.2%，符合市场预期'),
                                             fact('英国10月通胀率回落至3.2%，符合市场预期')))
        self.assertFalse(same_financial_event(fact('美联储威廉姆斯：当前通胀压力仍然较高，需关注后续数据变化'),
                                             fact('美联储鲍威尔：当前通胀压力仍然较高，需关注后续数据变化')))
        self.assertTrue(same_financial_event(fact('【快讯】美国10月通胀数据正式公布'),
                                            fact('美国10月通胀数据正式公布')))

    def test_updated_timestamp_is_not_counted_as_fresh_publication(self):
        source={'id':'test','name':'Test','kind':'媒体报道','url':'https://example.com/feed'}
        config={'mode':'financial_news','watchlist':[],'request_timeout':1}
        row={'title':'美国通胀数据公布','link':'https://example.com/old', 'updated_parsed':NOW.utctimetuple()}
        response=SimpleNamespace(content=b'<rss/>',status_code=200,finance_route='direct')
        with TemporaryDirectory() as directory,patch('finance_feeds.NetworkClient') as client, \
             patch('finance_feeds.feedparser.parse',return_value=feedparser.FeedParserDict(version='rss20',entries=[row])):
            client.return_value.get.return_value=response
            rows,status=fetch_feed(source,config,NOW,Path(directory))
        self.assertEqual(len(rows),1);self.assertEqual(status['in_window'],0)
        self.assertEqual(status['updated_only_entries'],1);self.assertIsNone(status['latest_at'])
        self.assertEqual(status['status'],'窗口内无条目')

    def test_two_distinct_macro_events_survive_without_repeating_one_event(self):
        a=fact('美国10月通胀率回落至3.2%，符合市场预期')
        b=fact('最新：美国10月通胀率回落至3.2%，符合市场预期')
        c=fact('美国新增非农就业人数降至10万人')
        packet={'focus_only':True,'report_at_singapore':NOW.isoformat(),'facts':[a,b,c]}
        brief=local_news_brief(packet)
        self.assertEqual(len(brief['points']),2)
        self.assertTrue(any('非农' in p['title'] for p in brief['points']))
        self.assertTrue(all('公开财经来源' in p['fact'] for p in brief['points']))

    def test_bad_dates_and_marks_are_excluded_or_normalized(self):
        rows=[fact('美国通胀数据公布') for _ in range(3)]
        for row,value in zip(rows,['not-a-date','2026-11-06T10:00:00',None]):row['published_at']=value
        self.assertEqual(select_focus_news(rows,NOW),[])
        self.assertEqual(news_importance('infinity'),0);self.assertEqual(news_importance(-1),0)
        self.assertEqual(news_importance(900),3);self.assertEqual(canonical_url('http://['),'')

    def test_latest_text_matches_saved_summary(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot=root/'snapshot';snapshot.mkdir()
            persist_focus_views(root,snapshot,{'created_at':NOW.isoformat(),'gaps':[],'selection_note':''},'金融重点。')
            self.assertEqual((root/'最新金融重点.txt').read_text(encoding='utf-8'),'金融重点。')

    def test_roundups_and_question_headers_do_not_create_misattribution(self):
        self.assertFalse(relevant_financial_news({'title':'周四美股盘前你需要了解的全球要闻','summary':'英国央行加息。'}))
        self.assertFalse(relevant_financial_news({'title':'是否下调关税？外交部：建议询问主管部门'}))
        self.assertEqual(focus_excerpt('【先降关税？外交部回应】外交部表示，建议询问主管部门。'),'外交部表示，建议询问主管部门。')
        self.assertEqual(focus_category({'title':'国家外汇管理局就交易统计核查规则公开征求意见'}),'policy')

if __name__=='__main__':unittest.main()

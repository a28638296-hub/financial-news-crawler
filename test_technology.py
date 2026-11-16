from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from finance_brief import local_news_brief,render_text,evidence_packet
from finance_focus import relevant_financial_news,focus_category,select_focus_news,validate_focus_text
from finance_history import select_new_content,delivered_items
from technology_news import TECH_KEYS

NOW=datetime(2026,11,16,4,tzinfo=timezone.utc)

def event(key,title,category=None):
    item={'id':key,'title':title,'summary':title+'。相关机构已公开说明适用范围，实际效果仍需后续验证。',
          'url':'https://example.com/'+key,'published_at':NOW.isoformat(),'time_kind':'published',
          'sources':[],'kind':'news','selection_priority':5,'importance':1}
    item['excerpt']=item['summary'];item['category']=category or focus_category(item)
    return item

def packet(*facts):
    return {'facts':list(facts),'focus_only':True,'report_at_singapore':NOW.isoformat(),'market_dates':[]}

class TechnologyTests(unittest.TestCase):
    def test_technology_does_not_require_financial_words(self):
        cases=[('研究团队发布开源大模型并公布测试方法','tech_ai'),
               ('芯片厂商发布新一代处理器并说明适用范围','tech_chips'),
               ('数据库发布新版本以改进故障恢复功能','tech_cloud'),
               ('官方披露网络安全漏洞并发布修复补丁','tech_security'),
               ('机器人完成新的场景测试并披露安全限制','tech_robotics'),
               ('SpaceX成功回收火箭上面级','tech_science')]
        for title,category in cases:
            with self.subTest(title=title):
                item=event('a',title)
                self.assertTrue(relevant_financial_news(item))
                self.assertEqual(focus_category(item),category)
                result=local_news_brief(packet(item))
                self.assertEqual(result['points'][0]['section'],'technology')
                self.assertTrue(result['points'][0]['analysis'])

    def test_promotions_leaks_games_and_stock_tips_are_excluded(self):
        for title in ['AI手机促销领券优惠','芯片新机外观曝光','AI游戏发布新玩法','芯片股价上涨值得关注','建议超配全球科技股票']:
            self.assertFalse(relevant_financial_news(event('a',title)))

    def test_technical_words_in_footer_do_not_create_tech_event(self):
        item=event('a','当地举办周末活动')
        item['summary']='更多人工智能和芯片新闻请关注本站。'
        self.assertNotIn(focus_category(item),TECH_KEYS)

    def test_financial_events_keep_their_own_capacity(self):
        titles=['美国通胀率继续回落并公布核心项目','中国国债收益率上升并公布期限数据','人民币汇率公布最新变化并说明报价',
                '国际原油价格上升并公布供应数据','政府宣布关税调整并公布适用清单','企业资本开支增加并公布投资安排']
        finance=[event(str(i),title,category) for i,(title,category) in enumerate(zip(titles,['macro','rates','fx','commodities','policy','industry']))]
        tech=[event('tech'+str(i),title) for i,title in enumerate(['大模型发布正式版本并说明测试条件','芯片厂商宣布量产新型处理器','云计算平台推出新的恢复功能','官方披露网络安全漏洞并提供补丁'])]
        for item in tech:item['selection_priority']=99
        result=local_news_brief(packet(*(finance+tech)))
        self.assertEqual(sum(p['section']=='finance' for p in result['points']),6)
        self.assertEqual(sum(p['section']=='technology' for p in result['points']),3)
        text=render_text(result,packet(*(finance+tech)))
        self.assertIn('\n金融重点\n',text);self.assertIn('\n科技重点\n',text)
        self.assertEqual(text.count('\n分析：'),9);self.assertNotIn('https://',text)
        validate_focus_text(text)

    def test_candidate_quota_does_not_starve_technology(self):
        finance=[event(str(i),'美国第'+str(i)+'项通胀数据正式公布','macro') for i in range(30)]
        for item in finance:item['importance']=3
        tech=event('tech','研究团队发布开源模型测试结果')
        selected=select_focus_news(finance+[tech],NOW)
        self.assertTrue(any(row['id']=='tech' for row in selected))

    def test_technology_only_is_allowed_and_deduplicated_across_sends(self):
        item=event('tech','研究团队发布开源大模型并公布测试方法')
        data=packet(item);brief=local_news_brief(data)
        history=delivered_items(brief,data,{'tech':item['url']})
        rows,stats=select_new_content([item],history)
        self.assertEqual(rows,[]);self.assertEqual(stats['suppressed_news'],1)

    def test_old_industry_facts_are_not_resent_under_a_technology_label(self):
        sentence='美国研究团队正式发布新的人工智能模型，公开了适用范围及完整的测试方法。'
        item=event('new','美国研究团队更新人工智能技术说明');item['summary']=sentence
        old={'id':'old','title':'美国研究团队发布模型说明','category':'industry','content':sentence,'url_keys':[]}
        rows,stats=select_new_content([item],[old])
        self.assertEqual(rows,[]);self.assertEqual(stats['suppressed_news'],1)

    def test_actual_evidence_pipeline_preserves_technology(self):
        item=event('tech','研究团队发布人工智能模型并公布测试方法')
        with TemporaryDirectory() as folder:
            root=Path(folder)
            data={'config':{'mode':'financial_news'},'news':[item],
                  'summary':{'mode':'financial_news','created_at':NOW.isoformat(),'gaps':[]}}
            (root/'research.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
            data,urls=evidence_packet(root)
        self.assertEqual(data['facts'][0]['category'],'tech_ai')
        result=local_news_brief(data);self.assertEqual(result['points'][0]['section'],'technology')

    def test_model_and_chip_links_use_only_selected_evidence(self):
        a=event('a','研究机构发布人工智能模型并说明任务范围')
        b=event('b','芯片厂商发布算力处理器并公布性能测试条件')
        result=local_news_brief(packet(a,b))
        self.assertEqual(len(result['connections']),1)
        self.assertEqual(set(result['connections'][0]['evidence_ids']),{'a','b'})
        self.assertIn('不能自动互相证明',result['connections'][0]['analysis'])

    def test_lab_result_is_not_presented_as_commercial_success(self):
        item=event('a','研究团队公布量子计算实验的新结果')
        point=local_news_brief(packet(item))['points'][0]
        self.assertIn('不同阶段',point['analysis'])
        self.assertIn('后续验证',point['impact'])

    def test_call_rankings_do_not_imply_global_market_share(self):
        item=event('a','人工智能模型平台公布最新调用量榜单')
        point=local_news_brief(packet(item))['points'][0]
        self.assertIn('不能代表全球',point['analysis'])
        self.assertIn('付费',point['impact'])

    def test_traffic_pilot_is_not_cloud_compute_capacity(self):
        item=event('a','高德发布云控红绿灯系统并在北京率先试点')
        point=local_news_brief(packet(item))['points'][0]
        self.assertEqual(item['category'],'tech_robotics')
        self.assertIn('通行效率',point['impact'])

    def test_chip_factory_plan_is_not_existing_production(self):
        item=event('a','芯片企业将在政府支持下建测试厂')
        point=local_news_brief(packet(item))['points'][0]
        self.assertEqual(point['analysis_basis']['stage'],'proposal')
        self.assertIn('若项目按计划建成',point['impact'])

    def test_official_job_title_does_not_replace_event_topic(self):
        item=event('a','美国财政部长表示预计通胀将在下个月下滑','macro')
        point=local_news_brief(packet(item))['points'][0]
        self.assertEqual(point['analysis_basis']['topic'],'inflation')
        self.assertEqual(point['analysis_basis']['direction'],'down')

    def test_interbank_rate_is_not_currency_depreciation(self):
        item=event('a','离岸人民币同业拆息利率涨跌互现','fx')
        point=local_news_brief(packet(item))['points'][0]
        self.assertEqual(point['analysis_basis']['topic'],'money_market')
        self.assertNotIn('本币持续贬值',point['impact'])

if __name__=='__main__':unittest.main()

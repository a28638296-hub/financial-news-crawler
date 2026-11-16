from copy import deepcopy
from datetime import datetime, timezone
import unittest

from finance_analysis import add_event_analysis, profile
from finance_brief import local_news_brief, render_text
from finance_focus import validate_focus_text, relevant_financial_news
from finance_history import delivered_items

NOW=datetime(2026,11,16,3,tzinfo=timezone.utc)


def event(identity,title,category='macro'):
    return {'id':identity,'kind':'news','title':title,'excerpt':title+'。',
            'published_at':NOW.isoformat(),'time_kind':'published','category':category,
            'sources':['公开来源'],'selection_priority':5}


def packet(*facts):
    return {'facts':list(facts),'focus_only':True,'report_at_singapore':NOW.isoformat(),'market_dates':[]}


def brief_for(*facts):
    return {'overview':'金融重点','points':[{'title':f['title'],'fact':f['excerpt'],
            'impact':'原分析','watch':'原观察','evidence_ids':[f['id']]} for f in facts],
            'next_watch':[],'caveat':''}


class EventAnalysisTests(unittest.TestCase):
    def test_every_selected_event_has_analysis_impact_and_watch(self):
        data=packet(event('a','美国通胀率回落至3.2%'),event('b','美国新增非农就业人数下降至10万人'),
                    event('c','美国10年期国债收益率上升至4.1%','rates'))
        result=local_news_brief(data)
        for point in result['points']:
            for key in ('analysis','impact','watch'):
                self.assertGreater(len(point[key]),15)
        text=render_text(result,data)
        self.assertEqual(text.count('\n分析：'),len(result['points']))
        self.assertIn('事件关联分析',text)
        self.assertNotIn('https://',text);validate_focus_text(text)

    def test_yield_fall_does_not_get_yield_rise_explanation(self):
        fact=event('a','中国10年期国债收益率下行至1.8%','rates')
        result=add_event_analysis(brief_for(fact),packet(fact))['points'][0]
        self.assertEqual(result['analysis_basis']['topic'],'yields')
        self.assertEqual(result['analysis_basis']['direction'],'down')
        self.assertIn('基准成本可能减轻',result['impact'])
        self.assertNotIn('成本可能增加',result['impact'])

    def test_forecast_and_denial_are_not_policy_decisions(self):
        for title,status in [('美联储官员预计可能加息','forecast'),('美联储尚未决定加息','uncertain')]:
            with self.subTest(title=title):
                fact=event('a',title);point=add_event_analysis(brief_for(fact),packet(fact))['points'][0]
                self.assertEqual(point['analysis_basis']['stage'],status)
                self.assertTrue('不能' in point['analysis'] or '暂缓' in point['analysis'])

    def test_unrelated_increase_does_not_reverse_inflation_signal(self):
        fact=event('a','美国通胀回落，美债收益率上升')
        meta=profile(brief_for(fact)['points'][0],[fact])
        self.assertEqual(meta['topic'],'inflation');self.assertEqual(meta['direction'],'down')

    def test_related_events_use_only_displayed_evidence(self):
        a=event('a','美国通胀回落至3.2%');b=event('b','美联储宣布降息25个基点')
        hidden=event('hidden','国际油价上涨5%','commodities')
        result=add_event_analysis(brief_for(a,b),packet(a,b,hidden))
        self.assertEqual(len(result['connections']),1)
        link=result['connections'][0]
        self.assertEqual(link['point_numbers'],[1,2])
        self.assertEqual(set(link['evidence_ids']),{'a','b'})
        self.assertIn('价格压力与政策选择',link['title'])
        self.assertIn('不足以确认因果',link['analysis'])

    def test_cross_region_events_are_comparisons_not_same_policy_evidence(self):
        a=event('a','美国通胀回落至3.2%');b=event('b','英国央行宣布加息25个基点')
        link=add_event_analysis(brief_for(a,b),packet(a,b))['connections'][0]
        self.assertTrue(link['cross_region']);self.assertIn('不同地区',link['analysis'])

    def test_opposite_signals_are_explicitly_compared(self):
        a=event('a','美国总体通胀回落至3.2%');b=event('b','美国核心通胀上升至3.6%')
        link=add_event_analysis(brief_for(a,b),packet(a,b))['connections'][0]
        self.assertIn('方向相反',link['analysis'])
        self.assertIn('指标',link['analysis'])

    def test_unrelated_events_are_not_forced_into_a_link(self):
        a=event('a','美国非农就业人数增加10万人');b=event('b','国际黄金价格上涨2%','commodities')
        result=add_event_analysis(brief_for(a,b),packet(a,b))
        self.assertEqual(result['connections'],[]);self.assertIn('不强行关联',result['connection_note'])

    def test_old_headline_does_not_reintroduce_removed_update_facts(self):
        fact=event('a','美联储宣布加息25个基点')
        fact.update(excerpt='美国最新非农就业人数下降至10万人。',is_update=True)
        point=add_event_analysis(brief_for(fact),packet(fact))['points'][0]
        self.assertEqual(point['analysis_basis']['topic'],'jobs')
        self.assertNotIn('政策实际收紧',point['impact'])

    def test_analysis_does_not_change_facts_or_dedup_history(self):
        a=event('a','美国通胀回落至3.2%');b=event('b','美联储宣布降息25个基点')
        original=brief_for(a,b);before=deepcopy(original);data=packet(a,b)
        enriched=add_event_analysis(original,data)
        self.assertEqual(original,before)
        self.assertEqual(delivered_items(original,data,{}),delivered_items(enriched,data,{}))

    def test_reserve_fund_and_stability_report_do_not_get_fx_or_rate_claims(self):
        for title,topic in [('香港外汇基金投资收益公布','reserves'),('美联储警示资产估值过高带来潜在风险','stability')]:
            fact=event('a',title);meta=profile(brief_for(fact)['points'][0],[fact])
            self.assertEqual(meta['topic'],topic)

    def test_existing_ai_impact_can_be_preserved(self):
        fact=event('a','美国通胀回落至3.2%')
        result=add_event_analysis(brief_for(fact),packet(fact),preserve_impact=True)
        self.assertEqual(result['points'][0]['impact'],'原分析')
        self.assertTrue(result['points'][0]['analysis'])

    def test_unemployment_decline_is_not_job_losses(self):
        fact=event('a','国家统计局：就业形势总体稳定，城镇调查失业率下降')
        point=add_event_analysis(brief_for(fact),packet(fact))['points'][0]
        self.assertEqual(point['analysis_basis']['direction'],'down')
        self.assertIn('中国',point['analysis_basis']['regions'])
        self.assertIn('收入和消费可能获得支撑',point['impact'])

    def test_remittances_do_not_become_currency_depreciation(self):
        fact=event('a','菲律宾9月份海外汇款同比增长2.6%')
        point=add_event_analysis(brief_for(fact),packet(fact))['points'][0]
        self.assertEqual(point['analysis_basis']['topic'],'remittances')
        self.assertIn('接收家庭',point['impact'])
        self.assertNotIn('本币持续贬值',point['impact'])

    def test_bond_future_price_drop_is_not_yield_drop(self):
        fact=event('a','国债期货开盘，30年期主力合约跌0.28%','rates')
        point=add_event_analysis(brief_for(fact),packet(fact))['points'][0]
        self.assertEqual(point['analysis_basis']['topic'],'bonds')
        self.assertEqual(point['analysis_basis']['direction'],'down')
        self.assertIn('不能把期货涨跌幅直接换算',point['analysis'])

    def test_energy_output_growth_is_not_an_energy_price_increase(self):
        fact=event('a','国家统计局：原油产量1845万吨，同比增长2.3%','commodities')
        point=add_event_analysis(brief_for(fact),packet(fact))['points'][0]
        self.assertEqual(point['analysis_basis']['direction'],'up')
        self.assertEqual(point['analysis_basis']['energy_metric'],'output')
        self.assertIn('供应保障',point['impact'])
        self.assertNotIn('若能源涨价',point['impact'])

    def test_unrelated_sanctions_do_not_explain_oil_or_technology_events(self):
        a=event('a','美国制裁某国官员','policy')
        b=event('b','中国原油产量同比增长2.3%','commodities')
        c=event('c','美国与参与者签署人工智能供应链合作宣言','industry')
        result=add_event_analysis(brief_for(a,b,c),packet(a,b,c))
        self.assertEqual(result['connections'],[])

    def test_cooperation_declaration_is_not_executed_capital_spending(self):
        fact=event('a','美国与参与者签署人工智能供应链合作宣言','industry')
        point=add_event_analysis(brief_for(fact),packet(fact))['points'][0]
        self.assertEqual(point['analysis_basis']['topic'],'cooperation')
        self.assertIn('不能直接等同于已获得订单',point['analysis'])

    def test_asset_allocation_advice_is_not_a_financial_event_digest(self):
        item={'title':'机构建议最大幅度超配全球股票，认为AI资本支出周期完好','summary':''}
        self.assertFalse(relevant_financial_news(item))
        with self.assertRaises(ValueError):validate_focus_text('机构偏好投资级公司债和黄金。')


if __name__=='__main__':unittest.main()

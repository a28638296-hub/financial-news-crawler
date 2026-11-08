"""Select important financial events; no security screening or recommendations."""
from datetime import datetime, timedelta
from html import escape
import re
from urllib.parse import urlsplit

from finance_overview import classify, SG
from finance_core import news_importance

STOCK_STORY = re.compile(r'个股|股价|目标价|买入评级|卖出评级|涨停|跌停|连板|盘前[涨跌]|盘后[涨跌]|ETF|\b(?:shares? (?:jump|surge|fall|rise|drop)|price target|stock picks?|buy rating)\b', re.I)
SYSTEMIC = re.compile(r'美联储|央行|通胀|非农|就业|失业|利率|国债|美债|信用|关税|制裁|原油|石油|黄金|外汇|汇率|全球|金融稳定|系统性|\b(?:inflation|federal reserve|central bank|treasury|tariff|gdp|cpi|pce|payroll)\b', re.I)
FORBIDDEN_OUTPUT = re.compile(r'短线|波段|选股|目标价|买入|卖出|个股|股票代码|观察名单|止盈|止损|ETF|(?<![A-Za-z0-9_])(?:AAPL|MSFT|NVDA|AMZN|GOOGL|JPM|XOM|LLY|SPY|QQQ|IWM|TLT|HYG|UUP|GLD|USO)(?![A-Za-z0-9_])', re.I)
HYPE = re.compile(r'板上钉钉|稳赚|暴赚|必涨|必跌|翻倍机会|闭眼买|guaranteed (?:profit|return)', re.I)
ROUNDUP = re.compile(r'你需要了解|全球要闻|要闻汇总|一文看懂|财经早报|财经晚报|盘前.*要闻|一周.*回顾|\b(?:morning briefing|what to know before|news roundup)\b',re.I)


def published_time(value):
    try:
        result=datetime.fromisoformat(value)
        return result if result.tzinfo is not None else None
    except (ValueError,TypeError):
        return None


def same_financial_event(left,right):
    """Merge formatting/editorial-prefix variants, not different actors or facts."""
    a,b=published_time(left.get('published_at')),published_time(right.get('published_at'))
    if a is None or b is None or abs(a-b)>timedelta(hours=6):return False
    raw_titles=[re.sub(r'^(?:(?:最新(?:消息)?|快讯|消息|报道|即时|更新)[：:\s]+|【(?:最新|快讯|更新)】)+',
                       '',str(item.get('title','')).strip()).casefold() for item in (left,right)]
    titles=[re.sub(r'[^\w]','',title) for title in raw_titles]
    if min(map(len,titles))<12:return titles[0]==titles[1]
    if re.findall(r'\d+(?:\.\d+)?',raw_titles[0]) != re.findall(r'\d+(?:\.\d+)?',raw_titles[1]):return False
    direction=r'不|未|否认|取消|上升|下降|增长|减少|上调|下调|加息|降息|上涨|下跌|维持|暂停|\b(?:not|no|rise|fall|cut|hike)\b'
    if set(re.findall(direction,raw_titles[0])) != set(re.findall(direction,raw_titles[1])):return False
    # High edit similarity can merge US/UK releases or different speakers.
    # Unknown wording changes stay separate until semantic evidence is available.
    return titles[0] == titles[1]


def relevant_financial_news(item):
    title = item.get('title', '')
    if STOCK_STORY.search(title) or ROUNDUP.search(title) or re.search(r'建议询问主管部门|不予置评|无可奉告',title):
        return False
    category = classify(item)
    if category == 'industry' and not re.search(r'融资|债务|资本开支|资本支出|投资|需求|订单|产能|出口|供应链|供需|收入|营收|盈利|利润|成本|\b(?:financ|investment|demand|capacity|supply|revenue|profit|capital spending)', title, re.I):
        return False
    return category is not None and category != 'company'


def focus_category(item):
    """A dollar-denominated commodity is not an FX event just for saying USD."""
    for text in (item.get('title', ''), item.get('summary', '')):
        if re.search(r'征求意见|监管规则|监管规定|暂行办法',text):
            return 'policy'
        if re.search(r'黄金|原油|石油|燃料油|天然气|布伦特|白银|大宗商品|\b(?:gold|crude|oil|brent|wti)\b', text, re.I):
            return 'commodities'
        found = classify({'title':text})
        if found:
            return found
    return None


def focus_excerpt(text):
    # Strip a bracketed headline before splitting punctuation inside the headline.
    text=re.sub(r'^\s*【[^】]*】\s*','',text)
    sentences = re.findall(r'[^。！？\n]+[。！？]|[^。！？\n]+$', text)
    return ''.join(sentence for sentence in sentences if not STOCK_STORY.search(sentence)
                   and not FORBIDDEN_OUTPUT.search(sentence) and not HYPE.search(sentence)
                   and not re.match(r'\s*(?:目前|当前|现在|而且|同时)?(?:我们|他们|我|他|她|其)', sentence)
                   and not sentence.rstrip().endswith(('？','?'))).strip()


def priority(item, now):
    """Inspectable editorial priority, not an asserted internet popularity rank."""
    at = published_time(item.get('published_at')) or now-timedelta(hours=24)
    age = max(0, (now-at).total_seconds()/3600)
    publishers = {urlsplit(src.get('url', '')).hostname for src in item.get('sources', [])} - {None}
    official = any(src.get('kind') == '官方宏观公告' for src in item.get('sources', []))
    return (5*bool(SYSTEMIC.search(item['title'])) + 3*official
            + 2*news_importance(item.get('importance'))
            + min(max(len(publishers)-1, 0), 2) + max(0, 1-age/24))


def select_focus_news(news, now):
    fresh = [item for item in news if relevant_financial_news(item) and item.get('time_kind') == 'published'
             and (at:=published_time(item.get('published_at'))) is not None and now-timedelta(hours=24) <= at <= now]
    ranked = sorted(fresh, key=lambda item:(priority(item, now), item['published_at']), reverse=True)
    counts, selected = {}, []
    for item in ranked:
        category = focus_category(item)
        if counts.get(category, 0) >= 5:
            continue
        selected.append(item)
        counts[category] = counts.get(category, 0)+1
        if len(selected) >= 24:
            break
    return selected


def focus_summary(data):
    now = datetime.fromisoformat(data['created_at'])
    selected = select_focus_news(data['news'], now)
    gaps = ['部分来源读取失败：' + '、'.join(src['name'] for src in data['sources'] if src['status']=='读取失败') + '。'] if any(src['status']=='读取失败' for src in data['sources']) else []
    if any(src.get('covers_24h') is False or src.get('partial_error') for src in data['sources']):
        gaps.append('部分快讯来源有分页或覆盖限制，未收录不表示没有事件。')
    if not selected:
        gaps.append('没有取得足够的新鲜金融重点，不使用旧闻补写。')
    return {'mode':'financial_news', 'title':'每日热门金融重点', 'created_at':data['created_at'],
            'price_dates':[], 'gaps':gaps, 'selected_news_ids':[item['id'] for item in selected],
            'selection_note':'按发布时间、来源重点标记、报道覆盖与宏观影响筛选；不代表全网热搜排名。',
            'points':['聚焦宏观经济、央行与利率、债券信用、汇率、能源黄金、政策及重大行业变化。'],
            'highlights':[], 'stock_points':[], 'changes':[], 'note':'正文解释发生了什么、可能影响和后续关注。'}


def validate_focus_text(text):
    if FORBIDDEN_OUTPUT.search(text):
        raise ValueError('金融重点出现证券筛选或交易内容')


def render_focus_html(summary, brief_text=''):
    at = datetime.fromisoformat(summary['created_at']).astimezone(SG).strftime('%Y-%m-%d %H:%M')
    body = brief_text or '金融信息已采集，中文重点正在整理。请稍后查看“最新金融重点.txt”。'
    gaps = ''.join('<li>'+escape(value)+'</li>' for value in summary['gaps'])
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>每日热门金融重点</title><style>body{{margin:0;background:#f3f5f8;color:#203047;font:17px/1.9 'Microsoft YaHei',sans-serif}}main{{max-width:850px;margin:32px auto;padding:28px;background:white;border-radius:12px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}}small{{color:#63758a}}</style><main><h1>每日热门金融重点</h1><small>{at} · 新加坡时间</small><pre>{escape(body)}</pre><details><summary>信息覆盖情况</summary><ul>{gaps or '<li>本轮取得的信息见正文。</li>'}</ul><small>{escape(summary['selection_note'])}</small></details></main></html>'''


def persist_focus_views(root, snapshot, summary, text):
    page = render_focus_html(summary, text)
    markdown = '# 每日热门金融重点\n\n'+text
    for filename in ('report.html', 'summary.html'):
        (snapshot/filename).write_text(page, encoding='utf-8')
    (snapshot/'summary.md').write_text(markdown, encoding='utf-8')
    # The old shortcuts now show the current financial briefing as well.
    for filename in ('最新金融总结.html', '最新美股研究.html', '最新美股总结.html'):
        (root/filename).write_text(page, encoding='utf-8')
    for filename in ('最新金融总结.md', '最新美股总结.md'):
        (root/filename).write_text(markdown, encoding='utf-8')
    (root/'最新金融重点.txt').write_text(text,encoding='utf-8')

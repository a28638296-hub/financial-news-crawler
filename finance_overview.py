"""Financial news and cross-asset overview with explicit dates and provenance."""
from datetime import datetime, timedelta
from html import escape
import math
import re
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from finance_core import NY, canonical_url

SG = ZoneInfo("Asia/Singapore")
CATEGORIES = (
    ("macro", "宏观经济与央行", r"\b(fomc|federal reserve|central bank|interest rates?|rate (?:hikes?|cuts?)|inflation|cpi|pce|payrolls?|unemployment|labor market|labour market|gdp|gross domestic product|pmi|retail sales|personal income|consumer spending|economic growth|recession)\b", "核对数据实际值、前值和市场预期，再判断利率预期是否改变。通胀回落与经济走弱对股票的影响并不相同。"),
    ("rates", "债券利率与信用", r"\b(treasur(?:y|ies)|bond(?:s| yields?)?|yield curve|credit spreads?|credit ratings?|default|debt market|borrowing costs?|deficit)\b", "区分国债收益率变化与信用风险。收益率上升可能压低高估值资产的估值，信用利差扩大则需要警惕融资压力。"),
    ("fx", "外汇与全球市场", r"\b(dollar|currenc(?:y|ies)|forex|yuan|renminbi|yen|sterling|euro|global markets?|world markets?|emerging markets?|fund flows?|capital flows?)\b", "美元变化可能影响跨国企业收入折算、商品价格与海外融资；不能仅凭美元ETF上涨就认定出现资金净流入。"),
    ("commodities", "能源与大宗商品", r"\b(crude|oil|opec|natural gas|gold|silver|copper|commodit(?:y|ies)|brent|wti|lng)\b", "区分供给冲击与需求变化。能源价格上涨可能支持上游收入，同时提高运输、制造和消费端成本；黄金上涨也不必然代表恐慌。"),
    ("policy", "政策监管与地缘风险", r"\b(tariffs?|sanctions?|antitrust|trade (?:war|deal|talks?)|export (?:controls?|restrictions?)|geopolitic\w*|elections?|war|russia|ukraine|iran|regulators?|lawsuits?)\b", "先分清政策提议、正式决定和生效日期，再核对供应链、成本及市场准入的具体影响。"),
    ("industry", "行业与科技趋势", r"\b(artificial intelligence|ai|data cent(?:er|re)s?|semiconductors?|gpu|chips?|cloud|robot\w*|biotech|obesity|drug approvals?|electric vehicles?)\b", "关注需求能否转化为订单、收入和自由现金流；行业热度或技术发布本身不能证明盈利上修。"),
    ("company", "公司财报与资本动作", r"\b(earnings|quarterly results|financial results|guidance|revenue|profit|margins?|acquisitions?|mergers?|buybacks?|repurchases?|dividends?|ipos?)\b", "区分已公布业绩、未来指引与市场预期；同时检查一次性项目和估值。盘后公告可能使上一收盘日的股票筛选失效。"),
)

CHINESE_CATEGORIES = {
    'macro': r'美联储|央行|降息|加息|利率决议|通胀|通缩|非农|失业率|就业数据|国内生产总值|消费者物价|零售销售|经济衰退|经济增长|采购经理',
    'rates': r'国债|美债|债券|收益率|信用利差|债务违约|信用评级|融资成本|财政赤字',
    'fx': r'美元|汇率|外汇|人民币|日元|欧元(?!区)|英镑|全球市场|资金流',
    'commodities': r'原油|石油|布伦特|天然气|黄金|白银|铜价|大宗商品|欧佩克',
    'policy': r'关税|制裁|反垄断|出口管制|贸易谈判|地缘|选举|战争|监管|诉讼',
    'industry': r'人工智能|算力|数据中心|半导体|芯片|云计算|机器人|生物医药|减肥药|电动汽车|存储|英伟达',
    'company': r'财报|业绩|营收|净利润|毛利率|回购|分红|收购|并购|上市融资|盈利指引',
}


def classify(item):
    """One primary category per story; title first avoids incidental summary mentions."""
    for text in (item.get("title", ""), item.get("summary", "")):
        for key, _, pattern, _ in CATEGORIES:
            if re.search(pattern, text, re.I) or re.search(CHINESE_CATEGORIES[key], text):
                return key
    source_ids = {source.get("id") for source in item.get("sources", [])}
    if source_ids & {"bea", "fed_monetary", "ecb"}:
        return "macro"
    return None


def parse_treasury_xml(content, now):
    root = ET.fromstring(content)
    local = now.astimezone(NY)
    cutoff = local.date() if (local.hour, local.minute) >= (16, 15) else local.date() - timedelta(days=1)
    rows = {}
    for properties in root.findall(".//{*}properties"):
        fields = {child.tag.rsplit("}", 1)[-1]: child.text for child in properties}
        day = (fields.get("NEW_DATE") or "")[:10]
        try:
            date = datetime.fromisoformat(day).date()
            two, ten = float(fields["BC_2YEAR"]), float(fields["BC_10YEAR"])
        except (TypeError, ValueError, KeyError):
            continue
        if date <= cutoff and all(math.isfinite(value) and 0 <= value <= 30 for value in (two, ten)):
            rows[day] = {"date": day, "two_year": two, "ten_year": ten}
    return [rows[day] for day in sorted(rows)]


def fetch_treasury(now, timeout, session, raw_dir, max_age=4):
    result = {"provider": "美国财政部每日国债收益率曲线", "retrieved_at": now.isoformat(),
              "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve", "rows": []}
    try:
        rows = []
        for year in (now.astimezone(NY).year, now.astimezone(NY).year - 1):
            url = f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            (raw_dir / f"treasury-{year}.xml").write_bytes(response.content)
            rows.extend(parse_treasury_xml(response.content, now))
            if len(rows) >= 2:
                break
        rows = sorted({row["date"]: row for row in rows}.values(), key=lambda row: row["date"])
        if not rows:
            raise ValueError("未取得已完成日期的2年期和10年期国债收益率")
        last, previous = rows[-1], rows[-2] if len(rows) > 1 else None
        age = (now.astimezone(NY).date() - datetime.fromisoformat(last["date"]).date()).days
        result.update(available=True, stale=age > max_age, as_of=last["date"], rows=rows,
                      two_year=last["two_year"], ten_year=last["ten_year"],
                      spread_bp=100 * (last["ten_year"] - last["two_year"]),
                      previous_date=previous["date"] if previous else None,
                      two_change_bp=100 * (last["two_year"] - previous["two_year"]) if previous else None,
                      ten_change_bp=100 * (last["ten_year"] - previous["ten_year"]) if previous else None)
    except Exception as error:
        result.update(available=False, reason=str(error)[:300])
    return result


def short_excerpt(value, limit=200):
    value = " ".join(value.split())
    return value if len(value) <= limit else value[:limit].rsplit(" ", 1)[0] + "…"


def build_overview(data, new_news, previous=None):
    now = datetime.fromisoformat(data["created_at"])
    hours = data.get("config", {}).get("financial_news_hours", 72)
    cutoff = now - timedelta(hours=hours)
    fresh_ids = {item.get("id") for item in new_news} if previous else set()
    grouped = {key: [] for key, *_ in CATEGORIES}
    for item in data.get("news", []):
        date = item.get("published_at")
        if not date:
            continue
        published = datetime.fromisoformat(date)
        if published > now or published < now - timedelta(days=data.get("config", {}).get("news_days", 30)):
            continue
        key = classify(item)
        if key:
            grouped[key].append(item)
    categories = []
    for key, title, _, transmission in CATEGORIES:
        items = grouped[key]
        recent = [item for item in items if item.get("time_kind") == "published" and datetime.fromisoformat(item["published_at"]) >= cutoff]
        # Reserve the latest official evidence when available, then prioritize recency.
        ranked = sorted(recent, key=lambda item: item["published_at"], reverse=True)
        official = [item for item in ranked if any("官方" in src.get("kind", "") for src in item.get("sources", []))]
        selected = ([official[0]] if official else [])
        selected += [item for item in ranked if item not in selected][:max(0, 2 - len(selected))]
        background = not bool(selected)
        if background and items:
            selected = sorted(items, key=lambda item: item["published_at"], reverse=True)[:1]
        if key == "macro":
            # Keep the latest scheduled official releases visible even when older
            # than the news window. They are always labeled as background.
            important = [item for item in items if re.search(r"\b(gdp|gross domestic product|personal income and outlays|fomc statement)\b", item["title"], re.I)
                         and any(src.get("id") in {"bea", "fed_monetary"} for src in item.get("sources", []))]
            for item in sorted(important, key=lambda item: item["published_at"], reverse=True)[:3]:
                if item not in selected:
                    selected.append(item)
        stories = []
        for item in selected:
            stories.append({"id": item.get("id"), "title": item["title"], "url": canonical_url(item["url"]),
                            "published_at": item["published_at"], "time_kind": item.get("time_kind"),
                            "sources": list(dict.fromkeys(src["name"] for src in item.get("sources", []))),
                            "excerpt": short_excerpt(item.get("summary", "")),
                            "is_new_collection": item.get("id") in fresh_ids,
                            "background": item.get("time_kind") != "published" or datetime.fromisoformat(item["published_at"]) < cutoff})
        count_new = sum(item.get("id") in fresh_ids for item in recent)
        state = f"近{hours}小时有明确发布时间的相关报道 {len(recent)} 条，其中本轮新采集 {count_new} 条。" if previous else f"近{hours}小时有明确发布时间的相关报道 {len(recent)} 条；首次建立基线。"
        if not recent:
            state = f"近{hours}小时未在已取得来源中找到本类明确发布时间的报道。" + ("以下仅为最近背景资料。" if stories else "")
        categories.append({"id": key, "title": title, "count": len(recent), "new_count": count_new,
                           "state": state, "stories": stories, "transmission": transmission})
    pulse = data.get("market_overview", [])
    valid = {row["ticker"]: row for row in pulse if row.get("metrics", {}).get("available") and not row["metrics"].get("stale")}
    readings, short_watch, swing_watch, gaps = [], [], [], []
    equity = [valid[symbol] for symbol in ("SPY", "QQQ", "IWM") if symbol in valid]
    if equity:
        readings.append("股票市场：" + "；".join(f"{row['name']}截至{row['metrics']['as_of']}，近5交易日{row['metrics']['return_5d']:+.2f}%" for row in equity if row["metrics"].get("return_5d") is not None) + "。")
        same_dates = len({row["metrics"]["as_of"] for row in equity}) == 1
        returns = [row["metrics"].get("return_5d") for row in equity]
        if len(equity) == 3 and same_dates and all(value is not None for value in returns):
            readings.append("大盘、科技与小盘近5日均下跌，股票市场承压较广。" if all(value < 0 for value in returns) else "大盘、科技与小盘近5日均上涨，反弹覆盖多个风格。" if all(value > 0 for value in returns) else "大盘、科技与小盘近5日表现分化，不能把单一指数的强弱当作全市场表现。")
    rates = data.get("treasury", {})
    if rates.get("available") and not rates.get("stale"):
        text = f"美国国债：截至{rates['as_of']}，2年期{rates['two_year']:.2f}%，10年期{rates['ten_year']:.2f}%；10年减2年利差{rates['spread_bp']:+.0f}基点。"
        if rates.get("ten_change_bp") is not None:
            text += f"相对上一可用日期{rates['previous_date']}，10年期变动{rates['ten_change_bp']:+.0f}基点。"
        readings.append(text)
        change = rates.get("ten_change_bp")
        if change is not None and change > 0:
            short_watch.append("10年期收益率较上一可用日期上升：观察高估值科技股是否继续承压；这是估值敏感性提示，不能证明当日股价波动由利率引起。")
        elif change is not None and change < 0:
            short_watch.append("10年期收益率较上一可用日期下降：观察是通胀预期缓和还是增长担忧，需结合经济数据和股市反应判断。")
    elif data.get("config", {}).get("treasury_enabled"):
        gaps.append("美国财政部收益率缺失或过期：" + rates.get("reason", "数据超过新鲜度窗口") + "。")
    for symbol, label in (("TLT", "长久期美债ETF"), ("HYG", "高收益公司债ETF"), ("UUP", "美元期货基金代理"), ("GLD", "黄金ETF"), ("USO", "原油期货基金代理")):
        if symbol not in valid:
            continue
        m = valid[symbol]["metrics"]
        if m.get("return_1d") is not None and m.get("return_5d") is not None:
            readings.append(f"{label} {symbol}：截至{m['as_of']}，最近一日{m['return_1d']:+.2f}%，近5交易日{m['return_5d']:+.2f}%。")
    if any(row.get("metrics", {}).get("stale") or not row.get("metrics", {}).get("available") for row in pulse):
        names = [row["ticker"] for row in pulse if row.get("metrics", {}).get("stale") or not row.get("metrics", {}).get("available")]
        gaps.append("跨资产行情缺失或过期：" + "、".join(names) + "。")
    short_watch.append("先核对央行讲话、宏观发布和盘后财报，再检查价格与成交量是否确认；新增消息不等于新增交易日信号。")
    swing_watch.extend(["跟踪通胀、就业与增长能否改变政策路径，再看利率、美元和企业融资成本是否持续变化。", "把行业需求、利润率、资本开支与现金流放在一起核对；新闻热度与ETF涨跌不能替代盈利预期和估值研究。"])
    return {"hours": hours, "readings": readings, "categories": categories, "market_pulse": pulse, "treasury": rates,
            "short_watch": short_watch, "swing_watch": swing_watch, "gaps": gaps,
            "note": "行情使用已完成的美股交易日；ETF/基金是观察代理，变化不等于现货价格、美元指数或信用利差。要闻按关键词归类，保留来源摘要原文；影响路径是条件性研究提示，并非已验证的因果结论。"}


def overview_html(overview):
    e = lambda value: escape(str(value), quote=True)
    readings = "".join(f"<li>{e(value)}</li>" for value in overview["readings"])
    rows = []
    for row in overview["market_pulse"]:
        m = row["metrics"]
        good = m.get("available") and not m.get("stale")
        cells = [f"{m[key]:+.2f}%" if good and m.get(key) is not None else "—" for key in ("return_1d", "return_5d", "return_20d")]
        status = m.get("as_of", "不可用") + (" / 过期" if m.get("stale") else "")
        rows.append(f'<tr><td><a href="{e(canonical_url(row["source_url"]))}" target="_blank" rel="noopener noreferrer">{e(row["ticker"])}</a> · {e(row["name"])}</td><td>{e(status)}</td>' + "".join(f"<td>{value}</td>" for value in cells) + "</tr>")
    table = '<div class="financial-scroll" style="overflow-x:auto"><table class="financial-table"><thead><tr><th>市场观察代理</th><th>日期</th><th>最近一日</th><th>近5日</th><th>近20日</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>" if rows else ""
    categories = []
    for category in overview["categories"]:
        stories = []
        for item in category["stories"]:
            at = datetime.fromisoformat(item["published_at"]).astimezone(SG).strftime("%m-%d %H:%M")
            time_label = "发布" if item["time_kind"] == "published" else "更新（非首发时间）"
            badge = "背景资料" if item["background"] else "本轮新采集" if item["is_new_collection"] else "近期持续跟踪"
            excerpt = f'<p class="excerpt">来源摘要（原文）：{e(item["excerpt"])}</p>' if item["excerpt"] else ""
            stories.append(f'<li><small>{e(badge)} · {e(time_label)} {at} · {e(" / ".join(item["sources"]))}</small><br><a href="{e(item["url"])}" target="_blank" rel="noopener noreferrer">{e(item["title"])}</a>{excerpt}</li>')
        categories.append(f'<article class="financial-topic"><h3>{e(category["title"])}</h3><p>{e(category["state"])}</p><ul class="news-list">{"".join(stories)}</ul><p><strong>影响与后续核对：</strong>{e(category["transmission"])}</p></article>')
    rates = overview["treasury"]
    rate_link = f'<p><a href="{e(canonical_url(rates["source_url"]))}" target="_blank" rel="noopener noreferrer">美国财政部收益率原始数据</a></p>' if rates.get("source_url") else ""
    short = "".join(f"<li>{e(value)}</li>" for value in overview["short_watch"])
    swing = "".join(f"<li>{e(value)}</li>" for value in overview["swing_watch"])
    return f'<div class="financial-overview"><h2>金融信息总览</h2><ul>{readings or "<li>本轮跨资产行情不足，先查看下方来源信息。</li>"}</ul>{table}{rate_link}<h2>金融要闻摘要</h2><p class="smallprint">各栏目采用最近{overview["hours"]}小时的报道，跨来源去重；无近期报道时仅列出标明日期的背景资料。未取得消息不代表没有事件。</p>{"".join(categories)}<h3>未来几天关注什么</h3><ul>{short}</ul><h3>未来数周至数月跟踪什么</h3><ul>{swing}</ul><p class="smallprint">{e(overview["note"])}</p></div>'


def overview_markdown(overview):
    lines = ["", "## 金融信息总览", ""] + ["- " + value for value in overview["readings"]]
    lines += ["", "| 市场观察代理 | 日期 | 最近一日 | 近5日 | 近20日 |", "| --- | --- | ---: | ---: | ---: |"] if overview["market_pulse"] else []
    for row in overview["market_pulse"]:
        m = row["metrics"]
        good = m.get("available") and not m.get("stale")
        cells = [f"{m[key]:+.2f}%" if good and m.get(key) is not None else "—" for key in ("return_1d", "return_5d", "return_20d")]
        lines.append(f"| [{row['ticker']}]({canonical_url(row['source_url'])}) {row['name']} | {m.get('as_of', '不可用')}{' / 过期' if m.get('stale') else ''} | " + " | ".join(cells) + " |")
    if overview["treasury"].get("source_url"):
        lines += ["", "[美国财政部收益率原始数据](" + canonical_url(overview["treasury"]["source_url"]) + ")"]
    lines += ["", "## 金融要闻摘要", ""]
    for category in overview["categories"]:
        lines += ["### " + category["title"], "", category["state"], ""]
        for item in category["stories"]:
            at = datetime.fromisoformat(item["published_at"]).astimezone(SG).strftime("%m-%d %H:%M")
            time_label = "发布" if item["time_kind"] == "published" else "更新（非首发时间）"
            label = "背景资料" if item["background"] else "本轮新采集" if item["is_new_collection"] else "近期持续跟踪"
            title = item["title"].replace("[", "(").replace("]", ")")
            lines += [f"- {label} · {time_label} {at} · {' / '.join(item['sources'])} · [{title}]({item['url']})"]
            if item["excerpt"]:
                lines += ["", "  来源摘要（原文）：" + item["excerpt"]]
        lines += ["", "影响与后续核对：" + category["transmission"], ""]
    lines += ["### 未来几天关注什么", ""] + ["- " + value for value in overview["short_watch"]]
    lines += ["", "### 未来数周至数月跟踪什么", ""] + ["- " + value for value in overview["swing_watch"]]
    lines += ["", overview["note"], ""]
    return lines

"""Deterministic, inspectable research filters; no forecasts or buy/sell scores."""
import hashlib
import math
import re
import statistics
from datetime import datetime, timedelta, timezone, time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
TOPICS = {
    "利率/货币政策": r"\b(fomc|federal reserve|interest rates?|monetary policy|rate cuts?|rate hikes?)\b",
    "通胀": r"\b(inflation|cpi|pce|consumer prices?)\b",
    "就业": r"\b(jobs|payrolls?|unemployment|labor market|labour market)\b",
    "业绩/指引": r"\b(earnings|quarterly results|financial results|guidance|outlook|revenue|profit)\b",
    "监管/诉讼": r"\b(antitrust|lawsuit|investigation|tariffs?|sanctions?|regulat\w*)\b",
    "AI/算力": r"\b(artificial intelligence|ai|data cent(?:er|re)s?|semiconductors?|gpu)\b",
    "能源": r"\b(oil|opec|natural gas|crude|energy)\b",
    "并购/资本回报": r"\b(acquisition|merger|buyback|repurchase|dividend)\b",
}
for _label, _pattern in {
    '利率/货币政策': '美联储|降息|加息|货币政策', '通胀': '通胀|通缩|消费者物价',
    '就业': '非农|就业|失业率', '业绩/指引': '财报|业绩|营收|净利润|盈利指引',
    '监管/诉讼': '监管|诉讼|反垄断|关税|制裁', 'AI/算力': '人工智能|算力|数据中心|半导体',
    '能源': '原油|石油|天然气|能源', '并购/资本回报': '并购|收购|回购|分红',
}.items():
    TOPICS[_label] += '|' + _pattern


def canonical_url(url):
    if not isinstance(url,str):
        return ''
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ''
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    query = [(key, val) for key, val in parse_qsl(parsed.query) if not key.lower().startswith("utm_") and key.lower() not in {"guccounter", "guce_referrer", "guce_referrer_sig"}]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, urlencode(query), ""))


def time_state(published, now, days):
    if not published:
        return "无日期"
    if published > now:
        return "未来日期"
    return "窗口内" if published >= now - timedelta(days=days) else "窗口外"


def news_importance(value):
    """Source marks are advisory; malformed or huge marks must not break ranking."""
    try:
        return max(0, min(int(value or 0), 3))
    except (ValueError, TypeError, OverflowError):
        return 0


def match_tickers(text, watchlist, declared=()):
    matches = set(declared)
    for item in watchlist:
        for alias in set(item.get("aliases", []) + [item["ticker"]]):
            pattern = re.escape(alias) if re.search(r'[\u3400-\u9fff]', alias) else r'(?<![A-Za-z0-9_])' + re.escape(alias) + r'(?![A-Za-z0-9_])'
            if re.search(pattern, text, re.I):
                matches.add(item["ticker"])
                break
    return sorted(matches & {item["ticker"] for item in watchlist})


def merge_news(items):
    """Merge URL repeats and same-title stories within 72h, transitively.

    Repeated quarterly headlines at different URLs must remain separate events.
    """
    parent = list(range(len(items)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def join(left, right):
        left, right = find(left), find(right)
        parent[max(left, right)] = min(left, right)

    urls, titles = {}, {}
    for index, item in enumerate(items):
        title = re.sub(r"\W+", "", item["title"].casefold())
        for url in [item["url"]] + item.get("alternate_urls", []):
            url = canonical_url(url)
            if url in urls:
                join(index, urls[url])
            urls[url] = index
        for other in titles.get(title, []):
            a, b = item.get("published_at"), items[other].get("published_at")
            if a and b and abs(datetime.fromisoformat(a) - datetime.fromisoformat(b)) <= timedelta(hours=72):
                join(index, other)
        titles.setdefault(title, []).append(index)
    groups = {}
    for index, original in enumerate(items):
        root = find(index)
        item = dict(original)
        if root not in groups:
            item["id"] = hashlib.sha256(canonical_url(item["url"]).encode()).hexdigest()[:16]
            item["alternate_urls"] = sorted(set([item["url"]] + item.get("alternate_urls", [])))
            groups[root] = item
            continue
        existing = groups[root]
        existing["tickers"] = sorted(set(existing["tickers"] + item["tickers"]))
        existing["sources"] = list({src["id"]: src for src in existing["sources"] + item["sources"]}.values())
        existing["alternate_urls"] = sorted(set(existing["alternate_urls"] + [item["url"]] + item.get("alternate_urls", [])))
        existing["topics"] = sorted(set(existing.get("topics", []) + item.get("topics", [])))
        existing['importance'] = max(news_importance(existing.get('importance')), news_importance(item.get('importance')))
        dates = [value for value in [existing.get("published_at"), item.get("published_at")] if value]
        if dates:
            earliest = min(dates)
            if earliest == item.get("published_at"):
                existing["time_kind"] = item["time_kind"]
            existing["published_at"] = earliest
        existing["first_seen"] = min(existing["first_seen"], item["first_seen"])
    return list(groups.values())


def closed_sessions(rows, now):
    """Exclude today's still-open US daily bar, and future-dated rows."""
    local = now.astimezone(NY)
    cutoff = local.date() if local.time() >= time(16, 15) else local.date() - timedelta(days=1)
    unique = {}
    for row in rows:
        if row["date"] <= cutoff.isoformat():
            if all(isinstance(row.get(key), (int, float)) and math.isfinite(row[key]) and row[key] > 0 for key in ("close", "adj_close")):
                unique[row["date"]] = row
    return [unique[day] for day in sorted(unique)]


def metrics(rows, benchmark_rows, now, max_age=4):
    rows = closed_sessions(rows, now)
    if not rows:
        return {"available": False, "reason": "没有已收盘且有效的日线"}
    closes = [row["adj_close"] for row in rows]
    latest = rows[-1]
    age = (now.astimezone(NY).date() - datetime.fromisoformat(latest["date"]).date()).days
    result = {"available": True, "as_of": latest["date"], "stale": age > max_age, "age_calendar_days": age,
              "close": latest["close"], "adjusted_close": closes[-1], "sessions": len(rows)}
    for n in (1, 5, 20, 60):
        result[f"return_{n}d"] = 100 * (closes[-1] / closes[-n - 1] - 1) if len(closes) > n else None
    for n in (20, 50, 200):
        result[f"sma{n}"] = statistics.mean(closes[-n:]) if len(closes) >= n else None
    volumes = [row.get("volume") for row in rows[-21:-1]]
    valid_volumes = len(volumes) == 20 and all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in volumes)
    avg_vol = statistics.mean(volumes) if valid_volumes else None
    last_vol = latest.get("volume")
    result["volume_ratio"] = last_vol / avg_vol if avg_vol and isinstance(last_vol, (int, float)) and math.isfinite(last_vol) and last_vol >= 0 else None
    result["drawdown_60d"] = 100 * (closes[-1] / max(closes[-60:]) - 1) if len(rows) >= 60 else None
    bench = {row["date"]: row["adj_close"] for row in closed_sessions(benchmark_rows, now)}
    for n in (5, 20):
        start = rows[-n - 1]["date"] if len(rows) > n else None
        end = latest["date"]
        # Use exactly the same two dates; missing benchmark is never zero.
        result[f"relative_{n}d"] = result[f"return_{n}d"] - 100 * (bench[end] / bench[start] - 1) if start in bench and end in bench else None
    return result


def screen(company, prices, news, config, now):
    symbol = company["ticker"]
    matched = [item for item in news if symbol in item["tickers"]]
    recent = [item for item in matched if item.get("time_kind") == "published" and time_state(datetime.fromisoformat(item["published_at"]) if item.get("published_at") else None, now, config["short_news_days"]) == "窗口内"]
    row = {**company, "metrics": prices, "news_count": len(matched), "recent_news_count": len(recent),
           "news_ids": [item["id"] for item in matched], "short_status": "数据不足", "swing_status": "数据不足",
           "short_reasons": [], "swing_reasons": [], "risks": [],
           "next_step": "核对原始公告、收入/利润影响、市场预期及估值；目前没有建立低估或盈利上修结论。"}
    if not prices.get("available") or prices.get("stale"):
        reason = prices.get("reason", "行情超过允许的新鲜度窗口")
        row["risks"].append(reason)
        return row
    need_short = ("return_5d", "relative_5d", "volume_ratio")
    if all(prices.get(key) is not None for key in need_short):
        if not recent:
            row["short_status"] = "缺近期事件"
        elif prices["return_5d"] > 0 and prices["relative_5d"] > 0 and prices["volume_ratio"] >= config["volume_ratio_threshold"]:
            row["short_status"] = "近期提及且量价较强"
        elif prices["return_5d"] < 0 and prices["volume_ratio"] >= config["volume_ratio_threshold"]:
            row["short_status"] = "放量走弱待复核"
        else:
            row["short_status"] = "等待量价确认"
        row["short_reasons"] = [f"近 {config['short_news_days']} 个自然日明确发布时间的相关故事 {len(recent)} 条", "结合5交易日涨跌、相对基准变化及最近完整交易日量比筛选"]
    if all(prices.get(key) is not None for key in ("sma50", "sma200", "relative_20d")):
        if prices["adjusted_close"] > prices["sma50"] > prices["sma200"] and prices["relative_20d"] > 0:
            row["swing_status"] = "趋势较强待基本面"
        elif prices["adjusted_close"] < prices["sma200"]:
            row["swing_status"] = "长期均线下方"
        else:
            row["swing_status"] = "趋势未共振"
        row["swing_reasons"] = ["比较复权收盘与50/200日均线、20日相对基准变化", "尚未核验盈利预期、估值及下一次财报日期"]
    if prices.get("return_5d") is not None and abs(prices["return_5d"]) > 10:
        row["risks"].append("5日波动超过10%，需核实跳空及事件风险")
    if prices.get("sma20") and prices["adjusted_close"] / prices["sma20"] > 1.1:
        row["risks"].append("价格高于20日均线超过10%，注意追涨风险")
    if not matched:
        row["risks"].append("当前订阅源中无匹配新闻，不代表公司没有事件")
    row["risks"].append("未接入一致预期、估值与完整公告；候选状态不是买入建议")
    return row

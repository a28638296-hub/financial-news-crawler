"""Shared public-feed collector for desktop and cloud financial briefs."""
import calendar
from collections.abc import Mapping
from time import perf_counter
from datetime import datetime, timezone
from html import unescape
import re
from urllib.parse import urlsplit
import feedparser
from parsel import Selector
from finance_core import canonical_url,match_tickers,TOPICS,time_state,news_importance
from finance_network import NetworkClient
from finance_domestic import fetch_chinese_entries
UTC=timezone.utc

def plain_text(value):
    return " ".join(unescape(" ".join(Selector(text=value or "").xpath("//text()[not(ancestor::script or ancestor::style)]").getall())).split())

def parse_entry(entry, source, config, now):
    if not isinstance(entry, Mapping):
        return None
    url = ""
    for link in entry.get("links", []):
        if link.get("rel", "alternate") == "alternate" and link.get("type", "text/html") in {"text/html", "application/xhtml+xml", ""}:
            url = canonical_url(link.get("href", ""))
            if url:
                break
    url = url or canonical_url(entry.get("link", ""))
    title = plain_text(entry.get("title", ""))
    if not url or not title:
        return None
    time_kind = "published" if entry.get("published_parsed") else "updated" if entry.get("updated_parsed") else "unknown"
    parsed = entry.get(time_kind + "_parsed")
    try:
        published = datetime.fromtimestamp(calendar.timegm(parsed), UTC) if parsed else None
    except (ValueError, TypeError, OverflowError, OSError):
        # Retain the record for inspection; it cannot enter a fresh-news digest.
        published, time_kind = None, 'unknown'
    summary = plain_text(entry.get("summary", ""))
    text = title + " " + summary
    return {"title": title, "url": url, "article_domain": urlsplit(url).hostname,
            "importance": news_importance(entry.get("importance")),
            "summary": summary[:700], "published_at": published.isoformat() if published else None,
            "time_kind": time_kind, "first_seen": now.isoformat(),
            "tickers": match_tickers(text, config["watchlist"], source.get("tickers", [])),
            "topics": [label for label, pattern in TOPICS.items() if re.search(pattern, text, re.I)],
            "sources": [{key: source[key] for key in ("id", "name", "kind", "url")}],
            "time_status": time_state(published, now, 1 if config.get('mode')=='financial_news' else config['news_days'])}

def fetch_feed(source, config, now, raw_dir):
    started = perf_counter()
    status = {key: source[key] for key in ("id", "name", "kind", "url")}
    if not source.get("enabled", True):
        status.update(status="未启用", message=source.get("disabled_reason", "配置禁用"), entries=0)
        return [], status
    try:
        client = NetworkClient(config.get('network', {}).get('allow_proxy_fallback', True))
        parsed = {}
        if source.get('format') in {'sina_live', 'wallstreetcn'}:
            entries, network_status = fetch_chinese_entries(source, now, config['request_timeout'], client, raw_dir)
            status.update(network_status)
            if network_status.get('partial_error'):
                status['message'] = '部分分页未完成，已保留成功采集的快讯'
            elif not network_status['covers_24h']:
                status['message'] = '已达到本轮分页上限，24小时新闻覆盖可能不完整'
        else:
            response = client.get(source["url"], headers={"User-Agent": "FinancialNewsDigest/1.0 (public feed reader)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}, timeout=config["request_timeout"])
            status.update(http_status=response.status_code, network_route=response.finance_route)
            if len(response.content) > 5 * 1024 * 1024:
                raise ValueError("RSS 大于5MB，未处理")
            (raw_dir / (source["id"] + ".xml")).write_bytes(response.content)
            parsed = feedparser.parse(response.content)
            if not parsed.get("version") or not parsed.entries:
                raise ValueError("返回内容不是有效的非空 RSS/Atom，可能是错误页")
            entries = parsed.entries[:100]
        items, rejected = [], 0
        for entry in entries:
            try:
                item = parse_entry(entry, source, config, now)
                if item:items.append(item)
                else:rejected += 1
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                rejected += 1
        dates = [item["published_at"] for item in items if item["time_kind"] == "published" and item["published_at"] and item["time_status"] != "未来日期"]
        status.update(status="可用", entries=len(items), latest_at=max(dates) if dates else None,
                      in_window=sum(item["time_kind"] == "published" and item["time_status"] == "窗口内" for item in items),
                      updated_only_entries=sum(item["time_kind"] == "updated" for item in items),
                      unknown_dates=sum(item["time_status"] == "无日期" for item in items),
                      future_dates=sum(item["time_status"] == "未来日期" for item in items))
        status.update(rejected_entries=rejected, duration_seconds=round(perf_counter()-started,2))
        if not status["in_window"]:
            status["status"] = "窗口内无条目"
        if parsed.get("bozo"):
            status["message"] = "源格式有兼容性提示，已解析可用条目"
        return items, status
    except Exception as error:
        status.update(status="读取失败", message=type(error).__name__, entries=0,
                      duration_seconds=round(perf_counter()-started,2))
        return [], status

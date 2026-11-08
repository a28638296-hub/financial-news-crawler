"""Validate trusted source configuration before opening files or connections."""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(config, dict):
        raise ValueError('配置必须是 JSON 对象')
    config.setdefault('mode', 'financial_news')
    config.setdefault('watchlist', [])
    config.setdefault('news_days', 30)
    config.setdefault('request_timeout', 8)
    config.setdefault('max_workers', 3)
    if config['mode'] != 'financial_news' or config['watchlist']:
        raise ValueError('此程序仅支持金融新闻摘要，watchlist 必须为空')
    for key, low, high in [('request_timeout', 1, 30), ('max_workers', 1, 8)]:
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f'{key} 必须是 {low} 到 {high} 之间的整数')
    if config.get('financial_news_hours', 24) != 24:
        raise ValueError('当前摘要窗口固定为 24 小时')
    feeds = config.get('feeds')
    if not isinstance(feeds, list) or not feeds:
        raise ValueError('feeds 必须包含至少一个来源')
    seen = set()
    for source in feeds:
        if not isinstance(source, dict):
            raise ValueError('来源必须是 JSON 对象')
        identity = source.get('id')
        if not isinstance(identity, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', identity) or identity in seen:
            raise ValueError('来源 id 必须唯一，且仅含英文字母、数字、下划线或连字符')
        seen.add(identity)
        if any(not isinstance(source.get(key), str) or not source[key].strip() for key in ('name', 'kind', 'url')):
            raise ValueError('来源缺少 name、kind 或 url')
        for key in ('url', 'endpoint'):
            if key not in source:
                continue
            value = source[key]
            if not isinstance(value, str):
                raise ValueError('来源网址必须是字符串')
            parsed = urlsplit(value)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('来源网址必须是无内嵌凭据的 HTTP(S) 地址')
        if source.get('format', 'rss') not in ('rss', 'sina_live', 'wallstreetcn'):
            raise ValueError('不支持该来源格式')
        pages = source.get('max_pages', 8)
        if isinstance(pages, bool) or not isinstance(pages, int) or not 1 <= pages <= 8:
            raise ValueError('max_pages 必须是 1 到 8 之间的整数')
    return config

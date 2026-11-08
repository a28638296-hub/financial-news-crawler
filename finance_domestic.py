"""Public Chinese finance feeds and USD daily bars, without API credentials."""
from datetime import datetime, timedelta, timezone
import json
import math
import re
import time
from zoneinfo import ZoneInfo

from finance_core import canonical_url, closed_sessions, news_importance

CN = ZoneInfo('Asia/Shanghai')
UTC = timezone.utc
USER_AGENT = 'LocalEquityResearch/1.1 (personal finance reader)'


def chinese_entries(kind, document):
    if kind == 'sina_live':
        result = document['result']
        if result.get('status', {}).get('code') not in (0, '0'):
            raise ValueError('新浪快讯返回错误状态')
        records = result['data']['feed']['list']
        for row in records:
            if not isinstance(row, dict):
                continue
            if row.get('is_delete') in (1, '1'):
                continue
            text = row.get('rich_text', '')
            if not isinstance(text,str):
                continue
            try:
                extra = json.loads(row.get('ext') or '{}')
                at = datetime.strptime(row['create_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=CN)
            except (ValueError, KeyError, TypeError):
                continue
            if not isinstance(extra,dict):
                continue
            url = canonical_url(extra.get('docurl') or row.get('docurl') or '')
            if not url:
                continue
            title = re.match(r'【([^】]+)】', text)
            yield {'title': title.group(1) if title else text.split('。')[0][:140],
                   'summary': text, 'link': url, 'published_parsed': at.utctimetuple(),
                   'importance': news_importance(row.get('is_focus'))}
    elif kind == 'wallstreetcn':
        if document.get('code') != 20000:
            raise ValueError('华尔街见闻返回错误状态')
        for row in document['data']['items']:
            if not isinstance(row,dict):
                continue
            # Public short news only. Do not fetch paywalled article content.
            if row.get('is_priced'):
                continue
            try:
                at = datetime.fromtimestamp(int(row['display_time']), UTC)
            except (ValueError, KeyError, TypeError, OverflowError):
                continue
            text = row.get('content_text') or row.get('content') or ''
            if not isinstance(text,str):
                continue
            yield {'title': row.get('title') or text.split('。')[0][:140],
                   'summary': text, 'link': canonical_url(row.get('uri', '')),
                   'published_parsed': at.utctimetuple(), 'importance': news_importance(row.get('score'))}
    else:
        raise ValueError('不支持的中文新闻来源')


def fetch_chinese_entries(source, now, timeout, client, raw_dir):
    kind = source['format']
    entries, seen, cursor = [], set(), None
    cutoff = now - timedelta(hours=24)
    pages = max(1, min(int(source.get('max_pages', 6)), 12))
    page_error = None
    route = None
    for page in range(1, pages + 1):
        params = ({'zhibo_id': 152, 'page': page, 'page_size': 100, 'type': 0}
                  if kind == 'sina_live' else {'channel': 'global-channel', 'limit': 100})
        if cursor is not None:
            params['cursor'] = cursor
        try:
            response = client.get(source['endpoint'], params=params, timeout=timeout,
                                  headers={'User-Agent': USER_AGENT, 'Referer': source['url']})
            if len(response.content) > 5 * 1024 * 1024:
                raise ValueError('新闻响应超过5MB')
            document = response.json()
            batch = list(chinese_entries(kind, document))
            route = response.finance_route
            (raw_dir / f'{source["id"]}-{page}.json').write_bytes(response.content)
        except Exception as error:
            if not entries:
                raise
            page_error = type(error).__name__
            break
        new = [entry for entry in batch if entry['link'] not in seen]
        entries.extend(new)
        seen.update(entry['link'] for entry in new)
        if not new:
            break
        oldest = min(datetime(*entry['published_parsed'][:6], tzinfo=UTC) for entry in new)
        if oldest <= cutoff:
            break
        if kind == 'wallstreetcn':
            next_cursor = document.get('data', {}).get('next_cursor')
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        time.sleep(0.25)
    if not entries:
        raise ValueError('未取得带明确日期的公开中文快讯')
    oldest = min(datetime(*entry['published_parsed'][:6], tzinfo=UTC) for entry in entries)
    return entries, {'network_route': route, 'coverage_start': oldest.isoformat(),
                     'covers_24h': oldest <= cutoff, 'partial_error': page_error}


def resolve_us_security(symbol, timeout, client):
    response = client.get('https://searchapi.eastmoney.com/api/suggest/get',
                          params={'input': symbol, 'type': '14', 'count': 20}, timeout=timeout)
    rows = response.json().get('QuotationCodeTable', {}).get('Data') or []
    found = [row for row in rows if row.get('Code') == symbol and row.get('Classify') == 'UsStock'
             and str(row.get('MktNum')) in {'105', '106', '107'}
             and row.get('QuoteID') == str(row.get('MktNum')) + '.' + symbol]
    if len(found) != 1:
        raise ValueError('无法唯一核验美股代码与市场')
    return found[0]


def parse_eastmoney_bars(document, symbol, market):
    data = document.get('data')
    if document.get('rc') != 0 or not data or data.get('code') != symbol or str(data.get('market')) != str(market):
        raise ValueError('备用行情证券代码或市场不匹配')
    rows = {}
    for value in data.get('klines') or []:
        parts = value.split(',')
        if len(parts) < 6:
            raise ValueError('备用日线字段不完整')
        day = datetime.strptime(parts[0], '%Y-%m-%d').date().isoformat()
        close, volume = float(parts[2]), float(parts[5])
        if not math.isfinite(close) or close <= 0 or not math.isfinite(volume) or volume < 0 or day in rows:
            raise ValueError('备用日线存在无效或重复数据')
        rows[day] = {'date': day, 'close': close, 'volume': volume}
    if not rows:
        raise ValueError('备用行情没有日线')
    return rows


def fetch_eastmoney(symbol, now, timeout, client, raw_dir=None):
    result = {'ticker': symbol, 'provider': '东方财富美股日线（前复权，非交易所直连）',
              'provider_id': 'eastmoney', 'adjustment_basis': 'eastmoney_qfq',
              'source_url': 'https://quote.eastmoney.com/us/' + symbol + '.html',
              'retrieved_at': now.isoformat(), 'rows': []}
    try:
        security = resolve_us_security(symbol, timeout, client)
        histories = {}
        for adjustment in (0, 1):
            params = {'secid': security['QuoteID'], 'klt': 101, 'fqt': adjustment,
                      'beg': (now - timedelta(days=550)).strftime('%Y%m%d'), 'end': now.strftime('%Y%m%d'),
                      'fields1': 'f1,f2,f3,f4,f5,f6', 'fields2': 'f51,f52,f53,f54,f55,f56'}
            response = client.get('https://push2his.eastmoney.com/api/qt/stock/kline/get', params=params,
                                  headers={'User-Agent': USER_AGENT, 'Referer': 'https://quote.eastmoney.com/'}, timeout=timeout)
            document = response.json()
            histories[adjustment] = parse_eastmoney_bars(document, symbol, security['MktNum'])
            if raw_dir:
                (raw_dir / f'eastmoney-{symbol}-{adjustment}.json').write_bytes(response.content)
        raw, adjusted = histories[0], histories[1]
        if raw.keys() != adjusted.keys():
            raise ValueError('原价与复权日线日期不一致，未混用')
        rows = [{**raw[day], 'adj_close': adjusted[day]['close']} for day in sorted(raw)]
        rows = closed_sessions(rows, now)
        if not rows:
            raise ValueError('备用行情没有有效的完整收盘日')
        result.update(available=True, currency='USD', currency_basis='已核验美国市场105/106/107',
                      symbol_verified=True, provider_name=security['Name'], exchange=security['MktNum'],
                      security_type='US_SECURITY', network_route=response.finance_route, rows=rows)
    except Exception as error:
        result.update(available=False, reason=str(error)[:300])
    return result

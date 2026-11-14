"""Track emailed events and their observed versions across delivery slots."""
from datetime import datetime, timedelta
import hashlib
import re
import unicodedata

from finance_core import canonical_url
from finance_focus import focus_excerpt, focus_category

HISTORY_DAYS = 30
BLOCKING_STATES = {'sent', 'sending', 'uncertain'}


def normalized(text):
    text = unicodedata.normalize('NFKC', str(text or '')).strip().casefold()
    text = re.sub(r'^(?:(?:最新(?:消息)?|快讯|消息|报道|即时|更新)[：:\s]+|【(?:最新|快讯|更新)】)+', '', text)
    # Keep decimal points, signs and percentages: 1.5%, 15%, -1.5 differ.
    return re.sub(r'[^\w+%\.\-−]', '', text)


def sentences(text):
    return [s.strip() for s in re.split(r'(?<=[。！？!?])\s*|\n+', text) if normalized(s)]


def source_record(text):
    return {'source_version':hashlib.sha256(normalized(text).encode()).hexdigest(),
            'source_sentence_keys':sorted({hashlib.sha256(normalized(s).encode()).hexdigest() for s in sentences(text)})}


def subject(text):
    countries = set(re.findall(r'中国|美国|英国|日本|德国|法国|加拿大|澳大利亚|欧元区|香港|韩国|印度|俄罗斯', text))
    speaker = re.match(r'^([^：:。！？\n]{2,45})[：:]', text)
    return (tuple(sorted(countries)), normalized(speaker[1]) if speaker else '')


def identity(item):
    urls = item.get('alternate_urls', []) + ([item['url']] if item.get('url') else [])
    return {'id': str(item.get('id', '')).removeprefix('news_'),
            'title': item.get('title', ''), 'category': item.get('category') or focus_category(item),
            'url_keys': sorted({hashlib.sha256(url.encode()).hexdigest() for value in urls if (url := canonical_url(value))})}


def sent_history(ledger, recipient, now):
    result = []
    for key, row in ledger.get('deliveries', {}).items():
        expected = hashlib.sha256((row['slot']+'\n'+recipient.lower()).encode()).hexdigest()
        if key != expected or row.get('status') not in BLOCKING_STATES:
            continue
        at = datetime.fromisoformat(row.get('accepted_at') or row['attempted_at'])
        if at >= now-timedelta(days=HISTORY_DAYS):
            result.extend(row.get('news_items', []))
    return result


def trim_history(ledger, now):
    """Bound content storage; retain delivery audit rows and their status."""
    for row in ledger.get('deliveries', {}).values():
        at = row.get('accepted_at') or row.get('attempted_at')
        if at and datetime.fromisoformat(at) < now-timedelta(days=HISTORY_DAYS):
            row.pop('news_items', None)


def select_new_content(items, history):
    retained, suppressed, updated = [], 0, 0
    for original in items:
        item = dict(original)
        info = identity(item)
        body = focus_excerpt(item.get('summary') or item.get('excerpt') or item.get('title', ''))
        body_parts = sentences(body)
        linked = []
        for old in history:
            same_article = bool(info['id'] and info['id'] == old.get('id')) or bool(set(info['url_keys']) & set(old.get('url_keys', [])))
            same_title = bool(normalized(info['title'])) and normalized(info['title']) == normalized(old.get('title'))
            # Exact factual overlap can identify a renamed/reprinted story.
            # Different countries or quoted speakers must not be conflated.
            compatible = info['category'] == old.get('category') and subject(info['title']) == subject(old.get('title', ''))
            old_parts = {normalized(s) for s in sentences(old.get('content', ''))}
            overlap = compatible and any(len(normalized(s)) >= 18 and normalized(s) in old_parts for s in body_parts)
            if same_article or same_title or overlap:
                linked.append(old)
        if not linked:
            retained.append(item)
            continue
        source = source_record(body)
        if any(old.get('source_version') == source['source_version'] for old in linked):
            # Selecting an unquoted paragraph from an unchanged old article is
            # not a new development. Candidates never emailed have no record.
            suppressed += 1
            continue
        already = {normalized(s) for old in linked for s in sentences(old.get('content', ''))}
        already.update(normalized(old.get('title')) for old in linked)
        old_source_keys = {key for old in linked for key in old.get('source_sentence_keys', [])}
        delta = [s for s in body_parts if normalized(s) not in already
                 and hashlib.sha256(normalized(s).encode()).hexdigest() not in old_source_keys]
        if not delta:
            suppressed += 1
            continue
        # An article may gain genuinely new statements after an earlier send.
        # Never discard the new tail just because its URL/title has been seen.
        item['summary'] = ''.join(delta)
        item['history_source_excerpt'] = body
        context = re.match(r'^([^：:。！？\n]{2,45})[：:]', body) or re.match(r'^([^：:。！？\n]{2,45})[：:]', item['title'])
        if context and not item['summary'].startswith(context[1]):
            item['summary'] = context[1]+'：'+item['summary']
        item['is_update'] = True
        retained.append(item)
        updated += 1
    return retained, {'suppressed_news': suppressed, 'updated_news': updated}


def delivered_items(brief, packet, urls):
    """Candidates not actually displayed must remain eligible next time."""
    facts = {f['id']: f for f in packet['facts'] if f.get('kind') == 'news'}
    result = []
    for point in brief['points']:
        content = re.sub(r'^\d{2}月\d{2}日 \d{2}:\d{2}，[^：\n]*：', '', point['fact'])
        for evidence_id in point['evidence_ids']:
            fact = facts[evidence_id]
            item = identity({**fact, 'url': urls.get(evidence_id, '')})
            item.update(content=content, published_at=fact.get('published_at'),
                        **source_record(fact.get('source_excerpt') or fact.get('excerpt') or content))
            result.append(item)
    return result

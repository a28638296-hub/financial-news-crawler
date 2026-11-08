"""Hosted financial-news digest. No desktop, securities or local login needed."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
import hashlib
import json
import os
from pathlib import Path
import smtplib
import ssl
from time import perf_counter
from zoneinfo import ZoneInfo

import requests
from cloud_collect import fetch_feed
from finance_core import merge_news
from finance_focus import relevant_financial_news, focus_summary, validate_focus_text, persist_focus_views
from finance_brief import evidence_packet, local_news_brief, render_text
from digest_config import load_config

ROOT = Path(__file__).resolve().parent
RUN_OUTPUT = ROOT / 'output'
SG = ZoneInfo('Asia/Singapore')


def current_slot(now):
    local = now.astimezone(SG)
    return max((local-timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
               for days in (0,1) for hour in (10,20)
               if (local-timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0) <= local)


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)


def finish(result):
    record={'checked_at':datetime.now(timezone.utc).isoformat(),**result}
    atomic_json(RUN_OUTPUT/'run-status.json',record)
    print(json.dumps(record,ensure_ascii=False))


class GitHubLedger:
    def __init__(self):
        repository=os.environ['GITHUB_REPOSITORY']
        self.url=f'https://api.github.com/repos/{repository}/contents/.delivery-state.json'
        self.headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'], 'Accept':'application/vnd.github+json', 'X-GitHub-Api-Version':'2022-11-28'}
        self.session=requests.Session();self.session.trust_env=False
        metadata=self.session.get(f'https://api.github.com/repos/{repository}',headers=self.headers,timeout=25)
        metadata.raise_for_status()
        if metadata.json().get('private') is not True:
            raise RuntimeError('邮件投递只允许在私有仓库运行，避免公开投递记录')
        result=self.session.get(self.url,headers=self.headers,timeout=25)
        if result.status_code==404:
            self.sha=None;self.data={'version':1,'deliveries':{}}
        else:
            result.raise_for_status();value=result.json();self.sha=value['sha']
            self.data=json.loads(base64.b64decode(value['content']))

    def save(self):
        value={'message':'Record financial digest delivery', 'content':base64.b64encode(json.dumps(self.data,ensure_ascii=False).encode()).decode()}
        if self.sha:value['sha']=self.sha
        result=self.session.put(self.url,headers=self.headers,json=value,timeout=25)
        result.raise_for_status();self.sha=result.json()['content']['sha']


def delivery_key(slot, recipient):
    return hashlib.sha256((slot+'\n'+recipient.lower()).encode()).hexdigest()


def report_delivery(slot, result):
    """Only acknowledge SMTP acceptance/ambiguity, never just a successful job."""
    url=os.environ.get('DIGEST_CONTROL_URL');key=os.environ.get('DIGEST_CONTROL_KEY')
    if not url or not key:return
    with requests.Session() as session:
        session.trust_env=False
        response=session.post(url,headers={'Authorization':'Bearer '+key},
            json={'action':'ack','slot':slot,'status':result['status'],
                  'accepted_at':result.get('accepted_at'),'run_id':os.environ['GITHUB_RUN_ID']},timeout=20)
        if response.status_code!=200:raise RuntimeError('独立定时器未确认投递记录')


def send_once(ledger, slot, recipient, password, text, smtp_factory=None):
    key=delivery_key(slot,recipient)
    previous=ledger.data['deliveries'].get(key,{})
    if previous.get('status') in {'sent','sending','uncertain'}:
        return {'status':previous['status'], 'skipped':True}
    validate_focus_text(text)
    if any(token in text.lower() for token in ('https://','http://','www.')):
        raise ValueError('邮件含链接，未发送')
    message=EmailMessage()
    message['From']=recipient;message['To']=recipient
    message['Subject']='每日金融重点｜'+datetime.now(SG).strftime('%Y-%m-%d %H:%M')
    message['Date']=format_datetime(datetime.now(timezone.utc))
    message['Message-ID']=f'<financial-cloud-{key[:40]}@qq.com>'
    message['Auto-Submitted']='auto-generated';message.set_content(text,charset='utf-8')
    factory=smtp_factory or smtplib.SMTP_SSL
    client=None;started=False
    row={'slot':slot,'run_id':os.environ.get('GITHUB_RUN_ID'),'attempted_at':datetime.now(timezone.utc).isoformat()}
    try:
        client=factory('smtp.qq.com',465,timeout=30,context=ssl.create_default_context())
        client.login(recipient,password)
        row['status']='sending';ledger.data['deliveries'][key]=row;ledger.save()
        started=True
        refused=client.send_message(message,from_addr=recipient,to_addrs=[recipient])
        if refused:raise smtplib.SMTPRecipientsRefused(refused)
        row.update(status='sent',accepted_at=datetime.now(timezone.utc).isoformat())
        ledger.save()
        return {'status':'sent','slot':slot,'accepted_at':row['accepted_at']}
    except Exception as error:
        rejected=isinstance(error,(smtplib.SMTPRecipientsRefused,smtplib.SMTPSenderRefused,smtplib.SMTPDataError))
        row.update(status='uncertain' if started and not rejected else 'failed',error_type=type(error).__name__)
        ledger.data['deliveries'][key]=row;ledger.save()
        raise RuntimeError('邮件投递未完成：'+row['status']) from None
    finally:
        if client:
            try:client.quit()
            except Exception:client.close()


def collect_brief(now, config_path=None, output_dir=None):
    started=perf_counter()
    config=load_config(config_path or ROOT/'finance_config.json')
    output_dir=Path(output_dir or ROOT/'output')
    snapshot=output_dir/'finance-data'/now.strftime('%Y%m%d-%H%M%S-%f')
    raw=snapshot/'raw-feeds';raw.mkdir(parents=True,exist_ok=True)
    incoming=[];statuses=[]
    with ThreadPoolExecutor(max_workers=config['max_workers']) as pool:
        futures=[pool.submit(fetch_feed,source,config,now,raw) for source in config['feeds'] if source.get('enabled',True)]
        for future in as_completed(futures):
            rows,status=future.result();incoming.extend(rows);statuses.append(status)
    incoming.sort(key=lambda item:(item.get('url',''),item.get('published_at') or '',item.get('title','')))
    statuses.sort(key=lambda status:status['id'])
    news=merge_news(incoming)
    news=[item for item in news if relevant_financial_news(item)]
    data={'mode':'financial_news','created_at':now.isoformat(),'config':config,'news':news,'sources':statuses,
          'candidates':[],'prices':{},'market_overview':[],'treasury':{},'anomalies':[]}
    data['summary']=focus_summary(data)
    atomic_json(snapshot/'research.json',data);atomic_json(snapshot/'summary.json',data['summary'])
    packet,urls=evidence_packet(snapshot)
    brief=local_news_brief(packet)
    if not brief or not brief['points']:
        raise RuntimeError('未取得新鲜金融重点，未发送旧闻或空白总结')
    brief['overview']='金融重点：按重要性整理过去24小时的金融事件及可能影响。'
    brief['caveat']='本版采用新闻重点摘录与规则分析；媒体报道不等于官方确认，影响解释为条件性分析。'
    if data['summary']['gaps']:
        brief['caveat']+='部分来源覆盖有限。'
    text=render_text(brief,packet);validate_focus_text(text)
    atomic_json(snapshot/'financial-brief.json',{'mode':'rules_summary','brief':brief,'evidence':packet,'source_urls':urls})
    (snapshot/'financial-brief.txt').write_text(text,encoding='utf-8')
    persist_focus_views(output_dir,snapshot,data['summary'],text)
    return text,{'points':len(brief['points']),'working_sources':sum(s['status'] in {'可用','窗口内无条目'} for s in statuses),
                 'fresh_sources':sum(s.get('in_window',0)>0 for s in statuses),
                 'rejected_entries':sum(s.get('rejected_entries',0) for s in statuses),
                 'duration_seconds':round(perf_counter()-started,2),
                 'failed_sources':[s['name'] for s in statuses if s['status']=='读取失败']}


def main():
    global RUN_OUTPUT
    parser=argparse.ArgumentParser(description='采集公开金融新闻并生成中文重点摘要')
    parser.add_argument('--preview',action='store_true',default=os.environ.get('DIGEST_PREVIEW')=='true',help='仅采集与生成摘要，不发送邮件')
    parser.add_argument('--config',type=Path,default=ROOT/'finance_config.json',help='来源配置 JSON 文件')
    parser.add_argument('--output',type=Path,default=ROOT/'output',help='报告与诊断输出目录')
    args=parser.parse_args()
    RUN_OUTPUT=args.output.resolve()
    now=datetime.now(timezone.utc);due=current_slot(now)
    # A manual recovery and a delayed scheduled run must share one delivery key.
    slot=due.isoformat()
    ledger=None;recipient=None
    if not args.preview:
        if os.environ.get('GITHUB_ACTIONS')!='true':raise RuntimeError('正式发送仅允许在云端任务运行')
        recipient=os.environ['QQ_EMAIL'];password=os.environ['QQ_SMTP_AUTH_CODE']
        ledger=GitHubLedger()
        prior=ledger.data['deliveries'].get(delivery_key(slot,recipient),{})
        if prior.get('status') in {'sent','sending','uncertain'}:
            report_delivery(slot,prior)
            finish({'status':prior['status'],'skipped':True,'slot':slot,
                    'accepted_at':prior.get('accepted_at')})
            if prior['status']!='sent':raise RuntimeError('上次投递结果不确定，需要查看收件箱后处理')
            return
        if now-due>timedelta(hours=3):
            print(json.dumps({'status':'missed_delivery_window','slot':slot}))
            raise RuntimeError('已错过发送窗口且没有成功投递记录')
    text,details=collect_brief(now,config_path=args.config,output_dir=RUN_OUTPUT)
    if args.preview:
        finish({'status':'preview','sent':False,**details});return
    result=send_once(ledger,slot,recipient,password,text)
    report_delivery(slot,result)
    finish({**result,**details})


if __name__=='__main__':
    try:main()
    except Exception as failure:
        # Never print raw network exceptions or credential-bearing headers.
        finish({'status':'failed','error_type':type(failure).__name__})
        raise SystemExit(1)

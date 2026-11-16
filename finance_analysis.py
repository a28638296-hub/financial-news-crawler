"""Evidence-bounded event mechanisms and links; no inferred market causation."""
from copy import deepcopy
from itertools import combinations
import re

TOPICS = (
    ('reserves', r'外汇基金|储备基金'),
    ('trade', r'关税|出口管制|制裁|贸易限制'),
    ('regulation', r'征求意见|监管规则|监管规定|反垄断|监管办法'),
    ('stability', r'金融稳定|系统性风险|资产估值|估值过高|流动性风险'),
    ('remittances', r'海外汇款|侨汇'),
    ('cooperation', r'(?:人工智能|科技|芯片|供应链).*(?:合作|宣言|工作组)|(?:合作|宣言).*(?:人工智能|科技|芯片|供应链)'),
    ('policy', r'加息|降息|政策利率|利率决议|货币政策|(?:美联储|央行).*(?:收紧|宽松)'),
    ('inflation', r'通胀|通缩|滞胀|消费者物价|价格压力|\b(?:cpi|pce|inflation)\b'),
    ('jobs', r'失业率|非农|就业|工资增速|薪资'),
    ('credit', r'债务违约|信用利差|信用评级|评级下调|债务展期'),
    ('yields', r'(?:国债|美债|债券).*收益率|收益率曲线'),
    ('bonds', r'国债期货|债券价格'),
    ('energy', r'原油|油价|石油|天然气|布伦特|欧佩克|\b(?:wti|opec)\b'),
    ('gold', r'黄金|金价|白银'),
    ('fiscal', r'财政|赤字|政府预算|国债发行'),
    ('investment', r'资本开支|资本支出|数据中心|算力|人工智能|半导体|芯片'),
    ('growth', r'经济增长|经济衰退|零售销售|采购经理|消费需求|工业产出|\b(?:gdp|pmi)\b'),
    ('fx', r'汇率|外汇|人民币|日元|英镑|欧元(?!区)|美元指数'),
)
LABELS = dict(policy='货币政策', inflation='通胀', jobs='就业', yields='债券收益率',
              credit='信用风险', energy='能源', gold='贵金属', trade='贸易政策',
              fiscal='财政', investment='投资与产业', growth='经济活动', fx='汇率',
              reserves='公共储备', regulation='监管', stability='金融稳定',
              remittances='海外汇款', cooperation='科技与供应链合作', bonds='债券价格')
REGIONS = (('美国', r'美国|美联储|美债|波士顿联储|纽约联储'), ('中国', r'中国|中国人民银行|人民币|国家统计局|全国城镇'),
           ('欧元区', r'欧元区|欧洲央行'), ('英国', r'英国|英格兰银行'), ('日本', r'日本|日本央行'),
           ('香港', r'香港'), ('加拿大', r'加拿大'), ('澳大利亚', r'澳大利亚'), ('菲律宾', r'菲律宾'))


def has(pattern, text):
    return bool(re.search(pattern, text, re.I))


def stage(text, topic):
    if has(r'否认|尚未决定|并未决定|不代表|没有宣布|不会|未(?:加息|降息|违约|生效|通过)', text):
        return 'uncertain'
    if has(r'征求意见|提议|草案|拟议|拟将|考虑|讨论|计划|建议|威胁', text):
        return 'proposal'
    if has(r'预计|预期|预测|有望|或将|可能|料将|料.*(?:升|降)|警告.*风险', text):
        return 'forecast'
    if topic == 'policy' and not has(r'宣布|决定|决议|正式|已将|实施', text):
        return 'statement'
    return 'reported'


def direction(text, topic):
    # Read the relevant clause after the metric, not unrelated changes elsewhere.
    text=re.sub(r'[，,](?=(?:同比|环比))','',text)
    anchors = {'inflation':r'通胀|通缩|物价|价格压力|\b(?:cpi|pce)\b', 'jobs':r'失业率' if '失业率' in text else r'非农|就业|工资|薪资',
               'yields':r'收益率', 'energy':r'油价|原油|布伦特|天然气|石油|\bwti\b',
               'bonds':r'主力合约|债券价格', 'remittances':r'海外汇款|侨汇',
               'gold':r'金价|黄金|白银', 'fx':r'汇率|人民币|日元|英镑|欧元|美元指数',
               'growth':r'经济增长|零售销售|工业产出|消费需求|\b(?:gdp|pmi)\b'}
    if topic in anchors:
        # A decimal point belongs to its number, not a sentence boundary.
        match = re.search('(?:'+anchors[topic]+r')[^。，,；;！？\n]{0,80}', text, re.I)
        if not match:
            return 'unknown'
        text = match[0]
    if has(r'未|不|否认', text):
        return 'unknown'
    if topic == 'policy':
        up, down = r'加息|收紧|上调.*利率', r'降息|宽松|下调.*利率'
    elif topic == 'trade':
        up, down = r'加征|上调|提高|扩大制裁|收紧|新增制裁', r'下调|降低|取消|豁免|放宽'
    else:
        up = r'上升|上涨|升至|增加|增长|走高|上行|回升|反弹|加速|升值|抬升|推高|攀升|创新高|涨\s*\d'
        down = r'下降|下跌|降至|减少|走低|下行|回落|放缓|走弱|贬值|减速|创新低|跌\s*\d'
    rising, falling = has(up,text), has(down,text)
    if rising and falling:
        return 'mixed'
    return 'up' if rising else 'down' if falling else 'unknown'


def profile(point, facts):
    body = re.sub(r'^\d{2}月\d{2}日 \d{2}:\d{2}，[^：\n]*：', '', point['fact'])
    updated = any(f.get('is_update') for f in facts)
    # An old headline must not reintroduce a removed event into update analysis.
    generic_titles={'宏观经济与央行','债券利率与信用','外汇与全球市场','能源与大宗商品','政策监管与地缘风险','行业与科技趋势'}
    title = '' if updated or point['title'] in generic_titles else point['title']
    text = title+'。'+body
    topic='other'
    for value in (title,body):
        protected=next((key for key,pattern in TOPICS[:6] if has(pattern,value)),None)
        candidates=[(match.start(),rank,key) for rank,(key,pattern) in enumerate(TOPICS)
                    if (match:=re.search(pattern,value,re.I))]
        if protected or candidates:
            topic=protected or min(candidates)[2];break
    energy_metric='output' if topic=='energy' and has(r'(?:原油|石油|天然气)产量|(?:原油|石油|天然气).*产量',text) else 'price'
    metric='失业率' if topic=='jobs' and '失业率' in text else '能源产量' if energy_metric=='output' else LABELS.get(topic,'事件')
    return {'topic':topic, 'direction':direction(text,topic), 'stage':stage(text,topic),
            'regions':[name for name,pattern in REGIONS if has(pattern,text)], 'text':text,
            'metric':metric, 'energy_metric':energy_metric,
            'energy_supply':has(r'减产|停产|停运|供给中断|供应中断|封锁|运输受阻',text)}


def explain(meta):
    topic, change, status = meta['topic'], meta['direction'], meta['stage']
    conditional = status in {'forecast','proposal','statement','uncertain'}
    lead = {'forecast':'这是预测或风险判断，不能当作已经实现的结果。',
            'proposal':'目前仍涉及提议、讨论或待落实措施，不能按已生效处理。',
            'statement':'这是政策表态，尚不足以确认正式利率决定。',
            'uncertain':'材料含否认、未确认或条件限制，方向性结论需要暂缓。'}.get(status,'')
    if topic == 'policy':
        analysis='关键在政策立场如何影响融资条件与需求，表态与实际执行应分开判断。'
        impacts={
            'up':'若政策实际收紧，新增贷款和再融资成本可能上升，随后抑制部分消费与投资；传导强度取决于持续时间和借款结构。',
            'down':'若政策实际放松，新增融资负担可能减轻，并支持部分消费与投资；是否见效还取决于信贷需求和金融机构传导。'}
        impact=impacts.get(change,'政策方向尚不明确；应先判断利率路径是否变化，再评估对融资成本、消费和投资的影响。')
        watch='正式决议、政策执行和实际贷款利率是否一致。'
    elif topic == 'inflation':
        analysis='需要区分总体与核心价格、短期能源波动与持续性价格压力，单次读数不足以确认趋势。'
        impact={'up':'若价格压力持续上升，居民购买力和企业成本可能承压，也可能增加维持较紧政策的压力；不能据此断言央行必然行动。',
                'down':'若价格压力持续回落，实际购买力和成本压力可能改善，也可能减轻继续收紧政策的必要性；核心项目是否同步改善仍关键。'}.get(change,'材料未给出清晰变化方向；需先核对核心项目和统计口径，再判断购买力、企业成本及政策压力。')
        watch='核心与服务价格、工资变化及央行后续表态。'
    elif topic == 'jobs':
        analysis='就业、工资和失业率代表不同侧面；失业率上升与就业人数上升的经济含义相反。'
        weak = (has('失业率',meta['text']) and change=='up') or (not has('失业率',meta['text']) and change=='down')
        strong = (has('失业率',meta['text']) and change=='down') or (not has('失业率',meta['text']) and change=='up')
        impact=('若劳动力市场持续走弱，收入与消费支撑可能减弱，政策权衡可能更重视增长；单项数据不足以确认衰退。' if weak else
                '若劳动力市场持续改善，收入和消费可能获得支撑；工资压力是否增加，还需结合劳动供给和生产率。' if strong else
                '需结合就业人数、劳动参与率和工资一起判断收入与需求，不能只凭单项变化推断政策方向。')
        watch='就业修订、劳动参与率、工资和消费数据能否相互印证。'
    elif topic == 'yields':
        analysis='收益率可能同时反映政策预期、通胀、期限溢价和债券供需，材料不足以把变化归因于单一因素。'
        impact={'up':'若收益率持续上行，新增融资和再融资的基准成本可能增加，并加大长久期资产的估值压力；已有固定利率债务不会立即重定价。',
                'down':'若收益率持续下行，新增融资基准成本可能减轻；但若源于避险需求，不能同时据此认定经济或风险偏好改善。'}.get(change,'需先区分期限和变化方向，再评估融资成本；单个期限的收益率水平不能代表整个信用市场。')
        watch='不同期限收益率、通胀预期和信用利差是否同向变化。'
    elif topic == 'credit':
        analysis='关键在偿付能力、融资可得性和损失承担方，应把单一主体风险与系统性风险分开。'
        impact='若信用压力扩大，相关借款人的再融资条件可能收紧，并影响债权人和上下游现金流；能否扩散取决于敞口与处置安排。'
        watch='正式偿付安排、相关敞口和信用利差，避免把传闻当作违约确认。'
    elif topic == 'bonds':
        analysis='债券价格与收益率通常反向变化，但期货还受交割、基差和持仓影响，不能把期货涨跌幅直接换算成利率变化。'
        impact=('若价格下跌也反映在现券收益率上，新增融资成本可能面临上行压力；单次期货波动不足以确认融资环境收紧。' if change=='down' else
                '若价格上涨也反映在现券收益率下降上，新增融资基准成本可能减轻；需排除期货自身交易因素。' if change=='up' else
                '需先确认期货价格和现券收益率是否相互印证，再判断融资成本的变化。')
        watch='现券收益率、期现基差、不同期限表现和后续持续性。'
    elif topic == 'energy':
        analysis=('需要区分供给受限与需求变化，并核对实际影响的产量、运力和持续时间。' if meta['energy_supply'] else
                  '能源变化通过生产、运输及居民支出传导；价格、质量规定和供给措施不能混作同一种冲击。')
        impact={'up':'若能源涨价持续，下游生产运输成本和生活支出可能增加，上游收入可能受益；对通胀的传导取决于持续性和成本转嫁。',
                'down':'若能源降价持续，下游成本和居民支出压力可能缓解，上游收入可能承压；若源于需求走弱，还需同时观察增长风险。'}.get(change,'若措施改变有效供给或运输成本，可能传导至能源价格和下游成本；当前材料不足以确定价格方向及幅度。')
        watch='实际供应、库存、运输状况和终端价格是否出现持续变化。'
        if meta['energy_metric']=='output':
            analysis='这是产量数据，应区分绝对产量、同比增速和实际可供量；增产不能直接解释成能源涨价。'
            impact=('若增产持续，可能改善相关地区供应保障，但价格是否承压仍取决于需求、进口、库存及全球供给。' if change=='up' else
                    '若减产持续，可能减少相关地区有效供给，增加进口或库存调节需求；价格影响仍取决于需求和其他供应。' if change=='down' else
                    '产量变化可能影响本地供应保障和进口需求；需明确方向并结合需求、库存及全球供应判断价格影响。')
            watch='产量增速、实际消费、进口量和库存是否相互匹配。'
    elif topic == 'gold':
        analysis='贵金属同时受实际利率、汇率、避险与供需影响，单次价格变化不能证明唯一驱动。'
        impact='若贵金属走势与实际利率或汇率变化一致，可作为资金定价的观察线索；仅凭涨跌无法确认恐慌或资金流向。'
        watch='实际利率、美元及实物供需是否支持同一解释。'
    elif topic == 'trade':
        analysis='需先核对适用商品、地区、生效时间与豁免条件，政策措辞不等于实际贸易成本已改变。'
        impact=('若限制收紧并落实，进口、合规或替代采购成本可能增加，进而影响供应链和终端价格；实际负担由成本分担方式决定。' if change=='up' else
                '若限制放松并落实，相关贸易和采购成本可能下降；终端价格是否受益仍取决于执行范围和企业定价。' if change=='down' else
                '政策可能通过贸易成本、供应链调整和市场准入影响企业；执行范围不明时，不能直接判断受影响规模。')
        watch='正式文本、生效时间、豁免清单及贸易流量。'
    elif topic == 'fiscal':
        analysis='财政措施需同时观察支出用途与融资来源，名义预算不等于已经形成的实际需求。'
        impact='若支出真正落地，可能改变相关需求与现金流；若融资需求同步增加，也需观察债券供给和利息负担。'
        watch='预算执行进度、融资安排和实际项目支出。'
    elif topic == 'investment':
        analysis='投资计划、实际支出与最终收入不是同一件事，需核对需求兑现、融资方式和产能利用。'
        impact='若投资落地，上游设备和基础设施需求可能受支持，同时带来资金占用和后续折旧；若需求不足，回收期可能延长。'
        watch='订单兑现、实际资本支出、利用率及融资成本。'
    elif topic == 'cooperation':
        analysis='合作宣言与工作组代表协调安排，不能直接等同于已获得订单、资金或新增产能。'
        impact='若合作落实为共同标准、基础设施或供应安排，可能改变采购路径与合规要求；是否降低成本或限制准入，取决于正式规则和执行。'
        watch='参与方义务、技术范围、资金安排和实际执行项目。'
    elif topic == 'growth':
        analysis='应区分经济活动的总量、增速和预期差，并核对单项指标能否代表更广泛需求。'
        impact='若需求改善持续，收入与现金流可能获得支持；若增长继续走弱，偿债能力与财政收入可能承压，需结合价格和就业判断。'
        watch='消费、生产、就业及后续修订是否一致。'
    elif topic == 'fx':
        analysis='汇率涉及两种货币及报价方向，需区分单一货币变化与广泛美元变化，不能直接推断资金净流向。'
        impact='若本币持续贬值，进口和外币偿债成本可能上升，部分出口商的价格竞争力可能改善；升值的方向相反，但取决于计价与对冲。'
        watch='明确报价口径、利差、进口价格和外币债务敞口。'
    elif topic == 'reserves':
        analysis='储备或基金投资收益需区分已实现现金、估值变化及资产类别，不能直接解释为汇率变化。'
        impact='收益变化可能影响财务缓冲与可分配资源；是否能转化为财政支出，还取决于制度安排和资金流动性。'
        watch='收益构成、现金实现情况和分配规则。'
    elif topic == 'remittances':
        analysis='海外汇款是跨境家庭收入渠道，应区分名义金额、币种折算和实际购买力，不能把汇款增速当作汇率涨跌。'
        impact=('若汇款增长持续，接收家庭的消费与偿债能力可能获得支持，也可能增加外汇供给；汇率结果仍受其他跨境收支影响。' if change=='up' else
                '若汇款持续减少，接收家庭收入和消费可能承压；影响大小取决于汇款占比、汇率及其他收入。' if change=='down' else
                '汇款变化可能影响接收家庭的收入、消费与外汇收支，需核对金额、币种和持续性。')
        watch='汇款实际金额、统计币种、家庭消费和整体国际收支。'
    elif topic == 'stability':
        analysis='风险提示反映潜在脆弱性，并不等于风险已经实现；需区分高估值、杠杆和流动性问题。'
        impact='若资产重定价与杠杆压力同时出现，可能通过融资和抵押品传导；是否扩散取决于实际敞口及金融机构承受能力。'
        watch='杠杆、融资压力、资产重定价和风险处置安排。'
    elif topic == 'regulation':
        analysis='应先区分征求意见与正式规则，并核对适用对象、实施期限及过渡安排。'
        impact='若规则实施，可能改变合规成本、融资约束或市场准入；范围未定时不能直接推断实际经营影响。'
        watch='最终文本、实施日期、豁免与企业执行反馈。'
    else:
        analysis='现有材料尚不足以确定主要传导路径，需要补充事件规模、受影响对象和落实时间。'
        impact='暂不能可靠判断影响方向或强度；应先确认事实及适用范围，避免用笼统利好或利空替代分析。'
        watch='正式披露、量化细节和后续可核验变化。'
    return {'analysis':lead+analysis, 'impact':impact, 'watch':watch, 'conditional':conditional}


def relate(left, right):
    a,b=left['topic'],right['topic'];pair=frozenset((a,b))
    if 'other' in pair:
        return None
    common=set(left['regions']) & set(right['regions'])
    cross=bool(left['regions'] and right['regions'] and not common)
    uncertain=left['stage']!='reported' or right['stage']!='reported'
    scope=('两条消息涉及不同地区，只作跨市场对照，不能互相替代当地证据。' if cross else
           '共同地区为'+ '、'.join(sorted(common))+'，但这仍不足以确认因果。' if common else
           '地区或适用范围未完全一致，只作机制对照。')
    if a==b:
        contrary={left['direction'],right['direction']}=={'up','down'}
        title=LABELS.get(a,'同类事件')+'线索对照'
        text=('两项方向相反，应先核对指标、期限和时点，再判断是否存在真实分歧。' if contrary else
              '两项消息涉及同一传导渠道，应核对口径与时间范围；多条报道不自动构成独立验证。')
        watch='比较原始口径、覆盖范围及后续数据，确认信号是否持续。'
    elif pair=={'inflation','policy'}:
        title='价格压力与政策选择'
        text='通胀影响政策权衡，政策又通过融资和需求影响价格；应比较物价信号与政策立场是否一致，不能把单次数据当成决定。'
        watch='核心物价与正式政策行动是否形成一致方向。'
    elif pair=={'energy','inflation'}:
        title='能源成本与通胀传导'
        text='能源可以影响总体物价和企业成本；需看持续时间、权重与成本转嫁，不能仅凭同时变化就认定能源造成了本次通胀变化。'
        watch='能源分项、核心物价与下游成本是否同步变化。'
    elif pair=={'trade','inflation'} or pair=={'trade','energy'}:
        trade=left if a=='trade' else right
        if 'energy' in pair and not has(r'原油|石油|天然气|能源|运输|航运',trade['text']):
            return None
        title='贸易约束与成本传导'
        text='贸易政策可能通过采购、运输与替代供应链改变成本；需要适用清单和执行证据，才能判断是否传导到本轮价格变化。'
        watch='实际生效范围、贸易流量和终端价格。'
    elif pair=={'policy','yields'} or pair=={'inflation','yields'}:
        title='政策定价与债券利率'
        text='政策和通胀预期是收益率的可能组成因素，期限溢价与供需也会影响债券定价；方向相符仅是观察线索。'
        watch='不同期限收益率、通胀预期和政策执行是否相互支持。'
    elif pair=={'jobs','policy'} or pair=={'growth','policy'}:
        title='经济活动与政策权衡'
        text='就业和需求会影响政策对增长与通胀的权衡；需区分短期波动与趋势，不能直接把数据变化等同于下一步政策。'
        watch='就业、需求、核心物价与正式政策表态。'
    elif pair=={'yields','credit'} or pair=={'yields','investment'} or pair=={'policy','investment'}:
        title='融资条件与实体支出'
        text='基准利率变化可能传至融资成本，但信用风险与现金流决定实际融资条件；融资环境变化不等于投资计划已落实。'
        watch='实际融资利率、信用利差和资本支出执行。'
    elif pair=={'stability','investment'} or pair=={'stability','credit'}:
        title='投资融资与金融脆弱性'
        text='投资扩张、信用敞口和资产估值可能形成共同风险渠道；需有杠杆与现金流证据，不能把风险提示当成损失已经发生。'
        watch='融资结构、需求兑现和金融机构风险敞口。'
    elif pair=={'trade','cooperation'} or pair=={'investment','cooperation'}:
        trade=left if a=='trade' else right if b=='trade' else None
        if trade and not has(r'人工智能|科技|芯片|半导体|技术|供应链',trade['text']):
            return None
        title='供应链安排与产业投入'
        text='贸易限制、合作规则与产业投入可能共同改变供应链；要核对是否涉及相同技术、参与方和实施范围，不能把宣言直接当成订单或成本变化。'
        watch='技术清单、执行义务、供应安排和已落实投资。'
    elif pair=={'jobs','energy'}:
        energy=left if a=='energy' else right
        if energy['energy_metric']!='output' or not common:return None
        title='就业与实际生产的对照'
        text='同一地区的就业与能源产量可分别观察收入基础和部分生产活动；能源只是一个行业，不能代替整体工业表现，也不能据此确认经济全面改善。'
        watch='更广泛的工业产出、就业与消费能否形成持续一致的信号。'
    elif pair=={'gold','yields'} or pair=={'gold','fx'}:
        title='贵金属与利率汇率线索'
        text='实际利率和汇率是贵金属的可能影响渠道；名义收益率并非实际利率，单一报价不能证明本轮价格驱动。'
        watch='实际利率、报价货币与贵金属供需。'
    else:
        return None
    if uncertain:
        text+='其中含表态、提议或预测，须与已发生结果分开比较。'
    return {'title':title,'analysis':text+scope,'watch':watch,'cross_region':cross}


def add_event_analysis(brief, packet, preserve_impact=False):
    result=deepcopy(brief)
    lookup={fact['id']:fact for fact in packet['facts']}
    profiles=[]
    for point in result['points']:
        facts=[lookup[key] for key in point['evidence_ids']]
        if not all(f.get('kind')=='news' for f in facts):
            profiles.append(None);continue
        meta=profile(point,facts);explanation=explain(meta)
        point['analysis']=explanation['analysis']
        if not preserve_impact:
            point['impact']=explanation['impact'];point['watch']=explanation['watch']
        point['analysis_basis']={key:value for key,value in meta.items() if key!='text'}
        profiles.append(meta)
    links=[];used_pairs=set()
    for i,j in combinations(range(len(profiles)),2):
        if profiles[i] is None or profiles[j] is None:continue
        link=relate(profiles[i],profiles[j])
        if link is None:continue
        pair=tuple(sorted((profiles[i]['topic'],profiles[j]['topic'])))
        if pair in used_pairs:continue
        link['point_numbers']=[i+1,j+1]
        signals=[]
        for index in (i,j):
            meta=profiles[index]
            change={'up':'上行','down':'下行','mixed':'方向混合'}.get(meta['direction'])
            if change:
                qualifier='所述或预期的' if meta['stage']!='reported' else ''
                signals.append(f"第{index+1}条{qualifier}{meta['metric']}{change}")
        if signals:link['analysis']='本期线索：'+'；'.join(signals)+'。'+link['analysis']
        link['evidence_ids']=list(dict.fromkeys(result['points'][i]['evidence_ids']+result['points'][j]['evidence_ids']))
        links.append(link);used_pairs.add(pair)
        if len(links)==3:break
    result['connections']=links
    result['connection_note']='关联分析仅使用本期入选事件；传导机制不等于已证实因果。' if links else '本期入选事件缺少足够的共同线索，暂不强行关联。'
    return result

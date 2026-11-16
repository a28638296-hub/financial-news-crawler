"""Technology event selection and conditional explanations, without trading advice."""
import re

TECH_CATEGORIES = (
    ('tech_security','网络安全与隐私',r'网络安全|数据泄露|信息泄露|隐私|勒索软件|网络攻击|安全漏洞|零日漏洞|\b(?:cybersecurity|ransomware|data breach|CVE-\d|zero.day)\b',''),
    ('tech_chips','芯片与算力',r'芯片|半导体|晶圆|光刻|先进封装|算力|\b(?:GPU|CPU|HBM|semiconductor)\b',''),
    ('tech_ai','人工智能',r'人工智能|大模型|语言模型|生成式|智能体|机器学习|深度学习|\b(?:AI|GPT[ -]?\d|ChatGPT|Claude|Gemini|DeepSeek|Qwen|LLM|OpenAI)\b',''),
    ('tech_cloud','软件与云计算',r'云计算|云服务|云平台|数据中心|数据库|操作系统|开源|浏览器|\b(?:Linux|Kubernetes|PostgreSQL|cloud computing)\b',''),
    ('tech_robotics','机器人与先进制造',r'机器人|自动驾驶|无人驾驶|固态电池|量产电池|储能技术|工业自动化|云控红绿灯|智能交通|交通信号系统|\b(?:robotics|autonomous driving)\b',''),
    ('tech_science','前沿科研与航天',r'科研|科学家|研究人员|研究团队|量子|超导|核聚变|脑机接口|基因编辑|航天|火箭|卫星|空间站|\b(?:SpaceX|NASA|quantum|fusion|CRISPR)\b',''),
)
TECH_KEYS={row[0] for row in TECH_CATEGORIES}
TECH_PATTERNS={row[0]:row[2] for row in TECH_CATEGORIES}
TECH_LABELS={row[0]:row[1] for row in TECH_CATEGORIES}
NOISE=re.compile(r'优惠券|领券|秒杀|促销|补贴到手|好价|低至\d|限时折扣|抽奖|报名|黑客松|发布会直播|谍照|爆料|排列曝光|外观曝光|网红|游戏|手游|网游|\b(?:Steam|PlayStation|Xbox)\b',re.I)
FINANCIAL=re.compile(r'资本开支|资本支出|财报|净利润|融资金额|发行债券|首次公开募股|通胀|加息|降息|利率决议',re.I)
SIGNIFICANT=re.compile(r'发布|推出|开放|开源|量产|投产|首个|首次|突破|批准|通过|漏洞|攻击|泄露|中断|故障|隐私|罚款|安全|试验|测试|发射|回收|合作|宣言|禁令|研究|\b(?:launch|release|open.source|breach|outage|trial)\b',re.I)


def technology_category(item):
    title=item.get('title','')
    if NOISE.search(title) or FINANCIAL.search(title):return None
    # The headline itself must identify technology; a boilerplate footer cannot.
    return next((key for key,_,pattern,_ in TECH_CATEGORIES if re.search(pattern,title,re.I)),None)


def technology_explanation(topic,text,status):
    lead={'forecast':'这是预测或尚待验证的判断，不能作为已经实现的技术结果。',
          'proposal':'目前涉及计划或待落实安排，实际效果需等待执行。',
          'uncertain':'材料仍有否认或不确定条件，应先确认事实。'}.get(status,'')
    if topic=='tech_ai':
        analysis='模型发布、演示成绩和真实使用效果不同，应核对任务范围、测试条件、开放方式及使用限制。'
        impact='若能力在实际任务中复现并具备合理成本，可能提升相关工作效率、改变软件使用方式，也会增加对算力、数据治理和可靠性的要求。'
        watch='独立评测、实际部署成本、可用范围以及隐私和可靠性表现。'
        if re.search(r'调用量|使用量|榜单|排名|Token',text,re.I):
            analysis='平台调用统计反映其覆盖范围内的使用情况；单个平台或榜单不能代表全球总使用量，也不能把调用量直接当作能力、收入或市场份额。'
            impact='若真实使用需求持续增长，可能增加推理算力和服务资源需求；商业价值仍取决于付费、单次成本、用户留存及统计口径。'
            watch='统计覆盖范围、计量方式、付费使用比例及持续性。'
    elif topic=='tech_chips':
        analysis='样片、测试成绩、量产能力和稳定交付是不同阶段；性能比较还需要相同负载、功耗和软件条件。'
        impact='若技术指标与产能按计划兑现，可能改变计算成本、能耗和供应选择；实际收益取决于良率、交付规模与软件适配。'
        watch='独立性能测试、量产良率、交付进度和软件兼容性。'
        if re.search(r'建.{0,25}厂|建厂|工厂|产线|扩产',text):
            analysis='建厂投资、建设进度与实际产能不同，应核对资金落实、审批、设备安装及客户验证。'
            impact='若项目按计划建成并通过验证，可能增加制造或测试能力并改变供应安排；建设期先发生资金占用，实际收益取决于利用率与需求。'
            watch='审批与资金落实、建设投产日期、认证进度及产能利用率。'
    elif topic=='tech_cloud':
        analysis='应核对版本状态、兼容性、服务覆盖和迁移成本，功能发布不等于用户已完成采用。'
        impact='若在实际系统中稳定落地，可能改变运维效率、计算成本与服务可用性；迁移、维护和供应商依赖也可能增加成本。'
        watch='稳定性、正式支持范围、迁移反馈和长期维护安排。'
        if re.search(r'中断|故障|宕机|outage',text,re.I):
            analysis='应先确认故障范围、持续时间和恢复状态；单一用户报告不能代表整个平台均不可用。'
            impact='若故障影响关键服务，可能中断业务与数据处理，并触发备用系统和恢复成本；实际损失取决于持续时间及冗余安排。'
            watch='官方恢复公告、受影响地区、数据完整性和故障复盘。'
    elif topic=='tech_security':
        analysis='漏洞披露、已经遭到利用、数据确认泄露和监管认定是不同事实，需核对受影响版本、权限及证据。'
        impact='若影响得到确认，相关组织可能承担修复、业务中断和合规成本，用户隐私或账户安全也可能受影响；披露漏洞本身不证明已发生损失。'
        watch='官方通报、补丁状态、受影响范围和已确认的利用或泄露情况。'
    elif topic=='tech_robotics':
        analysis='实验演示、受控场景测试和规模化运行应分开，关键在安全、稳定性、环境限制及实际生产成本。'
        impact='若能稳定部署，可能改变生产或运输效率、岗位任务和能源使用；规模推广仍取决于安全验证、维护成本与准入条件。'
        watch='实际场景测试、事故与故障率、维护成本及审批进度。'
        if re.search(r'红绿灯|智能交通|交通信号',text):
            analysis='交通系统试点需要区分宣传指标与实测效果，并核对覆盖路口、车流条件、行人安全和应急安排。'
            impact='若试点效果可复现，可能改善通行效率并减少等待时间；推广效果取决于路网差异、数据质量、维护成本及安全约束。'
            watch='试点前后可比较的数据、不同路况表现和安全评估。'
    else:
        analysis='论文结果、实验验证、工程试验和成熟应用属于不同阶段；单次里程碑不能证明技术已可规模推广。'
        impact='若结果可复现并能推进工程化，可能扩大相关研究或产业能力；时间、成本和应用范围仍取决于后续验证。'
        watch='原始研究或官方任务通报、独立复现、后续试验与工程约束。'
    return {'analysis':lead+analysis,'impact':impact,'watch':watch,'conditional':status!='reported'}

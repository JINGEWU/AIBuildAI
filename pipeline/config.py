# -*- coding: utf-8 -*-
"""集中配置：路径、外部数据源、筛选规则、抽取正则、评分权重。

所有阶段脚本只从这里取规则，改规则不用碰流程代码。
"""
import os, re, json

# ───────────────────────── 路径 ─────────────────────────
ROOT = os.environ.get("AIBUILDAI_ROOT", "/Users/jinge/Desktop/AIbuildAI")
DATA = f"{ROOT}/data"          # 中间产物 (jsonl / state json)
FULLTEXT = f"{ROOT}/fulltext"  # 官方全文 PDF / JATS XML
QUARANTINE = f"{ROOT}/arxiv_隔离"   # 审计出的 arXiv/预印本版，移出 fulltext
PAPERS = f"{ROOT}/papers"      # 既有 54 篇基线语料
LOGS = f"{ROOT}/logs"

# 交付物
XLSX_JOURNALS = f"{ROOT}/期刊清单_v2.xlsx"
XLSX_ROUND1   = f"{ROOT}/第一轮筛选结果.xlsx"
XLSX_ROUND2   = f"{ROOT}/第二轮筛选结果.xlsx"
XLSX_EXTRACT  = f"{PAPERS}/agent_papers_SOTA_evaluation.xlsx"

# ───────────────────────── 抓取范围 ─────────────────────────
YEARS = (2025, 2026)
IF_FLOOR = 15.0          # JCR IF 下限
# 数据刊/报告刊不收（无 benchmark pipeline）
JOURNAL_BLOCKLIST = {"Scientific Data", "Scientific Reports"}

# ───────────────────────── 外部数据源 ─────────────────────────
# 说明见 README「数据源现状」——OpenAlex 已转付费，OpenReview 已上 CAPTCHA，均不可用
MAILTO = "openalex-polite@researchmail.org"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
API = {
    "crossref":  "https://api.crossref.org/journals/{issn}/works",
    "epmc":      "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
    "epmc_xml":  "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
    "epmc_pdf":  "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextPDF",
    "s2_batch":  "https://api.semanticscholar.org/graph/v1/paper/batch",
    "unpaywall": "https://api.unpaywall.org/v2/{doi}",
    "arxiv":     "http://export.arxiv.org/api/query",
}
RATE = {"crossref": 1.0, "epmc": 0.6, "s2": 1.2, "unpaywall": 0.5,
        "arxiv": 3.2, "publisher": 1.5}   # 每次请求之间的最小间隔(秒)

# ═════════════════════ 第一轮筛选：关键词体系 ═════════════════════
# A. AI/模型信号（必须命中 ≥1，否则直接出局）
KW_AI = [
 r"\bagent(s|ic|-based)?\b", r"multi-?agent", r"\bllm[s]?\b", r"large language model",
 r"language model", r"foundation model", r"\bgpt-?[0-9o]?\b", r"chatgpt", r"\bgemini\b",
 r"\bclaude\b", r"\bllama\b", r"\bqwen\b", r"\bdeepseek\b", r"\bmistral\b", r"transformer",
 r"deep learning", r"machine learning", r"neural network", r"artificial intelligence",
 r"\bai\b", r"\bai-(based|driven|powered|assisted|enabled)", r"generative (ai|model)",
 r"diffusion model", r"vision.?language", r"multimodal (model|llm|learning)",
 r"reinforcement learning", r"self-supervised", r"graph neural", r"\bgnn\b",
 r"natural language processing", r"\bnlp\b", r"\bcopilot\b", r"retrieval.?augmented", r"\brag\b",
 r"chain-of-thought", r"in-context learning", r"fine-?tun", r"pre-?train", r"prompt(ing|s|ed)\b",
 r"\bautoml\b", r"knowledge graph", r"\bcnn\b", r"\bbert\b", r"\bvit\b", r"\bencoder-decoder\b",
 r"neural (operator|ode|network)", r"\bdeep neural\b", r"\bcomputer vision\b"]

# B. 评测/基准/系统信号
KW_BENCH = [
 r"\bbenchmark", r"\bdataset[s]?\b", r"\btest set\b", r"held-?out", r"\bevaluat",
 r"state-of-the-art", r"\bsota\b", r"\bbaseline[s]?\b", r"leaderboard", r"\bf1\b",
 r"\baccuracy\b", r"\bauroc\b", r"\bauc\b", r"\bprecision\b", r"\brecall\b", r"pass@\d",
 r"open-?source", r"publicly available", r"\bgithub\b", r"hugging ?face", r"\bzenodo\b",
 r"\bframework\b", r"\bpipeline\b", r"\bsystem\b", r"\btask[s]?\b", r"outperform",
 r"\bbits per\b", r"\bcode (is|are) available\b", r"\bwe release\b"]

# C. 强正向：agent 系统 / 自研 benchmark / 明确开源
KW_STRONG = [
 r"\bagentic\b", r"multi-?agent", r"\bllm[- ]?agent",
 r"agent(ic)? (framework|system|architecture|workflow|pipeline)",
 r"\bautonomous (agent|system|scientist|research|discovery|workflow)",
 r"\btool[- ]?(use|using|calling|augmented)\b", r"\bfunction calling\b",
 r"we (present|introduce|propose|develop|release) [^.]{0,60}\bbenchmark\b",
 r"\b(a|new|novel|comprehensive) benchmark\b",
 r"benchmark(ing)? (suite|dataset|framework|platform)",
 r"\bwe (release|open-?source)\b", r"code and data are (publicly )?available",
 r"\bfoundation model\b", r"\bagent benchmark\b", r"\bevaluation (suite|harness|framework)\b",
 r"\bself-(improv|evolv|verif|refin|correct)", r"\bhuman[- ]expert (level|performance)\b",
 r"\bend-to-end automation\b", r"\bscientific discovery\b",
 # 带限定词的 agent 短语。上面只认 multi-agent / agentic / llm-agent /
 # agent+{framework|system|...}，漏掉了 "AI agent" "language agents"
 # "embodied agents" 这些最常见的说法 —— 早期那批 agent 论文正因此没进判读队列。
 # 限定词不能省：裸 \bagents?\b 在全库命中 8592 条，绝大多数是化学/医学的
 # 「试剂」义（contrast agent、antimicrobial agent），加限定后只剩 399 条。
 # 不含 diagnostic：放射药物学里 "diagnostic/theranostic agents" 指诊断药剂，
 # 实测仅因它命中的 11 条全部是化学论文，判读后无一入选
 r"\b(ai|artificial intelligence|language|llm|gpt|embodied|conversational|autonomous|"
 r"software|web|research|scientific|coding)[- ]agents?\b"]

# D. 负向：湿实验 / 硬件 / 人工评测 / 临床试验（用户明确排除）
KW_NEG = [
 r"\bmice\b", r"\bmouse\b", r"\brats?\b", r"\bin vivo\b", r"\bin vitro\b", r"\bcell lines?\b",
 r"western blot", r"\bqpcr\b", r"\belisa\b", r"\bimmunohistochem", r"\bflow cytometry\b",
 r"\bknockout\b", r"\bcrispr\b", r"\bmutagenesis\b", r"\bcultured\b", r"\bxenograft\b",
 r"\bwe synthesi[sz]ed\b", r"\bwas synthesi[sz]ed\b", r"were synthesi[sz]ed",
 r"\bcrystal structure\b", r"\bx-ray diffraction\b", r"\bnmr spectra", r"\bmass spectrometry\b",
 r"randomi[sz]ed (controlled )?(clinical )?trial", r"\bdouble-blind\b", r"\bplacebo\b",
 r"\bcohort study\b", r"\bquestionnaire\b", r"\bsurvey of \d", r"\binterviews? (with|were)\b",
 r"\bfabricat(ed|ion)\b", r"\bwafer\b", r"\bnanoparticles?\b", r"\bthin film\b",
 r"\belectrode\b", r"\bbattery\b", r"\bphotovoltaic\b", r"\bcatalyst was\b",
 r"\bpatients (were|underwent)\b", r"\bparticipants (were|completed)\b",
 r"\bprospective(ly)? (study|enrolled|recruited)\b", r"\bcase report\b"]

# E. 高相关期刊：刊内 AI 论文一律进候选，防漏召回
PRIORITY_JOURNALS = {
 "npj Artificial Intelligence", "Nature Machine Intelligence", "Patterns",
 "IEEE Trans. Pattern Analysis and Machine Intelligence",
 "IEEE Transactions on Pattern Analysis and Machine Intelligence",
 "IEEE Trans. Software Engineering", "IEEE Transactions on Software Engineering",
 "ACM Trans. Software Engineering and Methodology",
 "ACM Transactions on Software Engineering and Methodology",
 "ACM Trans. Information Systems", "ACM Transactions on Information Systems",
 "IEEE Trans. Artificial Intelligence", "IEEE Transactions on Artificial Intelligence",
 "IEEE Trans. Knowledge and Data Engineering",
 "IEEE Transactions on Knowledge and Data Engineering",
 "NEJM AI", "Nature Computational Science", "npj Digital Medicine", "Cell Systems",
 "Journal of Artificial Intelligence Research", "Artificial Intelligence",
 "Communications AI & Computing", "npj Robotics", "Nature", "Science", "Nature Communications",
 "Nature Medicine", "Nature Methods", "Nature Biomedical Engineering", "Cell Reports Methods",
 "The Lancet Digital Health", "Journal of the American Medical Informatics Association",
 "IEEE Journal of Biomedical and Health Informatics", "Bioinformatics",
 "Briefings in Bioinformatics", "Nucleic Acids Research",
 "IEEE Trans. Audio, Speech and Language Processing",
 "IEEE Transactions on Audio Speech and Language Processing",
 # 这三本 Nature 系刊会发 AI 系统论文，但此前不在高相关名单里，
 # 「高相关期刊+强信号」这条晋级规则对它们一直失效
 "Nature Water", "Nature Health", "Nature Human Behaviour"}

# 一轮召回打分权重
SCORE1 = {"ai": 0.8, "bench": 0.6, "strong": 3.0, "ai_title": 1.5,
          "strong_title": 2.5, "neg": -1.5, "has_abstract": 1.5, "priority_journal": 1.5}

# ═════════════════════ 第一轮：非研究类型剔除 ═════════════════════
RE_DROP_TITLE = re.compile(r"^("
 r"correction|corrigend|erratum|retraction|editorial|comment|reply|withdrawn|"
 r"author correction|publisher correction|obituary|book review|news|correspondence|"
 r"in this issue|highlights|表紙|editor'?s? (note|choice|pick)|"
 r"in science journals|news at a glance|this week in science|research highlights|"
 r"\d+\s*(P|O|TiP|MO|PD|TPS|LBA)\b|"
 r"abstract\s+\d+|poster\s+\d+|"
 r"contents list|table of contents|masthead|front matter|back matter|issue information|"
 r"list of reviewers|acknowledg(e)?ment to reviewers|call for papers|"
 r"introduction to the special (issue|section)|guest editorial"
 r")", re.I)
RE_NUMBERED_TITLE = re.compile(r"^\s*\d{2,5}\s*[A-Z]{1,4}\b")   # 会议摘要编号

# ═════════════════════ 第一轮：规则分流（自动排除） ═════════════════════
RE_SURVEY_STRICT = re.compile(
 r"(:\s*a\s+(systematic\s+)?(survey|review|tutorial|taxonomy)|"
 r"^(a|an)\s+(systematic\s+)?(survey|review|overview|tutorial|taxonomy)\b|"
 r"\b(survey|review|tutorial|taxonomy|scoping review|systematic literature review)\s*$|"
 r"\ba (survey|review) (of|on)\b|\bsurvey and\b|\breview of\b|\breview and\b)", re.I)
# DOI 段本身就能判死的非论文体裁 —— 比正文关键词可靠得多：
#   10.1038/d41586  Nature 的新闻/评论/Daily briefing 段（候选池里 463 条）
#   10.1182/blood-YYYY-N  ASH 年会摘要（1842 条，全部以 "Abstract Background" 起手）；
#                         Blood 正刊论文是点号型 10.1182/blood.NNNN，不受影响
RE_NONPAPER_DOI = re.compile(r"10\.1038/d41586|10\.1182/blood-\d{4}-\d+", re.I)
RE_CONF_ABS = re.compile(
 r"^\s*(e?\d{1,6})\s+(Background|Methods|Introduction|Purpose|Objectives?|Aims?)\b", re.I)
RE_CONF_TITLE = re.compile(r"^\s*(e?\d{2,6}[A-Z]{0,3})\s+[A-Z]")
RE_ALLCAP_TITLE = re.compile(r"^[^a-z]{25,}$")

# 控制论假阳性："multi-agent" 指控制系统而非 LLM 智能体（一轮最大的假阳性来源）
RE_CTRL = re.compile(r"\b("
 r"consensus (control|tracking|problem|protocol)|bipartite consensus|leaderless|leader-follow|"
 r"containment control|formation (control|tracking)|flocking|rendezvous|"
 r"fault-tolerant control|actuator (fault|failure)|sensor fault|"
 r"event-triggered|self-triggered|prescribed-time|predefined-time|finite-time|fixed-time|"
 r"observer-based|disturbance observer|state observer|"
 r"synchronization control|output (regulation|feedback) control|tracking control|"
 r"sliding mode|backstepping|nussbaum|barrier lyapunov|lyapunov[- ]krasovskii|"
 r"zeroing neural network|\bznn\b|funnel control|"
 r"input (saturation|dead-?zone|quantization)|dead-?zone|"
 r"adaptive (neural network |fuzzy )?(control|controller)|"
 r"optimal (consensus|containment|tracking|regulation) |"
 r"h-?infinity|dynamic surface|command filter|"
 r"(dos|denial-of-service|fdi|false data injection|deception) attack|"
 r"cooperative (control|tracking|output)|distributed (control|observer|estimation)|"
 r"time-varying delay|semi-markov|switched (system|topolog)|directed topolog"
 r")\b", re.I)
RE_CTRL_RESCUE = re.compile(r"\b(llm|large language model|language model|gpt|agentic|benchmark|"
 r"foundation model|chatgpt|transformer|prompt|dataset|vision-?language)\b", re.I)
CTRL_JOURNALS = {
 "IEEE Trans. Cybernetics", "IEEE Trans. Neural Networks and Learning Systems",
 "Neural Networks", "IEEE Trans. Artificial Intelligence",
 "IEEE Trans. Information Forensics and Security", "IEEE Trans. Robotics",
 "IEEE Trans. Intelligent Transportation Systems", "IEEE Trans. Automatic Control"}
RE_CTRL2 = re.compile(r"\b(consensus|containment|formation|flocking|synchroni[sz]ation|"
 r"impulsive|output regulation|convergence rate|topology reconfiguration|"
 r"model predictive|mpc|descriptor system|fractional-?order|packet loss|time-?delay|"
 r"watermarking|pursuit-?evasion|actuator|saturation|quantiz|"
 r"distributed (optimization|convex|minimax|estimation|control|observer)|"
 r"cooperative (control|output|tracking)|safe critic|adaptive (critic|boundary))\b", re.I)
RE_CTRL2_RESCUE = re.compile(r"\b(llm|large language model|language model|gpt|agentic|benchmark|"
 r"foundation model|chatgpt|prompt|dataset|vision-?language|transformer|multimodal|"
 r"diffusion|retrieval|question answering)\b", re.I)

# ═════════════════════ 第二轮：全文信号抽取 ═════════════════════
RE_LINK = re.compile(r"(?:https?://)?(?:www\.)?("
 r"github\.com/[\w.\-]+/[\w.\-]+|huggingface\.co/[\w.\-/]+|"
 r"zenodo\.org/(?:record|records|doi)/[\w.\-/]+|figshare\.com/[\w.\-/]+|osf\.io/[\w]+|"
 r"datadryad\.org/[\w.\-/]+|codeocean\.com/[\w.\-/]+|gitlab\.com/[\w.\-/]+|"
 r"kaggle\.com/[\w.\-/]+|physionet\.org/[\w.\-/]+|openreview\.net/forum\?id=[\w]+|"
 r"paperswithcode\.com/[\w.\-/]+)", re.I)
RE_AVAIL = re.compile(r"(data (and code )?availability|code availability|availability of data"
 r"|data and materials availability|software availability|resource availability)", re.I)
RE_SOTA = re.compile(r"(state[- ]of[- ]the[- ]art|\bsota\b|outperform\w*|surpass\w*|best[- ]performing"
 r"|new record|achieves? (?:an? )?(?:accuracy|f1|auc|auroc|score|success rate|pass@\d)"
 r"|improv\w+ by \d|\bgain of \d)", re.I)
RE_METRIC = re.compile(r"\b(accuracy|f1[- ]?score|\bf1\b|auroc|auprc|\bauc\b|precision|recall|"
 r"pass@\d|exact match|\bem\b|bleu|rouge|meteor|cider|dice|iou|miou|mae|rmse|mse|r2|"
 r"spearman|pearson|success rate|win rate|elo|perplexity|top-?[15]|map@?\d*|ndcg|mrr|"
 r"hit@\d|c-index|concordance|sensitivity|specificity|balanced accuracy|kappa|"
 r"llm-as-a-judge|llm judge|human evaluation|expert evaluation)\b", re.I)
RE_BENCH_NAME = re.compile(
 r"\b([A-Z][A-Za-z0-9]*(?:-?[A-Z][A-Za-z0-9]*)*(?:Bench|BENCH|bench|Arena|Gym|Eval))\b"
 r"|\b(benchmark|test set|held-out set|evaluation suite|leaderboard)\b")

# 红旗：命中越多越不适合自动化复刻
RE_WET = re.compile(r"\b(in vivo|in vitro|mice|mouse|rats?|cell lines?|western blot|qpcr|elisa|"
 r"immunohistochem|flow cytometry|knockout|crispr|cultured|xenograft|synthesi[sz]ed|"
 r"x-ray diffraction|nmr spectra|mass spectrometry|wet[- ]lab|wet lab|liquid handling|"
 r"robotic arm|fabricat|wafer|electrode|photovoltaic|reactor)\b", re.I)
RE_HW = re.compile(r"\b(hardware[- ]in[- ]the[- ]loop|physical robot|real robot|robotic platform|"
 r"drone flight|test vehicle|on-?device chip|fpga|neuromorphic chip|memristor|"
 r"clinical trial|randomi[sz]ed controlled|prospective(?:ly)? (?:enrolled|recruited))\b", re.I)
RE_HUM = re.compile(r"\b(human (?:evaluation|raters?|annotators?|experts?|study|preference)|"
 r"expert (?:evaluation|review|rating|panel|assessment)|clinician (?:review|rating|evaluation)|"
 r"reader study|user study|questionnaire|likert|blinded (?:review|evaluation|assessment)|"
 r"physician (?:review|rating))\b", re.I)

# 知名公开基准：命中即说明测试集公开可下载
RE_KNOWN_BENCH = re.compile(r"\b("
 r"imagenet|coco|ade20k|cityscapes|pascal voc|kinetics|kitti|nuscenes|waymo|argoverse|"
 r"glue|superglue|squad|mmlu|mmlu-pro|gsm8k|math500|humaneval|mbpp|swe-?bench|bigcodebench|"
 r"livecodebench|apps|codecontests|defects4j|bugswarm|"
 r"agentbench|webarena|osworld|gaia|tau-?bench|toolbench|mint|alfworld|scienceworld|"
 r"minedojo|smac|melting pot|mujoco|atari|procgen|d4rl|metaworld|habitat|"
 r"medqa|medmcqa|pubmedqa|mimic-?(?:iii|iv|cxr)|eicu|chexpert|nih chestx|padchest|brats|"
 r"acdc|amos|msd|totalsegmentator|isic|camelyon|tcga|panda|"
 r"scib|tabula sapiens|cellxgene|human cell atlas|perturb-?seq|"
 r"casp|cafa|pdbbind|davis|kiba|bindingdb|moleculenet|qm9|md17|matbench|oc20|oc22|jarvis|"
 r"the pile|c4|wikitext|lambada|hellaswag|arc-?(?:easy|challenge)|truthfulqa|"
 r"vqa-?v2|gqa|okvqa|textvqa|mmbench|mmmu|mathvista|seed-?bench|pope|"
 r"librispeech|voxceleb|audioset|esc-?50|musdb|"
 r"ogb|planetoid|cora|citeseer|pubmed dataset|reddit dataset|"
 r"physionet|ukbiobank|uk biobank|adni|abide|hcp|openneuro|"
 r"hle|humanity.s last exam|arena-?hard|mt-?bench|alpacaeval|chatbot arena"
 r")\b", re.I)

# ═════════════════════ 全文版本审计（只要官方版） ═════════════════════
# 侧边戳形如 arXiv:2403.04780v3 [cs.CL] 24 Aug 2025 —— 版本号 v3 必须允许，否则漏判
RE_ARXIV_STAMP = re.compile(r"arXiv:\s?\d{4}\.\d{4,5}(v\d+)?\s*\[")
RE_AUTHOR_LATEX = re.compile(r"(JOURNAL OF LATEX CLASS FILES|REPLACE THIS LINE WITH YOUR MANUSCRIPT)")
# 必须是真出版商指纹。裸刊名页眉("IEEE TRANSACTIONS")和裸"© 2025"不算：
# 作者接收稿同样带这些，会把预印本误判成官方版。
RE_PUBLISHER_STAMP = re.compile(
 r"(Digital Object Identifier"
 r"|10\.\d{4,5}/[A-Za-z0-9.\-/]{4,}"
 r"|©\s?20\d\d\s*(IEEE|Elsevier|Springer|Nature|Macmillan|AAAS|The Author|Oxford|Wiley)"
 r"|\b(0162-8828|1939-3539)\b"
 r"|nature\.com/(articles|reprints)"
 r"|www\.science\.org"
 r"|Manuscript received .{0,80}\b20\d\d"
 r"|Received:.{0,120}Accepted:"
 r"|Published online[: ].{0,40}20\d\d"
 r"|VOL\.\s*\d+,\s*NO\.\s*\d+"
 r")", re.I)
# 抓取时必须排除的预印本/仓储域名
RE_BAD_HOST = re.compile(r"(arxiv\.org|export\.arxiv|biorxiv|medrxiv|chemrxiv|researchsquare|"
 r"research-square|ssrn|preprints?\.org|osf\.io|zenodo|semanticscholar|"
 r"researchgate|scholar\.archive|48550)", re.I)
MIN_PDF_BYTES = 40000
MIN_PDF_PAGES = 3

# ═════════════════════ 复刻优先级评分 ═════════════════════
AUTOMATION_LEVELS = {
 "A+": "可执行验证：单元测试/Pass@k，运行即知对错，最适合复刻对标",
 "A":  "有 ground truth 的客观指标：准确率/AUROC/mIoU/MAE 等",
 "B":  "需 LLM-as-judge：可自动化但依赖模型评判，需固定评判模型以保证可比",
 "C":  "需人评/湿实验/硬件：自动化受限，不建议作为对标基准"}
W_AUTO = {"A+": 40, "A": 30, "B": 15, "C": 0}       # 可自动化等级
W_OPEN = {"是": 25, "部分": 10, "否": 0}             # 基准公开度
W_SOTA = {"有": 10, "无": 0}                         # 文中是否报告 SOTA
W_LINK_EACH, W_LINK_CAP = 2, 8                       # 代码/数据链接数
W_KNOWN_EACH, W_KNOWN_CAP = 2, 8                     # 命中知名公开基准数
W_HEADROOM = 12                                      # 明确"头顶空间大"
PENALTY = {"hum": (0.4, 10), "wet": (0.15, 8), "hw": (0.3, 8)}  # (每次命中, 上限)
RE_HEADROOM = re.compile(r"(头顶空间大|空间大|远未饱和|上限高|提升空间)")
TIER_CUTS = [("S", 88), ("A", 78), ("B", 66), ("C", 0)]
# 期刊影响力加分
TOP_JOURNAL_BONUS = {
 "Nature": 10, "Science": 10, "Cell": 9, "Nature Medicine": 9,
 "Nature Machine Intelligence": 8, "Nature Biomedical Engineering": 8,
 "Nature Methods": 8, "Nature Communications": 5,
 "IEEE Trans. Pattern Analysis and Machine Intelligence": 7,
 "The Lancet Digital Health": 6, "Nature Computational Science": 6,
 "npj Digital Medicine": 5, "Nucleic Acids Research": 4}
TOP_JOURNAL_DEFAULT = 1

# ═════════════════════ 信息抽取（第 7 步）表结构 ═════════════════════
EXTRACT_COLUMNS = ["#", "系统·论文", "期刊", "年", "领域", "Benchmark 名称", "Benchmark 规模",
 "Benchmark·数据集链接", "论文报告的 SOTA", "评估指标 & 计算方式", "自动化等级",
 "代码链接", "Paper link", "复刻备注"]

# ───────────────────────── 期刊清单 ─────────────────────────
_J = None
def journals():
    """返回合并后的期刊清单 [{name, issn, jcr, jtype, field, ...}]"""
    global _J
    if _J is None:
        p = f"{DATA}/merged_journals.json"
        _J = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else []
    return _J

def if_of(name):
    for j in journals():
        if j.get("name") == name:
            return j.get("jcr")
    return None

def compiled(patterns):
    return [re.compile(p, re.I) for p in patterns]


# ═════════════════════ 第二轮（全文）判定规则 ═════════════════════
# 规则从 329 条实际判读里反推得出，与四条硬标准一一对应。
# 三道硬门槛（任一不过就不得入选），再用一条平局规则决定「部分公开」的去向。

OPEN_BLOCK = {"否"}        # 门槛一 测试集必须公开可下载
AUTO_BLOCK = {"C"}         # 门槛二 评估必须 AI 可自动化（排除湿实验/硬件/人评）
SOTA_BLOCK = {"无", ""}    # 门槛三 必须报告可对比的 SOTA

# 平局规则：基准公开=部分 时，要有直达链接或命中知名公开基准，才算真能拿到测试集
PARTIAL_NEEDS_EVIDENCE = True

# SOTA 强度分级 —— 只出现 "state-of-the-art" 字样不等于"报告了可对比 SOTA"。
# 实测 329 篇：96.4% 命中字样，但仅 65.7% 那句带数值，仅 35.9% 同句有对比对象。
RE_SOTA_NUM = re.compile(r"\d+\.?\d*\s*%|\b\d+\.\d+\b|\bby \d|\bfrom \d+.{0,20}to \d")
RE_SOTA_CLAIM = re.compile(r"(outperform|surpass|exceed|improv|achiev|higher than|better than"
                           r"|state[- ]of[- ]the[- ]art|new record|best[- ]performing)", re.I)
RE_SOTA_BASELINE = re.compile(r"(baseline|previous|prior|existing|compared (to|with)|versus"
                              r"|\bvs\.?\b|state[- ]of[- ]the[- ]art|sota)", re.I)

# 红旗阈值：超过则提示复核。不自动排除——数字是全文词频，噪声大
FLAG_HUM, FLAG_WET, FLAG_HW = 15, 40, 10


# ═══════════════════════ S9 信息增强：分类口径 ═══════════════════════
# 任务领域。自上而下匹配，先具体后宽泛
# 已知未覆盖：\bgraph\b 匹配不到 graphs/subgraph，另有 8 篇落在"其他"。
# 刻意不补——交付表格的领域列以此口径为准，改规则会让已发布的表格对不上。——"病理影像"必须排在"医学影像"前，
# 否则含 CT/MRI 字样的病理论文会被吃掉。判据取 标题+基准名+备注 拼接串。
DOMAIN = [
 ("科学计算与仿真", r"turbulence|fracture mechanic|interpolat(ing|ion) neural|partial differential|"
   r"constrained optimization|quantum experiment|multiscale deep formula|finite element|流体|PDE\b"),
 ("质谱与蛋白组", r"mass spectrometr|proteomic|data-dependent acquisition|peptide identification|DDA\b"),
 ("病理影像", r"patholog|whole[- ]slide|\bWSI\b|histopatholog|Gleason|CAMELYON|tumour infiltrating|"
   r"blood cell morpholog|spatial proteomic"),
 ("医学影像", r"\bCT\b|\bMRI\b|radiolog|chest|X-ray|CXR|ultrasound|echocardiog|endoscop|fundus|retina|"
   r"\bOCT\b|mammogra|neuroimag|haemorrhage|hemorrhage|fluorescen(ce|t) (image|micro)"),
 ("临床NLP与决策", r"clinical|electronic health|\bEHR\b|diagnos|medical (task|question|LLM|foundation)|"
   r"patient|\bICU\b|triage|MedQA|rare disease|natural history of human disease|atrial fibrillation|"
   r"immunotherapy outcome|prognos"),
 ("单细胞与组学", r"single[- ]cell|scRNA|transcriptom|cell type|gene expression|perturb|spatial (multi-)?omic|"
   r"cell embedding|CITE-seq|Hi-C|multi-omic|cancer genotype|microbiome"),
 ("基因组与序列", r"\bDNA\b|\bRNA\b|genom|nucleotide|splice|methylat|chromatin|enhancer|promoter|"
   r"epigenom|metagenom|virus|nanopore|mRNA"),
 ("蛋白与结构", r"protein|enzyme|structure prediction|docking|AlphaFold|residue|oligomer|\bpeptide\b|folding"),
 ("分子与药物", r"molecul|drug|compound|ligand|binding affinity|retrosynth|chemi|reaction|synthesiz|"
   r"bioactivity|QSAR|chiral|natural product"),
 ("材料与晶体", r"crystal|material|\bMOF\b|porous|interatomic|potential|catalys|perovskite|glacier"),
 ("遥感与地学", r"remote sensing|satellite|earth system|hyperspectral|geospatial|weather|climate|"
   r"tropical cyclone|photovoltaic|ground ice"),
 ("视觉-视频与具身", r"\bvideo\b|embodied|navigation|driving|autonomous|LiDAR|point cloud|action recognition|"
   r"skeleton|trajectory|deepfake|human mesh|photometric stereo|pose estimation|Minecraft"),
 ("多模态与VLM", r"vision[- ]language|multimodal|\bVQA\b|visual question|image[- ]text|caption|"
   r"text-to-image|face generation"),
 ("视觉-分割检测", r"segmentation|detection|localization|object|tracking|saliency|camouflag|restoration|"
   r"deblur|dehaz|super-resolution|\bimage\b|viewpoint|RAW image|text segmentation|adversarial attack"),
 ("图学习", r"\bgraph\b|\bGNN\b|node classification|link prediction|knowledge graph|graph neural"),
 ("推荐与信息检索", r"recommend|retrieval|search|literature synthesis|scholar"),
 ("时序与信号", r"\bECG\b|\bEEG\b|sleep|time series|forecast|signal|speech|audio|wireless|\bCSI\b|"
   r"spectral analysis|gait|walking|cardiac"),
 ("LLM与agent", r"\bLLM\b|large language model|\bagent\b|reasoning|prompt|chain-of-thought|hallucinat|"
   r"jailbreak|\bGPT\b|instruction|expert-level|human cognition|empirical software|model merging|"
   r"mixture of.*experts|language model"),
 ("表格与通用ML", r"tabular|federated|continual|noisy label|semi-supervised|domain (adaptation|generalization)|"
   r"quantiz|compress|calibrat|neural architecture|explainab|interpretab|meta-learning|label purification|"
   r"long-tailed|concept drift|shortcut|data bias|topological deep learning|genomic prediction|phenotype"),
]

# 文章类型人工判定表：依据逐篇通读，不做关键词推断。
# 关键词在这件事上误判率太高（标题含 benchmark 的常是方法论文，反之亦然）。
PURE_BENCH = {   # 只给评测集/横向排名，无自研待超越的方法
 "10.1038/s41586-025-09962-4",   # HLE
 "10.1109/tpami.2026.3683747",   # VLBiasBench
 "10.1038/s42256-025-01055-1",   # Matbench Discovery
 "10.1038/s41551-026-01719-2",   # BRIDGE
 "10.1109/tpami.2026.3653457",   # MERBench
 "10.1038/s41586-025-09716-2",   # FHIBE 公平性数据集
 "10.1038/s42256-025-01160-1",   # PoseBench
 "10.1109/tpami.2024.3373868",   # NineRec
 "10.1109/tpami.2026.3663547",   # DREAM
 "10.1109/tpami.2025.3574432",   # BlackboxBench
 "10.1038/s41467-026-76004-6",   # 病理基座横评
 "10.1038/s41467-026-73923-2",   # PathoROB
 "10.1038/s41551-025-01516-3",   # 病理基座特征提取器横评
 "10.1038/s41467-025-67481-2",   # scDrugMap
 "10.1038/s41467-025-65823-8",   # DNA 基座横评
 "10.1038/s41467-025-56989-2",   # 生物医学 NLP 横评
 "10.1038/s41557-025-01815-x",   # ChemBench
 "10.1038/s41467-026-74077-x",   # cfRNA LLM 横评
 "10.1038/s41467-025-56321-y",   # 生成式 AI 正常态表征评测
 "10.1038/s41467-025-65077-4",   # DNALONGBENCH
 "10.1038/s41467-025-64186-4",   # scHi-C 嵌入工具横评
 "10.1038/s41467-025-67127-3",   # FoldBench
 "10.1038/s41591-025-04151-2",   # MedHELM
 "10.1038/s42256-025-01152-1",   # LabSafety Bench
 "10.1016/j.landig.2025.100953", # RareArena
 "10.1038/s41467-026-68725-5",   # Counting cells（基线质疑研究）
 "10.1038/s41467-025-64769-1",   # MedR-Bench
 "10.1038/s41467-025-60801-6",   # 无捷径拓扑数据集
 "10.1038/s42256-024-00977-6",   # ChEBI-20-MM 分析
 "10.1038/s42256-024-00956-x",   # E(3) 等变设计空间分析
 "10.1093/nar/gkaf1314",         # 直接 RNA 测序技术评估
 "10.1038/s41551-025-01598-z",   # 见下方 METHOD_OVERRIDE 覆盖
}
REVIEW = {       # 综述/复现报告——用户明确排除
 "10.1038/s42256-026-01187-y",   # Reusability Report
}
METHOD_OVERRIDE = {   # 从 PURE_BENCH 挪回原创方法（有自研模型可超越）
 "10.1038/s41551-025-01598-z",   # BioPathNet
}

# SOTA 可对比性三档判据，作用在已抽取的 sota 字段文本上
RE_ST_NOCMP = re.compile(
    r"无可对比 ?SOTA|无跨方法(基线)?(定量)?对比|未能可靠抽取|需人工核表|"
    r"未给出跨方法定量对比|未抽到跨方法|不存在单一的|无法解析|无法可靠抽取|"
    r"不提供可超越|非单一 ?SOTA 竞赛|不提供跨方法 ?SOTA 排名")
RE_ST_NUM = re.compile(r"\d+\.\d{1,4}|\d{1,3}(\.\d)?\s?%")
RE_ST_CMP = re.compile(
    r"(vs\.?|→|优于|超[过出]?|高于|低于|不如|仅\s?\d|领先|提升|降低|改善|减少|"
    r"次优|最佳|基线|对照|对比|较\s|相比|反超|持平|排名第|第一|倍)")

# 出版社前缀 → 名称，手动下载清单按此分组
PUBLISHER = {'10.1109':'IEEE','10.1038':'Nature','10.1126':'Science','10.1016':'Elsevier',
             '10.1093':'OUP','10.1002':'Wiley','10.1158':'AACR','10.1136':'BMJ','10.1200':'ASCO',
             '10.1053':'Elsevier','10.1186':'BMC','10.1377':'HA','10.1073':'PNAS'}

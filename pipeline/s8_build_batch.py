# -*- coding: utf-8 -*-
"""构建 batch2/ 交付文件夹：仅含已抽取的 S/A/B 档论文 PDF + 汇总 xlsx。"""
import sys,os,json,shutil,re,collections; sys.path.insert(0,'/Users/jinge/Desktop/AIbuildAI/pipeline')
import config as C, common as m

OUT=f"{C.ROOT}/batch2"
PDFDIR=f"{OUT}/pdfs"
V=json.load(open(f"{C.DATA}/verdicts2.json"))
E=json.load(open(f"{C.DATA}/extracted.json"))
D={m.norm_doi(r['doi']):r for r in m.read_jsonl(f"{C.DATA}/fulltext_digest.jsonl")}
st=m.load_shards("fetch_state")

# 已抽取 且 入选 且 S/A/B 档
# XML 全文（EPMC JATS）剥离了表格与图注，抽出的信息不全，本批不纳入
def is_xml_source(doi):
    s=st.get(doi) or {}
    return s.get('src')=='epmc-xml' or (s.get('file') or '').lower().endswith('.xml')

rows=[]; skipped_xml=[]
for d,v in V.items():
    if v.get('v')!='入选' or d not in E: continue
    g=D.get(d,{})
    sc=m.repro_score(v,g,g.get('journal')); t=m.repro_tier(sc)
    if t not in ('S','A','B'): continue
    if is_xml_source(d):
        skipped_xml.append((t,d,(g.get('title') or '')[:60])); continue
    rows.append({'doi':d,'v':v,'g':g,'e':E[d],'score':sc,'tier':t})
if skipped_xml:
    print(f"排除 XML 来源 {len(skipped_xml)} 篇（信息不全）:")
    for t,d,ti in sorted(skipped_xml): print(f"   [{t}] {d}  {ti}")
rows.sort(key=lambda x:(-x['score']))

# 文件来源索引（fulltext 优先，隔离区兜底）
files={}
for dr in ('fulltext','papers','arxiv_隔离'):
    p=f"{C.ROOT}/{dr}"
    if os.path.isdir(p):
        for f in os.listdir(p): files.setdefault(f,(f"{p}/{f}",dr))

def safe(s,n=70):
    s=re.sub(r"[^\w一-鿿 .\-]", "_", re.sub(r"<[^>]+>","",str(s or "")))
    return re.sub(r"\s+"," ",s).strip()[:n].rstrip(". ")

os.makedirs(PDFDIR,exist_ok=True)
tier_n=collections.Counter(); copied=missing=[];copied=[];missing=[]
for i,r in enumerate(rows,1):
    tier_n[r['tier']]+=1
    idx=f"{r['tier']}{tier_n[r['tier']]:03d}"
    s=st.get(r['doi']) or {}
    src=files.get(s.get('file') or '')
    if not src:
        tail=r['doi'].split('/')[-1]
        src=next((v for k,v in files.items() if len(tail)>6 and tail[:20] in k),None)
    if not src:
        missing.append(r); r['pdf']=''; continue
    path,origin=src
    ext=os.path.splitext(path)[1].lower()
    name=f"{idx}_{safe(r['g'].get('title'))}{ext}"
    shutil.copyfile(path,f"{PDFDIR}/{name}")
    r['pdf']=name; r['origin']=origin
    copied.append(r)
print(f"S/A/B 已抽取 {len(rows)} 篇；复制 PDF {len(copied)}，缺文件 {len(missing)}")
print("  档位:",dict(tier_n))
print("  来源:",dict(collections.Counter(r.get('origin') for r in copied)))
json.dump([{k:v for k,v in r.items() if k not in ('g','v','e')} for r in rows],
          open('/tmp/batch2_rows.json','w'),ensure_ascii=False)

# ── 汇总 xlsx ──
wb=m.new_book(); ws=wb.create_sheet("batch2汇总")
cols=C.EXTRACT_COLUMNS+["复刻优先级","复刻分","基准公开","PDF 文件名"]
ws.append(cols)
DATA_RE=re.compile(r"(huggingface\.co/datasets|zenodo\.org|figshare\.com|kaggle\.com|physionet\.org|osf\.io|datadryad\.org|paperswithcode\.com)",re.I)
CODE_RE=re.compile(r"(github\.com|gitlab\.com|codeocean\.com)",re.I)
for i,r in enumerate(rows,1):
    g,v,e=r['g'],r['v'],r['e']
    lk=[x for x in (g.get('links') or []) if not re.match(r"openreview\.net",x,re.I)]
    dl=[x for x in lk if DATA_RE.search(x)]
    cl=[x for x in lk if CODE_RE.search(x)]+[x for x in lk if re.match(r"huggingface\.co/",x,re.I) and "/datasets" not in x.lower()]
    ws.append([i,g.get('title'),g.get('journal'),g.get('year'),g.get('field') or '',
        e.get('bench'),e.get('size'),"; ".join(dl[:3]),e.get('sota'),e.get('metric'),
        v.get('auto'),"; ".join(cl[:3]),f"https://doi.org/{r['doi']}",e.get('note'),
        r['tier'],r['score'],v.get('open'),r.get('pdf','')])
from openpyxl.styles import Font,PatternFill
for rr in ws.iter_rows(min_row=2):
    t=rr[14].value
    if t=='S':
        rr[14].font=Font(bold=True,color="C00000")
        f=PatternFill("solid",fgColor="FCE4D6")
        for c in rr: c.fill=f
    elif t=='A':
        f=PatternFill("solid",fgColor="FFF2CC")
        for c in rr: c.fill=f
m.style_sheet(ws,[5,58,24,6,14,30,40,44,60,36,9,42,40,46,10,8,9,50])

ws2=wb.create_sheet("字段说明")
ws2.append(["字段","含义"])
for a,b in [("复刻优先级","S/A/B/C 四档，由可自动化等级(40)+基准公开度(25)+SOTA标注(10)+期刊影响力+链接与公开基准数+头顶空间大(12)加权，再扣人评/湿实验/硬件依赖"),
 ("复刻分","上述加权总分，本表按此降序"),
 ("自动化等级","A+ 可执行验证(单元测试/Pass@k) / A 有ground truth的客观指标 / B 需LLM-as-judge / C 需人评·湿实验·硬件"),
 ("基准公开","是=有直达链接；部分=用公开基准但自建测试集受限；否=不公开(本表不含)"),
 ("Benchmark 规模","从 PDF 正文抽取的样本量/任务数/队列规模，抽不到则标注说明，未做推测"),
 ("论文报告的 SOTA","论文中可对比的具体数值，含对照方法名与数字；抽不到则明确标注"),
 ("评估指标 & 计算方式","指标名与计算/划分协议，含需注意的评测陷阱"),
 ("复刻备注","★数量表示推荐程度；⚠️标注需注意的限制（数据不公开、算力门槛、指标陷阱等）"),
 ("PDF 文件名","对应 pdfs/ 目录下的文件，前缀为 档位+序号")]:
    ws2.append([a,b])
m.style_sheet(ws2,[18,110])
wb.save(f"{OUT}/信息抽取batch2.xlsx")
print(f"→ {OUT}/信息抽取batch2.xlsx  {len(rows)} 行")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIBuildAI 论文发现 pipeline —— 统一入口

    python3 pipeline/run.py <阶段> [参数...]
    python3 pipeline/run.py status          # 全流程体检，看每步到哪了
    python3 pipeline/run.py --list          # 列出所有阶段

阶段（按顺序）:
    journals   S0 期刊清单        → 期刊清单_v2.xlsx
    harvest    S1 元数据拉取      → data/works_*.jsonl        [crossref|epmc|s2|jmlr|merge]
    screen1    S2 一轮筛选(标题+摘要) → 第一轮筛选结果.xlsx    [recall|triage|dump|save|export]
    fetch      S3 全文获取(只要官方版) → fulltext/
    audit      S3 版本审计+隔离非官方版 → data/cands.json + 下载脚本_*.js
    ingest     S3 归档手动下载的 PDF   → fulltext/
    extract    S4 全文信号抽取     → data/fulltext_digest.jsonl
    screen2    S5 二轮筛选+复刻优先级 → 第二轮筛选结果.xlsx   [dump|save|export]
    dedupe     S6 与既有 54 篇去重 → data/baseline_dois.json
    info       S7 信息抽取(14字段)  → 信息抽取_新增候选.xlsx   [dump|save|export]

判读环节（screen1/screen2/info 的 dump→save）是留给模型或人读的，
不在 pipeline 里假装自动化 —— dump 出批次，判完 save 回写，按 DOI 对齐。
"""
import os, sys, json, glob, argparse, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C, common as m

STAGES = {
    "journals": ("s0_journals", "S0 期刊清单"),
    "harvest":  ("s1_harvest",  "S1 元数据拉取"),
    "screen1":  ("s2_screen1",  "S2 一轮筛选(标题+摘要)"),
    "fetch":    ("s3_fetch",    "S3 全文获取(只要官方版)"),
    "audit":    ("s3_audit",    "S3 版本审计+隔离"),
    "ingest":   ("s3_ingest",   "S3 归档手动下载"),
    "extract":  ("s4_extract",  "S4 全文信号抽取"),
    "screen2":  ("s5_screen2",  "S5 二轮筛选+复刻优先级"),
    "dedupe":   ("s6_dedupe",   "S6 与既有语料去重"),
    "info":     ("s7_extract_info", "S7 信息抽取(14字段)"),
}

def _n(path):
    """文件行数/元素数，用于 status。"""
    if not os.path.exists(path):
        return None
    if path.endswith(".jsonl"):
        return sum(1 for ln in open(path, encoding="utf-8", errors="replace") if ln.strip())
    if path.endswith(".json"):
        try:
            return len(json.load(open(path, encoding="utf-8")))
        except Exception:
            return None
    return os.path.getsize(path)

def status():
    def mark(v, need=1):
        return "✓" if (v or 0) >= need else "·"
    print("═" * 74)
    print("  AIBuildAI 论文发现 pipeline —— 状态")
    print("═" * 74)

    nj = len(C.journals())
    print(f"{mark(nj)} S0 期刊清单        {nj:>7} 本  "
          f"{'(期刊清单_v2.xlsx 已出)' if os.path.exists(C.XLSX_JOURNALS) else '(xlsx 未生成)'}")

    wm = _n(f"{C.DATA}/works_merged.jsonl")
    parts = sum(_n(f"{C.DATA}/{f}") or 0 for f in os.listdir(C.DATA)
                if f.startswith("works_") and f.endswith(".jsonl") and "merged" not in f) \
        if os.path.isdir(C.DATA) else 0
    print(f"{mark(wm)} S1 元数据拉取      {wm or 0:>7} 篇  (分源合计 {parts})")

    cand = _n(f"{C.DATA}/candidates.jsonl")
    q = _n(f"{C.DATA}/review_queue.jsonl")
    V1 = json.load(open(f"{C.DATA}/verdicts.json", encoding="utf-8")) \
        if os.path.exists(f"{C.DATA}/verdicts.json") else {}
    # 一轮历史数据字段是 verdict，早期草稿是 v，两者都认
    c1 = collections.Counter((v.get("verdict") or v.get("v")) for v in V1.values())
    print(f"{mark(cand)} S2 一轮筛选        召回 {cand or 0:>5}  判读队列 {q or 0}  "
          f"已判 {len(V1)}  入选 {c1.get('入选',0)} 待定 {c1.get('待定',0)} 排除 {c1.get('排除',0)}")

    st = m.load_shards("fetch_state")
    okn = sum(1 for v in st.values() if v.get("ok"))
    srcs = collections.Counter(v.get("src") for v in st.values() if v.get("ok"))
    print(f"{mark(okn)} S3 全文获取        成功 {okn:>5} / 尝试 {len(st)}  "
          f"失败 {len(st)-okn}")
    if srcs:
        print(f"      来源: {dict(srcs.most_common())}")

    nft = len(glob.glob(f"{C.FULLTEXT}/*.pdf")) + len(glob.glob(f"{C.FULLTEXT}/*.xml"))
    nq = len(glob.glob(f"{C.QUARANTINE}/*")) if os.path.isdir(C.QUARANTINE) else 0
    ncand = _n(f"{C.DATA}/cands.json")
    print(f"{mark(nft)} S3 fulltext/       官方版 {nft:>5}  已隔离非官方 {nq}  待补 {ncand or 0}")

    dgn = _n(f"{C.DATA}/fulltext_digest.jsonl")
    print(f"{mark(dgn)} S4 信号抽取        {dgn or 0:>7} 篇")

    V2 = json.load(open(f"{C.DATA}/verdicts2.json", encoding="utf-8")) \
        if os.path.exists(f"{C.DATA}/verdicts2.json") else {}
    c2 = collections.Counter(v.get("v") for v in V2.values())
    # 自动化等级只统计入选（排除/待定的等级没有对标意义）
    ca = collections.Counter(v.get("auto") for v in V2.values() if v.get("v") == "入选")
    print(f"{mark(len(V2))} S5 二轮筛选        已判 {len(V2):>5}  "
          f"入选 {c2.get('入选',0)} 待定 {c2.get('待定',0)} 排除 {c2.get('排除',0)}  "
          f"| 入选自动化 A+{ca.get('A+',0)} A{ca.get('A',0)} "
          f"B{ca.get('B',0)} C{ca.get('C',0)}")
    if V2:
        dg = {m.norm_doi(r["doi"]): r for r in m.read_jsonl(f"{C.DATA}/fulltext_digest.jsonl", True)}
        tiers = collections.Counter(
            m.repro_tier(m.repro_score(v, dg.get(d, {}), (dg.get(d) or {}).get("journal")))
            for d, v in V2.items() if v.get("v") == "入选")
        print(f"      复刻优先级: S{tiers.get('S',0)} A{tiers.get('A',0)} "
              f"B{tiers.get('B',0)} C{tiers.get('C',0)}")

    nb = _n(f"{C.DATA}/baseline_dois.json")
    print(f"{mark(nb)} S6 去重基线        {nb or 0:>7} 个 DOI")

    ne = _n(f"{C.DATA}/extracted.json")
    sel2 = c2.get("入选", 0)
    print(f"{mark(ne)} S7 信息抽取        {ne or 0:>7} / {sel2} 篇入选已抽")

    print("─" * 74)
    for f in (C.XLSX_JOURNALS, C.XLSX_ROUND1, C.XLSX_ROUND2,
              f"{C.ROOT}/信息抽取_新增候选.xlsx"):
        e = os.path.exists(f)
        sz = f"{os.path.getsize(f)//1024}KB" if e else "-"
        print(f"  {'✓' if e else '·'} {os.path.basename(f):28s} {sz}")
    # 下一步建议
    print("─" * 74)
    if not wm:
        nxt = "run.py harvest crossref  然后 harvest epmc / s2 / merge"
    elif not cand:
        nxt = "run.py screen1 recall"
    elif len(V1) < (q or 0):
        nxt = f"run.py screen1 dump --batch N  →  判读  →  screen1 save --file ..."
    elif (ncand or 0) > 0:
        nxt = f"用 data/下载脚本_*.js 补 {ncand} 篇官方 PDF  →  run.py ingest  →  extract"
    elif len(V2) < (dgn or 0):
        nxt = "run.py screen2 dump --batch N  →  判读  →  screen2 save --file ..."
    elif (ne or 0) < sel2:
        nxt = "run.py info dump --batch N  →  读全文抽取  →  info save --file ..."
    else:
        nxt = "全流程已跑完；有新论文时从 harvest 重跑即可（增量）"
    print(f"  下一步: {nxt}")
    print("═" * 74)

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if sys.argv[1] == "--list":
        for k, (mod, desc) in STAGES.items():
            print(f"  {k:10s} {desc:26s} ({mod}.py)")
        return 0
    stage = sys.argv[1]
    if stage == "status":
        status()
        return 0
    if stage not in STAGES:
        print(f"未知阶段 {stage!r}。可用: status, {', '.join(STAGES)}", file=sys.stderr)
        return 2
    os.makedirs(C.DATA, exist_ok=True)
    os.makedirs(C.LOGS, exist_ok=True)
    mod = __import__(STAGES[stage][0])
    m.log(f"▶ {STAGES[stage][1]}  参数: {' '.join(sys.argv[2:]) or '(无)'}")
    rc = mod.main(sys.argv[2:])
    return 0 if rc is None or isinstance(rc, int) is False else 0

if __name__ == "__main__":
    sys.exit(main())

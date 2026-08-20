# -*- coding: utf-8 -*-
"""S2 第一轮筛选（标题 + 摘要）

三步，规则先把量压下来，人/模型只判读真正需要判读的：
  recall  关键词召回 + 打分            → data/candidates.jsonl
  triage  规则分流，自动排除明确不合格 → data/grp_*.jsonl + review_queue.jsonl
  dump    输出紧凑判读批次             → /tmp/w1_<n>.txt
  save    回写判读结论                 → data/verdicts.json
  export  出 xlsx                      → 第一轮筛选结果.xlsx

自动排除的类别都单独存 grp_*.jsonl 并在 xlsx 留抽样核查页，便于回查是否误杀。
用法: python3 run.py screen1 recall|triage|dump|save|export [...]
"""
import os, re, sys, json, argparse, collections
import config as C, common as m

AI_, BENCH_, STRONG_, NEG_ = (C.compiled(x) for x in (C.KW_AI, C.KW_BENCH, C.KW_STRONG, C.KW_NEG))

def hits(pats, t):
    return sorted({p.pattern for p in pats if p.search(t)})

def _vd(v):
    """判定字段兼容：历史数据用 verdict，早期草稿用 v。"""
    return (v or {}).get("verdict") or (v or {}).get("v") or ""

def _rs(v):
    return (v or {}).get("reason") or (v or {}).get("why") or ""

# ───────────────────────── recall ─────────────────────────
def recall():
    src = f"{C.DATA}/works_merged.jsonl"
    if not os.path.exists(src):
        m.die(f"缺少 {src}，先跑 harvest merge")
    out, dropped, total = [], 0, 0
    w = C.SCORE1
    for r in m.iter_jsonl(src):
        total += 1
        ti = (r.get("title") or "").strip()
        ab = (r.get("abstract") or "").strip()
        if not ti or C.RE_DROP_TITLE.match(ti) or C.RE_NUMBERED_TITLE.match(ti):
            dropped += 1
            continue
        t = f"{ti} . {ab}"
        ai, bn, st, ng = hits(AI_, t), hits(BENCH_, t), hits(STRONG_, t), hits(NEG_, t)
        if not ai:                       # 无任何 AI 信号 → 出局
            continue
        ai_ti, st_ti = hits(AI_, ti), hits(STRONG_, ti)
        prio = r.get("journal") in C.PRIORITY_JOURNALS
        score = (len(ai) * w["ai"] + len(bn) * w["bench"] + len(st) * w["strong"]
                 + len(ai_ti) * w["ai_title"] + len(st_ti) * w["strong_title"]
                 + len(ng) * w["neg"] + (w["has_abstract"] if ab else 0)
                 + (w["priority_journal"] if prio else 0))
        keep = {k: r.get(k) for k in ("doi", "title", "abstract", "journal", "jtype", "field",
                                      "jcr", "date", "year", "cited", "oa", "pdf", "authors",
                                      "pub", "src")}
        keep.update({"score": round(score, 2), "n_ai": len(ai), "n_bench": len(bn),
                     "n_strong": len(st), "n_neg": len(ng), "prio": prio, "has_abs": bool(ab),
                     "kw_strong": ";".join(x.replace("\\b", "") for x in st[:6]),
                     "kw_neg": ";".join(x.replace("\\b", "") for x in ng[:6])})
        out.append(keep)
    out.sort(key=lambda x: -x["score"])
    m.write_jsonl(f"{C.DATA}/candidates.jsonl", out)
    m.log(f"总库 {total} 篇 → 剔除非研究类 {dropped} → 关键词召回 {len(out)} "
          f"({len(out)/max(total,1)*100:.1f}%)，有摘要 {sum(1 for r in out if r['has_abs'])}")
    for th in (25, 20, 16, 13, 11, 9, 7, 5):
        print(f"    score≥{th:2d}: {sum(1 for r in out if r['score'] >= th):6d}")
    return len(out)

# ───────────────────────── triage ─────────────────────────
def classify(r):
    """返回 (分组, 理由)。前 4 类自动排除，review 进判读队列。"""
    ti, ab = (r.get("title") or ""), (r.get("abstract") or "")
    # DOI 段先判：Nature 新闻段与 ASH 年会摘要段，正文关键词拦不住（它们也谈 AI agent）
    if C.RE_NONPAPER_DOI.search(r.get("doi") or ""):
        return "auto_conf", "非论文体裁（Nature 新闻段 / 会议摘要段 DOI）"
    if C.RE_CONF_ABS.match(ab) or C.RE_CONF_TITLE.match(ti) or C.RE_ALLCAP_TITLE.match(ti.strip()):
        return "auto_conf", "会议摘要（无全文/无可复现基准）"
    if C.RE_SURVEY_STRICT.search(ti):
        return "auto_survey", "综述/survey/tutorial（无自研 benchmark 与 SOTA）"
    # 控制论假阳性：期刊 + multi-agent + 控制术语，且无 LLM/benchmark 反证
    if (r.get("journal") in C.CTRL_JOURNALS and re.search(r"multi-?agent|\bmas\b", ti, re.I)
            and C.RE_CTRL2.search(ti) and not C.RE_CTRL2_RESCUE.search(ti)):
        return "auto_control", "控制论类（期刊+multi-agent控制术语，无公开 benchmark/SOTA）"
    if C.RE_CTRL.search(ti) and not C.RE_CTRL_RESCUE.search(ti):
        return "auto_control", "控制论类（multi-agent 指控制系统，非 LLM 智能体）"
    if r.get("journal") == "IEEE Access":
        return "ieee_access", "IEEE Access（单独分组，待定）"
    if r["n_strong"] >= 2:
        return "review", "强信号≥2"
    if r["n_strong"] >= 1 and r["has_abs"]:
        return "review", "强信号≥1且有摘要"
    if r["prio"] and r["n_strong"] >= 1:
        return "review", "高相关期刊+强信号"
    if r["prio"] and r["n_ai"] >= 4 and r["n_bench"] >= 4:
        return "review", "高相关期刊+密集AI/评测信号"
    return "auto_weak", "关键词信号不足（无 agent/benchmark 等强信号）"

GROUP_NAME = {"review": "→ 逐条判读", "auto_conf": "自动排除:会议摘要",
              "auto_survey": "自动排除:综述", "ieee_access": "单独分组:IEEE Access",
              "auto_weak": "自动排除:信号不足", "auto_control": "自动排除:控制论类"}

def triage():
    rows = m.read_jsonl(f"{C.DATA}/candidates.jsonl")
    if not rows:
        m.die("缺少 candidates.jsonl，先跑 screen1 recall")
    buckets = {}
    for r in rows:
        g, why = classify(r)
        r["group"], r["group_why"] = g, why
        buckets.setdefault(g, []).append(r)
    for g, rs in buckets.items():
        rs.sort(key=lambda x: -x["score"])
        m.write_jsonl(f"{C.DATA}/grp_{g}.jsonl", rs)
    q = buckets.get("review", [])
    m.write_jsonl(f"{C.DATA}/review_queue.jsonl", q)
    m.log(f"候选池 {len(rows)} 分流：")
    for g in ("review", "ieee_access", "auto_survey", "auto_conf", "auto_control", "auto_weak"):
        if g in buckets:
            print(f"    {GROUP_NAME[g]:26s} {len(buckets[g]):6d}")
    print(f"  判读队列 {len(q)} 篇，有摘要 {sum(1 for r in q if r['has_abs'])}")
    return len(q)

# ───────────────────────── dump / save ─────────────────────────
def _clip(s, n):
    s = re.sub(r"\s+", " ", str(s or ""))
    return s[:n]

def dump(batch, size, out):
    """输出一批未判读的记录，行首 #i@doi —— save 按 DOI 回写，不依赖行号。"""
    q = m.read_jsonl(f"{C.DATA}/review_queue.jsonl")
    V = json.load(open(f"{C.DATA}/verdicts.json", encoding="utf-8")) \
        if os.path.exists(f"{C.DATA}/verdicts.json") else {}
    todo = [r for r in q if m.norm_doi(r.get("doi")) not in V]
    seg = todo[batch * size:(batch + 1) * size]
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"### 待判 {len(todo)} / 队列 {len(q)}；本批 {batch*size}~{batch*size+len(seg)-1}\n")
        f.write("### 回写格式: #i@doi|判定(入选/待定/排除)|置信(高/中/低)|理由\n")
        for i, r in enumerate(seg):
            f.write(f"#{batch*size+i}@{m.norm_doi(r.get('doi'))}|{_clip(r.get('journal'),22)} "
                    f"{r.get('year')} IF{r.get('jcr')}|{_clip(r.get('title'),110)}\n")
            if r.get("abstract"):
                f.write(f"  ABS: {_clip(r['abstract'], 700)}\n")
            f.write(f"  信号: 强{r['n_strong']} AI{r['n_ai']} 评测{r['n_bench']} 负{r['n_neg']}"
                    f"  {r.get('kw_strong','')}\n")
    m.log(f"批 {batch}: {len(seg)} 条 → {out}（待判总数 {len(todo)}）")
    return out

def save(path):
    """读判读结论文件：每行 `#i@doi|判定|置信|理由`，判定 ∈ 入选/待定/排除。

    落盘沿用既有 verdicts.json 字段名 verdict/conf/reason（3023 条历史判读靠它）。
    """
    p = f"{C.DATA}/verdicts.json"
    V = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    n = 0
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln.startswith("#") or "@" not in ln:
            continue
        head, _, rest = ln.partition("|")
        doi = m.norm_doi(head.split("@", 1)[1])
        c = rest.split("|")
        if not doi or not c or not c[0].strip():
            continue
        V[doi] = {"verdict": c[0].strip(),
                  "conf": c[1].strip() if len(c) > 1 else "",
                  "reason": c[2].strip() if len(c) > 2 else ""}
        n += 1
    json.dump(V, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    m.log(f"回写 {n} 条，累计判定 {len(V)}")
    print("  分布:", dict(collections.Counter(_vd(v) for v in V.values())))
    return n

# ───────────────────────── export ─────────────────────────
def export():
    q = m.read_jsonl(f"{C.DATA}/review_queue.jsonl")
    V = json.load(open(f"{C.DATA}/verdicts.json", encoding="utf-8")) \
        if os.path.exists(f"{C.DATA}/verdicts.json") else {}
    base = set(json.load(open(f"{C.DATA}/baseline_dois.json", encoding="utf-8"))) \
        if os.path.exists(f"{C.DATA}/baseline_dois.json") else set()
    base = {m.norm_doi(x) for x in base}
    cols = ["#", "判定", "置信", "★重复", "论文标题", "期刊", "年", "JCR IF", "领域",
            "强信号", "AI信号", "评测信号", "负向信号", "命中强关键词", "判定理由",
            "DOI", "DOI 链接", "摘要"]
    wb = m.new_book()
    by = {"入选": [], "待定": [], "排除": []}
    for r in q:
        d = m.norm_doi(r.get("doi"))
        v = V.get(d)
        if not v or not _vd(v):
            continue
        by.setdefault(_vd(v), []).append((r, v, d))
    for name in ("入选", "待定", "排除"):
        rows = by.get(name, [])
        ws = wb.create_sheet(f"{name}({len(rows)})")
        ws.append(cols)
        for i, (r, v, d) in enumerate(sorted(rows, key=lambda x: -x[0]["score"]), 1):
            ws.append([i, _vd(v), v.get("conf", ""), "★重复" if d in base else "", r.get("title"), r.get("journal"),
                       r.get("year"), r.get("jcr"), r.get("field"), r["n_strong"], r["n_ai"],
                       r["n_bench"], r["n_neg"], r.get("kw_strong"), _rs(v),
                       d, f"https://doi.org/{d}" if d else "", _clip(r.get("abstract"), 1200)])
        m.style_sheet(ws, [5, 8, 6, 8, 62, 26, 6, 8, 16, 7, 7, 8, 8, 30, 34, 30, 40, 80])

    # 自动排除抽样，供核查是否误杀
    ws = wb.create_sheet("自动排除抽样(核查用)")
    ws.append(["分组", "理由", "论文标题", "期刊", "年", "score"])
    for g in ("auto_survey", "auto_conf", "auto_control", "auto_weak", "ieee_access"):
        rs = m.read_jsonl(f"{C.DATA}/grp_{g}.jsonl", quiet=True)
        for r in rs[:40]:
            ws.append([g, r.get("group_why"), r.get("title"), r.get("journal"),
                       r.get("year"), r.get("score")])
    m.style_sheet(ws, [16, 40, 62, 26, 6, 8])

    ws = wb.create_sheet("漏斗统计")
    ws.append(["阶段", "篇数", "说明"])
    cand = sum(1 for _ in m.iter_jsonl(f"{C.DATA}/candidates.jsonl"))
    grp = {g: sum(1 for _ in m.iter_jsonl(f"{C.DATA}/grp_{g}.jsonl"))
           for g in ("auto_survey", "auto_conf", "auto_control", "auto_weak", "ieee_access")}
    for k, v, note in [("关键词召回", cand, "命中 ≥1 AI 信号"),
                       ("规则自动排除", sum(grp.values()), "综述/会议摘要/控制论/信号不足/IEEE Access"),
                       ("进入判读队列", len(q), "逐条读标题+摘要"),
                       ("已判定", len(V), ""),
                       ("入选", len(by.get("入选", [])), "进入第二轮全文核查"),
                       ("待定", len(by.get("待定", [])), "信息不足，需看全文"),
                       ("排除", len(by.get("排除", [])), "")]:
        ws.append([k, v, note])
    for g, n in grp.items():
        ws.append([f"  └ {GROUP_NAME[g]}", n, ""])
    m.style_sheet(ws, [26, 10, 52])

    ws = wb.create_sheet("入选期刊分布")
    ws.append(["期刊", "入选数"])
    for k, v in collections.Counter(r.get("journal") for r, _, _ in by.get("入选", [])).most_common():
        ws.append([k, v])
    m.style_sheet(ws, [52, 10])
    wb.save(C.XLSX_ROUND1)
    m.log(f"入选{len(by.get('入选',[]))} 待定{len(by.get('待定',[]))} 排除{len(by.get('排除',[]))}"
          f" → {C.XLSX_ROUND1}")

# ───────────────────────── 入口 ─────────────────────────
def main(argv):
    ap = argparse.ArgumentParser(prog="screen1")
    ap.add_argument("step", choices=["recall", "triage", "dump", "save", "export", "all"])
    ap.add_argument("--batch", type=int, default=0)
    ap.add_argument("--size", type=int, default=120)
    ap.add_argument("--out", default="/tmp/w1_batch.txt")
    ap.add_argument("--file", help="save 用：判读结论文件")
    a = ap.parse_args(argv)
    if a.step in ("recall", "all"):
        recall()
    if a.step in ("triage", "all"):
        triage()
    if a.step == "dump":
        dump(a.batch, a.size, a.out)
    if a.step == "save":
        if not a.file:
            m.die("save 需要 --file")
        save(a.file)
    if a.step in ("export", "all"):
        export()

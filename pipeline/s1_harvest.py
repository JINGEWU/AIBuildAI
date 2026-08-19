# -*- coding: utf-8 -*-
"""S1 元数据拉取：按期刊清单抓 2025-2026 全部论文 → data/works_*.jsonl

多源互补（单一源覆盖不全）：
  crossref  骨架：全，但摘要覆盖差（IEEE/Elsevier/Cell Press 近 0%）
  epmc      生医刊自带摘要，免费无额度
  s2        用 DOI 批量补摘要（500/批）
  jmlr      JMLR/TMLR 官网爬取（不进 Crossref）
支持 --shard i/N 并行；每本刊完成即落盘，可随时中断续跑。
用法: python3 run.py harvest crossref|epmc|s2|jmlr|merge [--shard 0/6] [--limit N]
"""
import os, re, sys, json, argparse, urllib.parse, collections
import config as C, common as m

SEL_CR = "DOI,title,abstract,issued,container-title,author,type,URL,subject"

def strip_jats(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()

def rec(src, j, **kw):
    """统一记录格式——后续所有阶段都依赖这些字段名。"""
    r = {"src": src, "journal": j.get("name"), "jtype": j.get("jtype"),
         "field": j.get("field", ""), "jcr": j.get("jcr"), "pub": j.get("pub", ""),
         "issn": j.get("issn"), "doi": "", "title": "", "abstract": "", "date": None,
         "year": None, "cited": None, "oa": None, "pdf": None, "authors": None}
    r.update(kw)
    r["doi"] = m.norm_doi(r["doi"])
    return r

# ───────────────────────── Crossref ─────────────────────────
def pull_crossref(j, cap=None):
    issn = j.get("issn")
    if not issn:
        return []
    out, cur = [], "*"
    while True:
        u = (C.API["crossref"].format(issn=issn) +
             f"?filter=from-pub-date:{C.YEARS[0]}-01-01,until-pub-date:{C.YEARS[1]}-12-31"
             f"&rows=500&cursor={urllib.parse.quote(cur)}&select={SEL_CR}&mailto={C.MAILTO}")
        d = m.http_json(u, bucket="crossref", timeout=90, retries=5)
        if not d:
            break
        msg = d.get("message", {})
        items = msg.get("items", [])
        for it in items:
            iss = (it.get("issued", {}).get("date-parts") or [[None]])[0]
            yr = iss[0] if iss else None
            if yr and not (C.YEARS[0] <= yr <= C.YEARS[1]):
                continue
            out.append(rec("crossref", j,
                doi=it.get("DOI", ""),
                title=strip_jats((it.get("title") or [""])[0]),
                abstract=strip_jats(it.get("abstract")),
                year=yr, date="-".join(str(x) for x in iss if x),
                pdf=it.get("URL"), pubtype=(it.get("type") or "").lower(),
                authors=len(it.get("author") or [])))
        cur = msg.get("next-cursor")
        if not cur or not items or (cap and len(out) >= cap):
            break
    return out

# ───────────────────────── Europe PMC ─────────────────────────
def pull_epmc(j, cap=None):
    issn = j.get("issn")
    if not issn:
        return []
    out, cm = [], "*"
    q = f'ISSN:"{issn}" AND (FIRST_PDATE:[{C.YEARS[0]}-01-01 TO {C.YEARS[1]}-12-31])'
    while True:
        u = (f"{C.API['epmc']}?query={urllib.parse.quote(q)}&format=json&pageSize=500"
             f"&resultType=core&cursorMark={urllib.parse.quote(cm)}")
        d = m.http_json(u, bucket="epmc", timeout=90, retries=5)
        if not d:
            break
        res = d.get("resultList", {}).get("result", [])
        for r in res:
            yr = r.get("pubYear")
            out.append(rec("epmc", j,
                doi=r.get("doi") or "", title=r.get("title"),
                abstract=strip_jats(r.get("abstractText")),
                date=r.get("firstPublicationDate"),
                year=int(yr) if (yr or "").isdigit() else None,
                cited=r.get("citedByCount"), oa=r.get("isOpenAccess") == "Y",
                pubtype=(r.get("pubType") or "").lower(),
                pmcid=r.get("pmcid"), pmid=r.get("pmid")))
        nxt = d.get("nextCursorMark")
        if not nxt or nxt == cm or not res or (cap and len(out) >= cap):
            break
        cm = nxt
    return out

# ───────────────────────── Semantic Scholar 补摘要 ─────────────────────────
def enrich_s2(dois, shard=None):
    """POST /paper/batch，500 DOI 一批，补 abstract 与 openAccessPdf。"""
    st = m.State("state_s2", shard)
    out_path = f"{C.DATA}/abs_s2{'_%dof%d' % shard if shard else ''}.jsonl"
    todo = [d for d in dois if d not in st and m.mine(d, shard)]
    m.log(f"S2 待补 {len(todo)} / 总 {len(dois)}")
    f = open(out_path, "a", encoding="utf-8")
    for i in range(0, len(todo), 500):
        chunk = todo[i:i + 500]
        body = json.dumps({"ids": [f"DOI:{d}" for d in chunk]}).encode()
        r = m.http(C.API["s2_batch"] + "?fields=abstract,openAccessPdf,title,year",
                   bucket="s2", data=body,
                   headers={"Content-Type": "application/json"}, timeout=90, retries=4)
        if not r:
            m.log(f"  批 {i//500} 失败，跳过")
            continue
        try:
            arr = json.loads(r)
        except Exception:
            continue
        got = 0
        for d, o in zip(chunk, arr or []):
            st[d] = {"ok": bool(o)}
            if o and o.get("abstract"):
                f.write(json.dumps({"doi": d, "abstract": o["abstract"],
                                    "pdf": (o.get("openAccessPdf") or {}).get("url")},
                                   ensure_ascii=False) + "\n")
                got += 1
        f.flush(); st.flush()
        m.log(f"  批 {i//500+1}/{(len(todo)+499)//500}  补到摘要 {got}/{len(chunk)}")
    f.close(); st.flush()
    return out_path

# ───────────────────────── JMLR / TMLR ─────────────────────────
def pull_jmlr():
    """JMLR/TMLR 不进 Crossref，从官网列表页爬。TMLR 只有标题（OpenReview 已封）。"""
    out = []
    for name, url in [("Journal of Machine Learning Research", "https://jmlr.org/papers/"),
                      ("Transactions on Machine Learning Research", "https://jmlr.org/tmlr/papers/")]:
        t = m.http(url, bucket="publisher", timeout=60)
        if not t:
            m.log(f"  {name} 抓取失败")
            continue
        # 注意 <dd> 无闭合标签，用 lookahead 到 </dl>
        pairs = re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)(?=</dl>|<dt>)", t, re.S)
        j = {"name": name, "jtype": "research", "field": "ML", "jcr": None, "pub": "JMLR", "issn": None}
        for dt, dd in pairs:
            ti = re.sub(r"<[^>]+>", " ", dt)
            ti = re.sub(r"\s+", " ", ti).strip()
            yr = re.search(r"\b(20\d\d)\b", dd)
            y = int(yr.group(1)) if yr else None
            if not ti or (y and not (C.YEARS[0] <= y <= C.YEARS[1])):
                continue
            link = re.search(r'href="([^"]+)"', dd)
            out.append(rec("jmlr", j, title=ti, year=y,
                           pdf=urllib.parse.urljoin(url, link.group(1)) if link else None))
        m.log(f"  {name}: {len(out)} 篇累计")
    m.write_jsonl(f"{C.DATA}/works_jmlr.jsonl", out)
    return out

# ───────────────────────── merge ─────────────────────────
def merge_all():
    """合并所有 works_*.jsonl + S2 摘要 → works_merged.jsonl（DOI 去重，摘要优先保留）。"""
    abs_map = {}
    for f in sorted(os.listdir(C.DATA)):
        if f.startswith("abs_s2") and f.endswith(".jsonl"):
            for r in m.iter_jsonl(f"{C.DATA}/{f}"):
                if r.get("abstract"):
                    abs_map[m.norm_doi(r["doi"])] = r["abstract"]
    m.log(f"S2 摘要池 {len(abs_map)}")

    best, no_doi = {}, []
    files = [f for f in sorted(os.listdir(C.DATA))
             if f.startswith("works_") and f.endswith(".jsonl") and "merged" not in f]
    for f in files:
        n = 0
        for r in m.iter_jsonl(f"{C.DATA}/{f}"):
            n += 1
            d = m.norm_doi(r.get("doi"))
            if not d:
                no_doi.append(r); continue
            cur = best.get(d)
            # 保留信息最全的那条：有摘要 > 无摘要
            if cur is None or (not cur.get("abstract") and r.get("abstract")):
                best[d] = r
            elif cur is not None:
                for k in ("abstract", "cited", "oa", "pdf", "pmcid", "year", "date"):
                    if not cur.get(k) and r.get(k):
                        cur[k] = r[k]
        m.log(f"  {f}: {n}")
    for d, r in best.items():
        if not r.get("abstract") and d in abs_map:
            r["abstract"] = abs_map[d]
    rows = list(best.values()) + no_doi
    n = m.write_jsonl(f"{C.DATA}/works_merged.jsonl", rows)
    has = sum(1 for r in rows if r.get("abstract"))
    m.log(f"合并 {n} 篇（DOI 去重后 {len(best)}，无 DOI {len(no_doi)}）"
          f"  有摘要 {has} ({has/max(n,1)*100:.1f}%)")
    print("  期刊 Top10:", collections.Counter(r.get("journal") for r in rows).most_common(10))
    return n

# ───────────────────────── 入口 ─────────────────────────
def main(argv):
    ap = argparse.ArgumentParser(prog="harvest")
    ap.add_argument("source", choices=["crossref", "epmc", "s2", "jmlr", "merge"])
    ap.add_argument("--shard", help="i/N 分片并行")
    ap.add_argument("--limit", type=int, help="只跑前 N 本刊（调试用）")
    a = ap.parse_args(argv)
    shard = m.parse_shard(a.shard)

    if a.source == "merge":
        return merge_all()
    if a.source == "jmlr":
        return pull_jmlr()
    if a.source == "s2":
        dois = [m.norm_doi(r["doi"]) for r in m.iter_jsonl(f"{C.DATA}/works_merged.jsonl")
                if r.get("doi") and not r.get("abstract")]
        return enrich_s2(sorted(set(dois)), shard)

    puller = {"crossref": pull_crossref, "epmc": pull_epmc}[a.source]
    # 刊型字段实际取值是 研究刊/综述刊；综述刊无自研 benchmark，不抓
    js = [j for j in C.journals()
          if j.get("issn") and j.get("jtype") == "研究刊"
          and j.get("name") not in C.JOURNAL_BLOCKLIST]
    if a.limit:
        js = js[:a.limit]
    tag = f"{a.source}_{shard[0]}of{shard[1]}" if shard else a.source
    st = m.State(f"state_{tag}")
    out = f"{C.DATA}/works_{tag}.jsonl"
    mine = [j for j in js if m.mine(j["issn"], shard)]
    m.log(f"{a.source}: 本片 {len(mine)}/{len(js)} 本刊，已完成 {len(st)}")
    f = open(out, "a", encoding="utf-8")
    for i, j in enumerate(mine, 1):
        k = j["issn"]
        if k in st:
            continue
        rows = puller(j)
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush()
        st[k] = {"n": len(rows), "name": j["name"]}
        st.flush()
        m.log(f"[{i}/{len(mine)}] {j['name'][:44]:44s} {len(rows):5d} 篇")
    f.close(); st.flush()
    tot = sum(v.get("n", 0) for v in st.d.values())
    m.log(f"{a.source} 完成：{len(st)} 本刊 / {tot} 篇 → {out}")

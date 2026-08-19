# -*- coding: utf-8 -*-
"""S3 全文获取 —— 只要出版社官方版

源顺序（全部排除 config.RE_BAD_HOST 里的预印本仓储）：
  1 unpaywall  best_oa_location / oa_locations，host_type=publisher 优先
  2 publisher  出版社页面直取；nature.com 需 cookie 会话（303 → idp 授权环）
  3 epmc       OA 子集的 fullTextPDF / fullTextXML
  4 arxiv      仅在 --allow-arxiv 时启用；产物会被 S3 audit 判为非官方版并隔离

拿不到的进「待手动下载」清单，配合 audit 生成的浏览器脚本用机构权限补。
支持 --shard i/N 并行；state 按 DOI 记录，可随时中断续跑。
用法: python3 run.py fetch [--shard 0/5] [--limit N] [--allow-arxiv] [--cookies ~/cookies.txt]
"""
import os, re, sys, json, argparse, http.cookiejar, urllib.request, urllib.parse, collections
import config as C, common as m

# ───────────────────────── 目标清单 ─────────────────────────
def targets():
    """第一轮入选 + 待定 = 需要看全文的。优先读 xlsx（用户可能手工调过），退回 verdicts。"""
    rows, seen = [], set()
    for xl in (f"{C.ROOT}/batch1_screen1.xlsx", C.XLSX_ROUND1):
        if not os.path.exists(xl):
            continue
        try:
            import openpyxl
            wb = openpyxl.load_workbook(xl, read_only=True, data_only=True)
        except Exception as e:
            m.log(f"  读 {os.path.basename(xl)} 失败: {e}")
            continue
        for ws in wb:
            if not (ws.title.startswith("入选") or ws.title.startswith("待定")):
                continue
            it = ws.iter_rows(values_only=True)
            hdr = [str(x or "") for x in next(it, [])]
            def col(*names):
                for n in names:
                    if n in hdr:
                        return hdr.index(n)
                return None
            ci = {k: col(*v) for k, v in {
                "doi": ("DOI",), "title": ("论文标题", "标题"), "journal": ("期刊",),
                "year": ("年",), "jcr": ("JCR IF", "IF"), "prio": ("优先级",)}.items()}
            if ci["doi"] is None:
                continue
            for r in it:
                d = m.norm_doi(r[ci["doi"]] if ci["doi"] < len(r) else None)
                if not d or d in seen:
                    continue
                seen.add(d)
                g = lambda k: (r[ci[k]] if ci[k] is not None and ci[k] < len(r) else None)
                rows.append({"doi": d, "title": g("title"), "journal": g("journal"),
                             "year": g("year"), "jcr": g("jcr"), "prio": g("prio")})
        m.log(f"  {os.path.basename(xl)} → 累计 {len(rows)} 篇")
    return rows

# ───────────────────────── 源 ─────────────────────────
def _save(url, path, bucket, opener=None):
    b = m.http(url, bucket=bucket, binary=True, timeout=120, retries=2, opener=opener)
    if not b or len(b) < C.MIN_PDF_BYTES:
        return False
    if b[:5] != b"%PDF-":
        return False
    open(path, "wb").write(b)
    return True

def s_unpaywall(doi, rec, base, opener=None):
    d = m.http_json(C.API["unpaywall"].format(doi=urllib.parse.quote(doi)) + f"?email={C.MAILTO}",
                    bucket="unpaywall", timeout=45)
    if not d:
        return None
    locs = [d.get("best_oa_location")] + (d.get("oa_locations") or [])
    # 出版社托管的排前面，仓储版排后面
    locs = [l for l in locs if l and l.get("url_for_pdf")]
    locs.sort(key=lambda l: 0 if l.get("host_type") == "publisher" else 1)
    for l in locs:
        u = l["url_for_pdf"]
        if C.RE_BAD_HOST.search(u):          # 预印本仓储直接跳过
            continue
        p = f"{base}.pdf"
        if _save(u, p, "publisher", opener):
            return p, f"unpaywall:{l.get('host_type')}"
    return None

def s_publisher(doi, rec, base, opener=None):
    """出版社页面。nature.com 的 303 授权环需要 cookie jar 才能拿到 PDF。"""
    pre = doi.split("/")[0]
    urls = []
    if pre == "10.1038":
        sfx = doi.split("/", 1)[1]
        urls = [f"https://www.nature.com/articles/{sfx}.pdf"]
    elif pre in ("10.1126",):
        urls = [f"https://www.science.org/doi/pdf/{doi}"]
    elif pre in ("10.1093",):
        urls = [f"https://academic.oup.com/article-pdf/doi/{doi}"]
    urls.append(f"https://doi.org/{doi}")
    op = opener or urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    for u in urls:
        p = f"{base}.pdf"
        if _save(u, p, "publisher", op):
            return p, "publisher"
    return None

def s_epmc(doi, rec, base, opener=None):
    d = m.http_json(f"{C.API['epmc']}?query=DOI:%22{urllib.parse.quote(doi)}%22"
                    f"&format=json&resultType=core&pageSize=1", bucket="epmc", timeout=45)
    res = ((d or {}).get("resultList") or {}).get("result") or []
    pmcid = (res[0].get("pmcid") if res else None)
    if not pmcid:
        return None
    p = f"{base}.pdf"
    if _save(C.API["epmc_pdf"].format(pmcid=pmcid), p, "epmc", opener):
        return p, "epmc"
    x = m.http(C.API["epmc_xml"].format(pmcid=pmcid), bucket="epmc", timeout=90)
    if x and "<article" in x:
        px = f"{base}.xml"
        open(px, "w", encoding="utf-8").write(x)
        return px, "epmc-xml"
    return None

def _wset(s):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower())) - {
        "the", "a", "an", "of", "for", "and", "with", "in", "on", "to", "via"}

def s_arxiv(doi, rec, base, opener=None):
    """长标题带标点会让 ti:"..." 查空，改用词片段 + 词集重叠兜底。"""
    ti = re.sub(r"<[^>]+>", "", rec.get("title") or "").strip().rstrip(".")
    clean = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 ]", " ", ti)).strip()
    w = clean.split()
    if len(w) < 3:
        return None
    tw = _wset(ti)
    frags = [" ".join(w[:8]), " ".join(w[1:8]), " ".join(w[-7:])]
    for fr in frags:
        q = 'ti:"' + fr + '"'
        x = m.http(f"{C.API['arxiv']}?search_query={urllib.parse.quote(q)}&max_results=8",
                   bucket="arxiv", timeout=60)
        if not x:
            continue
        for e in re.findall(r"<entry>(.*?)</entry>", x, re.S):
            mt = re.search(r"<title>(.*?)</title>", e, re.S)
            if not mt:
                continue
            at = re.sub(r"\s+", " ", mt.group(1)).strip()
            aw = _wset(at)
            if not aw:
                continue
            na = re.sub(r"[^a-z0-9]", "", at.lower())
            nt = re.sub(r"[^a-z0-9]", "", ti.lower())
            k = min(60, len(na), len(nt))
            ov = len(aw & tw) / max(1, min(len(aw), len(tw)))
            if (k > 20 and na[:k] == nt[:k]) or nt[:50] in na or na[:50] in nt or ov >= 0.75:
                mid = re.search(r"<id>https?://arxiv\.org/abs/([^<]+)</id>", e)
                if not mid:
                    continue
                p = f"{base}.pdf"
                if _save(f"https://arxiv.org/pdf/{mid.group(1)}", p, "arxiv", opener):
                    return p, "arxiv"
    return None

OFFICIAL_SOURCES = [s_unpaywall, s_publisher, s_epmc]

# ───────────────────────── 主流程 ─────────────────────────
fname = m.fname   # 命名规则收在 common，S3 抓取与 S3 归档必须一致

def main(argv):
    ap = argparse.ArgumentParser(prog="fetch")
    ap.add_argument("--shard")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--allow-arxiv", action="store_true",
                    help="允许 arXiv 兜底（产物非官方版，audit 会隔离）")
    ap.add_argument("--cookies", help="浏览器导出的 cookies.txt（机构订阅身份）")
    ap.add_argument("--only", help="只跑某个 DOI 前缀，如 10.1109")
    ap.add_argument("--retry-failed", action="store_true", help="重试此前失败的")
    a = ap.parse_args(argv)
    shard = m.parse_shard(a.shard)
    os.makedirs(C.FULLTEXT, exist_ok=True)

    opener = None
    if a.cookies:
        cj = http.cookiejar.MozillaCookieJar(os.path.expanduser(a.cookies))
        try:
            cj.load(ignore_discard=True, ignore_expires=True)
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            m.log(f"已载入 cookie {len(cj)} 条")
        except Exception as e:
            m.die(f"cookies 载入失败: {e}")

    srcs = OFFICIAL_SOURCES + ([s_arxiv] if a.allow_arxiv else [])
    tg = targets()
    if a.only:
        tg = [r for r in tg if r["doi"].startswith(a.only)]
    st = m.State("fetch_state", shard)
    todo = [r for r in tg if m.mine(r["doi"], shard)
            and (r["doi"] not in st or (a.retry_failed and not st[r["doi"]].get("ok")))]
    if a.limit:
        todo = todo[:a.limit]
    m.log(f"目标 {len(tg)}，本片待取 {len(todo)}，已有 state {len(st)}，"
          f"源: {'+'.join(f.__name__[2:] for f in srcs)}")
    ok = 0
    for i, r in enumerate(todo, 1):
        doi = r["doi"]
        base = f"{C.FULLTEXT}/{fname(r)}"
        got = None
        for fn in srcs:
            try:
                got = fn(doi, r, base, opener)
            except Exception as e:
                got = None
            if got:
                break
        if got:
            p, src = got
            st[doi] = {"ok": True, "src": src, "file": os.path.basename(p),
                       "title": r.get("title"), "journal": r.get("journal"),
                       "year": r.get("year"), "if": r.get("jcr"), "prio": r.get("prio")}
            ok += 1
            m.log(f"[{i}/{len(todo)}] ✓ {src:20s} {(r.get('title') or '')[:52]}")
        else:
            st[doi] = {"ok": False, "why": "无可用官方PDF(全部候选失败)",
                       "title": r.get("title"), "journal": r.get("journal"),
                       "year": r.get("year"), "if": r.get("jcr"), "prio": r.get("prio")}
            m.log(f"[{i}/{len(todo)}] ✗ {(r.get('title') or '')[:60]}")
    st.flush()
    all_st = m.load_shards("fetch_state")
    s = collections.Counter(v.get("src") if v.get("ok") else "失败" for v in all_st.values())
    m.log(f"本轮成功 {ok}/{len(todo)}；全局 {len(all_st)} 条 → {dict(s.most_common())}")

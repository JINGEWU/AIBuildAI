# -*- coding: utf-8 -*-
"""S3-ingest-dir 批量归档人工下载的整目录 PDF

与 s3_ingest 的区别：那个认 `TPAMI_*.pdf` 这类带映射表的规范名，
这个应付「从 IEEE Xplore 一篇篇点下来、文件名就是标题」的目录。

认名两级：
  ① 正文 DOI —— 最可靠，出版社 PDF 首页几乎都印了
  ② 标题模糊匹配 —— 扫描件/无 DOI 印记时兜底，对齐 S10 待补清单

版本走 pdf_version 审计，但对 IEEE 早期访问版做了修正：
TPAMI 在正式排版前只发作者接收稿（页眉是 IEEEtran 模板没填的
"JOURNAL OF LATEX CLASS FILES, VOL. 14, NO. 8"），pdf_version 会判成 preprint。
它有出版社版权印记、无 arXiv 印记、正文完整，官方版根本还不存在，
所以归为 early-access 收进 fulltext/，只在 fetch_state 里标明出处，不丢这批论文。
真正的 arXiv/作者自挂稿仍进 arxiv_隔离/；不足 3 页的（会议摘要、付费墙预览）直接跳过。

用法: python3 run.py ingest-dir <目录> [--dry-run] [--keep] [--cutoff 0.78]
"""
import os, re, sys, json, shutil, argparse, difflib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C, common as m
import s10_needlist


def _year_from_doi(doi):
    """IEEE DOI 形如 10.1109/tpami.2026.3697634，中段就是年份；works_merged 缺条目时兜底。"""
    mm = re.search(r"\.(20\d\d)\.", doi or "")
    return int(mm.group(1)) if mm else None


def norm_title(s):
    """标题归一：去扩展名、下划线转空格、去非字母数字、小写。"""
    s = re.sub(r"\.pdf$", "", s or "", flags=re.I)
    s = re.sub(r"[_\-]+", " ", s)
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def fname(rec):
    """与 S3 抓取同一套命名（common.fname），仅补上扩展名。"""
    return m.fname(rec) + ".pdf"


def walk_pdfs(root):
    for dp, _dn, fns in os.walk(root):
        for f in sorted(fns):
            if f.lower().endswith(".pdf") and not f.startswith("."):
                yield os.path.join(dp, f)


def main(argv):
    ap = argparse.ArgumentParser(prog="ingest-dir")
    ap.add_argument("srcdir", help="人工下载的 PDF 目录（递归）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true", help="归档后保留源文件（默认保留）")
    ap.add_argument("--cutoff", type=float, default=0.78, help="标题模糊匹配阈值")
    ap.add_argument("--min-pages", type=int, default=3,
                    help="低于此页数视为会议摘要/预览，不收（默认 3）")
    ap.add_argument("--report", default=None, help="把认名结果写成 json 便于人工复核")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.srcdir):
        m.die(f"目录不存在: {a.srcdir}")

    # ── 待补清单作为认名靶子 ──
    targets = s10_needlist.collect()
    # 待补清单只带 title/journal/if，没有 year；年份等元数据回 works_merged 取，
    # 否则写进 state 的 year 是 None，一路传到交付表的「年」列就是空的。
    W = {}
    wp = f"{C.DATA}/works_merged.jsonl"
    if os.path.exists(wp):
        for w in m.read_jsonl(wp, True):
            wd = m.norm_doi(w.get("doi") or "")
            if wd:
                W[wd] = w
        m.log(f"works_merged 元数据 {len(W)} 条，用于补 year/journal/if")
    by_doi = {m.norm_doi(t["doi"]): t for t in targets}
    tnorm = {norm_title(t["title"]): t for t in targets if t.get("title")}
    m.log(f"待补清单 {len(targets)} 篇；源目录 {a.srcdir}")

    st = m.State("fetch_state_manual")
    QUAR = f"{C.ROOT}/arxiv_隔离"
    ABSDIR = f"{C.ROOT}/_剔除_会议摘要"
    hit_doi = hit_title = 0
    rows, unmatched, notarget, skipped = [], [], [], []


    def classify(path, kind, pages, txt):
        """修正 pdf_version 的两类判断，返回 (最终类别, 去向目录)。"""
        if pages < a.min_pages:
            return "过短", ABSDIR          # 会议摘要 / 付费墙预览，不是全文
        if kind == "preprint" and not C.RE_ARXIV_STAMP.search(txt) \
                and C.RE_PUBLISHER_STAMP.search(txt):
            return "early-access", C.FULLTEXT   # IEEE 接收稿，官方版尚不存在
        return kind, (C.FULLTEXT if kind == "official" else QUAR)

    files = list(walk_pdfs(a.srcdir))
    for i, src in enumerate(files, 1):
        base = os.path.basename(src)
        kind, why, pages = m.pdf_version(src)

        doi = None
        try:
            txt, _ = m.pdf_text(src, pages=3)
            doi = m.doi_in_text(txt)
        except Exception:
            txt = ""

        t = by_doi.get(m.norm_doi(doi)) if doi else None
        how = "正文DOI"
        if not t:                                    # ② 标题模糊匹配
            key = norm_title(base)
            cand = difflib.get_close_matches(key, list(tnorm), n=1, cutoff=a.cutoff)
            if cand:
                t, how = tnorm[cand[0]], f"标题({difflib.SequenceMatcher(None, key, cand[0]).ratio():.2f})"
        if t:
            hit_doi += how == "正文DOI"; hit_title += how != "正文DOI"
        else:
            (notarget if doi else unmatched).append((base, doi, kind, pages))
            continue

        kind, dest_dir = classify(src, kind, pages, txt)
        if dest_dir == ABSDIR:
            skipped.append((base, t["doi"], pages))
            if not a.dry_run:      # 打上剔除标记，否则会一直挂在待补清单上
                st[t["doi"]] = {"ok": False, "src": "剔除/会议摘要", "file": "",
                                "title": t["title"], "journal": t["journal"],
                                "note": f"仅{pages}页，非全文"}
            continue
        name = fname(t)
        rows.append({"src": src, "file": name, "doi": t["doi"], "kind": kind,
                     "why": why, "pages": pages, "how": how,
                     "dest": os.path.basename(dest_dir)})
        if not a.dry_run:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copyfile(src, os.path.join(dest_dir, name))
            w = W.get(m.norm_doi(t["doi"])) or {}
            st[t["doi"]] = {"ok": True, "src": f"manual-dir/{kind}", "file": name,
                            "title": t["title"] or w.get("title"),
                            "journal": t["journal"] or w.get("journal"),
                            "year": w.get("year") or _year_from_doi(t["doi"]),
                            "if": t.get("if") or w.get("if")}
        if i % 25 == 0:
            m.log(f"  {i}/{len(files)}")
    if not a.dry_run:
        st.flush()

    # ── 汇总 ──
    import collections
    kc = collections.Counter(r["kind"] for r in rows)
    print(f"\n源 PDF {len(files)} 个 → 认出 {len(rows)}（正文DOI {hit_doi} / 标题 {hit_title}）"
          f"，未认出 {len(unmatched) + len(notarget)}")
    print("  版本审计:", dict(kc))
    print("  去向:", dict(collections.Counter(r["dest"] for r in rows)))
    if skipped:
        print(f"\n跳过 {len(skipped)} 个（不足 {a.min_pages} 页，是会议摘要或预览页，非全文）:")
        for b, d, p in skipped:
            print(f"   {b[:62]:62s} {p}页  {d}")
    if notarget:
        print(f"\n有 DOI 但不在待补清单 {len(notarget)} 个（可能本就已收录）:")
        for b, d, k, p in notarget[:20]:
            print(f"   {b[:62]:62s} {d}  [{k}]")
    if unmatched:
        print(f"\n认不出 {len(unmatched)} 个（无正文 DOI 且标题不匹配）:")
        for b, d, k, p in unmatched[:20]:
            print(f"   {b[:62]:62s} [{k}] {p}页")
    ea = [r for r in rows if r["kind"] == "early-access"]
    if ea:
        print(f"\nIEEE 早期访问版 {len(ea)} 个（作者接收稿，官方排版版尚未发布，已收进 fulltext/）:")
        for r in ea:
            print(f"   {os.path.basename(r['src'])[:62]:62s} {r['pages']}页  {r['doi']}")
    bad = [r for r in rows if r["kind"] not in ("official", "early-access")]
    if bad:
        print(f"\n非官方版 {len(bad)} 个，已进 arxiv_隔离/:")
        for r in bad[:20]:
            print(f"   {os.path.basename(r['src'])[:58]:58s} {r['kind']}: {r['why'][:40]}")
    left = [t for t in targets if m.norm_doi(t["doi"]) not in {m.norm_doi(r["doi"]) for r in rows}]
    print(f"\n清单仍缺 {len(left)} / {len(targets)} 篇")

    if a.report:
        json.dump({"matched": rows, "unmatched": unmatched, "notarget": notarget,
                   "left": [{k: t[k] for k in ('doi', 'title', 'journal', 'tier')} for t in left]},
                  open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"→ {a.report}")
    if a.dry_run:
        m.log("dry-run，未落盘")
    else:
        m.log("下一步: run.py extract  →  screen2 dump/save/export  →  info")


if __name__ == "__main__":
    main(sys.argv[1:])

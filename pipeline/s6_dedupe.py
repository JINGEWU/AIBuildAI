# -*- coding: utf-8 -*-
"""S6 与既有语料去重

papers/ 里已有 54 篇（agent_papers_SOTA_evaluation.xlsx + PDF）。
本步建立基线 DOI 集合 data/baseline_dois.json，供 S2/S5 导出时打「★重复」。
匹配用 DOI 为主；DOI 缺失时退回标题规范化匹配（去标点、小写、取前 60 字符）。

用法: python3 run.py dedupe [--report]
"""
import os, re, sys, json, glob, argparse, collections
import config as C, common as m

def tkey(s):
    s = re.sub(r"<[^>]+>", "", str(s or "")).lower()
    return re.sub(r"[^a-z0-9]", "", s)[:60]

def baseline():
    """从既有 xlsx + PDF 文件名 + PDF 正文里收集 DOI 与标题键。"""
    dois, titles = set(), {}
    if os.path.exists(C.XLSX_EXTRACT):
        import openpyxl
        wb = openpyxl.load_workbook(C.XLSX_EXTRACT, read_only=True, data_only=True)
        for ws in wb:
            it = ws.iter_rows(values_only=True)
            hdr = [str(x or "") for x in next(it, [])]
            di = next((i for i, h in enumerate(hdr) if "Paper link" in h or h == "DOI"), None)
            ti = next((i for i, h in enumerate(hdr) if "论文" in h or "系统" in h), None)
            for r in it:
                if di is not None and di < len(r):
                    d = m.doi_in_text(str(r[di] or "")) or m.norm_doi(r[di])
                    if d and d.startswith("10."):
                        dois.add(d)
                if ti is not None and ti < len(r) and r[ti]:
                    titles[tkey(r[ti])] = str(r[ti])
        m.log(f"  从 {os.path.basename(C.XLSX_EXTRACT)} 取到 DOI {len(dois)}，标题 {len(titles)}")
    # PDF 正文兜底
    pdfs = glob.glob(f"{C.PAPERS}/*.pdf")
    for p in pdfs:
        try:
            t, _ = m.pdf_text(p, pages=2)
        except Exception:
            continue
        d = m.doi_in_text(t)
        if d:
            dois.add(d)
    m.log(f"  papers/ 下 {len(pdfs)} 个 PDF，合计基线 DOI {len(dois)}")
    return sorted(dois), titles

def main(argv):
    ap = argparse.ArgumentParser(prog="dedupe")
    ap.add_argument("--report", action="store_true", help="只报告重叠，不写文件")
    a = ap.parse_args(argv)
    dois, titles = baseline()
    if not a.report:
        json.dump(dois, open(f"{C.DATA}/baseline_dois.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=0)
        json.dump(titles, open(f"{C.DATA}/baseline_titles.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=0)
        m.log(f"基线写入 data/baseline_dois.json（{len(dois)} 条）")

    B, BT = set(dois), set(titles)
    for tag, path, key in [("第一轮", f"{C.DATA}/verdicts.json", "v"),
                           ("第二轮", f"{C.DATA}/verdicts2.json", "v")]:
        if not os.path.exists(path):
            continue
        V = json.load(open(path, encoding="utf-8"))
        sel = [d for d, v in V.items() if v.get(key) == "入选"]
        ov = [d for d in sel if m.norm_doi(d) in B]
        m.log(f"{tag}入选 {len(sel)} 篇，与既有语料 DOI 重复 {len(ov)} 篇")
        for d in ov[:10]:
            print(f"    ★ {d}")
    # 标题兜底查一遍第二轮（防 DOI 不一致漏判）
    dgp = f"{C.DATA}/fulltext_digest.jsonl"
    if os.path.exists(dgp):
        extra = [r for r in m.read_jsonl(dgp)
                 if m.norm_doi(r.get("doi")) not in B and tkey(r.get("title")) in BT]
        if extra:
            m.log(f"标题匹配到 DOI 未覆盖的重复 {len(extra)} 篇:")
            for r in extra[:10]:
                print(f"    ≈ {(r.get('title') or '')[:70]}")

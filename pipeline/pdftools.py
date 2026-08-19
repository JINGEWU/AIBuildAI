# -*- coding: utf-8 -*-
"""PDF 证据抽取工具层。

信息抽取阶段（S7）真正干活的地方。按成本从低到高排四种手段，
前一种拿不到再上后一种：

  mine_sota()   全文挖带数值的跨方法对比句 —— 最便宜，覆盖约 2/3 的论文
  deep_read()   分类抽取规模/指标定义/可得性/对比句 —— 用于首次通读
  grab_tables() 按文字块坐标重建表格 —— 应对无框线排版的 IEEE 表
  render_page() 渲染成 PNG 供视觉阅读 —— 表格是图片时的最后手段

外加 shrink_pdf()：交付前压缩超大 PDF（只降采样内嵌图，不动文字层）。
"""
import os, re, io, sys
import fitz
# MuPDF 对轻微损坏的 PDF 会往 stdout 狂刷 "format error"，把抽取结果冲得没法读；
# 这些错误不影响取文本，直接静音。
try:
    fitz.TOOLS.mupdf_display_errors(False)
except Exception:
    pass
import config as C
import common as m

# ───────────────────────── 文件索引 ─────────────────────────
_FILES = None

def files(refresh=False):
    """文件名 → 绝对路径。取证时隔离区也要：抽 benchmark 信息时 arXiv 版与官方版等价。"""
    global _FILES
    if _FILES is None or refresh:
        _FILES = m.file_index(m.ALL_DIRS)
    return _FILES

def path_of(doi, state=None):
    """DOI → 全文路径。先查 fetch_state 记录的文件名，再按 DOI 尾号兜底匹配。"""
    d = m.norm_doi(doi)
    st = state if state is not None else m.load_shards("fetch_state")
    F = files()
    p = F.get((st.get(d) or {}).get("file") or "")
    if p:
        return p
    tail = d.split("/")[-1]
    if len(tail) > 6:
        for k, v in F.items():
            if tail[:20] in k:
                return v
    return None

def text_of(path):
    return m.xml_text(path) if path.lower().endswith(".xml") else m.pdf_text(path)[0]

# ───────────────────────── ① 数值对比句挖掘 ─────────────────────────
RE_NUM = re.compile(r"\d+\.\d{1,4}|\d{1,3}(\.\d)?\s?%")
RE_CMP = re.compile(
    r"(outperform\w*|surpass\w*|exceed\w*|compared (with|to)|versus|\bvs\.?\b|"
    r"higher than|lower than|better than|improv\w+ (by|of)|gain of|reduc\w+ by|"
    r"state[- ]of[- ]the[- ]art|\bSOTA\b|best[- ]performing|second[- ]best|baseline|"
    r"achiev\w+ (an? )?(accuracy|AUC|AUROC|F1|Dice|MAE|RMSE|R2|score|rate))", re.I)

def mine_sota(path, limit=12, lo=30, hi=420):
    """挖全文里同时含数值与对比措辞的句子——补 SOTA 数值最高效的手段。"""
    t = text_of(path)
    out = []
    for x in m.sentences(t):
        x = re.sub(r"\s+", " ", x).strip()
        if lo < len(x) < hi and RE_NUM.search(x) and RE_CMP.search(x) and x not in out:
            out.append(x)
        if len(out) >= limit:
            break
    return out

# ───────────────────────── ② 分类证据抽取 ─────────────────────────
RE_SIZE = re.compile(
    r"([\d,]{2,10}\s*(?:k\b|K\b|million|billion|thousand)?\s*"
    r"(?:questions?|problems?|tasks?|instances?|samples?|examples?|images?|slides?|scans?|videos?|"
    r"patients?|cases?|studies|subjects?|sequences?|molecules?|structures?|graphs?|nodes?|episodes?|"
    r"dialogues?|pairs?|records?|trials?|ECGs?|WSIs?|volumes?|frames?|points?|datasets?|classes?|"
    r"annotations?|objects?|utterances?|documents?|proteins?|compounds?|cells?)"
    r"|\b\d{1,4}\s*(?:downstream )?(?:tasks?|datasets?|benchmarks?|cohorts?|hospitals?|centers?|"
    r"centres?|modalities))", re.I)
RE_METRIC_DEF = re.compile(
    r"(we (?:use|report|adopt|employ|evaluate|measure|compute)|evaluation metric|"
    r"metrics? (?:are|is|include|used)|is (?:defined|computed|calculated) as|"
    r"following (?:the )?(?:standard|official|common) (?:protocol|practice|setting|split)|"
    r"we follow|scoring|judge|assessed by|success (?:is|was) (?:defined|counted))", re.I)
RE_AVAIL = re.compile(
    r"(data availability|code availability|is available at|are available at|"
    r"publicly available|can be (?:downloaded|accessed)|released? at|hosted (?:at|on))", re.I)

def deep_read(path, n_size=4, n_metric=2, n_avail=2, n_cmp=7):
    """首次通读用：分四类抽证据。返回 {规模, 指标定义, 可得性, 对比句}。"""
    t = text_of(path)
    ss = m.sentences(t)

    def pick(rx, n, lo=40, hi=300):
        out = []
        for x in ss:
            if lo < len(x) < hi and rx.search(x):
                y = re.sub(r"\s+", " ", x).strip()
                if y not in out:
                    out.append(y)
            if len(out) >= n:
                break
        return out

    cmp_ = []
    for x in ss:
        if 40 < len(x) < 320 and RE_CMP.search(x) and RE_NUM.search(x):
            y = re.sub(r"\s+", " ", x).strip()
            if y not in cmp_:
                cmp_.append(y)
        if len(cmp_) >= n_cmp:
            break
    return {"规模": pick(RE_SIZE, n_size), "指标定义": pick(RE_METRIC_DEF, n_metric),
            "可得性": pick(RE_AVAIL, n_avail), "对比句": cmp_}

# ───────────────────────── ③ 表格重建 ─────────────────────────
RE_CELL_NUM = re.compile(r"^\(?[+-]?\d{1,4}(?:[.,]\d{1,4})?%?\)?$")
RE_SUPER = re.compile(r"^\d{1,2}(,\d{1,2})*$")     # 作者姓名上标，非数据

def _page_rows(page, ytol=2.5):
    """同 y 聚为一行、按 x 排序——IEEE 表格无框线，只能靠坐标重建。"""
    d = page.get_text("dict")
    sp = []
    for b in d.get("blocks", []):
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                t = s["text"].strip()
                if t:
                    sp.append((round(s["bbox"][1], 1), s["bbox"][0], t))
    sp.sort()
    rows, cur, y0 = [], [], None
    for y, x, t in sp:
        if y0 is None or abs(y - y0) <= ytol:
            cur.append((x, t)); y0 = y if y0 is None else y0
        else:
            rows.append(sorted(cur)); cur = [(x, t)]; y0 = y
    if cur:
        rows.append(sorted(cur))
    return [[t for _, t in r] for r in rows]

def grab_tables(path, min_nums=3, max_rows=10, max_tabs=4):
    """返回 [(页码, [行文本])]。⚠️表格若是图片则抓不到，需转 render_page。"""
    doc = fitz.open(path)
    out = []
    try:
        for pi in range(doc.page_count):
            try:
                rows = _page_rows(doc[pi])
            except Exception:
                continue
            blk = []
            for r in rows:
                nums = [c for c in r if RE_CELL_NUM.match(c) and not RE_SUPER.match(c)]
                if len(nums) >= min_nums and len(r) <= 24:
                    blk.append(" | ".join(c[:18] for c in r)[:190])
                elif len(blk) >= 2:
                    out.append((pi + 1, blk[:max_rows])); blk = []
                    if len(out) >= max_tabs:
                        break
                else:
                    blk = []
            if len(blk) >= 2:
                out.append((pi + 1, blk[:max_rows]))
            if len(out) >= max_tabs:
                break
    finally:
        doc.close()
    return out

# ───────────────────────── ④ 定位与渲染 ─────────────────────────
RE_PAGE_CMP = re.compile(
    r"(compar\w+ (with|to|against)|versus|\bvs\.?\b|outperform\w*|baseline|"
    r"state-of-the-art|benchmark(ing)? (against|results)|performance comparison)", re.I)
RE_PAGE_NUM = re.compile(r"\d+\.\d{2,4}|\d{2,3}\.\d%|\b0\.\d{2,3}\b")

def find_pages(path, top=4):
    """按「对比措辞 ×2 + 数值」密度给页面打分，返回最可能含结果表的页。"""
    doc = fitz.open(path)
    try:
        sc = []
        for pi in range(doc.page_count):
            t = doc[pi].get_text()
            sc.append((len(RE_PAGE_CMP.findall(t)) * 2 + len(RE_PAGE_NUM.findall(t)), pi + 1))
        sc.sort(reverse=True)
        return sc[:top], doc.page_count
    finally:
        doc.close()

def render_page(path, pages, dpi=150, outdir="/tmp/pg"):
    """渲染成 PNG——表格是图片时，交给视觉阅读。"""
    os.makedirs(outdir, exist_ok=True)
    doc = fitz.open(path)
    out = []
    try:
        for pn in pages:
            pix = doc[pn - 1].get_pixmap(dpi=dpi)
            o = f"{outdir}/{re.sub(r'[^A-Za-z0-9]', '_', os.path.basename(path))[:50]}_p{pn}.png"
            pix.save(o); out.append(o)
    finally:
        doc.close()
    return out

# ───────────────────────── ⑤ 交付前压缩 ─────────────────────────
def shrink_pdf(path, max_px=1800, quality=72, min_kb=300, gain=0.85):
    """对超大内嵌图降采样重压，保留文字层。返回 (原MB, 新MB, 替换图数) 或 None。"""
    from PIL import Image
    before = os.path.getsize(path) / 1048576
    d = fitz.open(path)
    replaced = 0
    try:
        xrefs = {i[0] for pg in range(d.page_count) for i in d[pg].get_images(full=True)}
        for xref in xrefs:
            try:
                raw = d.extract_image(xref)["image"]
            except Exception:
                continue
            if len(raw) < min_kb * 1024:
                continue
            try:
                im = Image.open(io.BytesIO(raw))
                if im.mode in ("CMYK", "P", "LA", "RGBA"):
                    im = im.convert("RGB")
                w, h = im.size
                if max(w, h) > max_px:
                    s = max_px / max(w, h)
                    im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=quality, optimize=True)
                new = buf.getvalue()
                if len(new) < len(raw) * 0.9:
                    d.update_stream(xref, new); replaced += 1
            except Exception:
                continue
        tmp = path + ".tmp"
        d.save(tmp, garbage=4, deflate=True, deflate_images=True, clean=True)
    finally:
        d.close()
    after = os.path.getsize(tmp) / 1048576
    if after < before * gain:
        os.replace(tmp, path)
        return before, after, replaced
    os.remove(tmp)
    return None

# ───────────────────────── CLI ─────────────────────────
def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="pdftools")
    ap.add_argument("action", choices=["mine", "deep", "tables", "pages", "render", "shrink"])
    ap.add_argument("targets", nargs="*", help="DOI（mine/deep/tables/pages/render）或文件路径（shrink）")
    ap.add_argument("--list", help="从文件逐行读 DOI/路径，替代命令行传参（避免长列表被 shell 合并）")
    ap.add_argument("--pages", default="1", help="render 用：页码，逗号分隔")
    ap.add_argument("--dpi", type=int, default=150)
    a = ap.parse_args(argv)
    if a.list:
        a.targets += [l.strip() for l in open(a.list, encoding="utf-8") if l.strip()]
    if not a.targets:
        ap.error("需要至少一个目标：命令行传入或用 --list 指定文件")

    if a.action == "shrink":
        for p in a.targets:
            r = shrink_pdf(p)
            n = os.path.basename(p)[:56]
            print(f"  {'✓' if r else '–'} {n:56s} " +
                  (f"{r[0]:6.1f}MB → {r[1]:6.1f}MB (替换 {r[2]} 图)" if r else "压缩收益不足"))
        return

    st = m.load_shards("fetch_state")
    D = {m.norm_doi(r["doi"]): r for r in m.read_jsonl(f"{C.DATA}/fulltext_digest.jsonl", True)}
    for doi in a.targets:
        d = m.norm_doi(doi)
        p = path_of(d, st)
        ti = (D.get(d) or {}).get("title") or ""
        print("=" * 96)
        print(f"@{d}  {ti[:64]}")
        if not p:
            print("  [无文件]"); continue
        if a.action == "mine":
            hits = mine_sota(p)
            print("  未挖到数值对比句" if not hits else "")
            for h in hits:
                print("   •", h[:300])
        elif a.action == "deep":
            for k, v in deep_read(p).items():
                if v:
                    print(f"  --{k}--")
                    for x in v:
                        print("   ", x[:200])
        elif a.action == "tables":
            tabs = grab_tables(p)
            print("  未抓到数值表（多半是图片表，改用 render）" if not tabs else "")
            for pg, blk in tabs:
                print(f"  ── p{pg}")
                for b in blk:
                    print("    ", b)
        elif a.action == "pages":
            sc, n = find_pages(p)
            print(f"  {n} 页；对比信息最密集: " + "  ".join(f"p{x[1]}(分{x[0]})" for x in sc))
            print(f"  文件: {p}")
        elif a.action == "render":
            for o in render_page(p, [int(x) for x in a.pages.split(",")], a.dpi):
                print("  →", o)


if __name__ == "__main__":
    main(sys.argv[1:])

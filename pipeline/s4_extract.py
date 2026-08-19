# -*- coding: utf-8 -*-
"""S4 全文信号抽取 → data/fulltext_digest.jsonl

从每篇官方全文里抽第二轮判定要用的证据，压成紧凑 digest（不留全文，省 token）：
  links       github/hf/zenodo/figshare/osf/dryad/kaggle/physionet 等直达链接
  known_bench 命中的知名公开基准（imagenet/mmlu/swe-bench/mimic/tcga/matbench...）
  bench_names 文中自定义基准名（*Bench / *Arena / *Gym / *Eval）
  avail/code_av  Data/Code availability 声明原文
  sota        含 SOTA/outperform 的句子
  metrics     出现过的评估指标
  n_wet/n_hw/n_hum + 例句   红旗：湿实验 / 硬件 / 人工评测

增量：已在 digest 里的 DOI 跳过；新补了 PDF 就再跑一次即可。
用法: python3 run.py extract [--rebuild] [--include-baseline]
"""
import os, re, sys, json, glob, argparse, collections
import config as C, common as m

def digest(path):
    """单篇 → 信号字典。解析失败返回 {"err": ...} 而不是抛异常，保证批量不中断。"""
    if path.lower().endswith(".xml"):
        try:
            full, npg = m.xml_text(path), 0
        except Exception as e:
            return {"err": f"XML解析失败:{e}"}
    else:
        try:
            full, npg = m.pdf_text(path)
        except Exception as e:
            return {"err": f"打不开:{e}"}
    if len(full) < 800:
        return {"err": f"文本过少({len(full)}字符,可能扫描版)", "pages": npg}

    ss = m.sentences(full)

    def pick(rx, n, maxlen=230):
        out = []
        for s in ss:
            if 25 <= len(s) <= 600 and rx.search(s):
                out.append(s[:maxlen])
                if len(out) >= n:
                    break
        return out

    def context(rx, n, span=3, maxlen=420):
        out = []
        for i, s in enumerate(ss):
            if rx.search(s):
                out.append(" ".join(ss[i:i + span])[:maxlen])
                if len(out) >= n:
                    break
        return out

    links = []
    for mo in C.RE_LINK.finditer(full):
        u = mo.group(1).rstrip(").,;")
        if u.lower() not in {x.lower() for x in links}:
            links.append(u)

    bn = []
    for mo in C.RE_BENCH_NAME.finditer(full):
        g = mo.group(1)
        if g and len(g) > 4 and g.lower() not in {x.lower() for x in bn}:
            bn.append(g)
        if len(bn) >= 10:
            break

    return {
        "pages": npg, "chars": len(full),
        "links": links[:8],
        "known_bench": sorted({mo.group(0).lower() for mo in C.RE_KNOWN_BENCH.finditer(full)})[:14],
        "bench_names": bn,
        "avail": context(C.RE_AVAIL, 2),
        "code_av": context(re.compile(
            r"code availability|code (?:is |are )?available|our code|source code", re.I), 2, 2, 300),
        "sota": pick(C.RE_SOTA, 6),
        "metrics": sorted({mo.group(0).lower() for mo in C.RE_METRIC.finditer(full)})[:20],
        "bench_sents": pick(C.RE_BENCH_NAME, 4),
        "n_wet": len(C.RE_WET.findall(full)),
        "n_hw": len(C.RE_HW.findall(full)),
        "n_hum": len(C.RE_HUM.findall(full)),
        "wet_ex": pick(C.RE_WET, 2, 140),
        "hw_ex": pick(C.RE_HW, 2, 140),
        "hum_ex": pick(C.RE_HUM, 2, 140),
    }

def index_files(include_baseline):
    """文件名 → 路径。只认官方库；papers/ 的既有语料可选纳入（给那 54 篇也打分）。
    刻意不含 arxiv_隔离 —— 被审计下来的非官方版不该进 digest。"""
    return m.file_index(m.FT_DIRS + (("papers",) if include_baseline else ()))

def main(argv):
    ap = argparse.ArgumentParser(prog="extract")
    ap.add_argument("--rebuild", action="store_true", help="清空 digest 重抽")
    ap.add_argument("--include-baseline", action="store_true", help="也抽 papers/ 里的既有语料")
    ap.add_argument("--refresh-meta", action="store_true",
                    help="只用 state 刷新 digest 里的 title/journal/year/if，不重读 PDF")
    ap.add_argument("--refresh-changed", action="store_true",
                    help="全文文件换过（如 XML/arXiv 版升级为官方 PDF）的重抽一遍")
    a = ap.parse_args(argv)

    out = f"{C.DATA}/fulltext_digest.jsonl"
    if a.rebuild and os.path.exists(out):
        os.remove(out)
    prev = {m.norm_doi(r.get("doi")): r for r in m.read_jsonl(out, quiet=True)}
    done = set(prev)
    st = m.load_shards("fetch_state")

    if a.refresh_meta:
        # digest 的元数据是抽取时从 state 复制的快照。人工下载路径写进 state 的条目
        # 只有 ok/src/file，没有 journal/year —— 一旦这类条目触发重抽，新记录就会
        # 把原先带 journal 的旧记录覆盖掉，期刊加分随之丢失、档位无声下滑。
        # 所以这里按 state → works_merged → DOI 反解 三级兜底解析，不依赖单一来源。
        W = {}
        wp = f"{C.DATA}/works_merged.jsonl"
        if os.path.exists(wp):
            for w in m.read_jsonl(wp, True):
                wd = m.norm_doi(w.get("doi") or "")
                if wd:
                    W[wd] = w
            m.log(f"works_merged 元数据 {len(W)} 条")
        yr = re.compile(r"\.(20\d\d)\.")
        fixed = collections.Counter()
        for d, r in prev.items():
            s_, w_ = st.get(d) or {}, W.get(d) or {}
            for k in ("title", "journal", "year", "if"):
                if r.get(k) not in (None, ""):
                    continue
                v2 = s_.get(k) or w_.get(k)
                if not v2 and k == "year":
                    mm = yr.search(d)
                    v2 = int(mm.group(1)) if mm else None
                if v2 not in (None, ""):
                    r[k] = v2
                    fixed[k] += 1
        tmp = out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fo:
            for r in prev.values():
                fo.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, out)
        m.log(f"元数据补全: {dict(fixed)}；digest 去重后 {len(prev)} 条")
        return
    if a.refresh_changed:
        # digest 是 append-only，后写的记录在下游 {doi: rec} 里覆盖先写的，直接追加即可
        chg = {d for d, r in prev.items()
               if (st.get(d) or {}).get("file") and r.get("file") != st[d]["file"]}
        done -= chg
        m.log(f"全文文件已变更、需重抽 {len(chg)} 篇")
    files = index_files(a.include_baseline)
    m.log(f"state {len(st)} 条，全文文件 {len(files)} 个，已抽 {len(done)}")

    # papers/ 里的既有语料从未进过 fetch_state（早期人工收集），按文件名尾号反解 DOI 补进来，
    # 否则它们拿不到 digest，复刻分会被系统性压低、与新批次不可比。
    if a.include_baseline and os.path.isdir(C.PAPERS):
        B = json.load(open(f"{C.DATA}/baseline_dois.json", encoding="utf-8")) \
            if os.path.exists(f"{C.DATA}/baseline_dois.json") else []
        tail2doi = {m.norm_doi(x).split("/")[-1].replace("/", "_"): m.norm_doi(x) for x in B}
        added = 0
        for fn in sorted(os.listdir(C.PAPERS)):
            if not fn.lower().endswith(".pdf"):
                continue
            stem = os.path.splitext(fn)[0]
            hit = next((d for t, d in tail2doi.items() if stem.endswith("_" + t)), None)
            if hit and hit not in st:
                st[hit] = {"ok": True, "src": "papers/已有", "file": fn}
                added += 1
        if added:
            m.log(f"papers/ 中补入未登记的既有语料 {added} 篇")

    f = open(out, "a", encoding="utf-8")
    n, miss = 0, 0
    for doi, s in st.items():
        if not s.get("ok") or doi in done:
            continue
        path = files.get(s.get("file") or "")
        if not path:
            # 文件被 audit 隔离或改名过：按 DOI 尾号兜底匹配
            tail = doi.split("/")[-1]
            for k, v in files.items():
                if len(tail) > 6 and tail[:20] in k:
                    path = v
                    break
        if not path:
            miss += 1
            continue
        dg = digest(path)
        dg.update({"doi": doi, "title": s.get("title"), "journal": s.get("journal"),
                   "year": s.get("year"), "if": s.get("if"), "prio": s.get("prio"),
                   "src": s.get("src"), "file": os.path.basename(path)})
        f.write(json.dumps(dg, ensure_ascii=False) + "\n")
        f.flush()
        n += 1
        if n % 25 == 0:
            m.log(f"  已抽取 {n}")
    f.close()
    total = len(m.read_jsonl(out, quiet=True))
    m.log(f"本轮新抽 {n} 篇，累计 {total} 篇；文件缺失(已隔离/未下载) {miss}")
    errs = [r for r in m.read_jsonl(out, quiet=True) if r.get("err")]
    if errs:
        m.log(f"  解析失败 {len(errs)} 篇（扫描版/损坏），需人工看: "
              + ", ".join(x["doi"] for x in errs[:5]))

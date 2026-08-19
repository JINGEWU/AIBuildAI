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
import os, re, sys, json, glob, argparse
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
    """文件名 → 路径。papers/ 的基线语料可选纳入（用于给既有 54 篇也打分）。"""
    pats = [f"{C.FULLTEXT}/*.pdf", f"{C.FULLTEXT}/*.xml", f"{C.ROOT}/fulltext_xml/*.xml"]
    if include_baseline:
        pats.append(f"{C.PAPERS}/*.pdf")
    files = {}
    for p in pats:
        for f in glob.glob(p):
            files[os.path.basename(f)] = f
    return files

def main(argv):
    ap = argparse.ArgumentParser(prog="extract")
    ap.add_argument("--rebuild", action="store_true", help="清空 digest 重抽")
    ap.add_argument("--include-baseline", action="store_true", help="也抽 papers/ 里的既有语料")
    a = ap.parse_args(argv)

    out = f"{C.DATA}/fulltext_digest.jsonl"
    if a.rebuild and os.path.exists(out):
        os.remove(out)
    done = {m.norm_doi(r.get("doi")) for r in m.read_jsonl(out, quiet=True)}
    st = m.load_shards("fetch_state")
    files = index_files(a.include_baseline)
    m.log(f"state {len(st)} 条，全文文件 {len(files)} 个，已抽 {len(done)}")

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

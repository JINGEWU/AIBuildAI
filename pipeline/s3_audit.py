# -*- coding: utf-8 -*-
"""S3-audit 全文版本审计 —— 把非官方版揪出来隔离

逐个 PDF 读首页判定版本：official / arxiv / preprint / preprint? / invalid
非官方版移到 arxiv_隔离/，并生成两样东西给你用机构权限手动补：
  data/cands.json          待补清单（含 DOI、原文件名、判定原因）
  data/下载脚本_<商>.js     浏览器 console 脚本，批量触发官方 PDF 下载
  data/下载文件名映射.json  下载后的文件名 → fulltext/ 目标名，供 ingest 归档

用法: python3 run.py audit [--dry-run] [--no-quarantine]
"""
import os, re, sys, json, shutil, argparse, collections
import config as C, common as m

def scan(include_quarantine=True):
    """审计全文文件的版本。XML 一定来自 EPMC 官方，直接算 official。

    同时扫 fulltext/ 与 arxiv_隔离/ —— 已隔离的仍属「待补官方版」，
    不能因为文件被移走就从清单里消失。
    """
    st = m.load_shards("fetch_state")
    by_file = {}
    for d, v in st.items():
        if v.get("file"):
            by_file.setdefault(v["file"], []).append(d)
    out = []
    dirs = [C.FULLTEXT] + ([C.QUARANTINE] if include_quarantine else [])
    files = [(d, f) for d in dirs if os.path.isdir(d) for f in sorted(os.listdir(d))]
    for i, (dr, f) in enumerate(files, 1):
        p = f"{dr}/{f}"
        if not os.path.isfile(p):
            continue
        quarantined = (dr == C.QUARANTINE)
        if f.lower().endswith(".xml"):
            out.append({"file": f, "kind": "official", "why": "EPMC JATS XML",
                        "doi": (by_file.get(f) or [None])[0], "pages": None,
                        "size": os.path.getsize(p), "quarantined": quarantined})
            continue
        if not f.lower().endswith(".pdf"):
            continue
        kind, why, pages = m.pdf_version(p)
        doi = (by_file.get(f) or [None])[0]
        if not doi:                      # state 里查不到，从正文抓 DOI 反查
            try:
                t, _ = m.pdf_text(p, pages=2)
                doi = m.doi_in_text(t)
            except Exception:
                doi = None
        out.append({"file": f, "kind": kind, "why": why, "doi": doi,
                    "pages": pages, "size": os.path.getsize(p),
                    "quarantined": quarantined})
        if i % 50 == 0:
            m.log(f"  审计 {i}/{len(files)}")
    return out

# ───────────────────────── 浏览器下载脚本 ─────────────────────────
PUB_OF = [("10.1109", "IEEE"), ("10.1038", "Nature"), ("10.1126", "Science"),
          ("10.1016", "Elsevier"), ("10.1093", "OUP"), ("10.1016/j.gastro", "Elsevier")]

def publisher_of(doi):
    for pre, name in PUB_OF:
        if (doi or "").startswith(pre):
            return name
    return "Other"

JS_TMPL = """// {pub}：官方 PDF 批量下载（需先在浏览器里登录机构 VPN/账号）
// 用法：打开出版社任一文章页 → F12 Console → 粘贴运行 → 文件落到默认下载目录
// 下完执行：python3 pipeline/run.py ingest
const LIST = {list};
const SLEEP = 4000;   // 间隔别调太短，会被限流
(async () => {{
  for (const [i, it] of LIST.entries()) {{
    const a = document.createElement('a');
    a.href = it.url; a.download = it.name;
    document.body.appendChild(a); a.click(); a.remove();
    console.log(`[${{i + 1}}/${{LIST.length}}] ${{it.name}}`);
    await new Promise(r => setTimeout(r, SLEEP));
  }}
  console.log('完成，回终端跑 ingest');
}})();
"""

def pdf_url(doi, pub):
    sfx = doi.split("/", 1)[1] if "/" in doi else doi
    if pub == "Nature":
        return f"https://www.nature.com/articles/{sfx}.pdf"
    if pub == "Science":
        return f"https://www.science.org/doi/pdf/{doi}"
    if pub == "IEEE":
        return f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber="  # 需页面内解析
    return f"https://doi.org/{doi}"

def emit_scripts(cands):
    """按出版社分组出脚本 + 文件名映射。IEEE 用 DOI 跳转让页面自己解析 stamp 链接。"""
    mapping, groups = {}, collections.defaultdict(list)
    for c in cands:
        doi = c.get("doi")
        if not doi:
            continue
        pub = publisher_of(doi)
        tag = "TPAMI" if pub == "IEEE" else "NAT"
        dl = f"{tag}_{re.sub(r'[^A-Za-z0-9]', '_', doi)}.pdf"
        mapping[dl] = c["file"]
        groups[pub].append({"doi": doi, "name": dl,
                            "url": f"https://doi.org/{doi}" if pub == "IEEE" else pdf_url(doi, pub)})
    for pub, lst in groups.items():
        p = f"{C.DATA}/下载脚本_{pub}.js"
        open(p, "w", encoding="utf-8").write(
            JS_TMPL.format(pub=pub, list=json.dumps(lst, ensure_ascii=False, indent=1)))
        m.log(f"  → {os.path.basename(p)}  {len(lst)} 篇")
    json.dump(mapping, open(f"{C.DATA}/下载文件名映射.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return groups

def main(argv):
    ap = argparse.ArgumentParser(prog="audit")
    ap.add_argument("--dry-run", action="store_true", help="只报告；不移动文件、不写任何清单")
    ap.add_argument("--no-quarantine", action="store_true", help="不移动非官方版")
    ap.add_argument("--restore-official", action="store_true",
                    help="把隔离区里其实是官方版的移回 fulltext/（规则收紧后回补用）")
    a = ap.parse_args(argv)

    rows = scan()
    m.log(f"审计 {len(rows)} 个全文文件")
    cnt = collections.Counter(r["kind"] for r in rows)
    for k in ("official", "arxiv", "preprint", "preprint?", "invalid"):
        if cnt.get(k):
            print(f"    {k:10s} {cnt[k]:5d}")

    # 规则改动后，隔离区可能有被误判的官方版，可回补
    wrong = [r for r in rows if r["kind"] == "official" and r.get("quarantined")]
    if wrong:
        m.log(f"隔离区有 {len(wrong)} 个按当前规则属官方版"
              + ("，回补中" if a.restore_official and not a.dry_run else "（加 --restore-official 回补）"))
        if a.restore_official and not a.dry_run:
            for r in wrong:
                src, dst = f"{C.QUARANTINE}/{r['file']}", f"{C.FULLTEXT}/{r['file']}"
                if not os.path.exists(src):
                    continue
                if os.path.exists(dst):
                    print(f"    ⊘ {r['file'][:60]}  fulltext/ 已有同名，跳过")
                    continue
                shutil.move(src, dst)
                print(f"    ↩ {r['file'][:64]}")

    bad = [r for r in rows if r["kind"] != "official"]
    # 隔离非官方版：移出 fulltext/，这样 extract 只会看到官方版
    if bad and not a.no_quarantine and not a.dry_run:
        os.makedirs(C.QUARANTINE, exist_ok=True)
        moved = 0
        for r in bad:
            if r.get("quarantined"):
                continue                     # 已在隔离区
            src, dst = f"{C.FULLTEXT}/{r['file']}", f"{C.QUARANTINE}/{r['file']}"
            if os.path.exists(src):
                shutil.move(src, dst)
                moved += 1
        m.log(f"新隔离 {moved} 个非官方版 → {C.QUARANTINE}/（此前已隔离 "
              f"{sum(1 for r in bad if r.get('quarantined'))} 个）")

    if not a.dry_run:
        json.dump(bad, open(f"{C.DATA}/cands.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        with open(f"{C.ROOT}/arxiv_非官方版本清单.csv", "w", encoding="utf-8-sig") as f:
            f.write("判定,原因,页数,已隔离,DOI,DOI链接,文件名\n")
            for r in sorted(bad, key=lambda x: x["kind"]):
                f.write(f'"{r["kind"]}","{r.get("why") or ""}",{r.get("pages") or ""},'
                        f'"{"是" if r.get("quarantined") else "否"}",'
                        f'"{r.get("doi") or ""}","https://doi.org/{r.get("doi") or ""}",'
                        f'"{r["file"]}"\n')
        emit_scripts(bad)
    m.log(f"待补官方版 {len(bad)} 篇 → data/cands.json + arxiv_非官方版本清单.csv"
          + ("  (dry-run 未落盘)" if a.dry_run else ""))
    print("  按出版社:", dict(collections.Counter(publisher_of(r.get("doi")) for r in bad)))

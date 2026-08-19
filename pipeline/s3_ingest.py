# -*- coding: utf-8 -*-
"""S3-ingest 归档手动下载的官方 PDF

从桌面/Downloads 收 TPAMI_*.pdf / NAT_*.pdf，逐个校验（拒 HTML 登录页、arXiv 版、
作者 LaTeX 稿、页数过少、无出版社标记），通过后改名放进 fulltext/。
认名优先用 data/下载文件名映射.json；服务器改过名就从正文 DOI 反查。

用法: python3 run.py ingest [--dry-run] [--dl 目录 ...] [--keep]
"""
import os, re, sys, json, shutil, argparse
import config as C, common as m

def main(argv):
    ap = argparse.ArgumentParser(prog="ingest")
    ap.add_argument("--dl", nargs="*",
                    default=[os.path.expanduser("~/Desktop"), os.path.expanduser("~/Downloads")])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true", help="归档后不删源文件")
    ap.add_argument("--pattern", default=r"(TPAMI|NAT|SCI|OUP|ELS)_.*\.pdf$")
    a = ap.parse_args(argv)

    mp = f"{C.DATA}/下载文件名映射.json"
    MAP = json.load(open(mp, encoding="utf-8")) if os.path.exists(mp) else {}
    cp = f"{C.DATA}/cands.json"
    CANDS = json.load(open(cp, encoding="utf-8")) if os.path.exists(cp) else []
    by_doi = {}
    for c in CANDS:
        if c.get("doi"):
            by_doi.setdefault(m.norm_doi(c["doi"]), []).append(c["file"])
    if not MAP and not by_doi:
        m.die("缺少 data/下载文件名映射.json 与 cands.json，先跑 run.py audit")

    pat = re.compile(a.pattern)
    seen, ok, bad, dup = set(), 0, 0, 0
    for d in a.dl:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not pat.match(f):
                continue
            src = os.path.join(d, f)
            base = re.sub(r" \(\d+\)(?=\.pdf$)", "", f)     # 去掉 Chrome 的 "(1)"
            kind, why, pages = m.pdf_version(src)
            if kind != "official":
                print(f"  ✗ {f[:44]:44s} {kind}: {why}")
                bad += 1
                continue
            doi = None
            try:
                t, _ = m.pdf_text(src, pages=2)
                doi = m.doi_in_text(t)
            except Exception:
                pass
            tgts = [MAP[base]] if base in MAP else by_doi.get(doi or "", [])
            if not tgts:
                print(f"  ? {f[:44]:44s} 认不出对应论文 (正文DOI={doi})")
                bad += 1
                continue
            if base in seen:
                print(f"  ⊘ {f[:44]:44s} 重复下载")
                dup += 1
            else:
                seen.add(base)
                for t2 in tgts:
                    print(f"  ✓ {f[:44]:44s} {os.path.getsize(src)//1048576:3d}MB "
                          f"{pages:3d}页 → {t2[:52]}")
                    if not a.dry_run:
                        os.makedirs(C.FULLTEXT, exist_ok=True)
                        shutil.copyfile(src, os.path.join(C.FULLTEXT, t2))
                ok += 1
            if not a.dry_run and not a.keep:
                os.remove(src)
    left = [c for c in CANDS if not os.path.exists(os.path.join(C.FULLTEXT, c["file"]))]
    m.log(f"归档 {ok} / 重复 {dup} / 失败 {bad}" + ("  (dry-run 未落盘)" if a.dry_run else ""))
    m.log(f"清单剩余待补: {len(left)} / {len(CANDS)}")
    if ok and not a.dry_run:
        m.log("下一步: python3 pipeline/run.py extract  再  screen2 dump")

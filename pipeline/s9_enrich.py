# -*- coding: utf-8 -*-
"""S9 信息增强：为已抽取记录补 任务领域 / 文章类型 / SOTA 可对比性。

三个分类维度都作用在 S7 抽取结果之上，不再读 PDF，因此很便宜、可反复重跑。
口径表在 config.py（DOMAIN / PURE_BENCH / REVIEW / METHOD_OVERRIDE / RE_ST_*）。

作为库被 S8 交付构建引用；单独运行则打印各维度分布，用来核对口径合理性。
"""
import sys, os, re, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C, common as m

__all__ = ["domain", "art_type", "sota_status", "REVIEW"]
REVIEW = C.REVIEW


def domain(title, bench="", note=""):
    """任务领域。自上而下首个命中即返回——DOMAIN 的顺序本身就是优先级。"""
    t = f"{title} {bench} {note}"
    for name, pat in C.DOMAIN:
        if re.search(pat, t, re.I):
            return name
    return "其他"


def art_type(doi, title="", note=""):
    """文章类型。只查人工判定表——关键词推断在这件事上误判率过高。"""
    d = m.norm_doi(doi)
    if d in C.REVIEW:
        return "综述/复现报告"
    if d in C.METHOD_OVERRIDE:
        return "原创方法"
    if d in C.PURE_BENCH:
        return "纯基准评测"
    return "原创方法"


def sota_status(entry):
    """SOTA 可对比性三档，判据是已抽取的 sota 文本本身。

    完整   —— 同时有数值和对比对象，可直接照着复现对比
    无可对比数值 —— 论文确实没给跨方法定量对比，或数值只存在于图片表格
    部分   —— 只有排名或定性描述，需要人工再确认
    """
    b = (entry.get("sota") or "").strip()
    if C.RE_ST_NUM.search(b) and C.RE_ST_CMP.search(b) and not b.startswith("⚠️"):
        return "完整"
    if C.RE_ST_NOCMP.search(b) or b.startswith("⚠️"):
        return "无可对比数值"
    return "部分(仅排名或定性)"


def main(argv):
    E = json.load(open(f"{C.DATA}/extracted.json", encoding="utf-8"))
    D = {m.norm_doi(r["doi"]): r for r in m.read_jsonl(f"{C.DATA}/fulltext_digest.jsonl", True)}
    cd, ca, cs = collections.Counter(), collections.Counter(), collections.Counter()
    other = []
    for d, e in E.items():
        d = m.norm_doi(d)
        ti = (D.get(d) or {}).get("title") or e.get("title") or ""
        dm = domain(ti, e.get("bench", ""), e.get("note", ""))
        cd[dm] += 1; ca[art_type(d, ti)] += 1; cs[sota_status(e)] += 1
        if dm == "其他":
            other.append(f"{d}  {ti[:70]}")

    n = len(E)
    print(f"已抽取 {n} 篇\n")
    for name, c in (("任务领域", cd), ("文章类型", ca), ("SOTA 可对比性", cs)):
        print(f"── {name} ──")
        for k, v in c.most_common():
            print(f"  {k:<18s} {v:>4d}  {v*100/n:5.1f}%")
        print()
    if other:
        print(f"── 未归类（DOMAIN 需补规则）{len(other)} 篇 ──")
        for x in other[:25]:
            print("  ", x)


if __name__ == "__main__":
    main(sys.argv[1:])

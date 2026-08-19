# -*- coding: utf-8 -*-
"""S0 期刊清单：合并三份来源 → data/merged_journals.json + 期刊清单_v2.xlsx

来源：① 原目标清单  ② JCR IF≥15 全量  ③ Nature 大子刊
去重按刊名规范化；剔除 config.JOURNAL_BLOCKLIST（Scientific Data/Reports 类）。
用法: python3 run.py journals [--rebuild-xlsx]
"""
import os, re, sys, json, argparse, collections
import config as C, common as m

def nkey(s):
    """刊名规范化：大小写、标点、Transactions/Trans. 缩写统一。"""
    s = (s or "").lower().strip()
    s = s.replace("&", "and")
    s = re.sub(r"\btransactions\b", "trans", s)
    s = re.sub(r"\bjournal\b", "j", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

RESEARCH = "研究刊"

def merge(sources):
    """sources: [(标签, [记录])] → 去重合并，保留最先出现的字段并累计来源标签。"""
    out, idx = [], {}
    for tag, rows in sources:
        for r in rows:
            k = nkey(r.get("name"))
            if not k:
                continue
            if k in idx:
                cur = out[idx[k]]
                cur["来源"] = sorted(set(cur["来源"].split("+")) | {tag})
                cur["来源"] = "+".join(cur["来源"])
                for f in ("issn", "jcr", "jtype", "field", "pub"):
                    if not cur.get(f) and r.get(f):
                        cur[f] = r[f]
            else:
                idx[k] = len(out)
                out.append({**r, "来源": tag})
    return out

def scanned(j):
    """实际会被 harvest 抓取的：研究刊 + 有 ISSN + 不在 blocklist。"""
    return (j.get("jtype") == RESEARCH and bool(j.get("issn"))
            and j.get("name") not in C.JOURNAL_BLOCKLIST)

def export_xlsx(js):
    wb = m.new_book()
    ws = wb.create_sheet("合并期刊清单")
    cols = ["#", "期刊名", "ISSN", "JCR IF", "刊型", "领域", "出版社", "来源", "是否扫描", "不扫原因"]
    ws.append(cols)
    for i, j in enumerate(sorted(js, key=lambda x: -(x.get("jcr") or 0)), 1):
        why = ("" if scanned(j) else
               ("数据/报告刊，无 benchmark pipeline" if j.get("name") in C.JOURNAL_BLOCKLIST
                else "综述刊" if j.get("jtype") != RESEARCH else "无 ISSN，无法按刊抓取"))
        ws.append([i, j.get("name"), j.get("issn"), j.get("jcr"), j.get("jtype"),
                   j.get("field"), j.get("pub"), j.get("src"),
                   "是" if scanned(j) else "否", why])
    m.style_sheet(ws, [5, 52, 12, 9, 10, 20, 26, 20, 9, 30])

    ws = wb.create_sheet("统计")
    ws.append(["项", "值", "说明"])
    for k, v, note in [
            ("期刊总数", len(js), "三份来源合并去重后"),
            ("实际扫描", sum(1 for j in js if scanned(j)), "研究刊 + 有 ISSN + 非数据刊"),
            ("综述刊(不扫)", sum(1 for j in js if j.get("jtype") != RESEARCH), "无自研 benchmark"),
            ("数据/报告刊(不扫)",
             sum(1 for j in js if j.get("name") in C.JOURNAL_BLOCKLIST), "你指定排除"),
            ("无 ISSN(不扫)", sum(1 for j in js if not j.get("issn")), "无法按刊抓取"),
            (f"IF≥{C.IF_FLOOR}", sum(1 for j in js if (j.get("jcr") or 0) >= C.IF_FLOOR), ""),
            ("IF≥30", sum(1 for j in js if (j.get("jcr") or 0) >= 30), "")]:
        ws.append([k, v, note])
    ws.append(["", "", ""])
    ws.append(["来源分布", "", ""])
    for k, v in collections.Counter(j.get("src") or "?" for j in js).most_common():
        ws.append([f"  {k}", v, ""])
    m.style_sheet(ws, [30, 12, 40])

    ws = wb.create_sheet("筛选标准")
    ws.append(["维度", "要求"])
    for r in [("论文类型", "提出 agent 系统 / AI 系统 / 模型（垂直或通用域均可）"),
              ("benchmark", "必须有明确、AI 可复现的 benchmark pipeline"),
              ("测试集", "必须公开可下载"),
              ("评估方式", "必须 AI 可自动化；排除湿实验 / 硬件测评 / 人工评测"),
              ("SOTA", "论文中必须报告可对比的 SOTA 数值"),
              ("模型", "尽量公开")]:
        ws.append(list(r))
    m.style_sheet(ws, [16, 76])

    ws = wb.create_sheet("执行流程")
    ws.append(["步骤", "命令", "产出", "说明"])
    for r in [("S0 期刊清单", "run.py journals", "期刊清单_v2.xlsx", "三份来源合并去重"),
              ("S1 元数据拉取", "run.py harvest crossref|epmc|s2|jmlr|merge",
               "data/works_merged.jsonl", "多源互补，Crossref 摘要覆盖差需 EPMC/S2 补"),
              ("S2 一轮筛选", "run.py screen1 recall|triage|dump|save|export",
               "第一轮筛选结果.xlsx", "关键词召回 + 规则分流，只对剩下的读标题+摘要"),
              ("S3 全文获取", "run.py fetch", "fulltext/", "只要出版社官方版，排除预印本仓储"),
              ("S3 版本审计", "run.py audit", "data/cands.json + 下载脚本_*.js",
               "揪出 arXiv/作者稿并隔离，生成机构权限下载脚本"),
              ("S3 归档", "run.py ingest", "fulltext/", "校验手动下载的 PDF 后改名归档"),
              ("S4 信号抽取", "run.py extract", "data/fulltext_digest.jsonl",
               "抽链接/基准/SOTA/指标/红旗"),
              ("S5 二轮筛选", "run.py screen2 dump|save|export", "第二轮筛选结果.xlsx",
               "四维判定 + 复刻优先级 S/A/B/C"),
              ("S6 去重", "run.py dedupe", "data/baseline_dois.json", "与既有 54 篇比对"),
              ("S7 信息抽取", "run.py info dump|save|export", "信息抽取_新增候选.xlsx",
               "填 14 字段结构")]:
        ws.append(list(r))
    m.style_sheet(ws, [16, 46, 34, 52])

    os.makedirs(os.path.dirname(C.XLSX_JOURNALS), exist_ok=True)
    wb.save(C.XLSX_JOURNALS)
    return C.XLSX_JOURNALS

def main(argv):
    ap = argparse.ArgumentParser(prog="journals")
    ap.add_argument("--rebuild-xlsx", action="store_true",
                    help="只用已有 merged_journals.json 重出 xlsx，不重新合并")
    a = ap.parse_args(argv)
    p = f"{C.DATA}/merged_journals.json"
    if a.rebuild_xlsx or os.path.exists(p):
        js = json.load(open(p, encoding="utf-8"))
        m.log(f"载入已有清单 {len(js)} 本")
    else:
        m.die(f"缺少 {p}。首次构建需先准备三份来源清单（见 pipeline/README.md「S0」）")
    out = export_xlsx(js)
    m.log(f"期刊 {len(js)} 本（实际扫描 {sum(1 for j in js if scanned(j))} 本）→ {out}")
    print("  来源分布:", dict(collections.Counter(j.get("src") or "?" for j in js).most_common()))
    print("  刊型:", dict(collections.Counter(j.get("jtype") for j in js).most_common()))

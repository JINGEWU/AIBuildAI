# -*- coding: utf-8 -*-
"""复现侧专用的判定表。

这些只在复现已发布交付时用到，不属于正式流程，所以从 config.py 挪出来——
config.py 是正式 pipeline 的唯一规则文件，不该混进历史包袱。
"""
# ── 期刊缩写映射 ──
# main/papers 的旧表用期刊缩写（Nat Commun），期刊清单用全名（Nature Communications）。
# 清单的 abbr 字段是空的，只能显式映射；复刻分用的 TOP_JOURNAL_BONUS 也按全名取键。
JOURNAL_ABBR = {
    "Nat Biomed Eng": "Nature Biomedical Engineering",
    "Nat Cancer": "Nature Cancer",
    "Nat Commun": "Nature Communications",
    "Nat Comput Sci": "Nature Computational Science",
    "Nat Electron": "Nature Electronics",
    "Nat Hum Behav": "Nature Human Behaviour",
    "Nat Mach Intell": "Nature Machine Intelligence",
    "Nat Med": "Nature Medicine",
    "Nat Methods": "Nature Methods",
    "Nature": "Nature",
    "Nature Health": "Nature Health",
    "Nature Water": "Nature Water",
    "npj Digit Med": "npj Digital Medicine",
}

# main/papers 里属于「纯基准评测」的（只提供评测集与横向排名，无自研待超越的方法）。
# 与 PURE_BENCH 分开维护，因为那张表是按 batch2/3 的 DOI 建的。
BASELINE_PURE_BENCH = {
    "10.1038/s41591-024-03328-5",   # CRAFT-MD 对话化评测框架
    "10.1038/s44360-026-00152-8",   # 动态红队医学基准
    "10.1038/s41746-026-02674-7",   # AgentClinic
    "10.1038/s41746-026-02443-6",   # AgentBenchMedicine 横评
    "10.1038/s41562-025-02172-y",   # Playing repeated games with LLMs（行为评测研究）
}

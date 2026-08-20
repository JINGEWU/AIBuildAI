# -*- coding: utf-8 -*-
"""复现侧专用的判定表。

只在复现已发布交付时用到，不属于正式流程，所以从 config.py 挪出来——
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

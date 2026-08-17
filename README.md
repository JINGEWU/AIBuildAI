# AIBuildAI — Nature 系 Agent 论文可复刻性评估

2025–2026 年 Nature 正刊、Nature 子刊、Nature Communications 与 npj Digital Medicine 中
**AI/LLM agent 系统与基准**的原创研究论文清单，按「AI 能否自动化评估」分级。

## 目录

```
papers/
├── 54 × 期刊_年份_标题_文章ID.pdf
└── agent_papers_SOTA_evaluation.xlsx
```

## 表格字段

`papers/agent_papers_SOTA_evaluation.xlsx` — 54 篇，字段包括：

| 字段 | 说明 |
|---|---|
| Benchmark 名称 / 规模 / 链接 | 评测集及其公开获取地址 |
| 论文报告的 SOTA | 从正文原句提取的最好成绩 |
| 评估指标 & 计算方式 | 指标如何计算、是否需要人评/湿实验/硬件 |
| 自动化等级 | A+ 可执行验证 · A 有 ground truth · B 需 LLM-judge · C 需人评 |
| 代码链接 | 开源仓库 |

## 方法

Crossref API 全量枚举 44 本 Nature 冠名刊 + npj Digital Medicine 的 2025–2026 全部
journal-article（共扫描约 48,700 篇），本地正则过滤 agent 相关，逐篇抓取 Nature 页面
的 article type 标签判定 research 原创，再从 PDF 全文提取 SOTA 数值与评估方法。

## 说明

论文全文 PDF 位于 `papers/`，文件名格式为 `期刊_年份_标题_文章ID.pdf`，与表格逐行一一对应。

⚠️ 这些 PDF 受出版商版权保护，仅供内部研究使用，请勿公开分发。本仓库为私有仓库。

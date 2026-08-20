# AIBuildAI — 可复刻 AI 论文候选库

面向 2025–2026 年 Nature 系、IEEE TPAMI、Science、Cell 系、Lancet 系等期刊中
**AI/LLM agent 系统与基准**的原创研究论文，筛出能被 AI 自主复刻的那批，并做优先级分级。

判据只回答一个问题：**AI 能不能自己把这篇论文的评测跑一遍，并对上它报告的 SOTA？**

## 目录结构

```
papers/     早期 54 篇 + 旧格式评估表(14 列)
batch2/     254 篇：pdfs_batch2/ + 信息抽取batch2.xlsx(23 列)
batch3/      60 篇：pdfs_batch3/ + 信息抽取batch3.xlsx(23 列)
pipeline/   流水线：正式版 20 个模块 + legacy/ 复现工具 6 个
data/       三个判定文件（见下）
```

`data/` 整体不入库，只对三个文件开了例外——它们是人和模型的判断，程序重算不出来，
而所有交付表都由它们生成：

| 文件 | 内容 | 丢了的代价 |
|---|---|---|
| `data/verdicts2.json` | 582 篇四维判读 | 重判 582 篇 |
| `data/extracted.json` | 396 篇 14 字段抽取 | 逐篇重读 PDF |
| `data/baseline_verdicts.json` | 54 篇三维判定 | 重判 54 篇 |

## 交付批次

三套交付物，互不重复（合计 368 篇 = 368 个唯一 DOI）：

| 批次 | 篇数 | 汇总表 | PDF 目录 |
|---|---|---|---|
| papers | 54 | `papers/agent_papers_SOTA_evaluation.xlsx` | `papers/` |
| batch2 | 254 | `batch2/信息抽取batch2.xlsx` | `batch2/pdfs_batch2/` |
| batch3 | 60 | `batch3/信息抽取batch3.xlsx` | `batch3/pdfs_batch3/` |

`batch2` 与 `batch3` 判据、字段完全一致（23 列），分成两批只因 batch3 的官方全文
是后来补齐下载的。`papers/` 是早期语料，表只有 14 列。

每篇的 Benchmark 名称与规模、SOTA 数值、评估指标计算方式、复刻备注都是**逐篇打开 PDF
读出来的**，抽不到就明确标注，不做推测。

核对三套是否仍自洽：

```bash
python3 pipeline/legacy/reproduce.py verify
```

## 入选标准

必须**同时**满足：

1. 提出 agent 系统 / AI 系统 / 模型
2. 有明确的、AI 可复现的 benchmark pipeline
3. **测试集公开可下载**（部分公开也算，如 29 个测试集里公开 10 个）
4. **评估可自动化** —— 排除湿实验、硬件测评、以人工评测为主判据的
5. **论文中报告了可对比的 SOTA 数值**

## 复刻优先级

```
可自动化(40) + 基准公开(25) + SOTA标注(10) + 期刊影响力 + 链接与公开基准数 + 头顶空间(12)
                                          − 人评/湿实验/硬件依赖惩罚
```

分档 **S ≥88 / A ≥78 / B ≥66 / C**。C 档按约定不交付。

自动化等级：`A+` 可执行验证（单元测试 / Pass@k）> `A` 有 ground truth 的客观指标 >
`B` 需 LLM-as-judge > `C` 需人评·湿实验·硬件（已排除）。

## Pipeline

`pipeline/` 下有**两套**东西：

| | 位置 | 用途 |
|---|---|---|
| **正式版** | `pipeline/run.py` | 未来一次性跑完新论文，不分批次 |
| **复现版** | `pipeline/legacy/reproduce.py` | 只为重建已发布的三个批次，日常不用 |

依赖单向：正式版不引用 legacy 任何东西。

### 正式版

```bash
python3 pipeline/run.py status     # 全流程体检，看每步到哪了
python3 pipeline/run.py --list     # 列出所有阶段
```

12 个阶段，前 6 步把 33 万篇元数据收敛成带证据的候选，后 6 步做判定、定级与交付：

```
S0 journals ─→ S1 harvest ─→ S2 screen1 ─→ S3 fetch ─→ S3 audit ─→ S3 ingest-dir
   期刊清单       元数据 33万    标题+摘要     抓官方全文   版本审计     归档人工下载
                                                                  │
   S7 info ←── S6 dedupe ←── S5 screen2 ←── S4 extract ←──────────┘
   14字段抽取    去重         全文判定+定级   正文信号抽取
      │
      └─→ S9 enrich ──→ S8 build
          领域/类型分档    出交付物
```

典型的一轮增量（拿到新论文后）：

```bash
python3 pipeline/run.py ingest-dir <人工下载目录>   # 归档，正文 DOI 优先、标题模糊匹配兜底
python3 pipeline/run.py extract                    # 抽正文信号
python3 pipeline/run.py screen2 dump|save|export    # 判定 + 定级
python3 pipeline/run.py info    dump|save|export    # 逐篇读 PDF 抽 14 字段
python3 pipeline/run.py build                       # 出交付物
python3 pipeline/run.py needlist                    # 还缺哪些官方 PDF
```

三个设计取向：

- **规则集中**。关键词、正则、权重、期刊清单、领域分类全在 `pipeline/config.py`，
  改规则只动这一个文件。
- **判读不假装自动化**。`screen1`/`screen2`/`info` 都是 `dump → 判 → save`：
  dump 出批次给模型或人读，判完 save 回写。永远按 DOI 对齐而非行号——行号会因排序变化错位。
- **交付不分批次**。逼出分批的从来不是筛选逻辑，而是文件命名：`A001_标题.pdf` 按复刻分
  排序，加一篇论文就要把所有文件重命名。S8 改用与排序无关的稳定命名
  （`期刊_年_标题_DOI尾号`）且幂等——只补缺失、只删已不合格，反复跑结果一致。

### 复现版

```bash
python3 pipeline/legacy/reproduce.py verify          # 核对三套交付物是否仍自洽
python3 pipeline/legacy/reproduce.py batch2|batch3   # 重建已发布批次
python3 pipeline/legacy/reproduce.py import-legacy   # 旧表导入（一次性迁移，已执行）
```

它保留了旧的 `A001_` 档位编号逻辑——正是当初逼出分批的根源——只为在需要对账时
一字不差地重建已发出去的 batch2/batch3。重建默认拒绝覆盖已有目录，`--xlsx-only`
只重出表格（复用现有文件名），`--force` 才作废旧名重建。

完整说明见 [`pipeline/README.md`](pipeline/README.md)，
复现侧见 [`pipeline/legacy/README.md`](pipeline/legacy/README.md)。

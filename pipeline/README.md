# 论文发现 pipeline

从顶刊里捞出**可复现、可对标**的 AI/agent 论文：拉全量元数据 → 两轮筛选 → 只取官方全文 →
抽取复刻所需信息，并给出复刻优先级 S/A/B/C。

## 两套东西

| | 位置 | 用途 |
|---|---|---|
| **正式 pipeline** | `run.py` + `s0…s10` | 未来一次性跑完新论文，不分批次 |
| **复现工具** | `legacy/reproduce.py` | 只为重建已发布的 batch2/batch3/main，日常不用 |

正式流程不引用 legacy 任何东西（`grep -rn legacy *.py` 只会命中一行注释）。
反向则复用父目录的 `config.py`/`common.py`/`s9_enrich.py`。
详见 [`legacy/README.md`](legacy/README.md)。

## 入选标准

必须**同时**满足，缺一条即排除：

| 维度 | 要求 |
|---|---|
| 论文类型 | 提出 agent 系统 / AI 系统 / 模型（垂直域、通用域都算） |
| benchmark | 有明确的、AI 可复现的 benchmark pipeline |
| 测试集 | 公开可下载 |
| 评估方式 | AI 可自动化。**排除**湿实验、硬件测评、人工评测 |
| SOTA | 论文中报告了可对比的 SOTA 数值 |
| 模型 | 尽量公开（非硬性） |

判定用两个正交维度记录，避免"能不能复刻"和"值不值得复刻"混在一起：

- **可自动化等级** `A+` 可执行验证(单元测试/Pass@k) > `A` 客观指标(准确率/AUROC/mIoU) >
  `B` LLM-as-judge > `C` 人评/湿实验/硬件
- **基准公开度** `是`(有直达链接) / `部分`(用公开基准但自建测试集受限) / `否`

**复刻优先级** 由两者加权算出（权重见 `config.py`），S 档最值得先做。

## 快速开始

```bash
python3 pipeline/run.py status        # 全流程体检，会告诉你下一步该跑什么
python3 pipeline/run.py --list        # 列出所有阶段
```

## 流程

```
S0 journals ──→ S1 harvest ──→ S2 screen1 ──→ S3 fetch ──→ S3 audit ──→ S3 ingest / ingest-dir
   期刊清单        元数据 33万     标题+摘要      抓官方全文    版本审计      归档人工下载
                                                                     │
   S7 info ←── S6 dedupe ←── S5 screen2 ←── S4 extract ←─────────────┘
   14字段抽取     去重         全文判定+定级     正文信号抽取
      │
      └─→ S9 enrich ──→ S8 build ──→ push_batch.sh
          领域/类型/SOTA   一套交付物      分批推 GitHub

   S10 needlist（旁路）→ 还缺哪些官方 PDF
```

### 不分批次
交付只有一套。逼出分批的从来不是筛选逻辑——batch2 与 batch3 判据、字段完全相同——
而是**文件命名**：`A001_标题.pdf` 这种按复刻分排序的序号，一加新论文排名就变、
所有文件都要重命名，于是只能把每次的结果冻成一批。

S8 改用**与排序无关的稳定命名**，直接沿用全文库的 `期刊_年_标题_DOI尾号.pdf`：
新增论文只新增文件、永不改名，一个平铺目录就够。排序交给表里的「复刻分」列。
S8 是幂等的——只补缺失、只删已不合格（`--prune`），反复跑结果一致。
所以下次拿到新论文，跑一遍 `extract → screen2 → info → build` 就是完整交付，不需要规划批次。

早期 `papers/` 那 54 篇也不再是特例：`run.py info import` 把它们的旧表导进
`extracted.json` 后，和其他论文走同一条路。

| 阶段 | 命令 | 产出 |
|---|---|---|
| S0 | `run.py journals` | `期刊清单_v2.xlsx` |
| S1 | `run.py harvest crossref\|epmc\|s2\|jmlr\|merge` | `data/works_merged.jsonl` |
| S2 | `run.py screen1 recall\|triage\|dump\|save\|export` | `第一轮筛选结果.xlsx` |
| S3 | `run.py fetch` | `fulltext/` |
| S3 | `run.py audit` | `data/cands.json`、`data/下载脚本_*.js` |
| S3 | `run.py ingest` | `fulltext/` |
| S4 | `run.py extract` | `data/fulltext_digest.jsonl` |
| S5 | `run.py screen2 dump\|save\|export` | `第二轮筛选结果.xlsx` |
| S6 | `run.py dedupe` | `data/baseline_dois.json` |
| S7 | `run.py info dump\|save\|export` | `信息抽取_新增候选.xlsx` |
| S8 | `run.py build [--tiers SAB\|--xlsx-only\|--prune\|--dry-run]` | `delivery/`（`pdfs/` + `信息抽取.xlsx`） |
| S9 | `run.py enrich` | 领域/类型/SOTA 分布（被 S8 引用） |
| — | `legacy/reproduce.py verify` | 核对三套已发布交付物是否仍自洽 |
| — | `legacy/reproduce.py batch2\|batch3\|index\|import-legacy` | 复现历史交付 |
| S10 | `run.py needlist` | `待手动下载_batch2.xlsx` + `.csv` |
| 工具 | `run.py pdftools mine\|deep\|tables\|pages\|render\|shrink <DOI...>` | 证据文本 / PNG / 压缩后 PDF |
| 工具 | `./push_batch.sh <目录> [每批MB]` | 分批 commit+push |

### S8 的幂等与命名
文件名沿用全文库的 `期刊_年_标题_DOI尾号`，不带档位序号——档位会随分数变，
带进文件名就意味着重命名。每次运行只做三件事：补缺失的 PDF、报告已不合格的
（`--prune` 才删）、重出表格。因此可以随时重跑，不会打乱已经发出去的文件。

旧的 `A001_` 编号逻辑搬到了 `legacy/build_batch.py`，只为复现已发布的 batch2/batch3；
它默认拒绝覆盖已有目录，要 `--force` 才会作废旧名重建。

### S7 信息抽取的四级手段
`pdftools` 按成本从低到高排，前一级拿不到再上后一级：

| 手段 | 用途 | 局限 |
|---|---|---|
| `mine` | 挖带数值的跨方法对比句，补 SOTA 最高效 | 只覆盖正文，表格里的抓不到 |
| `deep` | 分类抽 规模/指标定义/可得性/对比句，首次通读用 | 同上 |
| `tables` | 按文字块坐标重建无框线表格 | **表格是图片时完全失效** |
| `pages` + `render` | 定位结果页并渲染 PNG，交给视觉阅读 | 最贵，但兜得住图片表 |

IEEE 表格常为图片、Nature 结果常在图里——这两种只能走 `render`。

### 判读环节不假装自动化

S2 / S5 / S7 各有一个需要"读"的环节。pipeline 不把它藏进代码里假装自动，而是显式三段式：

```bash
run.py screen2 dump --batch 0 --size 45 --out /tmp/w2_0.txt   # 出批次(含证据摘要)
#   ... 由模型或人逐条判读，按行尾格式补上结论 ...
run.py screen2 save --file /tmp/w2_0.txt                       # 回写
```

每行以 `#序号@DOI` 开头，**回写按 DOI 对齐，不依赖行号** —— 早期版本按行号对齐，
批次间序号一错位就静默覆盖了上一批的判读结果，这个坑已经堵掉。

回写格式：

| 阶段 | 格式 |
|---|---|
| screen1 | `#i@doi\|判定(入选/待定/排除)\|置信(高/中/低)\|理由` |
| screen2 | `#i@doi\|判定\|可自动化(A+/A/B/C)\|基准公开(是/部分/否)\|SOTA(有/无)\|备注` |
| info | `#i@doi\|Benchmark名称\|规模\|SOTA数值\|评估指标&计算方式\|复刻备注` |

## 只要官方版，不要 arXiv 版

`fetch` 的源顺序把预印本仓储全部排除（`config.RE_BAD_HOST`）。`audit` 再逐个读 PDF 首页复核：

- 有 `arXiv:xxxx.xxxxxv3 [cs.XX]` 侧边戳 → `arxiv`
- 有 `JOURNAL OF LATEX CLASS FILES` 模板标记 → `preprint`
- 没有真出版商指纹 → `preprint?`

判"官方"要求真指纹：`Digital Object Identifier`、正文真 DOI、`© 20xx <出版商>`、
期刊 ISSN、真实卷期号 `VOL. 47, NO. 8` 等。

> **两个踩过的坑**（都在 `config.py` 里留了注释）：
> 1. 裸刊名页眉 `IEEE TRANSACTIONS` 和裸 `© 2025` **不能**当官方标记 —— 作者接收稿也有，
>    会把预印本误判成官方版。
> 2. arXiv 侧边戳正则必须允许版本号 `v3`。漏了它会让 90+ 篇 arXiv 版蒙混过关。

非官方版移入 `arxiv_隔离/`，同时生成 `data/下载脚本_<出版商>.js`：浏览器登录机构账号后
在 console 里跑，批量触发官方 PDF 下载；下完 `run.py ingest` 校验归档（会拒掉 HTML 登录页、
arXiv 版、作者稿、页数过少的）。

规则收紧后如果发现隔离区有误判的，`run.py audit --restore-official` 可回补。
`--dry-run` 只报告，不动文件也不写任何清单。

## 数据源现状

| 源 | 状态 | 说明 |
|---|---|---|
| Crossref | ✅ 主力骨架 | 全，但摘要覆盖差：IEEE / Elsevier / Cell Press 近 0% |
| Europe PMC | ✅ | 生医刊自带摘要，免费无额度；OA 子集可取全文 XML/PDF |
| Semantic Scholar | ✅ 补摘要 | `/paper/batch` 一次 500 个 DOI |
| Unpaywall | ✅ 找官方 OA | `host_type=publisher` 的优先 |
| JMLR / TMLR | ✅ 官网爬 | 不进 Crossref |
| **OpenAlex** | ❌ **已转付费** | 免费额度只够几百请求，超了返回 `Insufficient budget` |
| **OpenReview** | ❌ **已上 CAPTCHA** | 403 + challengeUrl，TMLR 摘要拿不到，只能靠标题筛 |

IEEE 不做金色 OA，TPAMI 只有作者放在 arXiv 的预印本 —— 官方版**只能靠机构权限**，
这不是 pipeline 能绕过的，所以才有 `audit` + 浏览器脚本 + `ingest` 这条人机协作路径。

## 断点续传与并行

所有耗时阶段都以 DOI 为主键记 state，中断后重跑自动跳过已完成的：

```bash
for i in 0 1 2 3 4; do
  python3 pipeline/run.py fetch --shard $i/5 > logs/fetch_$i.log 2>&1 &
done; wait
```

分片用 `md5(key) % N` 稳定哈希，多次运行分配一致。state 落盘走临时文件 + 原子替换，
中断不会留下半个 JSON。

## 关键假阳性（已在 `config.py` 里规则化）

一轮筛选靠关键词召回，量大，两类假阳性会淹没结果：

1. **控制论的 "multi-agent"** —— IEEE Cybernetics / TNNLS / Neural Networks 里
   `consensus control`、`containment`、`event-triggered`、`prescribed-time` 这类指的是
   多智能体**控制系统**，不是 LLM agent。约 400 篇。有 LLM/benchmark 反证词的会被捞回。
2. **"multiagent chemotherapy"** —— Blood / JCO 的会议摘要里指联合化疗。被会议摘要规则拦掉。

自动排除的每一类都单独存 `data/grp_*.jsonl`，并在 `第一轮筛选结果.xlsx` 留抽样核查页，
方便回查有没有误杀。

## 文件布局

```
pipeline/
  run.py            统一入口 + status
  config.py         全部规则：路径/关键词/正则/权重/期刊    ← 改规则只动这里
  common.py         限速HTTP、断点state、DOI规范化、分片、PDF版本判定、评分
  s0_journals.py … s10_needlist.py
  s8_build.py       交付构建（无批次，稳定命名，幂等）
  legacy/           复现已发布交付的独立工具，日常不用
    reproduce.py    统一入口（含各批次当初的构建参数）
    build_batch.py  旧的 A001_ 档位编号构建器
    merge_index.py  把三套已发布交付拼成总表
    import_legacy.py 旧表 → extracted.json 的一次性迁移
    tables.py       只服务复现的判定表（从 config.py 挪出）
  pdftools.py       PDF 证据抽取四件套 + 交付前压缩
  push_batch.sh     大批量二进制分批推送（单次 push 超 ~100MB 易被掐断，且无断点续传）
data/               中间产物（jsonl + state json）
fulltext/           官方全文 PDF / JATS XML
arxiv_隔离/          审计出的非官方版
papers/             既有 54 篇基线语料
logs/
delivery/           交付物：pdfs/ + 信息抽取.xlsx（S8 产出，不分批次）
batch2/ batch3/     历史交付批次，命名与 delivery/ 不同，保留以免打断在用的引用
```

依赖：`openpyxl`、`PyMuPDF`、`Pillow`（仅 `pdftools shrink` 用；其余全用标准库）。

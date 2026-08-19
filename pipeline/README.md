# 论文发现 pipeline

从顶刊里捞出**可复现、可对标**的 AI/agent 论文：拉全量元数据 → 两轮筛选 → 只取官方全文 →
抽取复刻所需信息，并给出复刻优先级 S/A/B/C。

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
S0 journals ──→ S1 harvest ──→ S2 screen1 ──→ S3 fetch ──→ S3 audit ──→ S3 ingest
   期刊清单        元数据          标题+摘要       官方全文      版本审计      归档手动下载
                                                                   │
   S7 info ←── S6 dedupe ←── S5 screen2 ←── S4 extract ←───────────┘
   14字段抽取     去重         全文判定+定级      信号抽取
```

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
  s0_journals.py … s7_extract_info.py
data/               中间产物（jsonl + state json）
fulltext/           官方全文 PDF / JATS XML
arxiv_隔离/          审计出的非官方版
papers/             既有 54 篇基线语料
logs/
```

依赖：`openpyxl`、`PyMuPDF`（其余全用标准库）。

# AIBuildAI — Agent/基础模型论文全文库与可复刻性评估

面向 2025–2026 年 Nature 系、IEEE TPAMI、Science、Cell 系、Lancet 系等期刊中
**AI/LLM agent 系统与基准**的原创研究论文,建立**官方版全文库**并做可复刻性分级。

## 目录结构

仓库里实际有的（其余目录是本地工作区，按 `.gitignore` 不上传）：

```
papers/                早期 54 篇 Nature 系 agent 论文 + 旧格式评估表(14 列)
batch2/                254 篇：pdfs_batch2/ + 信息抽取batch2.xlsx(23 列)
batch3/                 60 篇：pdfs_batch3/ + 信息抽取batch3.xlsx(23 列)
pipeline/              流水线 20 个模块 + legacy/ 复现工具 6 个
data/                  三个判定文件(见下)，data/ 其余内容不入库
```

`data/` 只对三个文件开了例外——它们是人和模型的判断，程序重算不出来，
而所有交付表都由它们生成：

| 文件 | 内容 | 丢了的代价 |
|---|---|---|
| `data/verdicts2.json` | 582 篇四维判读 | 重判 582 篇 |
| `data/extracted.json` | 396 篇 14 字段抽取 | 逐篇重读 PDF |
| `data/baseline_verdicts.json` | 54 篇三维判定 | 重判 54 篇 |

### 只存在于本地的工作目录

这些不上传，但下面「全文库现状」等章节的统计是基于它们的：

```
fulltext/              官方版全文库(主库，543 篇)
fulltext_xml/          EPMC JATS XML(表格被剥离，信息不全)
官方全文_整合/          全库快照 + _清单.csv(硬链接，不占额外空间)
arxiv_隔离/             审计出的 arXiv/预印本版(保留备查，105 篇)
_剔除_会议摘要/         1 页的会议摘要，非全文
_剔除_重复/             重复条目
114篇/  另 5 篇/        人工补齐下载的原始文件，已由 ingest-dir 归档进 fulltext/
data/                  抓取状态、元数据、下载脚本(除上表三个文件外均不入库)
logs/
```

## 交付批次

三套交付物，互不重复（合计 368 篇 = 368 个唯一 DOI）：

| 批次 | 篇数 | 汇总表 | PDF 目录 |
|---|---|---|---|
| papers | 54 | `papers/agent_papers_SOTA_evaluation.xlsx` | `papers/` |
| batch2 | 254 | `batch2/信息抽取batch2.xlsx` | `batch2/pdfs_batch2/` |
| batch3 | 60 | `batch3/信息抽取batch3.xlsx` | `batch3/pdfs_batch3/` |

`batch2` 与 `batch3` 判据、字段完全一致（23 列），分成两批只因 batch3 的官方全文
是后来补齐下载的。`papers/` 是早期语料，表只有 14 列。

核对三套是否仍自洽：

```bash
python3 pipeline/legacy/reproduce.py verify
```

## 入选标准（判据）

必须**同时**满足：

1. 提出 agent 系统 / AI 系统 / 模型
2. 有明确的、AI 可复现的 benchmark pipeline
3. **测试集公开可下载**（部分公开也算）
4. **评估可自动化** —— 排除湿实验、硬件测评、人工评测为主判据的
5. **论文中报告了可对比的 SOTA 数值**

流水线与判据实现见 [`pipeline/README.md`](pipeline/README.md)。

## 全文库现状

| 指标 | 数值 |
|---|---|
| `fulltext/` 官方版全文 | 543 |
| `arxiv_隔离/` 审计出的非官方版 | 105 |
| 其中由 arXiv/预印本换成官方版 | 80 |
| 人工补齐下载后归档 | 111（官方版 99 + IEEE 早期访问版 12） |

版本状态分布来自 `官方全文_整合/_清单.csv` 的「版本状态」列，
是**人工补齐那 111 篇之前**的快照（下表合计 434；该 csv 现有 432 行）：

| 状态 | 篇数 | 含义 |
|---|---|---|
| 正式刊出 | 378 | 出版社最终排版版 |
| 在版 Article in Press | 41 | 已有 DOI、正式版式，尚未定最终页码 —— 出版社当前唯一官方 PDF |
| IEEE Early Access | 13 | IEEE 官方发布的预出版形态（作者排版 + IEEE 模板） |
| 接受稿 | 2 | Journal of Hepatology、The Innovation 各一篇，待换最终版 |

补齐的 111 篇里另有 12 篇 IEEE 早期访问版，在 `data/fetch_state_manual.json` 里以
`manual-dir/early-access` 标注可追溯，各批次 README 也列了具体篇目。

## 非官方版识别与替换

起点是发现 `fulltext/` 里混入了大量 arXiv 版。识别依据是首页边栏的
`arXiv:XXXX.XXXXX vN [cs.CV] 日期` 水印(arXiv 下载件的确凿标记),
另加无出版社排版标记的作者稿。首轮审计识别 102 篇，后续补充至 **105 篇**，全部移入 `arxiv_隔离/`,
清单见 `arxiv_非官方版本清单.csv`（本地，不入库）。

## 官方 PDF 获取路径(按有效性排序)

1. **Playwright + 机构登录的 Chrome(CDP)** — 对 IEEE 唯一有效的路径
   服务端脚本一律被 WAF 拦截(IEEE 返回 202 空壳、Elsevier/Science/OUP 返回 403)。
   实际可行的做法是连接用户已登录的真实浏览器,导航到 `stamp.jsp` 阅读器,
   **从 `chrome-extension://` 的 PDF 流响应里截获字节** —— PDF 字节不走带 `.pdf`
   的 URL,只按 URL 过滤会全部漏掉,必须按 `content-type: application/pdf` 判断。
2. **nature.com 直链** — OA/hybrid 文章 `nature.com/articles/{id}.pdf` 可直接下载
3. **OpenAlex 查 OA 位置** — 只接受期刊托管的 publishedVersion,机构仓储的作者稿不算

### 权限边界(实测)

IEEE 按卷期授权,不是全刊通吃。同一账号下部分 TPAMI 文章可下、部分不可:
- 会话失效 → `stamp.jsp` **302 重定向**到文章页(连续 3 次自动停机)
- 该篇无授权 → 阅读器外壳能开,但 `getPDF.jsp` 返回 HTML(秒级判定)
- 页面元数据里的 `subscribedContent:false` **不可信** —— 该字段为 false 时仍可能下载成功

## 主要脚本

流水线在 `pipeline/`（随仓库分发）：

```bash
python3 pipeline/run.py status          # 全流程体检，看每步到哪了
python3 pipeline/run.py --list          # 列出所有阶段
```

12 个阶段：`journals → harvest → screen1 → fetch → audit → ingest → extract
→ screen2 → dedupe → info → enrich → build`，规则集中在 `pipeline/config.py`。
详见 [`pipeline/README.md`](pipeline/README.md)。

### 本地专用的浏览器抓取脚本（不入库）

IEEE 不做金色 OA，TPAMI 官方 PDF 需机构权限，这类只能靠真浏览器带登录态抓。
脚本在本地 `data/` 下，按 `.gitignore` 不上传（依赖个人机构账号与本机 Chrome 配置，
换机器也不可直接复用）：

| 脚本 | 用途 |
|---|---|
| `data/ieee_playwright.py` | 连 CDP 抓 IEEE 官方 PDF(隔离清单)，断点续传 |
| `data/tpami_csv_download.py` | 按 `待下载_TPAMI链接.csv` 批量补齐 TPAMI，优先级排序 + 连续 302 自动停机 |
| `data/oa_playwright.py` | 抓非 IEEE 的 OA 官方 PDF(Cloudflare 拦服务端，真浏览器可过) |
| `data/refetch_official.py` | 服务端找官方 OA 直链(对 Nature 系有效) |
| `data/verify_fulltext.py` | 全库质量核验 → `核验报告.csv`（本地） |
| `data/ingest_downloads.py` | 浏览器下到桌面的文件校验改名后归库 |
| `data/skip_dois.txt` | 显式跳过清单，所有下载脚本都遵守 |

人工下载完整目录后，用流水线归档（这一步在仓库里）：

```bash
python3 pipeline/run.py ingest-dir <目录>    # 正文 DOI 优先、标题模糊匹配兜底
python3 pipeline/run.py needlist             # 还缺哪些官方 PDF
```

### 前置:启动带调试端口的 Chrome

Chrome 136+ 禁止在默认配置上开调试端口,必须用独立 user-data-dir:

```bash
open -na "Google Chrome" --args --remote-debugging-port=9222 \
     --user-data-dir="$HOME/chrome-ieee-profile"
```

在弹出的窗口里完成机构登录(Institutional Sign In),然后运行脚本。
PDF 设置需为「在 Chrome 中打开」(靠阅读器加载时截获字节,设成「下载」反而抓不到)。

## 待下载与授权边界

`代下载清单.xlsx`(3 个工作表)是人工补下载的作业单:

- **代下载清单** 103 条,含可点的 IEEE 阅读器直链;已排除复刻优先级 C(判定为入选/待定的 C 级仍保留并标注)
- **已入库-版本状态** 全库核验结果,只有 2 篇真接受稿需要处理
- **统计与说明** 使用步骤

其中 98 条实测为**机构授权边界**:`institute=true`(机构已识别)但 `subscribedContent=false`、
`openAccessFlag=F`,文章页显示 Subscribe。会话保活 + 重新登录后复测结果一致,自动化已无解。

## 说明

⚠️ 全文 PDF 受版权保护,通过机构订阅合法获取,仅供内部研究,请勿公开分发。本仓库为私有仓库。

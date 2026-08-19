# AIBuildAI — Agent/基础模型论文全文库与可复刻性评估

面向 2025–2026 年 Nature 系、IEEE TPAMI、Science、Cell 系、Lancet 系等期刊中
**AI/LLM agent 系统与基准**的原创研究论文,建立**官方版全文库**并做可复刻性分级。

## 目录结构

```
fulltext/              官方版全文库(正在使用的主库)
官方全文_整合/          全库快照 + _清单.csv(硬链接,不占额外空间)
arxiv_隔离/             被替换下来的 arXiv/预印本版(保留备查)
_剔除_会议摘要/         1 页的会议摘要,非全文
papers/                早期 54 篇 Nature 系 agent 论文 + 评估表
data/                  抓取脚本、状态文件、元数据
```

## 全文库现状

| 指标 | 数值 |
|---|---|
| `fulltext/` 官方版 PDF | 434 |
| 其中本轮新下载 | 105 |
| 由 arXiv/预印本换成官方版 | 80 |

版本状态分布(见 `官方全文_整合/_清单.csv` 的「版本状态」列):

| 状态 | 篇数 | 含义 |
|---|---|---|
| 正式刊出 | 378 | 出版社最终排版版 |
| 在版 Article in Press | 41 | 已有 DOI、正式版式,尚未定最终页码 —— 出版社当前唯一官方 PDF |
| IEEE Early Access | 13 | IEEE 官方发布的预出版形态(作者排版 + IEEE 模板) |
| 接受稿 | 2 | Journal of Hepatology、The Innovation 各一篇,待换最终版 |

## 非官方版识别与替换

起点是发现 `fulltext/` 里混入了大量 arXiv 版。识别依据是首页边栏的
`arXiv:XXXX.XXXXX vN [cs.CV] 日期` 水印(arXiv 下载件的确凿标记),
另加无出版社排版标记的作者稿。共识别 **102 篇**,全部移入 `arxiv_隔离/`,
清单见 `arxiv_非官方版本清单.csv`。

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

| 脚本 | 用途 |
|---|---|
| `data/ieee_playwright.py` | 连 CDP 抓 IEEE 官方 PDF(隔离清单),断点续传 |
| `data/tpami_csv_download.py` | 按 `待下载_TPAMI链接.csv` 批量补齐 TPAMI,优先级排序 + 连续 302 自动停机 |
| `data/oa_playwright.py` | 抓非 IEEE 的 OA 官方 PDF(Cloudflare 拦服务端,真浏览器可过) |
| `data/refetch_official.py` | 服务端走 OpenAlex 找官方 OA 直链(对 Nature 系有效) |
| `data/verify_fulltext.py` | 全库质量核验 → `核验报告.csv` |
| `data/ingest_downloads.py` | 浏览器下到桌面的文件校验改名后归库 |
| `data/skip_dois.txt` | 显式跳过清单,所有下载脚本都遵守 |

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

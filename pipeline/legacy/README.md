# legacy —— 复现已发布交付物

**日常不用这里的东西。** 正式流程在 `../run.py`。

## 为什么单独一层

正式 pipeline 不分批次：一套判据、稳定命名、幂等，未来拿到新论文跑一遍
`extract → screen2 → info → build` 就是完整交付。

这里放的是只为复现历史交付而保留的部分，它们带着两样正式流程已经不用的包袱：

| 包袱 | 问题 |
|---|---|
| `A001_标题.pdf` 档位序号 | 序号按复刻分排，加一篇论文就要把所有文件重命名——**这正是当初逼出「分批交付」的根源** |
| main 的旧 14 列表结构 | 缺 `基准公开`/`SOTA有无` 两个判据，算不出复刻分，排不进统一尺度 |

留着的理由：batch2 的 254 篇、batch3 的 60 篇已经发出去、同事在引用，
出问题时得能一字不差地重建出来对账。

## 用法

```bash
python3 pipeline/legacy/reproduce.py verify          # 核对三套交付物是否仍自洽（最常用）
python3 pipeline/legacy/reproduce.py batch2          # 重建 batch2/（254 篇）
python3 pipeline/legacy/reproduce.py batch3          # 重建 batch3/（60 篇）
python3 pipeline/legacy/reproduce.py index           # 拼成 全量索引.xlsx
python3 pipeline/legacy/reproduce.py import-legacy   # 把 main 旧表导入 extracted.json（已执行过）
```

重建默认**拒绝覆盖**已有目录——重新编号会与已发布的文件名冲突。
只想重出表格用 `--xlsx-only`（复用现有文件名），确认要作废旧名才加 `--force`。

## 文件

| 文件 | 作用 |
|---|---|
| `reproduce.py` | 统一入口，记录了各批次当初的构建参数（`RECIPES`） |
| `build_batch.py` | 旧的 `A001_` 档位编号构建器 |
| `merge_index.py` | 把三套已发布交付拼成总表（正式流程不需要，因为它本来就只有一套） |
| `import_legacy.py` | 一次性迁移：旧表 → `extracted.json` / `verdicts2.json` |
| `tables.py` | 只服务复现的判定表：期刊缩写映射、旧语料里的纯基准论文清单 |

`tables.py` 从 `config.py` 挪出来是有意的——`config.py` 是正式 pipeline 的唯一规则文件，
不该混进历史包袱。

## 依赖

复用父目录的 `config.py` / `common.py` / `s9_enrich.py`，靠 `sys.path` 把父目录接进来。
反向不成立：正式流程不引用这里任何东西（可用 `grep -rn "legacy" ../*.py` 验证）。

判定数据仍在 `data/` 下：`verdicts2.json`、`extracted.json`、`baseline_verdicts.json`、
`batch3_selected.json`。这些是人和模型的判断，程序重算不出来——`data/` 没进版本库，
丢了就得重判，是这个项目最脆弱的一环。

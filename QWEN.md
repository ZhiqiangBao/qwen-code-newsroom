# 星期时报 · 主编工作流

进本项目你就是主编。本文件每轮自动加载，**只讲身份与流程**。所有标准、阈值、口径都在根目录 `rules/` 里，一个主题一个文件，谁需要谁读：

| 规则 | 文件 | 主编 | 子代理 |
|---|---|---|---|
| R1 线与采集口径 | `rules/lines.md` | ✔（下方自动加载） | `fetch` 必读 |
| R2 内容量与重稿 | `rules/volume.md` | ✔ | `copy-check`、`layout-check` 必读 |
| R3 文体纪律 | `rules/prose.md` | ✔ | `copy-check` 必读 |
| R4 样式与配图 | `rules/visual.md` | ✔ | `makeup`、`fetch-poster`、`image-check` 必读 |
| R5 版面与尺寸 | `rules/page-size.md` | ✔ | `layout-check` 必读 |
| R6 落盘（路径模板＋写盘方法） | `rules/disk.md` | ✔ | `fetch`、`makeup`、`copy-check`、`layout-check`、`fetch-poster` |

**改口径只改 `rules/` 里对应那一条**；本文件与各代理定义不得复述其中的数字（代理文件里只写「读 `rules/×.md`」）。

办报脚本在 `.qwen/tools/`，经项目 MCP 服务器 `desk`（`.qwen/settings.json`）调用。禁止用 `run_shell_command` 去跑 `.qwen/tools/`。子代理 `tools:` 必须写规范名 `mcp__desk__feed`（短名 `feed` 进不了允许列表）。改过配置要重启 Qwen，进项目后确认 `desk` 已 Connected。

## MCP 工具（desk）

| 工具 | 谁用 | 作用 |
|---|---|---|
| `mcp__desk__plan` | **主编** | 线索／榜单／行情；看 `labs.missing`、`fetch_urls` 条数 |
| `mcp__desk__feed` | `fetch` | 一条线可抓 URL |
| `mcp__desk__materials` | `makeup` | 素材路径清单，无正文 |
| `mcp__desk__serve` / `writer_status` | **主编** | 拉起／探 llama.cpp `/v1` |
| `mcp__desk__copy_lineup` | **主编** | 按版式槽写稿，最多 20；只回 path／chars |
| `mcp__desk__copy` | **主编** | 单篇补稿 |
| `mcp__desk__pack` | **主编**、`copy-check` | 目录.json，无正文 |
| `mcp__desk__compose` | **主编** | 有版式 json 才拼 HTML |
| `mcp__desk__review` | `layout-check` | 按版 PNG＋`measure[]` |

不要把稿件正文、素材原文打进对话。`ok`／条数只认工具回的那一行 JSON。

## 主编要读的规则（自动加载）

@rules/lines.md
@rules/volume.md
@rules/prose.md
@rules/visual.md
@rules/page-size.md
@rules/disk.md

> 若上面几条没有以内联形式出现在本文件上下文里（版本差异），定版写稿前先 `read_file` 这六个文件，不要凭记忆写。

## 这份报纸

中文大报，报名 **星期时报** / *The Monday Times*，报眼 `All the News That's Fit to Print`，周期每周一；用户说「今日」＝当天日期。版式学《纽约时报》——学的是气不是皮：每版有硬数字，每段有出处，不靠字体和分栏装出来。格调第一：读者随手翻到任意一栏，能不能在两三句里读到一条他之前不知道的事实；能，就是报纸，不能就是排版过的聊天记录。哪条上头条、开不开专栏、分几版按本周新闻自己判断（一周的窗口界定见 R1）——规则只管下限，不管选稿。

## 每期顺序（不要另搞一套）

0. **线索** 主编先调 `mcp__desk__plan`（`date`＝刊头日期）。不要手搜列表页，不要 `run_shell_command` 跑 `desk.py`。
1. **取材** 派 `fetch`，四条线并行派四个，一路一条线。任务里只写：线名（照 R1）＋刊头日期＋希望补什么＋素材落盘文件名（照 R6）；本期要出重稿的那一路加一句「重稿线」（预算更宽，数值在 `.qwen/agents/fetch.md`）。并写「只抓线索.json 里该线 fetchable 的文章页」。人工智能线对线索里 `labs.missing` 再 `web_search` 模型名；死路不要抓。一件事只归一条线，归属拿不准照 R1 的跨线判定；派工时顺手列出已归他线的主体，防止两路重复深挖。子代理自己读 `rules/lines.md`、`rules/disk.md` 与 `desk/数据源.md`；步数与深浅预算写在 `.qwen/agents/fetch.md`，要改深浅改那个文件，不要在这里抄数字。
   - 禁止 fork。子代理只回路径与条数；数字以对应线的素材文件为准，写稿前 `read_file`（按节读，不要把聊天摘要当出处）。**子代理关于自己有哪些工具、自己是否超支的自报一律不可信。**
   - 主编不亲自抓页面。缺料就再派 `fetch`（见「事实补充」）。
   - 原 `fetch-news`／`fetch-page` 两步制于 2026-09-01 废弃（`fetch-news` 在 `qwen3.7-flash` 上调不动 `web_search`，两步接不上）；旧定义在 `.qwen/agents/_backup-2026-09-01/`。
2. **定槽** 版式必须由**主编本人或派 `makeup`** 写 `desk/版式/<日期>.json`（几版、谁上头条、短讯栏放哪一版、每槽性质、每版 `flow`）。**禁止** `compose` / `auto_pages` 按线均分或按文件名切块。只点素材里的事件，**不写正文**。槽数上限见 R2。
3. **写稿** 调 `mcp__desk__copy_lineup`（`date`）。stdout／工具回执只有路径和字数，不要 `read_file` 正文。单篇补漏用 `mcp__desk__copy`。然后需要时 `mcp__desk__pack`。
4. **校对成稿** 派 `copy-check` 读 `desk/稿件/`（对素材核数字）。按报告改槽或重跑 `copy`，不要手写一段充数。
5. **拼版** 有版式 json 才能调 `mcp__desk__compose`。脚本只按槽位填 HTML，缺 json 就停，不许机械补一套 pages。外观照 R3–R5：`<head>` 只留 `<link rel="stylesheet" href="css/site.css" />`。缺字数按 R2 由主编或 `makeup` 改槽再 `copy_lineup`（仍计入 20 份上限）。
6. **配图** 照 R4：公开成图优先，缺的或人物头像才走内置 `image_gen`。出图后派 `image-check`（任务里写图片路径，头像写姓名，并让它读 `rules/visual.md`）。禁止主编 `read_file` 图片。回 `通过` 才上版，否则按 `问题：` 重出。
7. **版面** 派 `layout-check`（它自己跑导出与量尺脚本，判定线在 `rules/page-size.md`）。主编只读它回报的版面报告，禁止 `read_file` PNG。高宽比不达标按 R5 末尾处理：缺稿就补槽再 `copy`，不许拉伸。
8. **出刊** 读者打开根目录最新一期。需要时写 R6「交接」行的文件。出刊后跑 `python 更新首页.py`，把最新一期发布到 `docs/`。

## 事实补充（定版后发现某版缺料）

再派 `fetch` 补抓，一次只补一条线。任务里必须写明：
- 哪条线、哪个版面缺料，希望补什么（背景数字、当事方表态、时间线等）；
- 已有哪些内容——每条一行只写要点，不抄全文，让子代理知道不要重复抓；
- 素材写入 R6「素材补」行给的新文件，**不要追加进原来的素材文件**（避免读回旧文件重写，省 token）。落盘后再 `mcp__desk__copy`，不要手改见报正文。

补不到就按 R3 第 8 条交代。

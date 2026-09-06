# R6 · 落盘（路径模板与写盘方法）

**读的人**：凡是要落盘文件的角色——主编、`fetch`、`makeup`、`copy-check`、`layout-check`、`fetch-poster`。

办报脚本只在 `.qwen/tools/`，经 MCP 服务器 `desk` 调用（工具名 `mcp__desk__…`）。禁止 `run_shell_command` 跑该目录。`.qwen/tmp/` 是探针残骸，不是入口。`.qwen/skills/` 只留说明；导出实现是 `.qwen/tools/review.py`。

## 路径模板（唯一路径定义）

各代理与技能文件**不得各自改写路径**，只写「见 `rules/disk.md`『××』行」。日期一律用**刊头日期**。

| 行名 | 路径模板 | 谁写 |
|---|---|---|
| 见报 | `YYYY-MM-DD.html`（项目根目录，读者打开其中最新一期；日期版 HTML 不进仓库） | 主编 |
| 见报图 | `img/YYYY-MM-DD/`（网页内引用一律正斜杠相对路径） | fetch 或主编 |
| 素材 | `desk/素材/YYYY-MM-DD/<线名>.md` | fetch（四路各写各的） |
| 素材补 | `desk/素材/YYYY-MM-DD/<线名>-补N.md`（N 从 1 起，新文件不追加旧文件） | fetch |
| 榜单 | `desk/素材/YYYY-MM-DD/榜单.json` | `desk.py hot`／`plan` |
| 线索 | `desk/素材/YYYY-MM-DD/线索.json` | `desk.py plan`（热榜+RSS+大厂命中+可抓 URL） |
| 行情 | `desk/素材/YYYY-MM-DD/行情.md` | `desk.py quotes`／`plan` |
| 稿件 | `desk/稿件/YYYY-MM-DD/<线名>/<内容>-<性质>-<标题>-<字数>.md` | `desk.py copy`（填槽；现行过渡期仍可能是 `<id>.md`） |
| 稿件目录 | `desk/稿件/YYYY-MM-DD/目录.json` | `desk.py pack` |
| 校对 | `desk/校对/YYYY-MM-DD.md` | copy-check（对成稿，不对本期 HTML） |
| 版式 | `desk/版式/YYYY-MM-DD.json` | 主编或 `makeup`（槽位；禁止脚本机械生成） |
| 交接 | `desk/交接/YYYY-MM-DD.md` | 主编 |
| 版面 | `desk/版面/YYYY-MM-DD/report.md`（同目录放导出 PNG） | layout-check |
| 数据源 | `desk/数据源.md`（不按日期，长期累积） | fetch／主编 |
| 发布 | `docs/`（GitHub Pages 只部署这里，由 `更新首页.py` 生成） | 脚本 |

工作稿一律按类型进 `desk/`，不要写回根目录。文件名只用英文或拼音（线名沿用 R1 表里的中文线名，因为派工与素材要一一对应）。

## 结构化文件名（方便排版，待实施）

文件名只描述**这篇稿是什么、叫什么、多长**，不写上哪一版。版位（A1 / B1）写进 `desk/版式/YYYY-MM-DD.json`。

**稿件** `desk/稿件/YYYY-MM-DD/<线名>/<内容>-<性质>-<标题>-<字数>.md`

| 段 | 取值 | 作用 |
|---|---|---|
| 线名 | 目录：`人工智能` `科技` `娱乐` `动漫` `评论` | 按线扫盘 |
| 内容 | 英文短名，如 `fable51` | 同一事件只一篇；`copy --id` |
| 性质 | `快讯` `普通` `深挖` `评论` | 栏宽、字号 |
| 标题 | 见报标题，去掉 `\ / : * ? " < > \|`，截到约 24 字 | 资源管理器里直接看见头条 |
| 字数 | 落盘后实测（与 `pack` 同一套），不是目标字数 | 按剩余栏位抽稿 |

例：`desk/稿件/2026-09-07/人工智能/fable51-深挖-Anthropic发布Fable51-1382.md`

写完若标题或字数变了就改文件名。未改脚本之前，现行仍是 `desk/稿件/YYYY-MM-DD/<id>.md`。

**素材**（分类时就拆开）：

- 大新闻一件一文件：`desk/素材/YYYY-MM-DD/<线名>/<内容>.md`
- 该线快讯合订一本：`desk/素材/YYYY-MM-DD/<线名>-快讯.md`

## 目标流程（主编定槽，脚本填稿）

主编管目录、短讯位置、版面结构；**不管写正文**。写稿份数由槽位卡死，见 R2。

0. `mcp__desk__plan` → 线索 / 榜单 / 行情  
1. `fetch` 只抓 `fetchable` 文章页；分类即拆文件（原料可以多于 20 条，不上槽的不写稿）  
2. **定槽**：主编自写或派 `makeup`（`mcp__desk__materials`）写 `desk/版式/<日期>.json`。禁止机械均分。槽数上限见 R2。  
3. `mcp__desk__copy_lineup` 只填这些槽；`mcp__desk__pack`  
4. **校对成稿**：派 `copy-check`（可 `mcp__desk__pack`）读 `desk/稿件/`  
5. `mcp__desk__compose` 必须已有版式 json；没有 pages 就失败  
6. 配图 → `mcp__desk__review`（layout-check）→ 出刊  

版式 json 里一槽一例：

```json
{
  "pages": [
    {"id": "a1", "lead": "fable51", "articles": ["gemini38"], "shorts": []},
    {"id": "b2", "lead": "", "articles": [], "shorts": ["ai-briefs"]}
  ],
  "slots": [
    {"id": "fable51", "line": "人工智能", "kind": "深挖", "source": "desk/素材/2026-09-07/人工智能/fable51.md"},
    {"id": "ai-briefs", "line": "人工智能", "kind": "快讯", "source": "desk/素材/2026-09-07/人工智能-快讯.md"}
  ]
}
```

`shorts` 指向快讯合订槽（一份写稿，不是一条快讯一份）。没有 `--lineup` 的零散 `copy` 也算入本期槽数，超额脚本应拒绝。`compose` 若发现没有 `pages`，直接失败，**不要**用均分函数补一套版面。

还没接到脚本上的：字数卡、快讯少过模型、结构化文件名落盘。

## 写盘方法（Windows）

- 中文内容**一律用 `write_file` 工具**落盘（UTF-8）。禁止 `echo … >`、`type`、`cat <<EOF`、PowerShell `Set-Content`／`Out-File`——cmd.exe 默认 GBK，中文必乱码。
- 建目录 `mkdir "…"`（cmd 支持多级）。删除用 PowerShell `Remove-Item -Recurse -Force <路径>`，不用 `rm -rf`。
- 含中文或空格的路径加引号；绝对路径最稳，相对路径要先确认工作目录是项目根。
- 下载模板：`Invoke-WebRequest -Uri … -OutFile … -UseBasicParsing -TimeoutSec 20 -Headers @{'Referer'=…;'User-Agent'=…}`。
- cmd 两个坑：`set X=… & copy "%X%\f"` 会在解析行时就展开 `%X%` 拿到空值——写全路径或分行执行；往命令里传含 `|` 的正则会被 cmd 当管道——用 grep 工具，或改写正则避开 `|`（如 `[a-d][0-9]`）。

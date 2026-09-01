# R6 · 落盘（路径模板与写盘方法）

**读的人**：凡是要落盘文件的角色——主编、`fetch`、`copy-check`、`layout-check`、`fetch-poster`。

## 路径模板（唯一路径定义）

各代理与技能文件**不得各自改写路径**，只写「见 `rules/disk.md`『××』行」。日期一律用**刊头日期**。

| 行名 | 路径模板 | 谁写 |
|---|---|---|
| 见报 | `YYYY-MM-DD.html`（项目根目录，读者打开其中最新一期；日期版 HTML 不进仓库） | 主编 |
| 见报图 | `img/YYYY-MM-DD/`（网页内引用一律正斜杠相对路径） | fetch 或主编 |
| 素材 | `desk/素材/YYYY-MM-DD/<线名>.md` | fetch（四路各写各的） |
| 素材补 | `desk/素材/YYYY-MM-DD/<线名>-补N.md`（N 从 1 起，新文件不追加旧文件） | fetch |
| 校对 | `desk/校对/YYYY-MM-DD.md` | copy-check |
| 版式 | `desk/版式/YYYY-MM-DD.md` | 主编 |
| 交接 | `desk/交接/YYYY-MM-DD.md` | 主编 |
| 版面 | `desk/版面/YYYY-MM-DD/report.md`（同目录放导出 PNG） | layout-check |
| 数据源 | `desk/数据源.md`（不按日期，长期累积） | fetch／主编 |
| 发布 | `docs/`（GitHub Pages 只部署这里，由 `更新首页.py` 生成） | 脚本 |

工作稿一律按类型进 `desk/`，不要写回根目录。文件名只用英文或拼音（线名沿用 R1 表里的中文线名，因为派工与素材要一一对应）。

## 写盘方法（Windows）

- 中文内容**一律用 `write_file` 工具**落盘（UTF-8）。禁止 `echo … >`、`type`、`cat <<EOF`、PowerShell `Set-Content`／`Out-File`——cmd.exe 默认 GBK，中文必乱码。
- 建目录 `mkdir "…"`（cmd 支持多级）。删除用 PowerShell `Remove-Item -Recurse -Force <路径>`，不用 `rm -rf`。
- 含中文或空格的路径加引号；绝对路径最稳，相对路径要先确认工作目录是项目根。
- 下载模板：`Invoke-WebRequest -Uri … -OutFile … -UseBasicParsing -TimeoutSec 20 -Headers @{'Referer'=…;'User-Agent'=…}`。
- cmd 两个坑：`set X=… & copy "%X%\f"` 会在解析行时就展开 `%X%` 拿到空值——写全路径或分行执行；往命令里传含 `|` 的正则会被 cmd 当管道——用 grep 工具，或改写正则避开 `|`（如 `[a-d][0-9]`）。

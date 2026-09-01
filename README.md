<div align="center">

<img src="https://img.shields.io/badge/THE%20MONDAY%20TIMES-%E7%A4%BA%E4%BE%8B%E6%8A%A5%E7%BA%B8%20%C2%B7%20%E6%98%9F%E6%9C%9F%E6%97%B6%E6%8A%A5-d4380d?style=for-the-badge&labelColor=1a1a1a" alt="示例报纸：星期时报 The Monday Times">

# Qwen Code 办报工作流 · AI Newsroom

**一个人 + Qwen Code = 一间报社。**
说一声「出今日报纸」，AI 主编自动派出一支子代理团队：取材的、配图的、校对的、排版的——六步之后，一份《纽约时报》风格的中文大报在你的浏览器里成型，GitHub Pages 全球发行。

<img src="https://img.shields.io/badge/powered%20by-Qwen%20Code-blue" alt="Qwen Code">&nbsp;&nbsp;
<img src="https://img.shields.io/badge/subagents-4-orange" alt="Agents">&nbsp;&nbsp;
<img src="https://img.shields.io/badge/%E6%96%B0%E9%97%BB%E7%BA%BF-4-red" alt="Lines">&nbsp;&nbsp;
<img src="https://img.shields.io/badge/rules-6%20files-yellow" alt="Rules">&nbsp;&nbsp;
<img src="https://img.shields.io/badge/GitHub%20Pages-auto-green" alt="Pages">

<br>

<a href="https://zhiqiangbao.github.io/qwen-code-newsroom/">
  <table align="center" role="presentation" cellpadding="0" cellspacing="0" border="0">
    <tr>
      <td bgcolor="#1a1a1a" align="center" valign="middle" width="72"><img src="assets/cover.png" width="56" height="56" alt="星期时报封面"></td>
      <td bgcolor="#d4380d" valign="middle" align="left"><font color="#ffffff">&nbsp;&nbsp;<b>在线看最新一期</b>&nbsp;·&nbsp;Read the Latest Issue&nbsp;&nbsp;</font></td>
    </tr>
  </table>
</a>

</div>

---

## 它解决什么问题

用 LLM 办报，难的不是写字，是**上下文经济学**和**AI 腔**：网页正文动辄几万 token，主对话里连抓十个源，预算直接爆炸；而模型一提笔就容易写成"读后感"——先贴一句「值得注意的是」再讲感想、把编辑部的版号当论证材料、用对偶句替代证据。本仓库给出一套实刊验证的解法。

```
        rules/  ← 全部标准与阈值，一个主题一个文件（R1–R6）
          │
          │ 主编：QWEN.md 用 @rules/xxx 自动内联加载
          │ 子代理：各自定义里点名「只读 rules/×.md」，不读 QWEN.md
          ▼
              主会话（主编）        ← 只留结论，不养正文
                   │
     ┌─────────┬───┴────┬─────────┐
     ▼         ▼        ▼         ▼
   fetch      fetch    fetch     fetch   ← 四路并行，一路一条线
     │    搜→抓→落盘 一步到位；禁止再 fork
     ▼         ▼        ▼         ▼
   desk/素材/YYYY-MM-DD/<线名>.md        ← 原文逐字摘录入库，主会话只收「路径+条数」
     │
     ▼
   主编写稿 → copy-check / image-check / layout-check   ← 三道质检，各开各的上下文
     │
     ▼
   YYYY-MM-DD.html → docs/index.html → GitHub Pages
```

每路 `fetch` 头顶都悬着**硬停止条件**：`web_search` ≤2、`web_fetch` ≤6、总工具调用 ≤12；一个 URL 只许抓一次、403 零决策成本立刻换源、超 80KB 的大页直接判失败；整路取材墙钟目标 ≤5 分钟。想陷进去？规则不允许（这些数字住在 `.qwen/agents/fetch.md`，别处只给指针）。

**标准只有一份。** 同一口径散在多个文件里，早晚会互相打架（我们真的踩过：一处写 ≤4、一处写 ≤2）。所以 `rules/` 是唯一来源，`QWEN.md` 与各代理定义只写「见 `rules/×.md`」——你改一个文件，整条工作流跟着变。

## 武器库

| 能力 | 实现 | 亮点 |
|---|---|---|
| 取材 | `fetch` 子代理 ×4 并行 | 一路一条线，自己搜、自己抓、自己落盘；原文逐字摘录入库（6000–12000 字），主会话只收「路径+条数」 |
| 补料 | 再派 `fetch`（单线） | 定版后发现某版缺料，任务里写明已有哪些要点，补进新文件 `<线名>-补N.md`，不覆盖旧素材 |
| 写稿 | 主编（主对话模型） | 自动加载 `rules/`：版量、重稿门槛、字体、数字写法、纸面尺寸一次到位 |
| 文体 | `rules/prose.md` + `copy-check` 机检 | 八条禁令配 grep 词表：版号互见、评论引用自家版面、口头禅配额、「不是 A 而是 B」句式配额、删掉评价句就不剩事实的空转段 |
| 配图 | `fetch-poster` 技能 + 内置 `image_gen` + `image-check` | 官方海报从 `og:image` 直取并验真图；人物一律素描头像，不像本人就重出 |
| 校对 | `copy-check` 子代理 | 数字、人名、出处、栏目条数逐条过；`[文体]`／`[元叙述]`／`[容量]` 分类落报告 |
| 版面 | `layout-check` + `layout-review` 技能（Edge 无头截图） | 页宽、高宽比、哨兵溢出、栏高、裁图五项量化验收；脚本自己从 HTML 的 CSS 读纸宽与纸色，不在代码里抄常数 |
| 发行 | `更新首页.py` + GitHub Pages | 最新一期发布到 `docs/`（配图自动压成 JPEG），零构建、推送即上线 |

## 快速开始（10 分钟见报）

### 1. 装 Qwen Code

官方仓库：<https://github.com/QwenLM/qwen-code>（开源 AI 编程智能体，跑在终端里）

**Windows（PowerShell，官方一键脚本，推荐）：**

```powershell
irm https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/installation/install-qwen-standalone.ps1 | iex
```

**Linux / macOS：**

```bash
curl -fsSL https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/installation/install-qwen-standalone.sh | bash
```

**或走 NPM**（需 [Node.js](https://node.js.org/) 22+）/ **Homebrew**：

```bash
npm install -g @qwen-code/qwen-code@latest
brew install qwen-code
```

装完重开终端，`qwen --version` 验证。

### 2. 配置模型（系统设置文件）

编辑 `~/.qwen/settings.json`（Windows：`C:\Users\<用户名>\.qwen\settings.json`），没有就新建。本项目需要两类模型：

**① 子代理用：qwen3.7-flash**（四个子代理的 `model:` 都指向它）

```json
{
  "env": { "DASHSCOPE_API_KEY": "sk-你的密钥" },
  "modelProviders": {
    "openai": [
      {
        "id": "qwen3.7-flash",
        "name": "qwen3.7-flash",
        "baseUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "envKey": "DASHSCOPE_API_KEY"
      }
    ]
  }
}
```

**② 内置 `image_gen` 用：文生图路由**（关键在 `supportsImageGeneration: true` + `imageOnly: true`，再以顶层 `imageModel` 指认默认）

```json
{
  "modelProviders": {
    "openai": [
      {
        "id": "qwen-image-2.0-pro",
        "name": "Qwen Image 2.0 Pro（文生图）",
        "baseUrl": "https://dashscope.aliyuncs.com/api/v1",
        "envKey": "DASHSCOPE_API_KEY",
        "supportsImageGeneration": true,
        "imageOnly": true
      }
    ]
  },
  "imageModel": "openai:qwen-image-2.0-pro"
}
```

> 注意生图端点是 `https://dashscope.aliyuncs.com/api/v1`，**不是**聊天用的 `compatible-mode/v1`。`imageOnly: true` 让这条路由不出现在聊天模型选择器里，只服务于 `image_gen`。换别的生图服务商同理：任何 OpenAI 兼容的文生图端点都行。

**验证：** 启动 `qwen` → `/model` 能看到 qwen3.7-flash；`/model --image` 能看到生图路由。主对话模型用 `/model` 切成更强的（建议 max/plus 级），子代理仍按 `.qwen/agents/*.md` 走 flash。

### 3. 装版面导出依赖

```bash
pip install pillow
```

版面截图脚本调用本机 **Microsoft Edge**（无头模式），Windows 自带即可；非 Windows 需自行改 `review.py` 里的浏览器路径。

### 4. 克隆本仓库

```bash
git clone https://github.com/ZhiqiangBao/qwen-code-newsroom.git
cd qwen-code-newsroom
```

### 5. 办报

```bash
qwen
```

对话里说 **「出今日报纸」**。`QWEN.md` 连同 `rules/` 六条规则自动加载，主编开始派工——四路 `fetch` 并行取材（人工智能／科技／娱乐／动漫各一路），然后写 HTML、出素描头像、跑校对（含文体机检）、截图验版，最后覆盖根目录的 `YYYY-MM-DD.html`。

**补充材料**：定版后若某个版面缺料，直接对主编说「B2 版缺深度，补一下」。主编会单线再派一路 `fetch`，任务里列明已有哪些要点（防止重复抓），新素材写进 `desk/素材/YYYY-MM-DD/<线名>-补N.md`，据此改稿。补不到就维持「未获取」，不许编。

### 6. 发行

每期出刊后先跑 `python 更新首页.py`，最新一期就进了 `docs/`。

然后建你自己的仓库：打开 <https://github.com/new>，填仓库名（如 `my-news`），可见性选 **Public**（免费版 Pages 要求），**不要勾选** "Add a README file" 等任何初始化选项，点 Create repository。

建好后，把 `docs` 文件夹推上去。先打开终端并进入 `docs`，三种方法任选其一：

1. **地址栏**：进入 `docs` 文件夹，在文件资源管理器顶部地址栏输入 `powershell` 回车
2. **右键**：进入 `docs` 文件夹，在空白处按住 Shift 右键（Win11 直接右键选「在终端中打开」），选择「在此处打开 PowerShell 窗口」
3. **命令切换**：先随便打开 PowerShell，再用 `cd` 命令切过去，如 `cd C:\Users\你的用户名\Desktop\qwen-code-newsroom\docs`（macOS/Linux 用终端，如 `cd ~/项目/qwen-code-newsroom/docs`）

确认提示符当前目录是 `docs` 后，逐行执行：

```bash
git init                                        # 把 docs 变成本地 git 仓库
git remote add origin https://github.com/你的用户名/my-news.git  # 关联到刚建的新仓库
git add -A                                      # 收集 docs 里的全部文件
git commit -m "issue: 2026-09-07"               # 打包成一次提交
git push -u origin main                         # 推送到 GitHub
```

> `cd docs` 的意思是「进入 docs 文件夹」。git 只对当前所在目录生效，所以必须先站在 `docs` 里再执行上面这些命令，推上去的就只有报纸页面和配图，不含办报工作流文件。首次 push 会弹浏览器登录 GitHub 授权，跟着提示走即可。

再到你的仓库 **Settings → Pages**，Source 选 **Deploy from a branch**，分支 `main`、目录 **`/`（根目录）**，保存。以后每期重复：跑脚本 → 进 `docs` → add / commit / push，报纸自动更新。你的报纸地址：

```
https://你的用户名.github.io/my-news/
```

## 仓库地图

```
├── YYYY-MM-DD.html          # 每期报纸（根目录，日期版不进仓库）
├── docs/                    # Pages 站点（生成物：index.html + 最新一期 img/，别手改）
├── 更新首页.py               # 最新一期 → docs/（配图压成 JPEG）
├── img/YYYY-MM-DD/          # 见报图（公开成图 / AI 生成）
│
├── QWEN.md                  # 【流程】主编身份 + 六步顺序 + 谁读哪条规则
├── rules/                   # 【标准】唯一来源，一条主题一个文件
│   ├── lines.md             #   R1 四条线与采集侧重、采集配额、出处口径指向
│   ├── volume.md            #   R2 版号分区、每期版数、字数下限、重稿门槛
│   ├── prose.md             #   R3 文体纪律（八条 + 真实反例句）
│   ├── visual.md            #   R4 字体、数字写法、成图与生成图口径、版式类名
│   ├── page-size.md         #   R5 纸宽/栏数/高宽比合格线
│   └── disk.md              #   R6 路径模板 + 写盘方法（非 Windows 改这里）
│
├── .qwen/
│   ├── agents/              # 四个子代理：只写「读哪条规则 + 怎么执行 + 输出格式」
│   │   ├── fetch.md         #   取材：预算、单页纪律、原文入库、素材文件格式
│   │   ├── copy-check.md    #   校对：grep 词表与标签，标准指向 R2/R3
│   │   ├── image-check.md   #   配图质检：只读 R4，回「通过」或「问题：」
│   │   └── layout-check.md  #   版面验收：跑导出脚本 + 量尺，标准指向 R5
│   ├── skills/
│   │   ├── fetch-poster/    # 海报直链下载技能（og:image + 绕防盗链 + 验真图）
│   │   └── layout-review/   # HTML 按版截图脚本（纸宽/纸色从 CSS 自动读）
│   └── settings.json        # 项目级设置
└── desk/                    # 工作底稿：素材 / 校对 / 版式 / 版面报告 / 交接 / 数据源.md
```

## 定制：克隆之后改哪里

**原则：一个口径只有一个文件。** 下面每一行都只改一个文件，改完立即生效，不用写代码、不用碰其他文件。**别把数字抄到第二个地方去**——那正是我们要消灭的东西。

### 第一层：让内容变成你想要的（改 `rules/`）

| 想改什么 | 只改这个文件 |
|---|---|
| 选题方向、四条线、各线采集配额（例：把「动漫」换成「体育」） | `rules/lines.md`（R1）——表里的线名同时是派工名与素材文件名 |
| 每期几版、每版多少字、单条稿下限、重稿门槛、版号字母分区 | `rules/volume.md`（R2） |
| 文风（禁用句式与每版配额、不许出现「本期/未获取清单」这类交代、署名规则） | `rules/prose.md`（R3） |
| 字体、字号栈、数字写法、图必须黑白、图注三种口径、人像必须像本人 | `rules/visual.md`（R4） |
| 纸宽、栏数、高宽比合格线（嫌版面太挤或太空就调这里） | `rules/page-size.md`（R5） |
| 工作稿存放位置、文件名规则、非 Windows 的写盘与命令写法 | `rules/disk.md`（R6） |

改完 R5 的纸宽或 R4 的字体，**下一期**的 HTML 会照新规则生成；已出版的历史那几期是独立 HTML，要改得手改。

### 第二层：报名与流程（改 `QWEN.md`）

| 想改什么 | 动哪里 |
|---|---|
| 报名、报眼标语（`All the News That's Fit to Print`）、出版周期 | `QWEN.md`「这份报纸」段 |
| 六步顺序、要不要多派一路、先校对还是先配图 | `QWEN.md`「每期顺序」 |
| 主编上下文里加载哪几条规则 | `QWEN.md`「主编要读的规则」里的 `@rules/×.md` 列表 |

`QWEN.md` 顶部还有一张「规则 → 谁读」对照表，加一条规则就在表里挂一行、并在需要的代理定义里补一句「读 `rules/新文件.md`」。

### 第三层：代理行为（改 `.qwen/agents/`）

| 想改什么 | 动哪里 |
|---|---|
| 取材深浅与开销（次数、80KB 判失败、5 分钟墙钟、素材 6000–12000 字） | `.qwen/agents/fetch.md` |
| 素材文件内部格式（要不要多一个「背景资料」节） | 同上，「落盘」节的格式模板 |
| 校对多查一类问题 | `.qwen/agents/copy-check.md` 的 grep 词表与标签 |
| 子代理用哪个模型 | 各代理文件顶部 `model:`（改档位还要看 `.qwen/settings.json` 的 `allowedGrades`） |
| 版面导出细节（浏览器路径、导出倍率、单版导出） | `.qwen/skills/layout-review/review.py`，参数 `--html` `--pages` `--width` `--scale` `--output` |
| 抓图技能的重试与校验门槛 | `.qwen/skills/fetch-poster/SKILL.md` |

### 第四层：数据源（改 `desk/数据源.md`）

换语言、换国家、换行业，最先要动的是这份网址库：直达地址、「实测／待验证」标记、死路名单、什么才算出处。取材代理开工第一步就读它，改完立即生效，不需要动任何提示词。

### 首页与站点外观

`docs/` 是生成物，由 `更新首页.py` 覆盖，别手改。要改首页样式就改报纸 HTML 本身（版式类名清单在 `rules/visual.md` 末节），或改 `更新首页.py` 里生成 `index.html` 的那段。

## 声明

本项目的工作流运行依赖开源命令行工具 **[Qwen Code](https://github.com/QwenLM/qwen-code)**（官方仓库：<https://github.com/QwenLM/qwen-code>）。`QWEN.md`、`rules/`、`.qwen/agents/`、`.qwen/settings.json` 均为 Qwen Code 的项目配置格式（`rules/` 是本仓库自定的普通 Markdown，靠 `QWEN.md` 里的 `@rules/×.md` 引用加载）。报纸内容含 AI 生成成分，图片注明「公开资料」或「人工智能生成／本报制图」，不代表任何真实媒体机构。

## License

内容示例仅供学习参考。

<div align="center">

<img src="https://img.shields.io/badge/THE%20MONDAY%20TIMES-%E7%A4%BA%E4%BE%8B%E6%8A%A5%E7%BA%B8%20%C2%B7%20%E6%98%9F%E6%9C%9F%E6%97%B6%E6%8A%A5-d4380d?style=for-the-badge&labelColor=1a1a1a" alt="示例报纸：星期时报 The Monday Times">

# Qwen Code 办报工作流 · AI Newsroom

**一个人 + Qwen Code = 一间报社。**
说一声「出今日报纸」，AI 主编自动派出一支子代理团队：取材的、配图的、校对的、排版的——六步之后，一份《纽约时报》风格的中文大报在你的浏览器里成型，GitHub Pages 全球发行。

<img src="https://img.shields.io/badge/powered%20by-Qwen%20Code-blue" alt="Qwen Code">&nbsp;&nbsp;
<img src="https://img.shields.io/badge/subagents-4-orange" alt="Agents">&nbsp;&nbsp;
<img src="https://img.shields.io/badge/%E6%96%B0%E9%97%BB%E7%BA%BF-4-red" alt="Lines">&nbsp;&nbsp;
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

用 LLM 办报，难的不是写字，是**上下文经济学**：网页正文动辄几万 token，主对话里连抓十个源，预算直接爆炸。本仓库给出一套经过实刊验证的解法——

```
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

每路 `fetch` 头顶都悬着**硬停止条件**：`web_search` ≤2、`web_fetch` ≤6、总工具调用 ≤12；一个 URL 只许抓一次、403 零决策成本立刻换源、超 80KB 的大页直接判失败；整路取材墙钟目标 ≤5 分钟。想陷进去？规则不允许。

## 武器库

| 能力 | 实现 | 亮点 |
|---|---|---|
| 取材 | `fetch` 子代理 ×4 并行 | 一路一条线，自己搜、自己抓、自己落盘；原文逐字摘录入库（6000–12000 字），主会话只收「路径+条数」 |
| 补料 | 再派 `fetch`（单线） | 定版后发现某版缺料，任务里写明已有哪些要点，补进新文件 `<线名>-补N.md`，不覆盖旧素材 |
| 配图 | `fetch-poster` 技能 + 内置 `image_gen` + `image-check` | 官方海报从 `og:image` 直取；人物一律素描头像，不像本人就重出 |
| 写稿 | 主编（主对话模型） | 按《办报说明》的 NYT 格调写，每期至少一篇撑满整页的重稿 |
| 校对 | `copy-check` 子代理 | 数字、人名、出处逐条过 |
| 版面 | `layout-check` + `layout-review` 技能（Edge 无头截图） | 页宽、高宽比、留白、裁图，五项量化验收，不达标退回重写 |
| 发行 | `更新首页.py` + GitHub Pages | 最新一期发布到 `docs/`，零构建、推送即上线 |

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

**或走 NPM**（需 [Node.js](https://nodejs.org/) 22+）/ **Homebrew**：

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

### 4. 建你自己的报纸仓库

在本仓库页面点上方绿色 **Use this template → Create a new repository**（或先 Fork），生成一个属于你的空仓库：

- 仓库名随意（如 `my-news`），下文用 `你的仓库名` 指代
- 可见性选 **Public**（免费版 Pages 要求）

克隆到本地：

```bash
git clone https://github.com/你的用户名/你的仓库名.git
cd 你的仓库名
```

### 5. 办报

```bash
qwen
```

对话里说 **「出今日报纸」**。`QWEN.md` 自动加载，主编开始派工——四路 `fetch` 并行取材（人工智能／科技／娱乐／动漫各一路），然后写 HTML、出素描头像、跑校对、截图验版，最后覆盖根目录的 `YYYY-MM-DD.html`。

**补充材料**：定版后若某个版面缺料，直接对主编说「B2 版缺深度，补一下」。主编会单线再派一路 `fetch`，任务里列明已有哪些要点（防止重复抓），新素材写进 `desk/素材/YYYY-MM-DD/<线名>-补N.md`，据此改稿。补不到就维持「未获取」，不许编。

### 6. 发行

每期出刊后，把最新一期发布到 `docs/` 并推送——`docs/` 就是 Pages 的站点根：

```bash
python 更新首页.py          # 最新一期 → docs/index.html，同步 docs/img/
git add docs
git commit -m "issue: 2026-09-07"
git push
```

再到仓库 **Settings → Pages**，Source 选 **Deploy from a branch**，分支 `main`、目录选 **`/docs`**，保存。报纸全用相对路径，无构建、无依赖，之后每次跑脚本再推送即自动更新。你的报纸地址：

```
https://你的用户名.github.io/你的仓库名/
```

## 仓库地图

```
├── YYYY-MM-DD.html          # 每期报纸（根目录，日期版不进仓库）
├── docs/                    # Pages 站点（生成物：index.html + 最新一期 img/，别手改）
├── 更新首页.py               # 最新一期 → docs/
├── img/YYYY-MM-DD/          # 见报图（公开成图 / AI 生成）
├── QWEN.md                  # 主编工作流 · Qwen Code 进入目录自动加载
├── 办报说明.md               # 报社"社规"：格调、选题线、版式、字体
├── .qwen/
│   ├── agents/              # 四个子代理：fetch 取材 / copy-check 校对 / image-check 配图质检 / layout-check 版面验收
│   ├── skills/
│   │   ├── fetch-poster/    # 海报直链下载技能（og:image + 绕防盗链）
│   │   └── layout-review/   # HTML 按版截图脚本
│   └── settings.json        # 项目级设置
└── desk/                    # 工作底稿：素材/校对/版面报告/交接
```

## 定制：把它变成你的报纸

全部是配置与文档，**不用写代码**：

| 想改什么 | 动哪里 |
|---|---|
| 报名、报眼标语、出版周期 | `办报说明.md` 开头 |
| 选题线（现在是 AI/科技/娱乐/动漫） | `办报说明.md`「四条线」+ `QWEN.md` 取材步骤的线名，两处同步 |
| 版式格调、重稿要求、字体 | `办报说明.md` 对应小节 |
| 每期流程与派工规则 | `QWEN.md` |
| 子代理用什么模型、token 预算 | `.qwen/agents/*.md` 顶部 `model:` 与各文件内硬上限 |
| 版面验收标准 | `.qwen/skills/layout-review/review.py` + `layout-check.md` 判定表 |
| 首页样式 | 报纸 HTML 本身（`docs/` 是生成物，由 `更新首页.py` 覆盖） |

## 声明

本项目的工作流运行依赖开源命令行工具 **[Qwen Code](https://github.com/QwenLM/qwen-code)**（官方仓库：<https://github.com/QwenLM/qwen-code>）。`QWEN.md`、`.qwen/agents/`、`.qwen/settings.json` 均为 Qwen Code 的项目配置格式。报纸内容含 AI 生成成分，图片注明「公开资料」或「人工智能生成／本报制图」，不代表任何真实媒体机构。

## License

内容示例仅供学习参考。

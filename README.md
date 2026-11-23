# 星期时报

《星期时报》是一个由 Qwen Code 协作编辑的中文周报项目。采编会话产出候选页，主编核对后决定发行。读者打开 GitHub Pages 首页阅读。已发行的日期版有自己的地址与配图资源。

## 准备编辑台

- 在仓库根目录打开 Qwen Code。让 `python` 指向安装了 `mcp` 和 `pillow` 的 Python 环境。导出版面需要 Windows 上的 Microsoft Edge。
- 按本机环境配置 `.qwen/tools/writer.json`。它不进入 Git。 `endpoints` 为空时写稿会明确报错。
- 重启 Qwen Code，确认能看到 `desk` 工具。主编归纳出处，取材工位可按线索定位原件。首次配置先看 [主编规程](rules/editor.md)。

写稿服务用 OpenAI 兼容的 `/v1`。可沿用本机已运行的 llama.cpp。需要为分析指定更强的模型时，给对应端点设置 `"roles": ["analysis"]`。普通稿使用无角色或带 `ordinary` 的端点。认证通过 `api_key_env` 指定的本机环境变量提供。

```json
{
  "endpoints": [
    {"base_url": "http://127.0.0.1:8080", "model": "本机实际模型名", "roles": ["ordinary"]}
  ]
}
```

## 做一期候选

在 Qwen Code 告诉主编「做 YYYY-MM-DD 期候选」。主编依次收线索、核原件、选一篇分析、写稿并排版，返回可打开的候选路径与指纹。来源超时或只有标题时，先定位一手文件。证据不够时去掉该选题，并按[证据表格式](rules/evidence.md)更新入选稿。

Windows 也可从仓库根运行：

```powershell
.\weekly_issue.ps1 -Date YYYY-MM-DD
```

平日用 `.\weekly_issue.ps1 -CollectOnly` 给下一周一积累固定来源，选定其他刊头日期时加 `-Date`。该模式只抓固定来源。按来源用短时缓存复用请求，刷新保留当期已取得的带日期条目。结果会区分无更新、暂时失败与使用旧缓存的降级。按需要到 [来源表](desk/feeds.json) 增删入口。启用 SEC 来源前填写带机构及联络方式的 `sec_user_agent`，或设置 `SEC_USER_AGENT`；具体配置以来源表字段为准。

## Windows 定时运行

在长期保留的干净检出中操作。注册前准备 Python、Node、Qwen CLI 入口和已有写稿配置四个绝对路径。`WriterConfig` 可以指向原目录已有的本机配置。启动脚本通过文件路径读取它。

```powershell
& $node $qwenCli mcp approve desk
.\weekly_issue.ps1 -Check -PythonPath $python -NodePath $node -QwenCli $qwenCli -WriterConfig $writerConfig
.\install_weekly_task.ps1 -PythonPath $python -NodePath $node -QwenCli $qwenCli -WriterConfig $writerConfig
```

使用运行任务的账户为当前检出批准 `desk`。Qwen 将批准绑定到该目录与服务器配置。预检返回 `dependencies_ready` 后再注册。机器使用中国标准时间，两项任务都依赖注册账户的现有登录会话。

- `MondayTimesCollect` 每日 20:00 为下一刊期更新固定来源缓存。
- `MondayTimes` 每周一 00:00 生成候选。已有文件、证据与量尺回执一致的候选时，直接复用该候选。

每次运行都有独立的 `schedule/<刊期>/<运行目录>/run.json`。从中查看刊期、当前阶段、尝试次数和最终状态，详细输出在同目录的日志。可确认的网络故障允许 10 分钟后重试一次。整期生成共用 4 小时时间预算，预采最多 25 分钟。运行中断时，已保存的证据、稿件和缓存可用于下一次生成。跨周补跑时用 `-Date` 指定原刊期。

只有 `candidate_ready` 或 `reused` 表示有可交给主编打开的候选。查看回执给出的候选路径和指纹，再按下节终审发行。

## 核准发行

主编打开候选 `index.html` 和导出图，核对头条和分析的核心主张、来源及图表。检查桌面和窄屏中的标题、正文衔接、图注与导航。候选量尺要有全部版面的通过记录。修改稿件后重新生成候选并核对受影响的位置。指纹以最新候选为准。

已确认候选后才在仓库根执行以下命令，用真实日期和完整指纹替换占位符。

```powershell
python 更新首页.py --date YYYY-MM-DD --approve CANDIDATE_FINGERPRINT
```

发行成功后打开 `docs/index.html`，核对日期和图片。 `docs/YYYY-MM-DD.html` 是该期归档。只提交本期已验收页面及其引用资源，通过仓库的 main 交付约定发布。候选过期、证据已变或任何硬伤尚存时，保留现行首页。

采编文件的存放位置见 [编辑台目录](rules/desk-map.md)。

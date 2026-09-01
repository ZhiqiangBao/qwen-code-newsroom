---
name: fetch-poster
description: "抓官方海报／剧照／主视觉成图：定位图片直链、带 Referer 下载、校验是真图、落 img/日期/。由 fetch 子代理或主编调用；找不到就放弃交 image_gen，不要硬试。"
priority: 30
---

# 官方成图下载

目标：拿到**片方／平台／机构放出的公开成图**（海报、剧照、主视觉、现场照）。本技能只管**怎么把图弄到手并验真**；什么图能上版、黑白处理、图注口径、哪些必须留给 `image_gen`，一律见 `rules/visual.md`（R4）；落盘目录与写盘、下载命令写法见 `rules/disk.md`（R6）「见报图」行。本文件不重复规定。

**硬停条件（本技能自己的规定，别处不再重复）**：最多试 3 个直链；成 1 张即算完成，立刻收手。触发硬停就走降级——素材里写「图片线索：未获取」，交调用方用 `image_gen` 补。这是省时间的全部关键。

**验证状态**：截至 2026-09-02 本技能尚未经过实战调用（历次 `fetch` 均未触发）。首次使用请核对产物是否真落盘、是否通过第 3 步校验，再决定是否长期保留。

## 第 1 步：找图片直链（别在正文里翻）

最稳的是页面 metadata，一条命令就出：

```powershell
$html = (Invoke-WebRequest -Uri '<文章页URL>' -UseBasicParsing -TimeoutSec 20 -Headers @{'User-Agent'='Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}).Content
Select-String -InputObject $html -Pattern '<meta[^>]+(og:image|twitter:image)[^>]+content="([^"]+)"' -AllMatches |
  ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[2].Value } | Select-Object -First 5
```

`og:image` / `twitter:image` 拿到的就是该页主图直链。此外可看 `<img` 标签里的 `data-src`（懒加载站点的真地址常藏在这）。

**注意**：`web_fetch` 返回的是转好的文本，图片地址常被丢掉。要图就用上面的 shell 抓原始 HTML。

## 第 2 步：带 Referer 下载

门户／片方站几乎都防盗链——直链能打开、裸下必 403。必须带来源页 Referer 和浏览器 UA：

```powershell
$hdr = @{'Referer'='<第1步那个文章页URL>'; 'User-Agent'='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
Invoke-WebRequest -Uri '<图片直链>' -OutFile 'img\YYYY-MM-DD\st-movie.jpg' -UseBasicParsing -TimeoutSec 25 -Headers $hdr
```

- 目录先建：`mkdir "img\YYYY-MM-DD"`
- 文件名只用英文或拼音，海报 `st-`、剧照 `ju-`、主视觉 `kv-` 开头。
- 一次失败就换下一个直链。**不要重试同一个，不要换 UA 再赌。**

## 第 3 步：校验（这步不能省）

下回来的经常是 403 错误页或占位图，扩展名照样是 `.jpg`。必须验：

```powershell
$f = 'img\YYYY-MM-DD\st-movie.jpg'
$len = (Get-Item $f).Length
$magic = ([System.BitConverter]::ToString((Get-Content $f -Encoding Byte -TotalCount 3)))
"$f  $len bytes  magic=$magic"
```

判定：

| 情况 | 处理 |
|---|---|
| `< 20 KB` | 判失败，删掉（多半是占位图或错误页） |
| magic 非 `FF-D8-FF`（JPEG）／`89-50-4E`（PNG）／`47-49-46`（GIF）／`52-49-46`（WebP） | 判失败，删掉 |
| 通过 | 保留，进第 4 步 |

删除：`Remove-Item $f -Force`（不要用 `rm`）。

## 第 4 步：登记

按 `.qwen/agents/fetch.md` 素材格式里的「图片线索」节登记（文件名、来源页、图注口径），缺一条都不算完成；图注写什么照 `rules/visual.md`，本文件不另定口径。网页里引用一律正斜杠相对路径。黑白不用单独跑脚本——版式给图片挂了灰度滤镜（取值以 `css/site.css` 为准，别在这里抄数值）。

## 硬规则

- 需要登录、带 DRM、或站点明确禁止外链的，直接放弃。
- 触发上文硬停即按降级路径交代，禁止重试同一个链接。
- 海报／剧照上版不许裁切（实现写法在 `css/site.css` 的图类里，本文件不抄；是否合格由 `layout-check` 按 `rules/page-size.md`（R5）判）。
- 哪类素材算公开成图、哪些必须留给生成图，见 `rules/visual.md`（R4），此处不重复列。

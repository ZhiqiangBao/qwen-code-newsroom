---
name: fetch-poster
description: "抓官方海报／剧照／主视觉成图：定位图片直链、带 Referer 下载、校验是真图、落 img/日期/。由 fetch 子代理或主编调用；找不到就放弃交 image_gen，不要硬试。"
priority: 30
---

# 官方成图下载

目标：拿到**片方／平台／机构放出的公开成图**（海报、剧照、主视觉、现场照），做成黑白上版，图注写「公开资料」。
拿不到就交给 `image_gen`。**最多试 3 个直链，不成就停手**——这是省时间的全部关键。

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
Invoke-WebRequest -Uri '<图片直链>' -OutFile 'img\2026-09-01\st-movie.jpg' -UseBasicParsing -TimeoutSec 25 -Headers $hdr
```

- 目录先建：`mkdir "img\2026-09-01"`
- 文件名只用英文或拼音，海报 `st-`、剧照 `ju-`、主视觉 `kv-` 开头。
- 一次失败就换下一个直链。**不要重试同一个，不要换 UA 再赌。**

## 第 3 步：校验（这步不能省）

下回来的经常是 403 错误页或占位图，扩展名照样是 `.jpg`。必须验：

```powershell
$f = 'img\2026-09-01\st-movie.jpg'
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

在素材文件里写三行，缺一条都不算完成：

```
## 图片线索
- 文件名：img/2026-09-01/st-movie.jpg（已校验，NNN KB）
- 来源页：<文章页 URL>
- 图注口径：公开资料（黑白处理）
```

网页里引用一律正斜杠相对路径 `img/2026-09-01/st-movie.jpg`。黑白处理不用跑脚本，版式 `figure img` 已带 `filter:grayscale(.94)`。

## 硬规则

- **人物头像不要找照片。** 一律 `image_gen` 素描，标注生成。
- 海报／剧照**不许裁切**：`object-fit:contain; max-height:none`，宁可占满一栏。
- 不要下粉丝手机抓拍、营销号抠图、霓虹大头、假人脸。
- 需要登录、带 DRM、或站点明确禁止外链的，直接放弃。
- 3 个直链内拿不到就写「图片线索：未获取」，交主编走 `image_gen`。

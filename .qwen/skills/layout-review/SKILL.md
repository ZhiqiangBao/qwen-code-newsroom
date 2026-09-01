---
name: layout-review
description: "把报纸 HTML 按版导出成 PNG 并量好尺寸，不识图。由 layout-check 调用；主编不要自己跑，也不要 read_file 导出图。"
priority: 30
---

# 按版导出并量尺

只截图与量像素，不看图。识图与判定派 `layout-check`，判定线在 `rules/page-size.md`（R5）。

```powershell
python ".qwen/skills/layout-review/review.py" --html "<rules/disk.md『见报』行的文件>" --output "<rules/disk.md『版面』行的目录>"
```

- `--html`／`--output` 都必填（不给 `--output` 直接报错）——路径模板只在 `rules/disk.md` 里，本文件不另记一份。
- `--pages a1,b1` 只导指定版；`--width <px>`、`--scale <n>` 临时覆盖纸宽与导出倍率（默认从样式表读、倍率 2）。
- 浏览器路径写在 `find_edge()`，非 Windows 自行改这里。

## 脚本做什么

1. 按 `<section class="page">` 切版，剥掉导航，注入 `<base href>` 指向项目根。
2. **把外链的本机样式表（`css/site.css`）内联进临时页**——临时页在别的目录，相对 `<link>` 解析不到。磁盘上的 HTML 仍然是 `<link>`，所以样式只有 `css/site.css` 一处。
3. 从 HTML 与样式表里读 `.page{width:min(<N>px…)}` 与 `--paper`，按 N × 倍率截图（默认 2 倍）。
4. 裁掉底部哨兵绿；整窗都不绿则该版回一条 warning（撞到窗口高＝溢出）。
5. 顺带量好每张 PNG 的像素与高宽比，省掉调用方第二次跑 Python。

## 回吐的 JSON（下面的数字是**示例**，实际值随 `css/site.css` 的纸宽与 `--scale` 变，不要当合格线抄走）

```json
{"ok": true, "dir": "…", "n": 2, "pages": ["01_A1.png", "02_C1.png"],
 "page_width_px": 912, "scale": 2, "expect_png_width_px": 1824, "window_h_px": 3600,
 "measure": [{"page": "01_A1.png", "px": [1824, 3022], "ratio": 1.66}],
 "warnings": ["b2: …底部不是哨兵绿…"]}
```

判定一律拿 `measure[].px`、`measure[].ratio` 对照 `expect_png_width_px` 与 R5 的高宽比区间，不要把任何像素常数抄进别的文件。

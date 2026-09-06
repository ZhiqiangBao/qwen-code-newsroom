---
name: layout-review
description: "把报纸 HTML 按版导出成 PNG 并量好尺寸，不识图。由 layout-check 调 mcp__desk__review；主编不要自己跑，也不要 read_file 导出图。"
priority: 30
---

# 按版导出并量尺

实现已归到 `.qwen/tools/review.py`。调用方用 **`mcp__desk__review`**（`date`，可选 `pages`），不要 `run_shell_command`。

识图与判定派 `layout-check`，合格线在 `rules/page-size.md`（R5）。回吐 JSON 字段：`dir`、`n`、`pages`、`measure[]`（`px`／`ratio`）、`expect_png_width_px`、`warnings`。不要把像素常数抄进别的文件。

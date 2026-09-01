---
name: layout-review
description: "把报纸 HTML 按版导出成 PNG，不识图。由 layout-check 调用；主编不要自己跑，也不要 read_file 导出图。"
priority: 30
---

# 按版导出

只截图，不看图。识图派 `layout-check`。

```powershell
python ".qwen/skills/layout-review/review.py" --html "2026-08-30.html"
```

指定版：`--pages a1,b1`。图落到 `desk/版面/<日期>/`。

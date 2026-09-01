# 更新首页.py —— 把最新一期发布到 docs/，供 GitHub Pages（main /docs）部署
# 产物：docs/index.html（最新一期副本）+ docs/img/（报纸引用的相对路径图片）
# 出刊后运行：python 更新首页.py
import re
import shutil
import sys
from pathlib import Path

root = Path(__file__).parent
issues = sorted(
    p for p in root.glob("*.html") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)
)
if not issues:
    sys.exit("根目录未找到 YYYY-MM-DD.html，不更新")

latest = issues[-1]
site = root / "docs"
site.mkdir(exist_ok=True)
shutil.copyfile(latest, site / "index.html")

# 报纸用相对路径 img/YYYY-MM-DD/xxx，只需最新一期的图片；清掉旧期避免堆积
site_img = site / "img"
if site_img.is_dir():
    shutil.rmtree(site_img)
issue_img = root / "img" / latest.stem
if issue_img.is_dir():
    shutil.copytree(issue_img, site_img / latest.stem)

print(f"docs/index.html ← {latest.name}（本地共 {len(issues)} 期，仅同步 {latest.stem} 配图）")

# 更新首页.py —— 把最新一期发布到 docs/，供 GitHub Pages（main /docs）部署
# 产物：docs/index.html（最新一期副本）+ docs/img/（配图压缩为 JPEG，仅 docs 内；img/ 原图不动）+ docs/css/site.css（样式表副本）
# 出刊后运行：python 更新首页.py
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

root = Path(__file__).parent
issues = sorted(
    p for p in root.glob("*.html") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)
)
if not issues:
    sys.exit("根目录未找到 YYYY-MM-DD.html，不更新")

latest = issues[-1]
site = root / "docs"
site.mkdir(exist_ok=True)

# 报纸用相对路径 img/YYYY-MM-DD/xxx，只需最新一期的图片；清掉旧期避免堆积
site_img = site / "img"
if site_img.is_dir():
    shutil.rmtree(site_img)
issue_img = root / "img" / latest.stem

# 复制时压成 JPEG（灰度照片类 PNG 是体积黑洞），并记录改名供 index.html 改写引用
renamed = {}
if issue_img.is_dir():
    for src in sorted(issue_img.iterdir()):
        dst_dir = site_img / latest.stem
        dst_dir.mkdir(parents=True, exist_ok=True)
        if src.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            im = Image.open(src)
            if im.mode not in ("L", "RGB"):
                im = im.convert("RGB")
            if im.width > 1200:
                im = im.resize((1200, round(im.height * 1200 / im.width)), Image.LANCZOS)
            dst = dst_dir / (src.stem + ".jpg")
            im.convert("L" if im.mode == "L" else "RGB").save(
                dst, "JPEG", quality=82, optimize=True
            )
            if src.suffix.lower() == ".png":
                renamed[src.name] = dst.name
        else:
            shutil.copyfile(src, dst_dir / src.name)

# index.html：复制最新一期，并把改名的 .png 引用改写为 .jpg
html = latest.read_text(encoding="utf-8")
for old, new in renamed.items():
    html = html.replace(old, new)
(site / "index.html").write_text(html, encoding="utf-8")

# 样式表：报纸 HTML 引用 <link href="css/site.css">，发布时一并带上
root_css = root / "css" / "site.css"
if root_css.is_file():
    (site / "css").mkdir(exist_ok=True)
    shutil.copyfile(root_css, site / "css" / "site.css")
elif (site / "css").is_dir():
    shutil.rmtree(site / "css")  # 样式表不存在就不留旧副本

saved = sum(p.stat().st_size for p in site_img.rglob("*")) if site_img.is_dir() else 0
print(
    f"docs/index.html ← {latest.name}（本地共 {len(issues)} 期，"
    f"配图压缩 {len(renamed)} 张 PNG→JPEG，docs/img 共 {saved // 1024} KB，"
    f"样式 {'docs/css/site.css' if root_css.is_file() else '内嵌'}）"
)

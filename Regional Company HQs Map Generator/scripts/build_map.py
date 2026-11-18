#!/usr/bin/env python3
"""把数据集、官方 Logo、第三方库与底图 TopoJSON 注入 HTML 模板，生成单文件地图。

设计前提：**运行时零网络请求**。WorkBuddy 静态 HTML 预览会下发严格 CSP，
connect-src 不含 data: 也不含公网 CDN，页面内 fetch('data:...') / fetch('https://...')
会被拦截并抛 Failed to fetch，导致整张底图降级。因此 D3 / topojson-client /
html2canvas 与 TopoJSON 全部在构建期写进 HTML，页面只读内存对象。

用法:
    # 生成数据骨架（含 1 条示例，需补足到 20 条以上）
    python3 build_map.py --init ./dataset.json --region 日本

    # 校验并构建（自动内嵌 logos/ 目录下的官方 Logo）
    python3 build_map.py --data ./dataset.json --out ./日本-头部企业总部分布图.html --logos-dir ./logos

    # 中国区域：必须传入符合国家标准与审图要求的合规边界数据
    python3 build_map.py --data ./dataset.json --out ./out.html --topo-file ./china-compliant.json

    # 构建后用严格 CSP 复验（推荐）
    python3 verify_map.py --html ./out.html

占位符: __REGION_NAME__ (HTML 文本) / __REGION_JS__ (JS 字符串)
        __MAP_DATA__ (JS 对象字面量) / __TOPO_DATA__ (JS 对象字面量)
        __VENDOR_LIBS__ (构建期内联的 <script> 块)
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_TEMPLATE = SKILL_DIR / "assets" / "map-template.html"
VENDOR_DIR = SKILL_DIR / "assets" / "vendor"
DEFAULT_TOPO_FILE = SKILL_DIR / "assets" / "topo" / "countries-50m.json"
VENDOR_FILES = ("d3.min.js", "topojson-client.min.js", "html2canvas.min.js")
PLACEHOLDERS = ("__REGION_NAME__", "__REGION_JS__", "__MAP_DATA__", "__TOPO_DATA__", "__VENDOR_LIBS__")

try:
    from validate_dataset import validate
    from embed_logos import resolve_logos
except ImportError:  # 从其他 cwd 直接执行时兜底
    sys.path.insert(0, str(SCRIPT_DIR))
    from validate_dataset import validate
    from embed_logos import resolve_logos


SKELETON = {
    "region": "日本",
    "title": "日本头部企业总部分布图",
    "subtitle": "Top 50 · 依据法定注册地标注 · 数据口径请补充年份",
    "map": {
        "object": "countries",
        "match": ["Japan"],
        "sourceLabel": "Natural Earth / world-atlas 50m（构建期内嵌）",
    },
    "layout": {"clusterWidth": 240, "ring": {"pad": 18, "gap": 12}},
    "panels": {
        "outlying": {"label": "离岛 / 飞地"},
        "metro": {"threshold": 0.35, "layoutMode": "auto"}
    },
    "companies": [
        {
            "id": "example-toyota",
            "name": "Toyota",
            "local_name": "トヨタ自動車株式会社",
            "city": "丰田市",
            "prefecture": "爱知县",
            "coords": [137.156, 35.083],
            "industry": "汽车制造",
            "metric": "全球汽车销量第一",
            "desc": "以丰田市为本部的汽车制造商。（示例记录，请替换为真实检索结果）",
            "brandColor": "#EB0A1E",
            "logoFile": "logos/example-toyota.svg",
            "logoSlug": "toyota",
            "metro": "名古屋都市圈"
        }
    ],
}


def js_literal(value) -> str:
    """生成可安全放进 <script> 的 JS 字面量：转义 < > & 与行分隔符，防止 </script> 截断。"""
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return (raw.replace("<", "\\u003c")
               .replace(">", "\\u003e")
               .replace("&", "\\u0026")
               .replace("\u2028", "\\u2028")
               .replace("\u2029", "\\u2029"))


def load_topo(path: Path) -> dict:
    """读取并校验 TopoJSON；失败直接抛 ValueError。"""
    try:
        topo = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"无法读取 TopoJSON {path}：{e}") from e
    if not isinstance(topo, dict) or topo.get("type") != "Topology":
        raise ValueError(f"{path} 不是有效的 TopoJSON（缺少 type: Topology）")
    objects = topo.get("objects")
    if not isinstance(objects, dict) or not objects:
        raise ValueError(f"{path} 缺少 objects")
    if not isinstance(topo.get("arcs"), list):
        raise ValueError(f"{path} 缺少 arcs")
    return topo


def vendor_scripts() -> str:
    """把 assets/vendor/ 下的三个库内联成 <script> 块。"""
    blocks = []
    for name in VENDOR_FILES:
        path = VENDOR_DIR / name
        if not path.is_file():
            raise ValueError(f"缺少离线依赖 {path}；请恢复 assets/vendor/ 目录")
        code = path.read_text(encoding="utf-8").rstrip()
        if re.search(r"</script", code, re.I):
            raise ValueError(f"{name} 含 </script 序列，不能直接内联")
        blocks.append(f"<script>/* vendored {name} · 许可与来源见 assets/PROVENANCE.md */\n{code}\n</script>")
    return "\n".join(blocks)


def requires_compliant_topo(data: dict) -> bool:
    """涉及中国领土轮廓时，禁止使用内置 Natural Earth 境外边界数据。"""
    region = str(data.get("region") or "")
    cfg = data.get("map") if isinstance(data.get("map"), dict) else {}
    match = cfg.get("match") or []
    text = (region + " " + " ".join(str(x) for x in match)).lower()
    tokens = ("china", "中国", "台湾", "taiwan", "hong kong", "香港",
              "macao", "澳门", "南海", "south china sea")
    return any(t in text for t in tokens)


def render(template: str, data: dict, topo: dict, libs: str) -> str:
    region = str(data.get("region") or "目标区域")
    out = template
    out = out.replace("__VENDOR_LIBS__", libs)
    out = out.replace("__REGION_NAME__", html.escape(region, quote=True))
    out = out.replace("__REGION_JS__", js_literal(region))
    out = out.replace("__MAP_DATA__", js_literal(data))
    out = out.replace("__TOPO_DATA__", js_literal(topo))
    return out


def check_placeholders(text: str) -> list[str]:
    return [p for p in PLACEHOLDERS if p in text]


def offline_violations(text: str) -> list[str]:
    """构建期硬校验：成品不得依赖运行时网络。"""
    bad: list[str] = []
    if re.search(r"<script[^>]*\bsrc\s*=", text, re.I):
        bad.append("存在外链 <script src>，预览 CSP / 离线环境会加载失败")
    if re.search(r"<link[^>]*\bhref\s*=\s*[\"']https?://", text, re.I):
        bad.append("存在外链 <link href>")
    if re.search(r"<img[^>]*\bsrc\s*=\s*[\"']https?://", text, re.I):
        bad.append("存在外链 <img src>")
    if re.search(r"<!--\s*<script|</script>\s*-->", text, re.I):
        bad.append("内联依赖被 HTML 注释包裹，浏览器不会执行（占位符不能写在 <!-- --> 里）")
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", text, re.S)
    app = blocks[-1] if blocks else ""
    code = re.sub(r"/\*[\s\S]*?\*/", "", app)
    code = re.sub(r"(?m)^\s*//.*$", "", code)
    if "fetch(" in code:
        bad.append("应用脚本仍调用 fetch()，严格 CSP 下会抛 Failed to fetch")
    if "const EMBEDDED_TOPO" not in app:
        bad.append("应用脚本未声明 EMBEDDED_TOPO")
    if '"type":"Topology"' not in text:
        bad.append("TopoJSON 未内嵌")
    return bad


def write_init(path: Path, region: str | None) -> None:
    skeleton = json.loads(json.dumps(SKELETON, ensure_ascii=False))
    if region:
        skeleton["region"] = region
        skeleton["title"] = f"{region} · 头部企业总部分布图"
        skeleton["map"]["match"] = []
        skeleton["map"]["sourceLabel"] = "请填写合规底图来源（默认 assets/topo/countries-50m.json 仅适用于中国以外地区）"
        skeleton["panels"] = {"outlying": {"label": "离岛 / 飞地"},
                             "metro": {"threshold": 0.35, "layoutMode": "auto"}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(skeleton, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入数据骨架：{path}")
    print("下一步：按 references/data-sources.md 检索并补足 companies 至 20–100 条，再执行构建。")


def main() -> int:
    ap = argparse.ArgumentParser(description="构建零网络请求的单文件企业总部地图 HTML")
    ap.add_argument("--data", help="数据集 JSON 路径")
    ap.add_argument("--out", help="输出 HTML 路径")
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="HTML 模板路径")
    ap.add_argument("--topo-file", help="TopoJSON 路径；涉及中国领土时必须传合规边界数据")
    ap.add_argument("--init", metavar="PATH", help="生成数据骨架后退出")
    ap.add_argument("--region", help="配合 --init 指定地区名")
    ap.add_argument("--logos-dir", help="官方 Logo 目录，按 <id>.png/svg 命名；构建时内嵌为 data URI")
    ap.add_argument("--download-logos", action="store_true", help="尝试下载 company.logoUrl（网络不可用时自动回退）")
    ap.add_argument("--no-embed", action="store_true", help="跳过 Logo 内嵌（仅调试模板时使用）")
    ap.add_argument("--logo-manifest", help="输出缺少官方 Logo 的企业 id 清单 JSON")
    ap.add_argument("--no-validate", action="store_true", help="跳过数据集校验（仅调试模板时使用）")
    args = ap.parse_args()

    if args.init:
        write_init(Path(args.init).expanduser().resolve(), args.region)
        return 0

    if not args.data or not args.out:
        ap.error("构建时必须同时提供 --data 与 --out（或使用 --init）")

    data_path = Path(args.data).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    template_path = Path(args.template).expanduser().resolve()
    topo_path = Path(args.topo_file).expanduser().resolve() if args.topo_file else DEFAULT_TOPO_FILE.resolve()

    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: 无法读取数据集 {data_path}：{e}")
        return 1

    # 合规红线：中国区域不得使用内置 Natural Earth 边界
    if requires_compliant_topo(data) and topo_path == DEFAULT_TOPO_FILE.resolve():
        print("ERROR: 涉及中国领土轮廓，禁止使用内置 Natural Earth / world-atlas 境外边界数据。")
        print("       请用 --topo-file 传入符合国家标准与审图要求的 TopoJSON（自然资源部标准地图 / 天地图等合规来源），")
        print("       并在 map.sourceLabel 写明来源；标注统一使用「中国台湾 / 中国香港 / 中国澳门」。")
        return 1
    if requires_compliant_topo(data):
        print(f"底图合规：使用自定义 TopoJSON {topo_path.name}；请确认已标注来源且边界符合国家标准。")

    try:
        topo = load_topo(topo_path)
        libs = vendor_scripts()
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    # 先内嵌官方 Logo，再做校验，让 Logo 覆盖率告警基于真实结果
    if not args.no_embed:
        logos_dir = Path(args.logos_dir).expanduser().resolve() if args.logos_dir else None
        if logos_dir and not logos_dir.is_dir():
            print(f"WARNING Logo 目录不存在：{logos_dir}（将跳过目录扫描）")
            logos_dir = None
        logo_stats = resolve_logos(data, data_path.parent, logos_dir, args.download_logos)
        total = len(data.get("companies") or [])
        print(f"Logo 内嵌：官方图 {len(logo_stats['embedded'])}/{total} · "
              f"中性占位 {len(logo_stats['fallback'])} · 伪 Logo/失败 {len(logo_stats['failed'])}")
        for f in logo_stats["failed"][:6]:
            print(f"  REJECT {f['id']}: {f['reason']}")
        if args.logo_manifest:
            m = Path(args.logo_manifest).expanduser().resolve()
            m.parent.mkdir(parents=True, exist_ok=True)
            m.write_text(json.dumps({
                "missing_logos": logo_stats["fallback"],
                "rejected": logo_stats["failed"],
                "policy": "禁止首字母牌 / 纯文字字标冒充 Logo；缺失显示无字母无文字的中性占位",
                "naming": "运行 fetch_logos.py 抓取官方 SVG，或把官方图保存为 logos/<id>.svg，再执行 build_map.py --logos-dir logos",
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"缺图清单：{m}")

    if not args.no_validate:
        report = validate(data)
        for e in report["errors"]:
            print("ERROR   " + e)
        for w in report["warnings"]:
            print("WARNING " + w)
        if report["errors"]:
            print("已终止构建：请先修正 error 级问题。")
            return 1
        s = report["stats"]
        print(f"校验通过：{s.get('companies')} 家企业 / {s.get('cities')} 个城市集群 / "
              f"最高都会区 {s.get('top_metro', '?')} {s.get('top_metro_share', 0):.0%} / "
              f"右下区块 {'需启用' if s.get('metro_panel_required') else '非必需'} / "
              f"离岛飞地 {s.get('outlying_count', 0)} 家 / 官方 Logo {s.get('logo_embedded', 0)} 张")
    else:
        print("WARNING 已跳过数据集校验，输出可能不符合质量清单。")

    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"ERROR: 无法读取模板 {template_path}：{e}")
        return 1

    missing = [p for p in PLACEHOLDERS if p not in template]
    if missing:
        print(f"ERROR: 模板缺少占位符 {missing}，请检查 assets/map-template.html")
        return 1

    rendered = render(template, data, topo, libs)
    leftover = check_placeholders(rendered)
    if leftover:
        print(f"ERROR: 占位符未被完全替换：{leftover}")
        return 1
    violations = offline_violations(rendered)
    if violations:
        for v in violations:
            print("ERROR   " + v)
        print("已终止构建：成品必须运行时零网络请求，否则预览 CSP 会拦截底图加载。")
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    obj = (data.get("map") or {}).get("object") or next(iter(topo["objects"]))
    geoms = topo["objects"].get(obj, {}).get("geometries", [])
    print(f"已生成单文件 HTML：{out_path}")
    print(f"底图 {topo_path.name}（{len(geoms)} 个要素）+ 3 个依赖库 + 官方 Logo 全部内嵌，运行时零网络请求")
    print(f"收录 {len(data.get('companies', []))} 家 · 官方 Logo {len([c for c in data.get('companies', []) if c.get('logoDataUri')])} 张 · "
          f"四周均匀环绕 + 都会区双布局自动择优 + 左下离岛区块")
    print(f"建议复验：python3 {SCRIPT_DIR / 'verify_map.py'} --html {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

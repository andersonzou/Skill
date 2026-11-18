#!/usr/bin/env python3
"""校验「区域头部企业总部地图」数据集。

用法:
    python3 validate_dataset.py <dataset.json> [--json] [--quiet]

校验项：结构 / 收录数量 [20,100] / 必填字段 / 坐标范围 / ID 唯一 /
        品牌色与枚举值 / 行业多样性 / 城市集中度与特写视口触发 / 推荐字段完整度。

退出码：0 = 无 error；1 = 存在 error 或文件无法读取。
本模块不依赖第三方库，可直接被 build_map.py import。
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

MIN_COMPANIES = 20
MAX_COMPANIES = 100
INSET_THRESHOLD = 0.35
# 底图在构建期由 build_map.py 内嵌；运行时不请求任何 URL。
DEFAULT_TOPO_FILE = "assets/topo/countries-50m.json"

REQUIRED_FIELDS = ("id", "name", "city", "coords", "industry")
RECOMMENDED_FIELDS = ("local_name", "prefecture", "metric", "desc", "brandColor", "wordmark", "logoStyle")
ALLOWED_FIELDS = set(
    REQUIRED_FIELDS + RECOMMENDED_FIELDS
    + ("mark", "markShape", "logoFile", "logoUrl", "logoDataUri", "logoSlug", "logoSlugs",
       "metro", "outlying")
)
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
LOGO_STYLES = {"sans", "serif", "heavy", "italic"}
MARK_SHAPES = {"square", "circle", "diamond"}
METRO_LAYOUT_MODES = {"auto", "cols4", "cols-4", "cols2", "cols-2"}


def decode_svg_data_uri(uri: str) -> str | None:
    """取出 data:image/svg+xml 的 SVG 源码；非 SVG 返回 None。"""
    if not isinstance(uri, str) or not uri.startswith("data:image/svg+xml"):
        return None
    head, _, payload = uri.partition(",")
    if not payload:
        return None
    if "base64" in head.lower():
        try:
            return base64.b64decode(payload).decode("utf-8", errors="replace")
        except Exception:
            return None
    return urllib.parse.unquote(payload)


def is_fake_logo(svg: str) -> str | None:
    """识别「首字母色块 / 纯文字字标」伪 Logo；返回原因，合法则 None。

    真实官方 Logo（worldvectorlogo / 官方素材）以 <path> 矢量图形为主；
    程序生成的伪 Logo 只用 <rect> 色块 + <text> 文字，且常见 64x20 窄幅版式。
    """
    if not svg:
        return None
    texts = re.findall(r"<text\b[^>]*>(.*?)</text>", svg, re.I | re.S)
    has_vector = bool(re.search(r"<(path|polygon|polyline|circle|ellipse|image|use)\b", svg, re.I))
    if texts and any(len(re.sub(r"<[^>]+>", "", t).strip()) == 1 for t in texts) and not has_vector:
        return "首字母色块占位（<text> 单字母 + 色块），不是官方 Logo"
    # 官方 Logo 的字标均已转曲为 <path>；旧版模板生成的拼装牌固定 64x20 且含 <text>
    if texts and re.search(r'viewBox="\s*0\s+0\s+64\s+20\s*"', svg, re.I):
        return "程序拼装字标牌（64×20 版式 + <text>），不是官方 Logo 原图"
    if texts and not has_vector:
        return "纯文字字标占位（仅 <text> + 色块），不是官方 Logo"
    vb = re.search(r'viewBox="([^"]+)"', svg, re.I)
    nums = re.findall(r"[-+]?[\d.]+", vb.group(1)) if vb else []
    narrow = len(nums) == 4 and float(nums[3]) > 0 and float(nums[2]) / float(nums[3]) >= 2.5
    if texts and narrow and not has_vector:
        return "窄幅文字牌，疑似程序生成徽标"
    if re.search(r'\bviewBox="[^"]*"[^>]*\bviewBox="', svg, re.I) or len(re.findall(r"\bviewBox=", svg, re.I)) > 1:
        return "SVG 含重复 viewBox 属性（浏览器会判为无效图并破图）"
    return None


def validate(data: object) -> dict:
    """返回 {'errors': [...], 'warnings': [...], 'stats': {...}}。"""
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict = {}

    if not isinstance(data, dict):
        return {"errors": ["顶层必须是 JSON 对象"], "warnings": [], "stats": {}}

    region = data.get("region")
    if not isinstance(region, str) or not region.strip():
        errors.append("缺少必填顶层字段 region（非空字符串）")

    for key in ("map", "layout", "inset", "panels"):
        if key in data and not isinstance(data[key], dict):
            errors.append(f"顶层字段 {key} 必须是对象")

    companies = data.get("companies")
    if not isinstance(companies, list):
        errors.append("缺少必填顶层字段 companies（数组）")
        return {"errors": errors, "warnings": warnings, "stats": stats}

    n = len(companies)
    stats["companies"] = n
    if n < MIN_COMPANIES or n > MAX_COMPANIES:
        errors.append(f"收录企业数量 {n} 越界，必须处于 [{MIN_COMPANIES}, {MAX_COMPANIES}] 区间")

    seen_ids: set[str] = set()
    cities: Counter = Counter()
    industries: Counter = Counter()
    metros: Counter = Counter()
    outlying_groups: Counter = Counter()
    missing_recommended: Counter = Counter()
    logo_embedded = 0

    for idx, c in enumerate(companies):
        tag = f"companies[{idx}]"
        if not isinstance(c, dict):
            errors.append(f"{tag} 必须是对象")
            continue

        for field in REQUIRED_FIELDS:
            if field not in c or c[field] in (None, "", []):
                errors.append(f"{tag} 缺少必填字段 {field}")

        cid = c.get("id")
        if isinstance(cid, str) and cid:
            if cid in seen_ids:
                errors.append(f"{tag} id 重复：{cid}")
            seen_ids.add(cid)
            tag = f"companies[{cid}]"
        elif cid is not None:
            errors.append(f"{tag} id 必须是非空字符串")

        coords = c.get("coords")
        if coords is not None:
            if not isinstance(coords, list) or len(coords) != 2:
                errors.append(f"{tag} coords 必须是 [经度, 纬度] 两个数字")
            elif not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in coords):
                errors.append(f"{tag} coords 含非数字值")
            else:
                lon, lat = float(coords[0]), float(coords[1])
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    errors.append(f"{tag} coords 超出范围：经度 [-180,180] / 纬度 [-90,90]")
                if abs(lon) < 0.001 and abs(lat) < 0.001:
                    warnings.append(f"{tag} 坐标接近 (0,0)，疑似占位值，请核验")

        color = c.get("brandColor")
        if color is not None and (not isinstance(color, str) or not COLOR_RE.match(color)):
            errors.append(f"{tag} brandColor 必须是 6 位 HEX，如 #EB0A1E")
        if c.get("logoStyle") not in (None, *LOGO_STYLES):
            errors.append(f"{tag} logoStyle 必须是 {sorted(LOGO_STYLES)} 之一")
        if c.get("markShape") not in (None, *MARK_SHAPES):
            errors.append(f"{tag} markShape 必须是 {sorted(MARK_SHAPES)} 之一")

        logo_uri = c.get("logoDataUri")
        if logo_uri:
            if not isinstance(logo_uri, str) or not logo_uri.startswith("data:image/"):
                errors.append(f"{tag} logoDataUri 必须是 data:image/... 内嵌图，禁止外链 http(s) 图片")
            else:
                fake = is_fake_logo(decode_svg_data_uri(logo_uri))
                if fake:
                    errors.append(
                        f"{tag} logoDataUri 是伪 Logo：{fake}。禁止用首字母或文字牌冒充 Logo；"
                        f"请用 fetch_logos.py 抓取官方原图，缺失则留空由模板显示中性占位"
                    )
                else:
                    logo_embedded += 1
        if c.get("logoSlugs") is not None and not isinstance(c.get("logoSlugs"), list):
            errors.append(f"{tag} logoSlugs 必须是字符串数组")
        if c.get("logoSlug") is not None and not isinstance(c.get("logoSlug"), str):
            errors.append(f"{tag} logoSlug 必须是字符串")
        for f in ("logoFile", "logoUrl", "metro", "outlying"):
            if c.get(f) is not None and not isinstance(c[f], str):
                errors.append(f"{tag} {f} 必须是字符串")
        if isinstance(c.get("logoUrl"), str) and c["logoUrl"].startswith("data:"):
            errors.append(f"{tag} logoUrl 应为 http(s) 直链；内嵌图请写入 logoDataUri")

        unknown = set(c) - ALLOWED_FIELDS
        if unknown:
            warnings.append(f"{tag} 存在未识别字段（模板将忽略）：{', '.join(sorted(unknown))}")

        for field in RECOMMENDED_FIELDS:
            if not c.get(field):
                missing_recommended[field] += 1

        city = c.get("city")
        if isinstance(city, str) and city.strip():
            cities[city.strip()] += 1
        industry = c.get("industry")
        if isinstance(industry, str) and industry.strip():
            industries[industry.strip()] += 1
        metro_key = (c.get("metro") or c.get("city"))
        if isinstance(metro_key, str) and metro_key.strip():
            metros[metro_key.strip()] += 1
        out = c.get("outlying")
        if isinstance(out, str) and out.strip():
            outlying_groups[out.strip()] += 1

    stats["cities"] = len(cities)
    stats["industries"] = len(industries)
    stats["top_city"] = cities.most_common(1)[0] if cities else None
    stats["logo_embedded"] = logo_embedded
    stats["logo_total"] = n
    stats["outlying_groups"] = dict(outlying_groups)
    stats["metro_groups"] = dict(metros.most_common(5))

    # 行业多样性
    if industries and len(industries) < 5:
        warnings.append(f"行业仅 {len(industries)} 类，建议覆盖至少 5 类以保证多样性")
    if n and industries:
        top_industry, cnt = industries.most_common(1)[0]
        if cnt / n > 0.40:
            warnings.append(f"行业「{top_industry}」占比 {cnt / n:.0%}，建议控制在 40% 以内")

    # 面板配置（左下离岛/飞地、右下都会区）
    panels = data.get("panels") if isinstance(data.get("panels"), dict) else {}
    metro_cfg = panels.get("metro") if isinstance(panels.get("metro"), dict) else {}
    out_cfg = panels.get("outlying") if isinstance(panels.get("outlying"), dict) else {}
    if data.get("inset") is not None:
        warnings.append("inset 字段已弃用，请改用 panels.metro（模板仍兼容读取）")

    threshold = metro_cfg.get("threshold", INSET_THRESHOLD)
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        errors.append("panels.metro.threshold 必须是 0–1 之间的数字")
        threshold = INSET_THRESHOLD
    mode = metro_cfg.get("layoutMode")
    if mode is not None and mode not in METRO_LAYOUT_MODES:
        errors.append(f"panels.metro.layoutMode 必须是 {sorted(METRO_LAYOUT_MODES)} 之一；省略时为自动择优")
    ring = (data.get("layout") or {}).get("ring") if isinstance(data.get("layout"), dict) else None
    if ring is not None:
        if not isinstance(ring, dict):
            errors.append("layout.ring 必须是对象（四周环绕布局参数）")
        else:
            for key in ("pad", "gap"):
                if key in ring and (not isinstance(ring[key], (int, float)) or ring[key] < 0):
                    errors.append(f"layout.ring.{key} 必须是非负数字")

    # 都会区集中度：以 metro 为准，缺失时以 city 兜底
    if n and metros:
        top_metro, cnt = metros.most_common(1)[0]
        share = cnt / n
        stats["top_metro"] = top_metro
        stats["top_metro_share"] = round(share, 4)
        stats["metro_panel_required"] = share > threshold
        if share > threshold:
            if metro_cfg.get("enabled") is False:
                errors.append(
                    f"都会区「{top_metro}」占比 {share:.0%} > {threshold:.0%}，必须启用右下都会区区块（panels.metro.enabled 不得为 false）"
                )
            if metro_cfg.get("target") and metro_cfg["target"] not in metros:
                errors.append(f"panels.metro.target「{metro_cfg['target']}」与任何 metro/city 分组键都不匹配")
            for key in metro_cfg.get("keys") or []:
                if key not in metros:
                    errors.append(f"panels.metro.keys 中的「{key}」与任何 metro/city 分组键都不匹配")
        elif metro_cfg.get("enabled") is True and not metro_cfg.get("force"):
            warnings.append(f"最高都会区占比仅 {share:.0%}，未超过 {threshold:.0%}；右下区块仍会按显式配置绘制")

    # 离岛 / 飞地
    stats["outlying_count"] = sum(outlying_groups.values())
    if outlying_groups and out_cfg.get("enabled") is False:
        errors.append("存在离岛/飞地企业，必须启用左下离岛区块（panels.outlying.enabled 不得为 false）")
    known_city_keys = set(cities) | set(outlying_groups)
    for g in out_cfg.get("groups") or []:
        if not isinstance(g, dict) or not g.get("name"):
            errors.append("panels.outlying.groups 的每一项必须包含 name")
            continue
        for key in g.get("cities") or []:
            if key not in known_city_keys:
                errors.append(f"离岛分组「{g['name']}」中的 city「{key}」与任何 company.city / outlying 都不匹配")

    # Logo 覆盖率
    if n:
        coverage = logo_embedded / n
        stats["logo_coverage"] = round(coverage, 4)
        if coverage < 0.8:
            warnings.append(
                f"仅 {logo_embedded}/{n} 家企业内嵌了官方 Logo（{coverage:.0%}）；"
                f"缺失的 {n - logo_embedded} 家将由模板显示无字母、无文字的中性占位，"
                f"请用 fetch_logos.py 补抓官方原图或把 <id>.svg 放入 logos/"
            )
        if any(c.get("logoFile") for c in companies if isinstance(c, dict)) and logo_embedded == 0:
            warnings.append("数据集含 logoFile 但未内嵌任何图片；请检查路径或使用 build_map.py --logos-dir")

    # 底图配置：TopoJSON 在构建期内嵌，运行时零网络请求
    cfg = data.get("map") if isinstance(data.get("map"), dict) else {}
    if cfg.get("topoUrl"):
        warnings.append("map.topoUrl 已弃用：底图由 build_map.py 在构建期从 assets/topo/ 或 --topo-file 内嵌，"
                        "运行时不会请求该 URL；如需记录来源请写 map.sourceLabel")
    if cfg.get("topoFile") is not None and not isinstance(cfg["topoFile"], str):
        errors.append("map.topoFile 必须是字符串路径（或直接给 build_map.py 传 --topo-file）")
    region_and_match = str(data.get("region") or "") + " " + " ".join(
        str(x) for x in (cfg.get("match") or []))
    if any(t in region_and_match.lower() for t in
           ("china", "中国", "台湾", "taiwan", "hong kong", "香港", "macao", "澳门", "南海")):
        warnings.append("涉及中国领土轮廓：构建时必须用 --topo-file 传入符合国家标准与审图要求的边界数据，"
                        "并在 map.sourceLabel 标注来源；build_map.py 会拦截默认境外底图")
    if cfg.get("padding") is not None:
        p = cfg["padding"]
        if not (isinstance(p, list) and len(p) == 4 and all(isinstance(v, (int, float)) for v in p)):
            errors.append("map.padding 必须是 [top, right, bottom, left] 四个数字")
    width = (data.get("layout") or {}).get("clusterWidth") if isinstance(data.get("layout"), dict) else None
    if width is not None and (not isinstance(width, (int, float)) or not 120 <= width <= 360):
        errors.append("layout.clusterWidth 必须是 120–360 之间的数字")

    for field, cnt in missing_recommended.items():
        warnings.append(f"推荐字段 {field} 缺失 {cnt} 条（影响详情信息与徽标还原度）")

    return {"errors": errors, "warnings": warnings, "stats": stats}


def load(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    ap = argparse.ArgumentParser(description="校验区域企业总部地图数据集")
    ap.add_argument("dataset", help="dataset.json 路径")
    ap.add_argument("--json", action="store_true", help="以 JSON 格式输出报告")
    ap.add_argument("--quiet", action="store_true", help="只输出错误与摘要")
    args = ap.parse_args()

    try:
        report = validate(load(args.dataset))
    except (OSError, json.JSONDecodeError) as e:
        msg = f"无法读取数据集：{e}"
        print(json.dumps({"errors": [msg], "warnings": [], "stats": {}}, ensure_ascii=False) if args.json else "ERROR: " + msg)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["errors"] else 0

    for e in report["errors"]:
        print("ERROR   " + e)
    if not args.quiet:
        for w in report["warnings"]:
            print("WARNING " + w)
    s = report["stats"]
    print(f"SUMMARY 企业 {s.get('companies', '?')} 家 / 城市 {s.get('cities', '?')} 个 / "
          f"行业 {s.get('industries', '?')} 类 / 最高都会区 {s.get('top_metro', '?')} "
          f"{s.get('top_metro_share', 0):.0%} / 离岛 {s.get('outlying_count', 0)} 家 / "
          f"官方 Logo {s.get('logo_embedded', 0)} 张 / "
          f"错误 {len(report['errors'])} 条 / 警告 {len(report['warnings'])} 条")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())

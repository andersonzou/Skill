#!/usr/bin/env python3
"""从 worldvectorlogo 抓取企业/品牌的官方矢量 Logo，供 build_map.py 内嵌。

设计前提
--------
本 skill **禁止使用首字母色块、文字字标或任何"占位徽标"冒充 Logo**。
每家企业必须有一张真实官方 Logo 图；抓取不到的企业不生成假 Logo，
而是写入 missing-logos.json，由模板显示无字母、无文字的中性占位。

来源
----
worldvectorlogo 的 SVG 直链形如 https://cdn.worldvectorlogo.com/logos/<slug>.svg
slug 与站内 /logo/<slug> 页面一致，同名品牌常带 -1 / -2 版本后缀。
本脚本按候选 slug 并发探测，命中即以官方原图保存（不重绘、不拼字标）。

用法
----
    # 按数据集自动抓取（可写 company.logoSlug / logoSlugs 指定确切 slug）
    python3 fetch_logos.py --data dataset.json --out-dir ./logos \
                           --manifest ./missing-logos.json

    # 用外部 slug 映射表（{"company-id": ["slug-a","slug-b"]}）
    python3 fetch_logos.py --data dataset.json --out-dir ./logos --hints ./slugs.json

    # 网络不可用时跳过抓取，只统计本地已有素材
    python3 fetch_logos.py --data dataset.json --out-dir ./logos --offline

产物：out-dir/<company.id>.svg，以及 manifest 中的来源与缺失清单。
抓取完成后执行 build_map.py --logos-dir ./logos 即可内嵌。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
import urllib.request
from pathlib import Path

CDN = "https://cdn.worldvectorlogo.com/logos/{slug}.svg"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
MAX_BYTES = 900_000
VERSION_SUFFIXES = ("", "-1", "-2", "-3")

# 从品牌全称派生 slug 时剥离的通用公司后缀（不改变品牌识别部分）
GENERIC_TAILS = (
    "financial group", "holdings", "group", "corporation", "company", "co ltd",
    "motor", "motors", "industries", "pharmaceutical", "manufacturing",
    "electric power", "brewery", "breweries", "limited", "inc", "ltd",
)

try:
    from embed_logos import sanitize_svg
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from embed_logos import sanitize_svg


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def candidate_slugs(company: dict, hints: dict) -> tuple[list[str], list[str]]:
    """返回 (精确候选, 派生候选)。精确候选来自显式配置，直接试用、不加版本后缀。"""
    cid = str(company.get("id") or "")
    exact: list[str] = []

    explicit = company.get("logoSlugs")
    if isinstance(explicit, list):
        exact.extend(str(s) for s in explicit if s)
    if isinstance(company.get("logoSlug"), str) and company["logoSlug"].strip():
        exact.append(company["logoSlug"].strip())
    hv = hints.get(cid)
    if isinstance(hv, list):
        exact.extend(str(s) for s in hv if s)

    bases = [cid, company.get("wordmark") or "", company.get("name") or ""]
    name = str(company.get("name") or "").lower()
    for tail in GENERIC_TAILS:
        if name.endswith(tail):
            bases.append(name[: -len(tail)].strip())

    def dedup(seq):
        seen: set[str] = set()
        out = []
        for x in seq:
            s = slugify(x)
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    exact = dedup(exact)
    derived = dedup(bases)
    return exact, derived


def harden_svg(text: str) -> str | None:
    """清洗并返回可安全内嵌的 SVG；不可用时返回 None。"""
    text = sanitize_svg(text)
    # 外链资源（<image href>、<use href="http...">）在严格 CSP 下会失败
    text = re.sub(r"<image\b.*?(?:/>|</image\s*>)", "", text, flags=re.I | re.S)
    text = re.sub(r"\s(?:xlink:)?href\s*=\s*(['\"])(?:https?:)?//.*?\1", "", text, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style\s*>", "", text, flags=re.I | re.S)
    m = re.search(r"<svg\b[^>]*>", text, re.I)
    if not m or "</svg" not in text.lower():
        return None
    # 必须有实际图形内容，避免拿到空壳
    if not re.search(r"<(path|polygon|polyline|rect|circle|ellipse|g|text|use)\b", text, re.I):
        return None
    # viewBox 缺失才补一份，保证 object-fit: contain 计算得出真实宽高比。
    # 注意统一转小写比对：重复 viewBox 属性会让浏览器直接判定 SVG 无效并破图。
    tag = m.group(0)
    if "viewbox=" not in tag.lower():
        w = re.search(r'\bwidth="([\d.]+)', tag)
        h = re.search(r'\bheight="([\d.]+)', tag)
        if w and h:
            text = text.replace(tag, tag[:-1] + f' viewBox="0 0 {w.group(1)} {h.group(1)}">', 1)
    # 兜底：任何情况下都不允许出现两个 viewBox
    text = re.sub(r'(viewBox="[^"]*")\s+viewBox="[^"]*"', r'\1', text, count=1, flags=re.I)
    return text.strip()


def fetch_one(slug: str, timeout: float) -> tuple[str, str] | None:
    try:
        req = urllib.request.Request(CDN.format(slug=slug), headers={
            "User-Agent": UA, "Accept": "image/svg+xml,*/*",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(MAX_BYTES + 1)
        if not data or len(data) > MAX_BYTES:
            return None
        text = data.decode("utf-8", errors="replace")
        if "<svg" not in text[:600].lower():
            return None
        cleaned = harden_svg(text)
        return (slug, cleaned) if cleaned else None
    except Exception:
        return None


def resolve(company: dict, hints: dict, workers: int, timeout: float) -> tuple[str, str] | None:
    """返回 (slug, svg_text)。精确候选先串行快试，其余并发且命中即取消剩余请求。"""
    exact, derived = candidate_slugs(company, hints)
    for slug in exact:
        hit = fetch_one(slug, timeout)
        if hit:
            return hit

    rest = [s + suffix for s in derived for suffix in VERSION_SUFFIXES]
    rest += [s + suffix for s in exact for suffix in VERSION_SUFFIXES[1:]]
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {ex.submit(fetch_one, s, timeout): s for s in dict.fromkeys(rest)}
        for fut in concurrent.futures.as_completed(futures):
            hit = fut.result()
            if hit:
                return hit
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="抓取 worldvectorlogo 官方品牌 SVG Logo")
    ap.add_argument("--data", required=True, help="dataset.json 路径")
    ap.add_argument("--out-dir", required=True, help="Logo 输出目录（按 <id>.svg 命名）")
    ap.add_argument("--hints", help="slug 映射 JSON：{\"id\": [\"slug-a\", \"slug-b\"]}")
    ap.add_argument("--manifest", help="输出来源与缺图清单 JSON")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--timeout", type=float, default=12.0)
    ap.add_argument("--offline", action="store_true", help="不联网，仅统计本地已有素材")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的本地 Logo 文件")
    args = ap.parse_args()

    data_path = Path(args.data).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: 无法读取数据集 {data_path}：{e}")
        return 1

    hints: dict = {}
    if args.hints:
        try:
            hints = json.loads(Path(args.hints).expanduser().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"ERROR: 无法读取 hints：{e}")
            return 1

    companies = [c for c in data.get("companies") or [] if isinstance(c, dict)]
    found: dict[str, str] = {}
    missing: list[str] = []

    for c in companies:
        cid = str(c.get("id") or c.get("name") or "?")
        target = out_dir / f"{cid}.svg"
        if target.is_file() and not args.force:
            found[cid] = target.name + " (local)"
            continue
        if args.offline:
            missing.append(cid)
            continue
        hit = resolve(c, hints, args.workers, args.timeout)
        if hit:
            slug, svg = hit
            target.write_text(svg + "\n", encoding="utf-8")
            found[cid] = slug
            print(f"  OK   {cid:24s} <- {slug}")
        else:
            missing.append(cid)
            print(f"  MISS {cid:24s}  （该站无此品牌官方 Logo，将使用中性占位）")

    total = len(companies)
    print(f"官方 Logo：{len(found)}/{total} · 缺失 {len(missing)} · 目录 {out_dir}")
    if missing:
        print("待补 id：" + ", ".join(missing))
        print("补齐方式：把官方 SVG/PNG 存为 logos/<id>.svg，或写 company.logoUrl 后重新抓取。")

    if args.manifest:
        m = Path(args.manifest).expanduser().resolve()
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(json.dumps({
            "source": "worldvectorlogo.com (cdn.worldvectorlogo.com/logos/<slug>.svg)",
            "total": total,
            "found": len(found),
            "missing_logos": missing,
            "slugs": {k: v for k, v in found.items() if not v.endswith("(local)")},
            "policy": "缺失企业不生成首字母/文字占位 Logo；模板显示无字母无文字的中性标记",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"清单：{m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

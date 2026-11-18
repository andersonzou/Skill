#!/usr/bin/env python3
"""第二层 Logo 来源：从企业官网发现并抓取官方 SVG Logo。

为什么需要分层
--------------
第一层 `fetch_logos.py` 走 worldvectorlogo 的官方 CDN，覆盖率约 88%（38/43），
但地方银行、区域公用事业等常缺图。本脚本补第二层：企业官网自己的 SVG Logo。

「搜索官网」这一步**不在脚本内做**：实测当前网络下 Google / DuckDuckGo 直连
返回 000、Bing 返回 302，且抓搜索引擎 HTML 违反其使用条款、极易被封。正确做法是
由 Agent 用 WorkBuddy 的搜索能力查到官网，把结果写进数据集的
`company.officialSite` / `company.officialLogoUrl`，或用 `--sites` 传入；脚本只做
确定性的「抓官网 → 发现候选 → 严格校验 → 落盘」。

安全红线
--------
- 绝不生成首字母色块、文字字标或任何替代 Logo；任何不确定的候选一律丢弃。
- 只采用官网页面自身引用的 SVG，且必须通过 `looks_like_logo()` 全部校验。
- 抓到的图标 / 横幅 / 装饰图不是 Logo，宁可留中性占位也不误用。
- 未命中写入 manifest 的 `unverified`，供人工复核，不写 `<id>.svg` 文件。

用法
----
    # 官网写进数据集（推荐）
    python3 fetch_official_logos.py --data dataset.json --out-dir logos \
                                    --manifest official-logos.json

    # 或用外部映射 {"company-id": "https://www.example.com/"}
    python3 fetch_official_logos.py --data dataset.json --out-dir logos \
                                    --sites sites.json

    # 支持 {"company-id": {"site": "...", "logoUrl": "https://.../logo.svg"}}
    # --dry-run 只列候选不写文件；--force 覆盖已有本地 Logo。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
MAX_BYTES = 900_000
MAX_HTML_BYTES = 2_000_000

# 文件名命中这些词才可能是 Logo；命中排除词一律不看（官网里 90% 的 .svg 是 UI 图标）
GOOD_WORDS = ("logo", "brand", "wordmark", "logotype", "corporate", "symbol")
BAD_WORDS = (
    "icon", "btn", "button", "banner", "bnr", "social", "sns", "search", "arrow",
    "sprite", "background", "decoration", "illust", "loading", "spinner",
    "facebook", "twitter", "instagram", "linkedin", "youtube", "chevron",
    "menu", "hamburger", "close", "nav", "qr", "thumb", "photo", "ad-", "cm-",
    "footer", "header_icon", "pict", "deco", "line", "tel", "mail", "share",
)
COMMON_PATHS = (
    "/logo.svg", "/img/logo.svg", "/images/logo.svg", "/assets/logo.svg",
    "/common/images/logo.svg", "/_themes/assets/img/common/img_logo.svg",
)
VECTOR_TAGS = ("path", "polygon", "polyline", "rect", "circle", "ellipse", "g", "text", "use")

try:
    from fetch_logos import harden_svg
    from validate_dataset import is_fake_logo
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fetch_logos import harden_svg
    from validate_dataset import is_fake_logo


def _ssl_context(verified: bool):
    """macOS 自带 Python 常缺根证书；优先用 certifi 的 CA 做验证。"""
    ctx = ssl.create_default_context()
    if verified:
        try:
            import certifi
            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            return ctx
    # 仅对公开静态资源、且证书链验证失败时回退；不发送任何凭据
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


SSL_VERIFIED = _ssl_context(True)
SSL_RELAXED = _ssl_context(False)


def get(url: str, timeout: float, accept: str = "*/*") -> str | None:
    """下载并解码为文本；失败返回 None。证书链不完整时降级重试一次。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": accept,
        "Accept-Language": "ja,en;q=0.8",
    })
    for ctx in (SSL_VERIFIED, SSL_RELAXED):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read(MAX_BYTES + 1)
            if not raw or len(raw) > MAX_BYTES:
                return None
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if all(k not in ctype for k in ("svg", "xml", "text", "octet-stream")):
                return None
            return raw.decode("utf-8", errors="replace")
        except (ssl.SSLCertVerificationError, urllib.error.URLError) as e:
            # 只在证书验证失败时用宽松上下文重试；代理 502 / 超时直接放弃
            if ctx is SSL_VERIFIED and "CERTIFICATE_VERIFY" in str(getattr(e, "reason", e)).upper():
                continue
            return None
        except Exception:
            return None
    return None


def score_candidate(url: str) -> int | None:
    """按文件名给候选打分；命中排除词返回 None（硬排除）。"""
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path).lower()
    name = path.rsplit("/", 1)[-1]
    if any(w in path for w in BAD_WORDS):
        return None
    score = 0
    for w in GOOD_WORDS:
        if w in name:
            score += 10
        elif w in path:
            score += 4
    if name.startswith("logo") or name.startswith("img_logo"):
        score += 6
    return score if score > 0 else None


SVG_REF = re.compile(
    r"""(?:(?:src|data-src|data-original|href|content|srcset)\s*=\s*|
         url\(\s*)(?:["'])?([^"'\s)>]+\.svg(?:\?[^"'\s)>]*)?)""",
    re.I | re.X,
)


def extract_svg_urls(html: str, base: str) -> list[tuple[str, int]]:
    """从首页 HTML 抽取 SVG 引用，绝对化、打分、去重、按分数降序。"""
    seen: dict[str, int] = {}
    for m in SVG_REF.finditer(html[:MAX_HTML_BYTES]):
        ref = m.group(1).strip()
        if ref.startswith("data:"):
            continue
        absolute = urllib.parse.urljoin(base, ref)
        p = urllib.parse.urlparse(absolute)
        if p.scheme not in ("http", "https") or not p.netloc:
            continue
        s = score_candidate(absolute)
        if s is None:
            continue
        seen[absolute] = max(seen.get(absolute, 0), s)
    return sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))


def looks_like_logo(svg: str, url: str) -> tuple[bool, str]:
    """清洗后的 SVG 是否足以认定为官方 Logo。任何疑点都拒绝。"""
    if len(svg) < 200:
        return False, "文件过小，疑似占位或空壳"
    if re.search(r"<image\b", svg, re.I):
        return False, "内嵌栅格 <image>，不是纯矢量 Logo"
    if re.search(r"<(?:script|foreignObject)\b", svg, re.I):
        return False, "含脚本或 foreignObject"
    if re.search(r'(?:xlink:)?href\s*=\s*["\']https?://', svg, re.I):
        return False, "含外部 href 引用"
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        return False, f"非法 XML：{e}"
    if not root.tag.split("}")[-1].lower() == "svg":
        return False, "根节点不是 <svg>"
    if len(re.findall(r"\bviewBox\s*=", svg, re.I)) != 1:
        return False, "viewBox 缺失或重复（会导致浏览器破图）"

    vb = None
    for k, v in root.attrib.items():
        if k.split("}")[-1].lower() == "viewbox":
            vb = v
            break
    parts = (vb or "").replace(",", " ").split()
    if len(parts) == 4:
        try:
            w, h = float(parts[2]), float(parts[3])
        except ValueError:
            return False, "viewBox 尺寸无法解析"
    else:
        def num(attr):
            v = root.attrib.get(attr, "")
            m = re.match(r"([\d.]+)", v)
            return float(m.group(1)) if m else 0.0
        w, h = num("width"), num("height")
    if w <= 0 or h <= 0:
        return False, "宽高无效"
    ratio = max(w, h) / min(w, h)
    # 横向字标很扁（如 KEYENCE 官方 Logo 为 90.8×16），不能按最小边 20 一刀切；
    # 但接近方形的小图基本是 favicon / UI 图标，单独排除。
    if min(w, h) < 12 or max(w, h) > 6000 or ratio > 16:
        return False, f"尺寸 {w:g}×{h:g} 不像 Logo（疑似图标/横幅）"
    if min(w, h) < 20 and ratio < 1.6:
        return False, f"尺寸 {w:g}×{h:g} 接近小方形，疑似 favicon / UI 图标"

    tags = [e.tag.split("}")[-1].lower() for e in root.iter()]
    if sum(1 for t in tags if t in VECTOR_TAGS) < 2:
        return False, "矢量图形元素过少"
    fake = is_fake_logo(svg)
    if fake:
        return False, f"疑似伪 Logo：{fake}"
    return True, f"ok {w:g}×{h:g}"


def site_and_direct(company: dict, sites: dict) -> tuple[str | None, str | None]:
    """返回 (官网首页 URL, 官方 Logo 直链)，数据集字段优先于 --sites。"""
    cid = str(company.get("id") or "")
    cfg = sites.get(cid)
    site, direct = None, None
    if isinstance(cfg, str):
        site = cfg
    elif isinstance(cfg, dict):
        site = cfg.get("site")
        direct = cfg.get("logoUrl")
    if isinstance(company.get("officialSite"), str) and company["officialSite"].strip():
        site = company["officialSite"].strip()
    if isinstance(company.get("officialLogoUrl"), str) and company["officialLogoUrl"].strip():
        direct = company["officialLogoUrl"].strip()
    return site, direct


def candidates(site: str | None, direct: str | None, html: str | None,
               timeout: float, limit: int) -> tuple[list[tuple[str, int]], list[str]]:
    """返回 (候选 URL+分数, 诊断信息)。"""
    notes: list[str] = []
    if direct:
        return [(direct, 999)], ["使用 company.officialLogoUrl 直链"]
    if not site:
        return [], ["未提供官网（company.officialSite 或 --sites）"]
    if html is None:
        return [], [f"官网不可达：{site}"]
    found = extract_svg_urls(html, site)
    if found:
        return found[:limit], [f"首页发现 {len(found)} 个疑似 Logo SVG"]
    # 首页没有 logo 命名的 SVG：限量探测常见路径（不猜图标）
    origin = f"{urllib.parse.urlparse(site).scheme}://{urllib.parse.urlparse(site).netloc}"
    probes = [(urllib.parse.urljoin(origin, p), 1) for p in COMMON_PATHS]
    notes.append("首页无 Logo 命名 SVG，限量探测常见路径")
    return probes[:limit], notes


def resolve(company: dict, sites: dict, timeout: float, limit: int,
            dry_run: bool) -> dict:
    cid = str(company.get("id") or company.get("name") or "?")
    site, direct = site_and_direct(company, sites)
    html = None
    if site and not direct:
        html = get(site, timeout, "text/html,application/xhtml+xml")
    urls, notes = candidates(site, direct, html, timeout, limit)

    tried: list[dict] = []
    for url, score in urls:
        text = get(url, timeout, "image/svg+xml,*/*")
        if text is None:
            tried.append({"url": url, "result": "下载失败 / 非 SVG"}); continue
        if "<svg" not in text[:800].lower():
            tried.append({"url": url, "result": "内容不是 SVG"}); continue
        cleaned = harden_svg(text)
        if not cleaned:
            tried.append({"url": url, "result": "清洗后无有效 SVG"}); continue
        ok, reason = looks_like_logo(cleaned, url)
        tried.append({"url": url, "result": reason})
        if ok:
            return {"id": cid, "status": "found", "svg": None if dry_run else cleaned,
                    "site": site or "", "url": url, "score": score,
                    "reason": reason, "notes": notes, "tried": tried}
    return {"id": cid, "status": "unverified", "site": site or "",
            "notes": notes, "tried": tried}


def main() -> int:
    ap = argparse.ArgumentParser(description="从企业官网抓取官方 SVG Logo（第二层来源）")
    ap.add_argument("--data", required=True, help="dataset.json 路径")
    ap.add_argument("--out-dir", required=True, help="Logo 输出目录（按 <id>.svg 命名）")
    ap.add_argument("--sites", help='官网映射 JSON：{"id": "https://..."} 或 {"id": {"site":..., "logoUrl":...}}')
    ap.add_argument("--manifest", help="输出来源与未验证清单 JSON")
    ap.add_argument("--only-missing", action="store_true", help="仅处理 out-dir 中尚无 <id>.svg 的企业（推荐接在第一层之后）")
    ap.add_argument("--force", action="store_true", help="覆盖已有本地 Logo 文件")
    ap.add_argument("--dry-run", action="store_true", help="只探测与校验，不写 <id>.svg")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=float, default=12.0)
    ap.add_argument("--max-candidates", type=int, default=8, help="每个官网最多尝试的候选数")
    args = ap.parse_args()

    data_path = Path(args.data).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: 无法读取数据集 {data_path}：{e}")
        return 1

    sites: dict = {}
    if args.sites:
        try:
            sites = json.loads(Path(args.sites).expanduser().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"ERROR: 无法读取 --sites：{e}")
            return 1
    if not isinstance(sites, dict):
        print("ERROR: --sites 必须是 JSON 对象")
        return 1

    companies = [c for c in data.get("companies") or [] if isinstance(c, dict)]
    if args.only_missing or not args.force:
        companies = [c for c in companies
                     if args.force or not (out_dir / f"{c.get('id')}.svg").is_file()]
    if not companies:
        print("没有需要处理的品牌（可加 --force 重抓）")
        return 0

    results: list[dict] = []
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=args.workers)
    try:
        futures = {ex.submit(resolve, c, sites, args.timeout,
                             args.max_candidates, args.dry_run): c for c in companies}
        for fut in concurrent.futures.as_completed(futures):
            r = fut.result()
            results.append(r)
            label = "OK  " if r["status"] == "found" else "MISS"
            print(f"  {label} {r['id']:24s} {r['url'] if r['status'] == 'found' else '；'.join(r['notes'])}")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    found = [r for r in results if r["status"] == "found"]
    if not args.dry_run:
        for r in found:
            (out_dir / f"{r['id']}.svg").write_text(r["svg"] + "\n", encoding="utf-8")
    print(f"官网 SVG 补齐：{len(found)}/{len(results)} · 目录 {out_dir}")
    print("未验证品牌请人工复核官网品牌页；绝不生成首字母/文字占位 Logo。")

    if args.manifest:
        m = Path(args.manifest).expanduser().resolve()
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(json.dumps({
            "source": "official website SVG (tier 2, after worldvectorlogo)",
            "policy": "只采用官网自身引用且通过矢量/尺寸/伪 Logo 校验的 SVG；未验证品牌保持中性占位",
            "search_step": "官网由 Agent 用 WorkBuddy 搜索能力查得并写入 company.officialSite / --sites；脚本不抓搜索引擎",
            "total_processed": len(results),
            "found": len(found),
            "found_details": {r["id"]: {"site": r["site"], "url": r["url"],
                                        "score": r["score"], "check": r["reason"]}
                              for r in found},
            "unverified": [{k: r[k] for k in ("id", "site", "notes", "tried")}
                           for r in results if r["status"] == "unverified"],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"清单：{m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

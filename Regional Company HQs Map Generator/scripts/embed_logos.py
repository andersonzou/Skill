#!/usr/bin/env python3
"""把官方 Logo 内嵌为 data URI，保证单文件 HTML 可离线显示、导出 PNG 不空白。

本 skill 禁止用首字母色块或纯文字字标冒充 Logo：读入的 SVG 会经过
validate_dataset.is_fake_logo() 检查，伪 Logo 一律拒绝，由模板显示
无字母、无文字的中性占位，并写入缺图清单。

解析顺序（命中即停）：
  1. company.logoDataUri 已是合法官方图 → 原样保留
  2. company.logoFile 指定的本地文件（相对 dataset.json 目录或绝对路径）
  3. logos-dir/<id>.<ext>，以及 <name 的 slug>.<ext>
  4. company.logoUrl（仅 --download 时联网抓取）
  5. 均未命中 → 不写入 logoDataUri，模板显示中性占位（绝不生成字母牌）

用法:
    python3 embed_logos.py --data dataset.json --logos-dir ./logos --inplace
    python3 embed_logos.py --data dataset.json --download --out dataset.embedded.json \
                           --manifest missing-logos.json
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import sys
import urllib.request
from pathlib import Path

EXTS = (".svg", ".png", ".webp", ".jpg", ".jpeg", ".gif")
MIME_BY_EXT = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}
MAX_BYTES = 800_000
UA = "WorkBuddy-RegionalHQMap/1.3 (+logo embedding)"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def sanitize_svg(text: str) -> str:
    """移除脚本与事件属性，并补齐 xmlns，避免内嵌 SVG 变成可执行内容。"""
    text = re.sub(r"<\?xml[^>]*\?>", "", text, flags=re.I)
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<script\b.*?</script\s*>", "", text, flags=re.I | re.S)
    text = re.sub(r"<foreignObject\b.*?</foreignObject\s*>", "", text, flags=re.I | re.S)
    text = re.sub(r"\son[a-zA-Z]+\s*=\s*(['\"]).*?\1", "", text, flags=re.I | re.S)
    text = re.sub(r"javascript\s*:", "", text, flags=re.I)
    if "<svg" in text.lower() and "xmlns=" not in text.lower():
        text = re.sub(r"<svg", '<svg xmlns="http://www.w3.org/2000/svg"', text, count=1, flags=re.I)
    return text


def mime_of(path: Path) -> str:
    return MIME_BY_EXT.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def to_data_uri(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def find_logo_file(c: dict, dataset_dir: Path, logos_dir: Path | None) -> Path | None:
    logo_file = c.get("logoFile")
    candidates: list[Path] = []
    if isinstance(logo_file, str) and logo_file.strip():
        p = Path(logo_file).expanduser()
        if not p.is_absolute():
            p = dataset_dir / p
        candidates.append(p)
        if logos_dir:
            candidates.append(logos_dir / Path(logo_file).name)
    if logos_dir:
        keys = {str(c.get("id") or ""), slug(c.get("id") or ""), slug(c.get("name") or "")}
        for key in {k for k in keys if k}:
            for ext in EXTS:
                candidates.append(logos_dir / f"{key}{ext}")
    for p in candidates:
        if p.is_file() and p.suffix.lower() in EXTS:
            return p
    return None


def _reject_fake_svg(text: str) -> str:
    """伪 Logo 返回拒绝原因，合法返回空串。"""
    try:
        from validate_dataset import is_fake_logo
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from validate_dataset import is_fake_logo
    return is_fake_logo(text) or ""


def read_logo(path: Path) -> tuple[str, str] | tuple[None, str]:
    try:
        raw = path.read_bytes()
    except OSError as e:
        return None, f"读取失败 {e}"
    mime = mime_of(path)
    if mime == "image/svg+xml":
        source = raw.decode("utf-8", errors="replace")
        reason = _reject_fake_svg(source)
        if reason:
            return None, f"拒绝伪 Logo：{reason}"
        cleaned = sanitize_svg(source).encode("utf-8")
        return to_data_uri(cleaned, mime), ""
    return to_data_uri(raw, mime), ""


def download_logo(url: str, timeout: float) -> tuple[str, str] | tuple[None, str]:
    if not url.startswith(("http://", "https://")):
        return None, "非 http(s) 链接"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            mime = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            raw = resp.read(MAX_BYTES + 1)
        if not raw:
            return None, "空响应"
        if len(raw) > MAX_BYTES:
            return None, f"超过 {MAX_BYTES} 字节上限"
        if mime == "image/svg+xml" or url.lower().split("?")[0].endswith(".svg"):
            mime = "image/svg+xml"
            source = raw.decode("utf-8", errors="replace")
            reason = _reject_fake_svg(source)
            if reason:
                return None, f"拒绝伪 Logo：{reason}"
            raw = sanitize_svg(source).encode("utf-8")
        elif mime not in MIME_BY_EXT.values():
            return None, f"非图片响应 {mime or 'unknown'}"
        return to_data_uri(raw, mime), ""
    except Exception as e:  # 网络在部分环境不可用，属预期降级路径
        return None, f"{type(e).__name__}: {str(e)[:80]}"


def resolve_logos(
    data: dict,
    dataset_dir: Path,
    logos_dir: Path | None = None,
    download: bool = False,
    timeout: float = 8.0,
) -> dict:
    """就地补充 company.logoDataUri，返回统计字典。"""
    stats = {"embedded": [], "fallback": [], "failed": [], "too_large": []}
    for c in data.get("companies") or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or c.get("name") or "?")
        existing = c.get("logoDataUri")
        if isinstance(existing, str) and existing.startswith("data:image/"):
            try:
                from validate_dataset import decode_svg_data_uri
            except ImportError:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                from validate_dataset import decode_svg_data_uri
            reason = _reject_fake_svg(decode_svg_data_uri(existing) or "")
            if reason:
                # 剔除历史数据集里的首字母牌，继续尝试从 logos/ 找官方原图
                c.pop("logoDataUri", None)
                stats["failed"].append({"id": cid, "source": "logoDataUri", "reason": f"拒绝伪 Logo：{reason}"})
            else:
                stats["embedded"].append(cid)
                continue

        uri: str | None = None
        path = find_logo_file(c, dataset_dir, logos_dir)
        if path:
            uri, err = read_logo(path)
            if not uri:
                stats["failed"].append({"id": cid, "source": str(path), "reason": err})
            elif len(uri) > MAX_BYTES:
                stats["too_large"].append(cid)
                uri = None
        if not uri and download and isinstance(c.get("logoUrl"), str):
            uri, err = download_logo(c["logoUrl"], timeout)
            if not uri:
                stats["failed"].append({"id": cid, "source": c["logoUrl"], "reason": err})
        if uri:
            c["logoDataUri"] = uri
            stats["embedded"].append(cid)
        else:
            stats["fallback"].append(cid)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="把官方 Logo 内嵌为 data URI")
    ap.add_argument("--data", required=True, help="dataset.json 路径")
    ap.add_argument("--logos-dir", help="按 <id>.png/svg 命名的 Logo 目录")
    ap.add_argument("--download", action="store_true", help="尝试下载 company.logoUrl（网络不可用时自动回退）")
    ap.add_argument("--timeout", type=float, default=8.0, help="下载超时秒数")
    ap.add_argument("--inplace", action="store_true", help="写回原 dataset.json")
    ap.add_argument("--out", help="另存为新的 dataset json")
    ap.add_argument("--manifest", help="把缺少官方 Logo 的企业 id 写成 JSON 清单")
    args = ap.parse_args()

    if not args.inplace and not args.out:
        ap.error("需指定 --inplace 或 --out")

    src = Path(args.data).expanduser().resolve()
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: 无法读取数据集：{e}")
        return 1

    logos_dir = Path(args.logos_dir).expanduser().resolve() if args.logos_dir else None
    if logos_dir and not logos_dir.is_dir():
        print(f"WARNING Logo 目录不存在：{logos_dir}（将跳过目录扫描）")
        logos_dir = None

    stats = resolve_logos(data, src.parent, logos_dir, args.download, args.timeout)
    total = len(data.get("companies") or [])
    print(f"Logo 内嵌：官方图 {len(stats['embedded'])}/{total} · "
          f"中性占位 {len(stats['fallback'])} · 伪 Logo/失败 {len(stats['failed'])} · 超限 {len(stats['too_large'])}")
    for f in stats["failed"][:8]:
        print(f"  FAILED {f['id']}: {f['reason']}")
    if stats["fallback"]:
        print("  待补官方 Logo id：" + ", ".join(stats["fallback"][:20]) + (" …" if len(stats["fallback"]) > 20 else ""))

    dest = src if args.inplace else Path(args.out).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入：{dest}")

    if args.manifest:
        m = Path(args.manifest).expanduser().resolve()
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(json.dumps({
            "missing_logos": stats["fallback"],
            "naming": "把官方 Logo 保存为 logos/<id>.png 或 <id>.svg，再执行 build_map.py --logos-dir logos",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"缺图清单：{m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

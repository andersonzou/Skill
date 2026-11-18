#!/usr/bin/env python3
"""严格 CSP 回归校验：在与 WorkBuddy 静态预览相同的响应头下加载成品 HTML。

背景：预览容器下发的 CSP 中 connect-src 不含 data: 与公网 CDN。
历史上底图曾以 data URI + fetch() 在运行时读取，被 CSP 拦截后抛
「Failed to fetch」并降级为仅坐标定位。file:// 打开时没有 CSP，因此
本地直接双击 HTML 的自测无法发现该问题。本脚本用本地 HTTP 服务复现该环境。

用法:
    python3 verify_map.py --html ./map.html
    python3 verify_map.py --html ./map.html --chrome "/path/to/Chrome" --json

退出码: 0 = 全部通过；1 = 存在失败项；2 = 环境/参数错误。
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 与 WorkBuddy 静态 HTML 预览一致（含不含 data: 的 connect-src），用于复现真实故障。
PREVIEW_CSP = (
    "default-src 'self' 'unsafe-inline' 'unsafe-eval' blob: data:; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob: data: https: "
    "https://map.qq.com https://*.map.qq.com; "
    "connect-src 'self' http://127.0.0.1:* https://*.map.qq.com https://mapapi.qq.com "
    "https://*.gtimg.com https://*.qpic.cn https://*.myapp.com "
    "https://*.app.workbuddy.link https://*.app-tencent.workbuddy.link "
    "https://*.app.workbuddy.host https://*.app-tencent.workbuddy.host "
    "https://*.beacon.qq.com https://svibeacon.onezapp.com; "
    "img-src 'self' data: blob: https: https://*.map.qq.com https://mapapi.qq.com "
    "https://*.gtimg.com https://*.qpic.cn https://*.myapp.com; "
    "font-src 'self' data: blob: https: https://*.map.qq.com "
    "https://*.gtimg.com https://*.qpic.cn; "
    "media-src 'self' data: blob: https: http://127.0.0.1:*; "
    "worker-src 'self' blob: https: https://*.map.qq.com https://*.gtimg.com"
)

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
)


def find_chrome(explicit: str | None) -> str | None:
    if explicit:
        p = Path(explicit).expanduser()
        return str(p) if p.exists() else explicit
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def make_handler(payload: bytes, seen: list[str]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append(self.path)
            if self.path.split("?", 1)[0] not in ("/", "/map.html"):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", PREVIEW_CSP)
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    return Handler


def strip_tags(text: str) -> str:
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", text)).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="在严格 CSP 下复验单文件地图 HTML")
    ap.add_argument("--html", required=True, help="待验证的 HTML 绝对路径")
    ap.add_argument("--chrome", help="Chrome/Chromium 可执行文件路径；缺省自动探测")
    ap.add_argument("--timeout", type=int, default=120, help="浏览器超时秒数，默认 120")
    ap.add_argument("--budget", type=int, default=15000, help="virtual-time-budget 毫秒，默认 15000")
    ap.add_argument("--json", action="store_true", help="输出 JSON 结果")
    args = ap.parse_args()

    path = Path(args.html).expanduser().resolve()
    if not path.is_file():
        print(f"ERROR: 找不到 HTML：{path}")
        return 2
    chrome = find_chrome(args.chrome)
    if not chrome:
        print("ERROR: 未找到 Chrome/Chromium，请用 --chrome 指定路径")
        return 2

    payload = path.read_bytes()
    seen: list[str] = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(payload, seen))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/map.html"
    try:
        cmd = [chrome, "--headless", "--disable-gpu", "--no-sandbox",
               "--disable-dev-shm-usage", f"--virtual-time-budget={args.budget}",
               "--dump-dom", url]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
        dom = proc.stdout
    except subprocess.TimeoutExpired:
        print("ERROR: 无头浏览器超时")
        return 1
    finally:
        server.shutdown()
        server.server_close()

    failures: list[str] = []
    warnings: list[str] = []
    banner_shown = False
    banner_text = ""
    report: dict = {}

    m = re.search(r'id="error-banner"([^>]*)>(.*?)</div>', dom, re.S)
    if m:
        banner_shown = "display: block" in m.group(1)
        banner_text = strip_tags(m.group(2))
    if banner_shown:
        failures.append(f"页面出现错误横幅：{banner_text[:200]}")

    m = re.search(r'id="self-check-report"[^>]*>(.*?)</div>', dom, re.S)
    if not m or not m.group(1).strip():
        failures.append("未生成 #self-check-report（脚本可能未执行）")
    else:
        try:
            report = json.loads(html_mod.unescape(m.group(1)))
        except json.JSONDecodeError as e:
            failures.append(f"#self-check-report 不是合法 JSON：{e}")
    if report:
        topo = report.get("topology") or {}
        if not topo.get("embedded"):
            failures.append("底图 TopoJSON 未内嵌")
        if topo.get("degraded"):
            failures.append("页面降级为「仅坐标定位」模式")
        if not topo.get("land_paths"):
            failures.append("主地图未绘制任何陆地轮廓（land_paths = 0）")
        if not report.get("ok") or report.get("conflicts"):
            failures.append(f"零遮挡自检未通过：{report.get('conflicts')}")
        footer = report.get("footer")
        if footer is not None and not footer.get("clear"):
            failures.append(f"底部说明栏与集群/区块压叠：{footer.get('rect')}")
        if report.get("viewports_skipped"):
            warnings.append(f"视口框为避免重叠被省略：{report['viewports_skipped']}")

    unexpected = [u for u in seen if u.split("?", 1)[0] not in ("/", "/map.html", "/favicon.ico")]
    if unexpected:
        failures.append(f"页面发起了额外网络请求：{unexpected[:5]}")

    result = {
        "ok": not failures,
        "html": str(path),
        "url": url,
        "csp_strict": True,
        "dom_chars": len(dom),
        "banner_shown": banner_shown,
        "banner_text": banner_text,
        "report": report,
        "unexpected_requests": unexpected,
        "failures": failures,
        "warnings": warnings,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{'PASS' if result['ok'] else 'FAIL'}  {path.name}  (严格 CSP / connect-src 不含 data:)")
        if report:
            t = report.get("topology", {})
            print(f"  底图：内嵌={t.get('embedded')} 要素={t.get('features')} "
                  f"陆地路径={t.get('land_paths')} 降级={t.get('degraded')}")
            print(f"  自检：ok={report.get('ok')} conflicts={len(report.get('conflicts') or [])} "
                  f"区块={len(report.get('panels') or [])} 集群={report.get('clusters')} "
                  f"视口={report.get('viewports')} Logo={report.get('logos')}")
        for w in warnings:
            print("  WARNING " + w)
        for f in failures:
            print("  FAIL " + f)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

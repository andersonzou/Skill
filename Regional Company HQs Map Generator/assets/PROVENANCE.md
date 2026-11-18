# 离线资产来源与许可

这些文件由 `scripts/build_map.py` 在**构建期**内联进最终 HTML，页面运行时不发起任何网络请求。
之所以必须内嵌：WorkBuddy 静态 HTML 预览会对页面下发严格 CSP（`connect-src` 不含 `data:` 与公网 CDN），
浏览器里 `fetch('data:...')` 或 `fetch('https://cdn...')` 会被拦截并抛 `Failed to fetch`，导致底图降级。

| 文件 | 版本 | 上游 | 许可 |
| --- | --- | --- | --- |
| `vendor/d3.min.js` | 7.9.0 | <https://d3js.org> / npm `d3@7` | ISC / BSD-3-Clause（见文件头版权声明） |
| `vendor/topojson-client.min.js` | 3.1.0 | <https://github.com/topojson/topojson-client> | ISC（见文件头版权声明） |
| `vendor/html2canvas.min.js` | 1.4.1 | <https://html2canvas.hertzen.com> | MIT（见文件头版权声明） |
| `topo/countries-50m.json` | world-atlas 2.0.2 | Natural Earth 1:50m Admin 0 Countries，经 `world-atlas@2` 转 TopoJSON | Natural Earth 公有领域（Public Domain） |

保留每个 JS 文件首行的原始版权/许可注释，不得删除。
资产取自公开分发版，未做功能性改动；如需升级版本，替换文件后必须重跑 `scripts/verify_map.py` 严格 CSP 回归。

## 官方品牌 Logo（构建期抓取，不随 skill 分发）

`scripts/fetch_logos.py` 在**构建期**从 `https://cdn.worldvectorlogo.com/logos/<slug>.svg` 抓取企业官方 SVG，
清洗后以 `data:image/...;base64` 内嵌进成品 HTML；`logos/` 目录不随本 skill 分发，属于每次任务的数据资产。
商标图形仅用于信息图识别，须遵守来源站点使用条款；缺失品牌不伪造 Logo，显示中性占位并列入缺图清单。
抓取前先确认该品牌的官方素材在来源站是否存在，`--hints` 可给出精确 slug 以避免误取同名品牌的其它版本。

## 合规边界

`topo/countries-50m.json` 是境外 Natural Earth 数据，**仅用于中国以外地区的轮廓**。
涉及中国全图、中国省级区域或含中国台湾/中国香港/中国澳门/南海诸岛的表达时，
必须用 `--topo-file` 传入符合国家标准与审图要求的边界数据（自然资源部标准地图、天地图等合规来源），
并在 `map.sourceLabel` 写明来源；`build_map.py` 会对中国区域 + 默认境外底图直接报构建错误。

## 校验

```bash
python3 <skill>/scripts/build_map.py --data dataset.json --out map.html --logos-dir logos
python3 <skill>/scripts/verify_map.py --html map.html
```

# 执行流程与验收细则

`SKILL.md` 只保留路由与硬约束；本文件是 Step 0–6 的完整操作说明。数据口径见 `data-sources.md`，视觉与零遮挡判据见 `visual-spec.md`。

## Step 0 — 确定参数与输出位置

确认 `target_region`（必填）、`company_count`（默认 40–60，限 `[20,100]`）、`ranking_criteria`（默认市值 / 营收 / 品牌价值综合）、`logos_dir`、`output_dir`。缺失项按默认值执行，并在交付说明中标注所用默认值。

## Step 1 — 检索核验、抓官方 Logo 与建模

1. 读取 `data-sources.md`，按「官方指数成分股 → 政府/协会榜单 → Forbes / Fortune / Brand Finance → 当地财经媒体」优先级联网检索最新权威榜单。
2. 覆盖至少 5 类行业，单一行业占比建议不超过 40%。记录来源名称、年份与 URL。
3. 逐家核验法定注册地或核心运营总部（官网「公司概要 / Legal / Impressum / 有価証券報告書」优先），**禁止把跨国企业统一归入首都**；`city` 字符串同城必须完全一致。
4. 填写 `metro`（都会区/城市群）与 `outlying`（离岛/飞地分组）；语义见 `data-sources.md` 第 8 节。
5. 按 `assets/companies.schema.json` 写出 `dataset.json`。可用 `python3 scripts/build_map.py --init <path> --region <地区>` 生成骨架。
6. **抓取真实官方 Logo（三层降级，禁止自己画首字母牌或文字字标）**：

### 第一层 · worldvectorlogo 精确 slug 优先

```bash
python3 <skill>/scripts/fetch_logos.py \
  --data <dataset.json> --out-dir <logos_dir> \
  --hints <slug映射.json> --manifest <output_dir>/missing-logos.json
```

- 素材源是 worldvectorlogo。**主站 `worldvectorlogo.com` 实测 403**（首页与 `/logo/<slug>` 均不可直连），可用网页抓取工具查看主站页面确认 slug，但脚本必须走其官方 CDN `https://cdn.worldvectorlogo.com/logos/<slug>.svg`（实测 200）。
- 「精确 slug 优先」：`company.logoSlugs` / `logoSlug` / `--hints` 中的候选先串行快试、不加版本后缀；未命中才按 id / wordmark / name 派生并追加 `-1…-3` 后缀并发探测，命中即停。
- 清洗：剥脚本与事件属性、去外链 `<image>` / `<style>`、补 `xmlns`，**保证只有一个 `viewBox`**（重复 `viewBox` 会让浏览器判定 SVG 无效并整片破图）。
- `--hints` 格式为 `{"company-id": ["slug-a", "slug-b"]}`；已有本地文件默认跳过，`--force` 重抓、`--offline` 只统计。产物 `<logos_dir>/<id>.svg`，站里没有的品牌写入 `missing-logos.json`。

### 第二层 · 企业官网官方 SVG（缺图品牌兜底）

**「搜索官网」由 Agent 完成，不由脚本完成**：实测当前网络下 Google / DuckDuckGo 直连返回 000、Bing 返回 302，抓搜索引擎 HTML 既不可靠也违反其条款；WorkBuddy 的搜索能力可用。对 `missing-logos.json` 里每个 id 查官网（地方银行域名常与品牌名不同，例如琉球银行是 `ryugin.co.jp`），结果写入 `company.officialSite`；若已找到 Logo 直链写 `company.officialLogoUrl`；也可集中写进 `--sites`：

```json
{
  "keyence": "https://www.keyence.com/",
  "takeda": { "site": "https://www.takeda.com/", "logoUrl": "https://.../logo.svg" }
}
```

```bash
python3 <skill>/scripts/fetch_official_logos.py \
  --data <dataset.json> --out-dir <logos_dir> \
  --sites <sites.json> --only-missing \
  --manifest <output_dir>/official-logos.json
```

- 脚本只做确定性工作：抓官网首页 → 从 `src` / `data-src` / `href` / `srcset` / CSS `url()` 提取 `.svg` 引用 → 按文件名打分（含 logo/brand/wordmark 加分；含 icon/btn/banner/social 等硬排除）→ 首页无 Logo 命名 SVG 时限量探测常见路径。
- **校验闸门**（任一不过即丢弃）：合法 XML、根为 `<svg>`、恰好一个 `viewBox`、宽高比 ≤ 16 且不是小方形图标、至少 2 个矢量元素、无 `<image>` / `<script>` / `foreignObject` / 外部 `href`、`is_fake_logo()` 判定非伪 Logo。
- 横向字标往往很扁（KEYENCE 官方 Logo 为 90.8×16），**不要按「最小边 ≥ 20」一刀切**；要排除的是接近方形的小图标 / favicon。
- 只采用官网页面自身引用的 SVG：文件名是 hash 的云端插图、UI 图标、内联装饰 SVG 一律不认。未验证品牌写入 manifest 的 `unverified`（附每个候选的失败原因），**不写 `<id>.svg`**。
- `--dry-run` 只探测不落盘；`--force` 覆盖；`--max-candidates` 限流。官网在当前代理不可达（如 `ryugin.co.jp` 返回 000/502）属预期降级。

### 第三层 · 中性占位

两层都取不到的品牌显示无字母、无文字的斜纹中性占位，**绝不生成替代 Logo**。也可人工把官方 SVG 放进 `<logos_dir>/<id>.svg`，或用 `company.logoFile` / `logoUrl`（配 `--download-logos`）补齐。网络受限时保留缺图清单继续构建，并在交付说明列出待补品牌。

## Step 2 — 数据集校验

```bash
python3 <skill>/scripts/validate_dataset.py <dataset.json>
```

修正全部 `error` 级问题后再继续。重点检查：

- 收录数量 `[20,100]`、字段完整、`coords` 为 `[经度, 纬度]` 且在合法范围、ID 唯一；
- 最高 `metro` 分组占比是否超过 `panels.metro.threshold`（默认 0.35）；
- 存在 `outlying` 企业时 `panels.outlying.enabled` 是否被显式禁用（会被拦截）；
- `panels.metro.target/keys`、`panels.metro.layoutMode`、`panels.outlying.groups[].cities` 是否合法或与分组键匹配；
- `layout.ring.pad/gap` 为非负数；
- **伪 Logo 拦截**：`logoDataUri` 中含 `<text>` 单字母色块、纯文字字标、`viewBox="0 0 64 20"` 拼装牌、重复 `viewBox` 都会被判为 error；外链 http(s) 图片同样被拦截。官方 Logo 覆盖率低于 80% 会告警。

`embed_logos.py` 在读入时执行同一套检测：历史数据集里的首字母牌会被剔除，并尝试从 `logos_dir` 补官方原图。

## Step 3 — 视觉与合规配置

读取 `visual-spec.md`，确认配色、细体城市名、**四周环绕布局**、**都会区 4 列 / 2 列自动择优**、双区块预留规则、区块内外零遮挡判据与调参顺序。涉及中国全图或中国省级区域时，先按该文档「合规红线」准备符合国家标准与审图要求的 TopoJSON，构建时传 `--topo-file`；`build_map.py` 会拦截「中国区域 + 默认 Natural Earth 境外底图」并报错。其他地区使用内置 `assets/topo/countries-50m.json` 即可。

## Step 4 — 构建单文件 HTML

```bash
python3 <skill>/scripts/build_map.py \
  --data <dataset.json> \
  --out <output_dir>/<region>-company-hqs.html \
  --logos-dir <logos_dir> \
  --logo-manifest <output_dir>/missing-logos.json
# 中国区域追加：--topo-file <合规 TopoJSON 路径>
```

执行顺序：

1. 校验底图合规（中国区域禁止内置境外边界），读取 `assets/topo/` 或 `--topo-file` 的 TopoJSON，读取 `assets/vendor/` 三个依赖库；
2. `resolve_logos()` 内嵌官方 Logo → `data:image/...`（SVG 安全清洗 + 伪 Logo 拒绝），剔除历史字母牌；
3. 复跑 `validate_dataset.py`；
4. 注入 5 个占位符：`__REGION_NAME__` / `__REGION_JS__` / `__MAP_DATA__` / `__TOPO_DATA__` / `__VENDOR_LIBS__`（`<` `&` 转 `\u003c` 等，防止 `</script>` 截断）；
5. **离线硬校验**：成品不得含 `<script src>`、外链图片、应用脚本中的 `fetch(`，且必须含内嵌 Topology；任一不满足直接终止构建；
6. 写出单文件 HTML 并打印 Logo 覆盖、都会区占比、离岛家数与底图要素数。

**运行时零网络请求是硬要求**：WorkBuddy 预览对页面下发严格 CSP，`connect-src` 既不含 `data:` 也不含公网 CDN，页面里 `fetch('data:application/json;base64,...')` 或 `fetch('https://cdn...')` 会被拦截并抛 `Failed to fetch`，导致整张底图降级。因此底图必须是 JS 对象 `EMBEDDED_TOPO`，依赖库必须是内联 `<script>`，不得退回 CDN 或 data URI + fetch。占位符也不能写在 HTML 注释内，否则脚本不执行。

可选参数：`--topo-file`、`--download-logos`（尝试下载 `logoUrl`）、`--no-embed` / `--no-validate`（仅调试模板）、`--template`（替换模板）。也可单独运行 `scripts/embed_logos.py --inplace` 预处理数据集。

仅当模板能力不足时才直接编辑生成的 HTML，并把可复用改动回填 `assets/map-template.html`。

## Step 5 — 运行验证

**先跑严格 CSP 回归**，再人工查看。直接用 `file://` 双击打开没有 CSP，无法复现预览容器里的 `Failed to fetch`，必须用本地 HTTP + 预览同款响应头：

```bash
python3 <skill>/scripts/verify_map.py --html <out.html>
# 可选：--chrome <路径> / --json / --budget 15000
```

脚本启动临时本地服务，下发与 WorkBuddy 静态预览一致的 CSP（`connect-src` 不含 `data:` 与 CDN），用无头 Chrome 加载并断言：无错误横幅、`topology.embedded=true`、`degraded=false`、`land_paths>0`、`self-check-report.ok=true` 且 `conflicts: []`、`footer.clear=true`、无额外网络请求。任一失败返回非零退出码。

然后用 `present_files` 打开生成的 HTML：

- 底图渲染成功，无「地图数据加载失败」/「依赖未内嵌」横幅；
- **每家企业只显示官方 Logo 图**（`<img class="logo-img">`），磁贴内没有企业文字名称标签，页面上没有任何单首字母色块；缺图企业显示斜纹中性占位；
- **Logo 无破图**：若出现批量破图，先用 `XML` 解析 `<logos_dir>/*.svg` 检查重复 `viewBox` 与非法属性；
- **四周均匀**：上 / 右 / 下 / 左四条边都有集群，报告 `ring_layout.edges` 各边数量差不超过 1，`ring_layout.balance` 接近 0；
- 左下区块列出全部离岛 / 飞地企业 + 放大地理小地图 + 虚线视口框；右下区块列出占比超过 35% 的都会区企业 + 放大地理小地图 + 虚线视口框，并按 `metro_layout.chosen` 显示 4 列横向或 2 列纵向；
- **底部说明栏独占净空**：两行来源 / 统计文字完整可读，与下边集群卡片之间留白，不压叠任何小 Logo 或边框；`footer.clear === true` 且 `ring_layout.bands.bottom.y1 ≤ H - FOOTER_RESERVE`；
- 右上角零遮挡徽标为绿色；`#self-check-report` 中 `ok === true`、`conflicts: []`、`logos.letter_marks === 0`、`logos.official + neutral_placeholder === total`。报告还含 `panels`（listed/tiles/rect）、`clusters`、`viewports`、`viewports_skipped`、`ring_layout`、`metro_layout`、`footer`、`inner_tile_pairs_checked`、`boxes_checked`；
- 有冲突时按 `visual-spec.md` 第 6 节顺序调参后重建，禁止放宽容差或删除报告；
- 逐一试用行业筛选、详情弹窗、名录抽屉；点击导出 PNG 确认无空白、无破图、无跨域报错。

需要人工取 DOM 细节时（如导出截图、核对集群坐标），可另跑：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
  --no-sandbox --virtual-time-budget=14000 --dump-dom "file:///<out.html>"
```

从 DOM 中解析 `id="self-check-report"` 的文本即可得 JSON 报告。**注意：该命令不带 CSP，不能替代 `verify_map.py`。**

## Step 6 — 交付

用 `present_files` 展示最终 HTML（必要时附导出 PNG），说明：

- 收录企业数、行业分布、数据来源与年份；
- 官方 Logo 覆盖数与缺图清单（`missing-logos.json` / `--logo-manifest` 产物），以及 Logo 来源；
- 四周分布 `ring_layout.edges`、都会区布局 `metro_layout.chosen` 与评分依据；
- 离岛分组名 / 家数、都会区名称与占比、两个区块是否启用；
- 总部核验口径、坐标系、未核实项。

## 验收清单

- [ ] `validate_dataset.py` 无 `error`；伪 Logo 全部被拦截
- [ ] `fetch_logos.py` 产出官方 SVG 与缺图清单；所有 SVG 可被 XML 解析且只有一个 `viewBox`
- [ ] `build_map.py` 离线硬校验通过（无外链 script / 无 `fetch` / Topology 已内嵌）
- [ ] `verify_map.py` 在严格 CSP 下 PASS，无错误横幅、底图未降级
- [ ] 数量 `[20,100]`、行业 ≥ 5 类、注册地可追溯
- [ ] 每家企业均可见官方 Logo 或无字母无文字的中性占位；`letter_marks === 0`，无外链图片、无破图
- [ ] Logo 磁贴无附加名称文字标签，按原始宽高比 `object-fit: contain` 显示
- [ ] 集群沿地图四周均匀环绕，`ring_layout.edges` 各边数量差 ≤ 1
- [ ] 离岛 / 飞地企业全部在左下区块列出，含放大地理信息
- [ ] 占比超过 35% 的都会区在右下区块列出，含放大地理信息，`metro_layout` 有评分与选择依据
- [ ] `#self-check-report.conflicts` 为空，区块内与区块外均零遮挡；底部说明栏 `footer.clear === true`，文字完整可读且不与下边集群压叠
- [ ] 城市名称细体、紧凑、无加粗
- [ ] 行业筛选 / 详情弹窗 / 名录抽屉 / 2× PNG 导出逐项可用
- [ ] 交付说明含来源、口径、缺图清单与未核实项

## 维护与评测

修改 `description` 后必须复跑触发评测：

```bash
python3 <yao>/scripts/trigger_eval.py \
  --description-file <desc.txt> \
  --cases <skill>/evals/trigger_cases.json \
  --semantic-config <skill>/evals/semantic_config.json
```

目标：`precision = 1.0`、`recall = 1.0`、`false_positives = 0`、`false_negatives = 0`。同时运行 `resource_boundary_check.py` 与 `validate_skill.py`，保持 SKILL.md 初始加载在 1000 tokens 以内。

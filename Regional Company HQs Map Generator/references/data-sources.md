# 数据检索、注册地核验与数据集建模

供 Step 1 使用。目标：产出一份**可追溯、可复核、行业均衡**的 `dataset.json`，字段以 `assets/companies.schema.json` 为准。

## 1. 权威榜单优先级

按下列顺序检索，优先使用前两类，后两类用于补足品牌知名度维度：

1. **官方指数成分股 / 交易所名单**：如 TOPIX / 日经 225、DAX、S&P 500、CAC 40、沪深 300、台湾加权指数成分股等，可核实上市主体与注册地。
2. **政府 / 行业协会 / 央行发布的规模榜单**：制造业营收榜、出口百强、纳税百强等。
3. **国际综合榜单**：Forbes Global 2000、Fortune Global 500 / 区域 500、Brand Finance 国家品牌价值榜、Interbrand / Kantar BrandZ。
4. **当地权威财经媒体榜单**：用于补充非上市但国民知名度极高的品牌（如家族企业、合作社、国有品牌）。

要求：

- 记录每条数据的**来源名称、年份与 URL**，写入 `subtitle` 或交付说明；同一份名单尽量采用同一年度口径。
- 榜单口径冲突时以「营收 / 市值等可量化指标」为主，「品牌知名度」作为补充，避免主观挑选。
- 数量落在 `[20, 100]`，默认 40–60。行业覆盖至少 5 类：科技半导体、汽车 / 重工、金融 / 商社、消费零售、食品饮料、医药化工、通信娱乐。单一行业占比建议不超过 40%。

## 2. 总部注册地核验（最关键步骤）

**禁止把跨国企业统一归入首都。** 核验顺序：

1. 企业官网的「公司概要 / About / Legal / Impressum / 会社概要 / 有価証券報告書」页面 → 取「本店所在地 /  registered office / Sitz / 本社」。
2. 上市主体的年报 / 招股书注册地址。
3. 当地商业登记数据库或权威百科作为交叉验证。
4. 若「法定注册地」与「实际运营总部」不一致，优先使用**法定注册地**，并在 `desc` 中注明运营总部，例如「注册于山口县，实际运营总部位于东京」。

典型易错示例（用于校准，不作为固定结论，仍须复核）：

| 品牌 | 常见误标 | 应核验的方向 |
| --- | --- | --- |
| Toyota | 东京 | 爱知县丰田市 |
| Fast Retailing / UNIQLO | 东京 | 山口县（注册地），东京为运营总部 |
| Nintendo | 东京 | 京都府京都市 |
| TSMC | 台北 | 新竹科学园区 |
| Volkswagen | 柏林 | 下萨克森州沃尔夫斯堡 |
| BMW | 柏林 | 巴伐利亚州慕尼黑 |
| Nestlé | 苏黎世 | 沃州沃韦 |
| Apple | 纽约 / 旧金山 | 加州库比蒂诺 |

`city` 是**集群键**：同城企业必须使用完全相同的字符串（如统一「丰田市」，不要混用「丰田」「Toyota City」），否则会被拆成多个集群并制造无意义的引导线。

## 3. 坐标

- `coords` 为 `[经度, 纬度]`，十进制度，默认 WGS84，顺序不可颠倒。
- 精度到小数点后 3–4 位即可（约 10–100 m）；不要直接使用首都坐标代替企业所在地。
- 由地址反查坐标时，使用可核对的来源并在交付说明中标注；对无法确认的坐标，宁可归入最近的已知城市中心并注明「近似定位」。
- 若底图改用国内合规地图服务坐标（GCJ-02 等），须把全部 `coords` 统一转换到同一坐标系，否则引导线会整体偏移。

## 4. 底图数据配置

**底图在构建期内嵌，运行时不读取任何 URL。** 默认使用 `assets/topo/countries-50m.json`（Natural Earth / world-atlas 50m，公有领域），只适用于中国以外地区；来源与许可见 `assets/PROVENANCE.md`。

```json
{
  "map": {
    "object": "countries",
    "match": ["Japan"],
    "sourceLabel": "Natural Earth / world-atlas 50m（构建期内嵌）"
  }
}
```

- `match` 按要素的 `properties.name` 精确（忽略大小写）匹配，例：`["Japan"]`、`["Germany"]`、`["United States of America"]`。
- 需要**次国家级行政区**（日本的都道府县、德国的州、美国的州、中国的省）或其他底图时，自备 TopoJSON 并用 `build_map.py --topo-file <path>` 传入（也可写 `map.topoFile`），设置 `object` 为相应键名，`match` 留空以绘制全部要素。
- **`map.topoUrl` 已弃用**：运行时不会请求该 URL；`validate_dataset.py` 会告警，`build_map.py` 只把它当历史来源标注。来源统一写 `map.sourceLabel`。
- 涉及中国领土轮廓时，先读 `visual-spec.md` 的「合规红线」章节，必须用 `--topo-file` 传入符合国家标准与审图要求的边界数据（自然资源部标准地图 / 天地图等）；`build_map.py` 会拦截「中国区域 + 默认境外底图」。
- 预览容器对页面下发严格 CSP，`connect-src` 不含 `data:` 与公网 CDN，任何运行时 `fetch` 都会抛 `Failed to fetch` 并导致底图降级。因此**不要**把底图改成 data URI + fetch，也不要把依赖库改回 CDN `<script src>`；构建期离线硬校验会拦截这类改动，成品须通过 `verify_map.py`。

## 5. 品牌视觉字段（不用于生成 Logo）

v1.5 起页面**只显示真实官方 Logo 原图**，不再按字段重绘徽标。下列字段仅用于详情弹窗的品牌色条、slug 派生与向后兼容：

| 字段 | 用途 |
| --- | --- |
| `brandColor` | 品牌 VI 主色，6 位 HEX；仅用于详情弹窗的细色条，不参与 Logo 绘制 |
| `wordmark` | 官方标准字的拉丁写法（TOYOTA / SONY）；`fetch_logos.py` 用它派生候选 slug，**页面不显示该文字** |
| `officialSite` | 企业官网首页；Agent 搜索后写入，供 `fetch_official_logos.py` 发现官网自身的官方 SVG（第二层来源），不用于页面显示 |
| `officialLogoUrl` | 官网上官方 Logo SVG 的精确直链；同样须通过校验闸门，不用于页面显示 |
| `logoStyle` / `mark` / `markShape` | 已弃用，仅为兼容旧数据集保留，模板完全忽略 |

严禁把 `wordmark` 首字符、`mark` 或 `markShape` 渲染成 Logo。`validate_dataset.py` 会拦截任何含文字节点或 64×20 拼装版式的伪 Logo。

## 6. 数据集骨架

```json
{
  "region": "日本",
  "title": "日本头部企业总部分布图",
  "subtitle": "Top 50 · 依据法定注册地标注 · 数据口径 2025 年",
  "map": {
    "object": "countries",
    "match": ["Japan"],
    "sourceLabel": "Natural Earth / world-atlas 50m（构建期内嵌）"
  },
  "layout": { "clusterWidth": 240, "ring": { "pad": 18, "gap": 12 } },
  "panels": {
    "outlying": { "label": "离岛 / 飞地" },
    "metro": { "threshold": 0.35, "layoutMode": "auto", "label": "东京都市圈 · 放大特写" }
  },
  "companies": [
    {
      "id": "toyota",
      "name": "Toyota",
      "local_name": "トヨタ自動車株式会社",
      "city": "丰田市",
      "prefecture": "爱知县",
      "coords": [137.156, 35.083],
      "industry": "汽车制造",
      "metric": "全球汽车销量第一",
      "desc": "以丰田市为本部的全球最大汽车制造商。",
      "brandColor": "#EB0A1E",
      "wordmark": "TOYOTA",
      "logoFile": "logos/toyota.svg",
      "logoSlug": "toyota-1",
      "metro": "名古屋都市圈"
    }
  ]
}
```

`scripts/build_map.py --init <path>` 可直接生成该骨架（含 1 条示例记录，需补足到 20 条以上才能通过校验）。`inset` 是 v1.2 的旧字段，仍能读取但已弃用，请改用 `panels.metro`。

## 7. 官方 Logo 采集规范（三层降级）

**每家企业必须尽力取得真实官方 Logo；取不到时显示中性占位，绝不自造 Logo。**

### 7.1 第一层：worldvectorlogo 精确 slug

```bash
python3 <skill>/scripts/fetch_logos.py \
  --data dataset.json --out-dir logos \
  --hints slugs.json --manifest missing-logos.json
```

- 直链格式 `https://cdn.worldvectorlogo.com/logos/<slug>.svg`（实测 200）；站内页面为 `https://www.worldvectorlogo.com/logo/<slug>`。
- **主站 `worldvectorlogo.com` 实测 403**（首页、`/logo/<slug>`、`www` 均不可直连），可用网页抓取工具查看主站页面确认 slug，但脚本只能走其官方 CDN。两者是同一素材源，不存在"改走别的站"。
- 「精确 slug 优先」：显式 `company.logoSlug` / `logoSlugs` / `--hints`（`{"company-id": ["slug-a", ...]}`）先串行快试；未命中才按 id / wordmark / name 派生并追加 `-1…-3` 版本后缀并发探测，命中即停。
- 抓取是构建期行为，成品 HTML 不含任何外链；网络受限时可 `--offline` 只统计本地素材。
- 站里没有的品牌（多为地方银行、区域公用事业等）写入 `missing-logos.json`，进入第二层。

### 7.2 第二层：企业官网官方 SVG

**搜索官网这一步由 Agent 完成，脚本不做。** 实测当前网络下 Google / DuckDuckGo 直连返回 000、Bing 返回 302，抓搜索引擎 HTML 既不可靠也违反其条款；WorkBuddy 的搜索能力可用。Agent 查得官网后写 `company.officialSite` / `company.officialLogoUrl`，或集中写进 `--sites`。地方银行域名常与品牌名不同，必须搜而不要猜（例：琉球银行是 `ryugin.co.jp`，不是 `bank-ryukyu.co.jp`）。

```bash
python3 <skill>/scripts/fetch_official_logos.py \
  --data dataset.json --out-dir logos \
  --sites sites.json --only-missing --manifest official-logos.json
```

- `--sites` 支持 `{"id": "https://官网/"}` 或 `{"id": {"site": "https://官网/", "logoUrl": "https://.../logo.svg"}}`；数据集字段优先于 `--sites`。
- 发现策略：只做只读 GET 官网首页 → 从 `src` / `data-src` / `href` / `srcset` / CSS `url()` 抽 `.svg` → 按文件名打分（logo/brand/wordmark 加分；icon/btn/banner/social 等硬排除）→ 首页无命名 Logo 时限量探测常见路径。若给了 `officialLogoUrl` 则直接抓该直链。
- **校验闸门**：合法 XML、根为 `<svg>`、恰好一个 `viewBox`、宽高比 ≤ 16 且非小方形图标、≥ 2 个矢量元素、无 `<image>` / `<script>` / `foreignObject` / 外部 `href`、`is_fake_logo()` 判定非伪 Logo。横向字标常常很扁（KEYENCE 官方 Logo 为 90.8×16），不能按最小边 ≥ 20 一刀切。
- 只认官网自身引用的 SVG；hash 文件名的云端插图、UI 图标、内联装饰 SVG 一律不认。未验证品牌写入 manifest 的 `unverified`（含逐候选失败原因），**不写 `<id>.svg`**。
- 官网在当前代理不可达（如 `ryugin.co.jp` 返回 000/502）或官网只用内联 SVG / 栅格 Logo（如武田制药）时，属预期降级，进入第三层。
- macOS 自带 Python 常缺根证书：脚本优先用 `certifi` 的 CA 验证，仅在证书链验证失败时对公开静态资源回退一次，不发送任何凭据。

### 7.3 其他来源与优先级

1. 精确 slug → worldvectorlogo CDN 官方原图（第一层，推荐）。
2. Agent 查得官网 → `fetch_official_logos.py` 抓官网 SVG（第二层，仅补缺图品牌）。
3. 本地官方素材：企业品牌规范页 / 媒体资源包，保存为 `logos/<id>.svg`（或 `.png/.webp/.jpg`），构建时加 `--logos-dir`。
4. 数据集写 `logoFile`（相对 `dataset.json` 目录或绝对路径）。
5. 数据集写 `logoUrl` 并加 `--download-logos` 联网下载。
6. 以上都缺 → 中性占位 + 缺图清单。**没有第 7 项：不允许首字母色块、文字字标、几何图腾等任何替代徽标。**

### 7.4 约束

- 所有图片由 `embed_logos.py` 转成 `data:image/...;base64,...` 内嵌；**禁止**在 HTML 中留 `http(s)://...` 图片链接。
- 官网兜底只采用官网自身引用、且通过 7.2 校验闸门的 SVG；脚本不抓搜索引擎页面，Agent 查得的官网须写进 `officialSite` / `--sites` 数据契约，而不是把第三方矢量站的图片直接当官方 Logo。
- SVG 清洗：剥离脚本 / 事件属性 / `foreignObject` / 外链 `<image>` / `<style>`，补 `xmlns`，**保证只有一个 `viewBox`**（重复 `viewBox` 会让浏览器整片破图）。
- 伪 Logo 拦截：`validate_dataset.py` 与 `embed_logos.py` 会拒绝含 `<text>` 的单字母色块、纯文字字标、`viewBox="0 0 64 20"` 拼装牌、重复 `viewBox` 的无效 SVG。历史数据集里的字母牌会被自动剔除并尝试补真图。
- 官方 Logo 的字标通常已转曲为 `<path>`，因此含 `<text>` 的 SVG 基本可判定为程序生成徽标。
- 单张图片上限 900 KB；优先 SVG，避免 HTML 体积膨胀。图片统一按固定盒尺寸 `object-fit: contain` 渲染，不因异步加载撑高区块。
- 商标图形仅用于信息图识别，需遵守来源站点使用条款。

## 8. 都会区与离岛/飞地字段

| 字段 | 语义 | 影响 |
| --- | --- | --- |
| `metro` | 所属都会区 / 城市群，如「东京都市圈」「旧金山湾区」「鲁尔区」 | 按该值分组统计占比；最高组 `> 35%` 时右下区块列出该组全部企业与放大地理信息。留空时以 `city` 兜底 |
| `outlying` | 所属离岛 / 飞地分组，如「冲绳群岛」「奄美群岛」「夏威夷」「阿拉斯加」「加里宁格勒」 | 非空即进入左下区块，按分组名再细分小地图与 Logo 列表；这类企业**不再**出现在外围集群，也**不重复**出现在右下都会区区块 |
| `panels.metro` | `{ enabled, threshold, target, keys, layoutMode, label }` | `threshold` 默认 `0.35`；`target` 指定分组键，`keys` 可把多个相邻分组键合并成一个都会区；`layoutMode` 为 `auto`（默认，按均匀与拥挤评分在 4 列 / 2 列间择优）或强制 `cols4` / `cols2`；`enabled: false` 在超阈值时会被校验拦截 |
| `layout.ring` | `{ pad, gap }` | 四周环绕布局的边距与同边卡片最小间距，默认 `18 / 12` |
| `panels.outlying` | `{ enabled, label, groups }` | 省略 `groups` 时按 `outlying` 自动分组；显式 `groups: [{name, cities: [...]}]` 可按 `city` 归组，`cities` 值必须能在数据中找到 |

判定与排布全部由模板自动完成，`validate_dataset.py` 负责提前拦截配置错误。区块与外围集群的避让、区块内外零遮挡见 `visual-spec.md`。

## 9. 不确定项处理

- 榜单年份、注册地、坐标、Logo 来源中任何一项无法核实，都要在交付说明中列出「未核实项」，不要静默填入推测值。
- 企业退市、并购、更名时，以最新主体为准，并在 `desc` 中简述变更。
- 无法取得官方 Logo 时显示无字母、无文字的中性占位，并把该企业 id 写入缺图清单；**不要伪造、重绘或用首字母臆造商标图形**。

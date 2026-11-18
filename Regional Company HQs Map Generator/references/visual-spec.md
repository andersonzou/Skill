# 视觉规范、布局算法与合规红线

供 Step 3、Step 5 使用。模板 `assets/map-template.html` 已实现本文大部分规则；此处用于理解规则、调参与排查。

## 1. 画布与配色（Strict Visual Spec）

| 项目 | 规范 |
| --- | --- |
| 画布 | 固定 `1200 × 980`，作品级海报比例；外层容器可横向滚动，禁止对画布本身做 CSS 缩放（会破坏导出与自检坐标） |
| 背景 | `#FAFAFA` / `#FFFFFF` 纯净亮白 |
| 陆地填充 | `#C6CCCE` 柔和冷灰 |
| 陆地描边 | `#9CA3AF`，`1.0–1.5px` |
| 引导线 | `#B6BCC0`，`1.1px` 实线，折线 + 端点圆点 |
| 去噪 | 隐藏地形纹理、公路网、水系、内部行政区划文字；只保留纯净陆地轮廓 |

使用 `d3.geoMercator().fitExtent([[padL, padT], [W - padR, H - padB]], featureCollection)` 自动求最佳中心与缩放，默认内边距 `[70, 60, 70, 60]`。

## 2. Logo 渲染（v1.5 修订，不可协商）

- **只显示真实官方 Logo 图**：`company.logoDataUri` 为 `data:image/...;base64,...` 时渲染 `<img class="logo-img">`。素材由 `scripts/fetch_logos.py` 从 worldvectorlogo CDN 抓取官方 SVG，再由 `embed_logos.py` 内嵌，因此离线可用、无防盗链、无 CORS 污染、html2canvas 导出不空白。
- **不显示企业文字名称**：Logo 磁贴内只有图片，不附加 `<span>` 标准字或品牌名标签。企业名只出现在详情弹窗与完整名录（供查证）、`title` 悬停提示与页脚统计中。
- **严禁用首字母作 Logo**：不使用单字母色块、几何图腾、文字字标等程序生成徽标。官方 Logo 本身就是字母字标（如 NTT / KDDI / NEC）时允许，因为那是官方原图而非占位符。`validate_dataset.py` 与 `embed_logos.py` 会拦截含 `<text>` 单字母牌、纯文字牌、`viewBox="0 0 64 20"` 拼装牌。
- **缺图**：显示 `.logo-missing` 斜纹中性标记——**无字母、无文字、无空白**，并写入 `missing-logos.json` 待补清单。绝不自造替代 Logo。
- **合理尺寸与比例**：所有图片 `width:100%; height:100%; object-fit: contain`，按原始 `viewBox` 宽高比缩放，不拉伸变形。固定盒尺寸：外围集群 `.logo-chip` 54×36、区块 `.logo-tile` 高 42（4 列）/ 46（2 列）宽由 grid 决定、详情弹窗 168×84、名录缩略图 30×22。
- **固定盒尺寸**：图片异步解码不改变布局。模板在全部 `load`/`error` 后重测面板并二次 `layoutAll()`，防止 bottom 锚定区块被撑高压住集群。
- **破图防线**：内嵌 SVG 必须有且只有一个 `viewBox`、可被 XML 解析、无重复属性。重复 `viewBox` 会让浏览器判定整个 SVG 无效；`fetch_logos.py` 清洗时已做去重，`validate_dataset.py` 也会拦截。
- 导出时 `scale: 2`，矢量图形在任何缩放比例下保持锐利。

## 3. 集群布局算法：四周均匀环绕（v1.5 核心）

`renderPanels() → placeClusters() → drawLeaders() → drawViewports() → overlapCheck()` 的执行顺序：

1. 先渲染左下 / 右下区块，测量真实 bounding box；`state.panelIds` 中的企业从外围集群剔除。
2. 其余企业按 `city` 分组，取坐标均值作锚点；按锚点到四条边的距离 `d = {top: y, bottom: H-y, left: x, right: W-x}` 取最小者作**自然边**。
3. 计算四条可用带：上/下边沿 x 轴、左/右边沿 y 轴；下边避开底部两个面板（x ∈ [342, 858]），左/右边下界收紧到各自面板 `rect.y - 14`，上界让出顶部带高度。每带按 `(可用长度 + gap) / (卡片尺寸 + gap)` 求容量。
   - **下边带底边固定为 `H - FOOTER_RESERVE`（默认 52px）**：8px 底距 + 约 32px 两行说明文字 + 12px 与集群的间隔。说明栏 x ∈ [342, 858] 与下边带同宽、恰好避开左右两个 bottom 锚定面板；集群卡片底边最多到 `H - 52`，不得侵入说明栏。早期版本把说明栏固定在 `bottom:14px` 却让下边带延伸到 `H - pad`，导致「京都 / 名古屋」卡片与说明文字压叠，且因说明栏未进自检盒而漏报。
4. 先按自然边分配（容量不足改投次近边），再做**负载均衡迭代**：把最挤边中「迁移代价 `d[to] - d[from]` 最小」的卡片移到最空边，直到任意两边数量差 ≤ 1。报告 `ring_layout.edges` 与 `balance`（四边数量的标准差）。
5. 每条边内沿主轴按锚点投影排序、均匀分槽 `slot = span / n`，再用实测 `offsetHeight/offsetWidth` 做斥力迭代（最多 60 轮）消除重叠；溢出则整边回移。**禁止只排左右两列，禁止「整侧上移 + clamp」把卡片堆到顶部**。
6. 引导线按所在边从卡片内缘引出：左→右、右→左、上→下、下→上，折线 `[内缘, 外推 20px, 锚点]`，末端绘定位圆点；区块用虚线引导线接到主地图虚线视口框。
7. 集群卡片与区块内 Logo 列表用 `flex-wrap` / CSS Grid 流式排布，**禁止硬编码单个 Logo 的绝对坐标**。
8. 图片全部解码后重跑 `layoutAll()`，重新测量区块并重排集群。

## 4. 排版规范

- 地区 / 城市名称、区块标题、分组名一律 `font-weight: 300`（最多 400），**严禁加粗**；`line-height: 1.1`、紧凑字距。
- 目的：让彩色 Logo 成为视觉主体，灰色细体地名退为背景信息。
- 集群数量角标用更浅的 `#A2A9AD`，不与地名争夺注意力。

## 5. 双区块：左下离岛 / 飞地、右下都会区

两个区块均为 bottom 锚定、宽 `306px` 的白色面板，左右各距边缘 `22px`，互不水平相交。

| 区块 | 触发条件 | 内容 |
| --- | --- | --- |
| 左下 `#panel-outlying` | 任一 `company.outlying` 非空，或 `panels.outlying.groups[].cities` 命中企业 | 标题 + 每个分组一个 `284×72` 放大地理小地图 + 该组企业 Logo 磁贴（4 列 grid） |
| 右下 `#panel-metro` | 任一 `metro`（缺失时 `city`）分组占比超过阈值（默认 0.35） | 标题（含家数、占比、当前列数）+ `284×92` 放大地理小地图 + 该都会区企业 Logo 磁贴 |

**右下区块双布局自动择优（v1.5 核心）**：模板先用 `cols-4`（4 列横向）与 `cols-2`（2 列纵向）各渲染一次并实测高度，再按同一套评分取低分者：

| 维度 | 含义 | 权重 |
| --- | --- | --- |
| `crowd` | 面板高度 / 该侧可用高度 → 面板越高越挤压同侧、下侧集群（局部拥挤） | 1.35 |
| `balance` | 与左下区块高度差 / 画布高 → 版面左右均衡 | 0.85 |
| `occupancy` | 末行空位 / 列数 → Logo 阵列整齐度 | 0.55 |
| `aspect` | 磁贴宽高比与 Logo 常态的偏离 | 0.25 |
| `spread` | 4 列行数过少（横向铺散）或 2 列行数过多（纵向拥堵）的密度惩罚 | 直接加 |

结果写入 `metro_layout: {chosen, reason, scores, runner_up}`，含两种模式的行数、面板高度与各项分数，便于复核。企业多（如 20 家）通常选 4 列以避免面板过高；企业少（如 4 家）会选 2 列以避免 4 列只铺一行。可用 `panels.metro.layoutMode` 强制指定 `cols4` / `cols2`。

- 小地图以该组企业坐标均值为中心，用 `d3.geoMercator().center(...).scale(base × 8~14).clipExtent(...)` 重绘 `state.allFeatures`，并按视口 bounds 过滤，避免把全球轮廓塞进 DOM。
- 主地图上为每个分组画虚线视口框（84×60），并用虚线折线连到对应区块顶部；视口框会围绕真实锚点尝试 ±96/±152px 避让位，避开面板、集群与已有视口；**无空位时省略该视口框**（小地图仍完整），省略的分组名记录在 `viewports_skipped`。
- `outlying` 优先于 `metro`：离岛企业只进左下区块；都会区占比统计仍按全体企业计算。

## 6. 零遮挡自检与调参顺序

右上角徽标、「重叠自检」按钮与隐藏的 `#self-check-report` 都来自 `overlapCheck()`，检测四类冲突：

1. **区块外**：外围集群 / 两个区块 / 主地图视口框 / **底部说明栏** 的 bounding box 两两相交（2px 容差）；说明栏作为 `kind:'footer'` 的受保护盒参与此项判定，但不参与引导线穿越判定（细线穿过页脚属可接受排版）；
2. **区块内**：同一面板内所有 `.logo-tile` 两两相交，或任一磁贴越出面板边界；
3. **集群内**：同一外围集群内 `.logo-chip` 两两相压；
4. **引导线**：任一段折线采样点落入**其他**集群 / 区块（自身起点盒与视口框除外）。

隐藏报告结构：`{ ok, conflicts, panels:[{name,side,listed,tiles,rect}], clusters, viewports, viewports_skipped, topology:{embedded,features,land_paths,degraded}, logos:{official,neutral_placeholder,letter_marks,total}, ring_layout:{edges,balance,bands}, metro_layout:{chosen,scores,...}, footer:{rect,reserve,clear}, inner_tile_pairs_checked, boxes_checked }`。

验收门槛：`conflicts: []`、`ok === true`、`topology.embedded=true / degraded=false / land_paths>0`、`logos.letter_marks === 0`、`official + neutral_placeholder === total`、`footer.clear === true`、`ring_layout.balance` 接近 0。`verify_map.py` 在严格 CSP 下自动断言前几项，并单独断言 `footer.clear`；负例做法是把模板的 `FOOTER_RESERVE` 改小重构建，应稳定报出「区块外重叠：集群 ×× × 底部说明栏」。

修复优先级：

1. **检查 Logo 是否固定盒尺寸**：图片异步撑高面板是晚期重叠最常见原因，模板已用 `layoutAll()` 二次排布兜底。
2. **调小 `layout.clusterWidth`**（240 → 210 → 190），让卡片更窄、四边容量更大；注意换行会增加卡片高度。
3. **调整 `layout.ring.pad/gap`**：减小 `pad` 让四边带更长，`gap` 影响同边斥力间距。
4. **收紧 `map.padding`**，让主体地图更居中，为四边集群留出更多横向空间。
5. **合并离岛分组 / 放宽都会区 `keys`**：减少区块高度，缓解同侧挤压。
6. **强制指定 `panels.metro.layoutMode`**：面板过高时强制 `cols4`，企业少时强制 `cols2`。
7. 检查是否误把同一城市写成不同字符串导致集群数量虚高。

禁止通过放宽容差、隐藏告警徽标或删掉 `#self-check-report` 来「消除」冲突。

## 7. 交互与导出验收

| 功能 | 验收点 |
| --- | --- |
| 行业筛选 | 集群与两个区块中非目标行业 Logo 均 `opacity:.2; grayscale(100%)`，恢复「全部行业」后全部还原 |
| 详情弹窗 | 顶部显示官方 Logo 大图（或中性占位）+ 全称、当地语言名、注册地、行业、核心指标、坐标、简介；Esc / 遮罩可关闭 |
| 完整名录抽屉 | 按行业分组，每条带 Logo 缩略图与企业名，可点击打开详情 |
| 2× PNG 导出 | 点击后生成 2400×1960 无水印 PNG；无空白、无破图、无跨域报错 |
| 零遮挡自检 | 徽标绿色且 `#self-check-report.ok === true`；冲突明细可在控制台查看 |
| 降级提示 | 仅当成品被手工破坏（依赖或 TopoJSON 未内嵌）时显示横幅；正常构建产物在断网与严格 CSP 下均不降级 |

## 8. 合规红线（不可协商）

- **地图服务白名单**：若改用瓦片式 / SDK 式在线地图，只允许腾讯地图、高德地图、百度地图、天地图；禁止 Google Maps、Apple Maps、Bing 海外版、Mapbox、Leaflet + OSM 海外瓦片等无资质来源。本技能用的是静态 TopoJSON 轮廓，不属于在线瓦片服务，但边界数据本身仍需合规。
- **领土表达**：涉及中国全图或中国省级区域时，国界、台湾、南海诸岛必须符合国家标准和审图要求，不得错绘、漏绘或错误标注；标注统一使用「中国台湾 / 中国香港 / 中国澳门」，不得作为独立国家处理。境外边界数据（如 Natural Earth）用于中国区域前必须替换为合规标准底图；`build_map.py` 检测到中国区域 + 内置境外底图会直接终止构建，必须用 `--topo-file` 传入合规数据并写 `map.sourceLabel`。
- **离线资产**：`assets/vendor/` 三个库与 `assets/topo/` 底图在构建期内嵌，运行时零网络请求，不使用任何在线瓦片/SDK 服务；来源与许可见 `assets/PROVENANCE.md`。
- **敏感坐标**：不得标注军事禁区、涉密单位或未公开敏感坐标。
- **位置信息合规**：批量点位须为公开的企业注册地，不得收集、存储或公开个人位置数据。
- **密钥**：不得在前端内嵌任何有效地图 API Key；需要时使用占位符提示用户自行申请。

## 9. 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 顶部提示「依赖未内嵌」 | 直接打开了带占位符的模板，或 HTML 被手工删掉内联库 | 用 `build_map.py` 重新构建；检查 `assets/vendor/` 三个文件齐全，且占位符没被包在 `<!-- -->` 注释里 |
| 「地图数据加载失败：Failed to fetch」 | v1.3 及更早：底图用 `data:` URI 或 CDN 在运行时 `fetch`，被预览 CSP 拦截 | 升级到 v1.4+：底图改为构建期 JS 对象 `EMBEDDED_TOPO`，运行时不发起请求；重建并跑 `verify_map.py` |
| 「底图数据无效」横幅 | 手工改坏了 `EMBEDDED_TOPO`，或 `map.object` / `map.match` 写错 | 重新构建；核对 TopoJSON 要素 `properties.name`；`match` 留空测试全量要素 |
| `file://` 打开正常、预览里却降级 | 双击打开没有 CSP，掩盖了运行时请求被拦截 | 一律用 `verify_map.py` 在严格 CSP 下复验 |
| 引导线整体偏移 | 坐标系不一致（WGS84 vs GCJ-02）或经纬度写反 | 统一坐标系；确认 `coords` 顺序为 `[经度, 纬度]` |
| **大量 Logo 显示破图图标** | 内嵌 SVG 有重复 `viewBox` 属性或非法 XML | 用 XML 解析 `<logos_dir>/*.svg`；`fetch_logos.py` 已做 viewBox 去重，旧素材需重新抓取或清洗 |
| 导出 PNG 空白 / 破图 | 引入了外链图片或跨域资源 | 只使用 `data:image/...` 内嵌图；用 `--logos-dir` 重新构建 |
| 页面出现单首字母色块 / 品牌文字标签 | 数据集里带了旧版拼装字母牌 | `validate_dataset.py` / `embed_logos.py` 会自动拦截并剔除；用 `fetch_logos.py` 补官方原图 |
| 企业没有 Logo、只有斜纹块 | worldvectorlogo 该站无此品牌官方图 | 属预期中性占位；查 `missing-logos.json`，手动补 `<id>.svg` 后重建 |
| 包围集群只挤在左右两侧 | 用了 v1.4 及更早的模板 | 升级到 v1.5 四周环绕布局；检查 `ring_layout.edges` 四边是否都有卡片 |
| 底部说明文字与集群小 Logo / 文字压叠 | 下边集群带侵入说明栏净空（`FOOTER_RESERVE` 被改小或说明栏改宽盖住面板） | 恢复 `FOOTER_RESERVE = 52`、说明栏 `left:342px; width:516px`；检查 `footer.clear === true` 与 `ring_layout.bands.bottom.y1 ≤ H - 52` |
| 左下 / 右下区块不出现 | 未填 `outlying` / `metro`，或 `panels.*.enabled` 被显式设为 false | 补齐字段；超阈值却显式禁用会被校验拦截 |
| 区块内 Logo 溢出面板 | 企业数过多或磁贴过宽 | 强制 `panels.metro.layoutMode: cols4`，或合并离岛分组 |
| 图片加载后区块压住集群 | 早期版本的图片无固定盒尺寸 | 模板已固定 `.logo-img` 尺寸并在解码后重跑 `layoutAll()`；勿删该逻辑 |
| 页面 DOM 异常庞大 | 小地图把全球所有要素都画进 SVG | 保留 `clipExtent` 与 `path.bounds` 视口过滤 |
| 城市名称显示为粗体 | 手工改动了 `.cluster-name` | 恢复 `font-weight: 300` |
| 小地图只有定位点、没有陆地轮廓 | 该 TopoJSON 不含离岛几何，或 `map.match` 过滤太窄 | 换用含该区域的 TopoJSON（小地图读取全部要素），并保留主地图 `match` 用于聚焦 |

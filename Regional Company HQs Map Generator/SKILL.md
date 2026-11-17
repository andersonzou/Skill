---
name: regional-company-hqs-map-generator
display_name: 区域企业总部地图生成器
display_name_en: Regional Company HQs Map Generator
description: 检索指定国家或地区 Top 20–100 头部企业并核验其法定注册总部所在地，生成白底冷灰极简轮廓地图风格的单文件交互式 HTML 信息图，包含防遮挡空间集群布局、核心城市特写放大视口、行业筛选、详情弹窗与 2 倍高清 PNG 导出。当用户要求制作、可视化某地区头部企业/品牌总部地理分布、企业总部地图、品牌分布信息图，或要求迭代已有企业地图时，应使用本技能。
category: 数据可视化
version: 1.2.0
user-invocable: true
disable-model-invocation: false
agent_created: true
---

# 区域头部企业总部地图生成器

## 1. 目标

将某国家或地区最具代表性的 20–100 家头部企业/商业品牌，按其**法定注册地或核心运营总部**映射到白底冷灰极简轮廓地图上，产出一份可直接打开、可交互筛选、可导出高清 PNG 的**单文件 HTML** 信息图。全部 Logo 采用内联 CSS/SVG 矢量绘制，不依赖外部图片，保证离线可用与导出无空白。

## 2. 触发条件与输入

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `target_region` | 是 | 目标国家或地区，如日本、德国、美国加州、中国长三角、中国台湾 |
| `company_count` | 否 | 收录数量，默认 40–60，严格约束 `[20, 100]` |
| `ranking_criteria` | 否 | 默认综合市值、营收、品牌价值/国民知名度，行业不限 |
| `output_dir` | 否 | 默认当前工作区下的输出目录 |

仅当用户询问技能用法、要求修改本技能，或请求编辑既有地图时，跳过生成流程并按用户意图处理。

## 3. 资源清单

| 路径 | 用途 | 调用时机 |
| --- | --- | --- |
| `references/data-sources.md` | 权威榜单来源、注册地核验原则、数据集字段规范、区域示例 | Step 1 检索前读取 |
| `references/visual-spec.md` | 视觉规范、集群布局算法、零遮挡自检、地图合规红线、故障排查 | Step 3 配置前读取；出现渲染问题时查阅 |
| `assets/companies.schema.json` | 数据集 JSON Schema | Step 1 建模时对照 |
| `assets/map-template.html` | 单文件 HTML 模板（D3 + TopoJSON + html2canvas），含 `__REGION_NAME__` / `__REGION_JS__` / `__MAP_DATA__` / `__TOPO_URL__` 占位符 | 由 `build_map.py` 自动注入，通常无需手工编辑 |
| `scripts/validate_dataset.py` | 校验数量、字段、坐标、重复 ID、城市集中度与特写触发条件 | Step 2 执行 |
| `scripts/build_map.py` | 校验并把数据集注入模板，生成最终单文件 HTML；`--init` 生成数据骨架 | Step 4 执行 |

路径均相对于本 skill 目录；执行脚本时使用绝对路径。

## 4. 标准化工作流

### Step 0 — 确定参数与输出位置
确认 `target_region`、`company_count`、`ranking_criteria` 与 `output_dir`。信息缺失时按第 2 节默认值执行，并在交付说明中标注所用默认值。

### Step 1 — 检索、核验与建模
1. 读取 `references/data-sources.md`，按其中的榜单优先级联网检索该地区最新权威商业排名。
2. 覆盖尽量多的行业（科技半导体、汽车制造、金融、消费零售、食品饮料、医药重工、通信娱乐等），避免名单被单一行业占据。
3. 逐家核验法定注册地或核心运营总部，**禁止把跨国企业统一归入首都**。存疑时以企业官网「公司简介 / 公司概要 / Legal / Impressum」页面为准。
4. 按 `assets/companies.schema.json` 写出 `dataset.json`，包含 `region`、`title`、`map`（TopoJSON 配置）与 `companies` 数组；对照 `references/data-sources.md` 补全 `brandColor`、`wordmark`、`logoStyle` 等视觉字段。

### Step 2 — 数据集校验
执行 `python3 <skill>/scripts/validate_dataset.py <dataset.json>`。修正所有 `error` 级问题后再进入下一步；`warning` 级问题（如最高城市集中度超过 35%）按输出提示设置 `inset.enabled: true`。

### Step 3 — 视觉与合规配置
读取 `references/visual-spec.md`，确认配色、细体城市名、集群对齐方式、特写视口触发规则与地图数据合规红线。涉及中国全图或中国省级区域时，必须先按该文档的合规条款选择边界数据源。

### Step 4 — 构建单文件 HTML
执行 `python3 <skill>/scripts/build_map.py --data <dataset.json> --out <output_dir>/<region>-company-hqs.html`。
脚本会自动复跑校验、转义数据、替换占位符并写出单文件 HTML。仅在模板能力不足（如需要自定义视口形状、新增交互）时才直接编辑生成的 HTML，并把可复用改动回填模板。

### Step 5 — 运行验证
用 `present_files` 打开生成的 HTML，逐项确认：
- 底图成功渲染，无「地图数据加载失败」横幅；
- 页面右上角**零遮挡自检**显示通过（无重叠集群）；若报冲突，按 `references/visual-spec.md` 的调参顺序修正 `maxWidth` / 集群朝向 / 间距后重建；
- 逐一试用行业筛选、Logo 详情弹窗、完整名录抽屉；
- 点击导出 PNG，确认无空白、无破图、无跨域报错。

### Step 6 — 交付
用 `present_files` 展示最终 HTML（必要时附导出 PNG），并在回复中说明收录企业数、总部核验口径、特写视口是否启用、以及任何未核实项。

## 5. 不可协商的约束

- **数量**：`20 ≤ 收录企业 ≤ 100`，且均为该地区公认头部企业/品牌。
- **位置**：引导线端点必须指向企业真实注册地经纬度，禁止以首都批量替代。
- **Logo**：只用内联 CSS/SVG 徽标，禁止引用外链图片或跨域图床。
- **零遮挡**：集群内部用 `flex-wrap` 流式排列，禁止硬编码绝对坐标堆叠单个 Logo；集群之间、文字与引导线之间也不得重叠。
- **排版**：地区/城市名称使用细体（`font-weight: 300/400`），紧凑行高，禁止加粗。
- **特写视口**：单一城市企业占比 `> 35%` 时，必须绘制放大版灰色行政地图特写，并用虚线视口框与引导线连接主地图对应坐标。
- **单文件**：所有 HTML/CSS/JS 与数据内嵌于一个 `.html` 文件；第三方库走 CDN 并提供加载失败提示。
- **合规**：不使用不合规的境外瓦片地图服务；涉及中国领土轮廓时，国界、台湾、南海诸岛必须符合国家标准，标注统一使用「中国台湾 / 中国香港 / 中国澳门」。

## 6. 质量验收清单

- [ ] `validate_dataset.py` 无 `error` 级输出
- [ ] 收录数量在 `[20, 100]` 内，行业分布均衡
- [ ] 核心企业注册地可追溯至权威来源，坐标与引导线一致
- [ ] 底图符合「白底 + 浅灰纯轮廓」规范，无地形/路网/水系等杂讯
- [ ] 集中度 `> 35%` 的城市已启用特写放大视口
- [ ] 页面零遮挡自检通过；城市名称细体、紧凑、无加粗
- [ ] 行业筛选、详情弹窗、名录抽屉、2× PNG 导出逐项可用
- [ ] 单文件 HTML 可直接打开，导出 PNG 无空白与破图
- [ ] 交付时说明数据来源、核验口径与未核实项

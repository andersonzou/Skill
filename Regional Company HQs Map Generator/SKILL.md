---
name: regional-company-hqs-map-generator
display_name: 区域企业总部地图生成器
display_name_en: Regional Company HQs Map Generator
description: 检索指定国家或地区 Top 20–100 头部企业并核验法定注册总部，抓取真实官方品牌 Logo 内嵌为 data URI，生成白底冷灰极简轮廓地图风格的单文件交互式 HTML 信息图：企业 Logo 沿地图四周均匀环绕排布，只显示官方 Logo 图而不附加名称文字，严禁用首字母色块或文字牌冒充 Logo，左下角离岛/飞地区块与右下角都会区（占比超过 35%）区块各自列出该区企业 Logo 与放大地理信息，都会区按整体均匀与避免局部拥挤自动在 4 列横向与 2 列纵向中择优，区块内与区块外均零遮挡，并支持行业筛选、详情弹窗与 2 倍高清 PNG 导出。当用户要求制作、可视化某地区头部企业/品牌总部地理分布、企业总部地图、品牌分布信息图，或要求为已有企业地图补真实 Logo、去掉首字母占位、改四周均匀布局、补离岛飞地标注、补都会区特写时，应使用本技能。
category: 数据可视化
version: 1.5.0
user-invocable: true
disable-model-invocation: false
agent_created: true
---

# 区域头部企业总部地图生成器

## 目标

按注册总部生成白底冷灰极简、单文件可交互可导出 PNG 的企业总部 HTML 信息图。硬要求：只显示真实官方 Logo（无字母牌、无名称文字）、Logo 四周均匀环绕、离岛/飞地列左下、占比超过 35% 的都会区列右下并在 4 列 / 2 列自动择优、区块内外零遮挡。

## 输入

`target_region` 必填；`company_count`（默认 40–60，限 `[20,100]`）、`ranking_criteria`、`logos_dir`、`output_dir` 可选。仅咨询/改技能时不跑生成。

## 资源

| 路径 | 用途 |
| --- | --- |
| `references/workflow.md` | Step 0–6 完整命令、两层抓 Logo、严格 CSP 核验与验收清单 |
| `references/data-sources.md` | 榜单与注册地核验、Logo 三层来源、`metro` / `outlying` 语义 |
| `references/visual-spec.md` | 视觉规范、四周环绕与双布局算法、零遮挡判据、合规红线 |
| `assets/companies.schema.json` | 数据集 Schema |
| `assets/map-template.html` | 单文件 HTML 模板（5 个注入占位符） |
| `assets/vendor/` + `assets/topo/` + `assets/PROVENANCE.md` | 构建期内联的 D3 / topojson / html2canvas、底图数据与来源许可 |
| `scripts/fetch_logos.py` / `fetch_official_logos.py` | 两层抓官方 SVG：精确 slug → 官网兜底（校验 + 缺图清单） |
| `scripts/validate_dataset.py` / `embed_logos.py` | 数据集校验与伪 Logo 拦截 / 官方图内嵌 |
| `scripts/build_map.py` / `verify_map.py` | 生成单文件 HTML（`--init` 出骨架）/ 严格 CSP 回归 |
| `evals/` | 触发用例与语义配置，改 `description` 后复跑 |

## 工作流

1. **检索建模** — 读 `data-sources.md`，检索权威榜单、核验注册地、填 `metro` / `outlying`，按 schema 写 `dataset.json`。
2. **抓官方 Logo（两层）** — `fetch_logos.py` 精确 slug → 未命中由 Agent 查官网、跑 `fetch_official_logos.py`；仍缺图用中性占位，绝不造首字母牌。详见 `workflow.md` Step 6。
3. **校验** — `validate_dataset.py` 清零所有 `error`。
4. **配置与构建** — 读 `visual-spec.md`；涉及中国领土时用 `--topo-file` 传合规边界；跑 `build_map.py --data ... --out ... --logos-dir logos`，依赖库、TopoJSON、Logo 全部内嵌。
5. **验证** — 先 `verify_map.py --html ...`，再 `present_files` 打开，确认 `conflicts: []`、`letter_marks === 0`、`footer.clear`、四周均衡、`metro_layout.chosen` 有依据，试交互与导出。
6. **交付** — 说明来源、Logo 覆盖与缺图清单、四周分布、布局选择、未核实项。

## 硬约束

- 数量 `20–100`；注册地与引导线坐标真实，禁止首都批量替代。
- **只显示真实官方 Logo 图**：磁贴无名称标签，不以首字母作 Logo（官方字标除外）；缺图用无字母无文字中性占位；按原始宽高比 `object-fit: contain` 固定盒显示。
- 官方图只能以 `data:image/...` 内嵌，禁止外链；校验拦截 `<text>` 文字牌、64×20 拼装牌与重复 `viewBox`。
- 官网兜底只取官网自身引用、通过校验的 SVG；脚本不抓搜索引擎，未验证品牌中性占位。
- 外围集群按锚点分四边并负载均衡，同边均匀分槽，禁止只排左右两列。
- 所有 `outlying` 进左下、`metro` 超阈值必启右下，均含放大地理信息，显式禁用会被拦截。右下按面板高度、左右均衡、末行空位、磁贴比例与密度在 4/2 列间择优，可用 `panels.metro.layoutMode` 强制。
- 区块内 Logo 不重叠不越界；区块外集群、区块、视口框、引导线互不遮挡，以运行时自检报告为准。
- **依赖库与底图构建期内嵌，运行时禁止 `fetch` 与外链**；预览 CSP 拦截 `data:` / CDN，`verify_map.py` 必须 PASS。
- 涉及中国领土须用 `--topo-file` 传合规边界数据，标注用「中国台湾 / 中国香港 / 中国澳门」。

## 验收

门槛：校验无 `error`、`verify_map.py` PASS、`conflicts` 空、`letter_marks === 0`、四周均衡、双区块齐全、PNG 无空白。

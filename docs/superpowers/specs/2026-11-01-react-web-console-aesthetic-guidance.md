# React 字幕流水线工作台：美学与视觉设计规范

- 日期：2026-11-01（Asia/Shanghai）
- 状态：**可落地基线，随 M1 一起实施**；本文只定义视觉与呈现，不改交互语义。
- 需求权威：[2026-11-01-react-web-console-spec.md](./2026-11-01-react-web-console-spec.md)；并行契约：[实施计划 §2.7](../plans/2026-11-01-react-web-console-implementation-plan.md)。冲突时以 SPEC 为准。
- 边界：不新增“运行中取消”、参数编辑、ETA、总进度百分比等 SPEC 未批准的交互；状态枚举与筛选口径不因视觉需要改写。约束：系统字体栈、无 CDN/外链字体/遥测；浅色默认，深色为等价主题（非滤镜反色）。

## 1. 设计定位

这是一张**安静的运维台**：界面在多数时间只是被动显示轮询结果，价值出现在“哪一步错了、错在谁、还能不能救”的十秒内。因此视觉目标是**可信、可扫读、低刺激**——用稳定的栅格和克制的灰阶建立秩序，用单一品牌色标记“可以点/正在跑”，用语义色只标记状态。

中文桌面、长时间驻留、1280px 起：字号不为美观缩小，密度靠行高与留白调节；不使用大面积品牌色、渐变、玻璃拟态或装饰性插画，因为那会与“真实状态”争夺注意力。**宁可留白并写“暂无进度”，也不填 0%**——这是视觉层对 SPEC §3.4「不显示假 0%/假 100%」的落实。

## 2. 颜色系统

所有色值为 sRGB hex；深色不是浅色的反相，而是独立校准的一套。对比度为 WCAG 2.1 相对亮度计算值。

### 2.1 背景、边框与交互底色

| Token | Light | Dark | 用途 |
|---|---|---|---|
| `bg/app` | `#EEF1F5` | `#0B0F16` | 窗口最底层，仅侧栏/顶栏之外可见 |
| `bg/canvas` | `#F6F8FA` | `#10151D` | 内容区滚动底色 |
| `bg/surface` | `#FFFFFF` | `#161C26` | 卡片、表格、弹窗内容 |
| `bg/raised` | `#FFFFFF` | `#1D2531` | 下拉、Popover、Tooltip；浅色与 surface 同值，靠 L2 阴影区分 |
| `bg/hover` | `#F1F5F9` | `#1E2633` | 行 hover、次级按钮 hover、表头底 |
| `bg/selected` | `#EAF0FD` | `#17233A` | 选中行、选中导航项 |
| `border/subtle` | `#EEF1F5` | `#1C2532` | 表格内分隔线、卡片内分区 |
| `border/default` | `#DDE3EA` | `#232D3B` | 卡片外框、输入框默认边 |
| `border/strong` | `#B6C2D1` | `#46566B` | hover 描边、次级按钮描边 |
| `border/control` | `#7F8DA0` | `#62748A` | 仅用于必须靠边界识别的控件态（3.38:1 / 3.57:1） |

### 2.2 文本

| Token | Light | Dark | 对比度（on surface） | 用途 |
|---|---|---|---|---|
| `text/primary` | `#0F172A` | `#E6EDF7` | 17.85:1 / 14.51:1 | 标题、单元格主值 |
| `text/secondary` | `#475569` | `#A7B4C6` | 7.58:1 / 8.13:1 | 说明文字、表头、次级按钮 |
| `text/tertiary` | `#64748B` | `#8291A6` | 4.76:1 / 5.33:1 | 元信息、时间戳、单位 |
| `text/disabled` | `#94A3B8` | `#5C6B80` | 2.56:1 / 3.15:1 | 仅禁用控件；不承载唯一信息 |
| `text/inverse` | `#FFFFFF` | `#FFFFFF` | — | 主按钮文字（白） |

正文与 12px 标签一律 ≥4.5:1；≥18.66px 粗体或 ≥24px 可用 3:1。禁用态豁免于 WCAG，但凡禁用项同时带 `title` 或行内原因文案，不允许“只有变灰才算禁用”。

### 2.3 品牌与语义

| Token | Light 底 / 字 | Dark 底 / 字 | 说明 |
|---|---|---|---|
| `brand/fill` | `#1D4ED8` / `#FFFFFF` | `#2F6AD8` / `#FFFFFF` | 主按钮底与白字：6.70:1 / 5.03:1；深色按钮底色比链接深一档 |
| `brand/text` | — / `#1D4ED8` | — / `#6D9BFF` | 链接、选中导航文字（6.70:1 / 6.34:1） |
| `brand/soft` | `#EAF0FD` / `#1D4ED8` | `#17233A` / `#6D9BFF` | 选中底、当前阶段高亮底；其上文字用 `brand/text` |
| `success` | `#ECFDF3` / `#166534` | `#10251A` / `#6EE7A0` | 6.76:1 / 10.45:1 |
| `warn` | `#FFF7E6` / `#92400E` | `#2A2011` / `#F0B96B` | 6.65:1 / 9.03:1 |
| `danger` | `#FEF2F2` / `#B91C1C` | `#2C1518` / `#FCA5A5` | 5.91:1 / 9.01:1 |
| `info` | `#EEF4FF` / `#1D4ED8` | `#121E33` / `#7FA9FF` | 6.08:1 / 7.16:1 |
| `neutral` | `#F1F5F9` / `#334155` | `#1E2633` / `#A7B4C6` | 9.45:1 / 7.24:1 |
| `blocked` | `#FFF4E5` / `#92400E` | `#2B1D12` / `#E0A06A` | 6.52:1 / 7.31:1；与 warn 同族，靠图标与文案区分 |

### 2.4 状态标签矩阵（文字 + 图标 + 色，三重冗余）

| 状态 | 出现位置 | 文案 | 图标（`@ant-design/icons`） | Light 底/字 | Dark 底/字 |
|---|---|---|---|---|---|
| `queued` | Job / Task | 排队中 | `ClockCircleOutlined` | `#F1F5F9` / `#334155` | `#1E2633` / `#A7B4C6` |
| `claimed` | Task | 已领取 | `HourglassOutlined` | `#F1F5F9` / `#334155` | `#1E2633` / `#A7B4C6` |
| `running` | Job / Task | 运行中 | `SyncOutlined`（1.6s 线性旋转） | `#EEF4FF` / `#1D4ED8` | `#121E33` / `#7FA9FF` |
| `succeeded` | Job / Task | 已完成 | `CheckCircleFilled` | `#ECFDF3` / `#166534` | `#10251A` / `#6EE7A0` |
| `failed` | Job / Task | 失败 | `CloseCircleFilled` | `#FEF2F2` / `#B91C1C` | `#2C1518` / `#FCA5A5` |
| `blocked` | Task | 被阻断 | `StopOutlined` | `#FFF4E5` / `#92400E` | `#2B1D12` / `#E0A06A` |
| `cancelled` | Task | 已取消 | `MinusCircleOutlined` | `#F1F5F9` / `#475569` | `#1E2633` / `#A7B4C6` |

- 图标与文字同色、同 12px；**不使用 emoji**、不用实心色块铺满整行；语义色只出现在标签、图标、进度条、告警条，正文与表头一律灰阶。
- Job 无 `blocked`/`cancelled`：全 cancelled 的 Job 仍显示 `failed`，在其后追加 12px 三段色文字“已取消（未执行）”，不新增枚举、不改筛选。

## 3. 字体与排版

```text
SANS: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB",
      "Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", "Yu Gothic UI", Meiryo, sans-serif
MONO: ui-monospace, "Cascadia Mono", "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace
```

`Yu Gothic UI`/`Meiryo` 覆盖日文假名，`PingFang SC`/`Microsoft YaHei` 覆盖中文；不引入 Web Font。

| 层级 | px / 行高 | 字重 | 用途 |
|---|---|---|---|
| Caption | 11 / 16 | 500 | 图表单位、日志级别、极少量 eyebrow；禁止承载句子 |
| Meta | 12 / 18 | 400 | 时间戳、卡片元信息、表格辅助列、错误码 |
| Body | 13 / 20 | 400 | 正文、表格单元格、表单、说明段落（按钮同尺寸、字重 500） |
| Label | 14 / 22 | 500 | 表头、卡片标题、区块标签、导航项 |
| Panel | 16 / 24 | 600 | 弹窗标题、面板标题 |
| Title | 20 / 28 | 600 | 页面标题（每页唯一） |
| KPI | 24 / 32 | 600 | 概览计数卡数值，配 12px/18 标签 |

- 字重只用 400 / 500 / 600，不使用 700；中文不加字距，英文全大写标签可用 `letter-spacing: 0.04em`（仅 eyebrow）。
- 数字、时间、耗时、字节数、计数、进度百分比、Job/Task ID 一律 `font-variant-numeric: tabular-nums`；正文段落不开，避免中英混排松散。
- 等宽字体用于 ID、服务器路径、日志、请求 ID、`sha256`、配置键、preset_id、错误码，字号 12px 不加粗；说明段落最大宽度 68 字符（中文约 34 字），超过换行而非拉满 1440px。

## 4. 空间与形状

**4pt 网格**。间距只取 `2 / 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64`，禁止 6、10、14、18 这类非标值（1px 边框与 2px 指示条除外；表格单元格 10/12 的内边距由 40px 行高反推，属组件内部排版）。

| 场景 | 值 |
|---|---|
| 卡片内边距 | 16（紧凑卡片 12） |
| 卡片之间、栅格 gutter | 16 |
| 区块之间（标题区→内容、表格→分页） | 24 |
| 页面内容左右内边距 | 24（≤1023px 为 16） |
| 工具条与表格之间 | 12 |
| 表单行距、字段标签与控件 | 8 / 4 |
| 图标与文字 | 8（标签内 4，导航 8） |

**圆角**：标签 4，按钮/输入/下拉 6，卡片/面板 8，弹窗/抽屉 10，进度条轨道 2，状态圆点 50%，全局 `borderRadius` 不超过 8。**边框**：一律 1px；不用 2px 分隔线制造层级，聚焦用外环而非加粗边框；表格行分隔只用 `border/subtle`，纵向不加线。

**阴影（仅 3 级 + 无阴影）**：

| 级别 | Light | Dark | 用途 |
|---|---|---|---|
| L0 | none + 1px 边框 | 同 | 卡片、表格、面板（默认） |
| L1 | `0 1px 2px rgba(15,23,42,.06)` | `0 1px 2px rgba(0,0,0,.50)` | 吸顶表头、sticky 工具条 |
| L2 | `0 4px 12px rgba(15,23,42,.10)` | `0 4px 12px rgba(0,0,0,.55)` | 下拉、Popover、Tooltip |
| L3 | `0 12px 32px rgba(15,23,42,.16)` | `0 12px 32px rgba(0,0,0,.65)` | 弹窗、抽屉 |

**栅格与宽度**：内容容器 `max-width: 1440px; padding: 0 24px;`（可用 1392px），12 列、gutter 16；卡片按 4/6/12 列跨。1280px 下主区实际 1024px，三张预设卡各约 331px。

**侧栏 208px**：`padding: 12px`，导航项宽 184px、高 36px、圆角 6；图标 16px + 间距 8px + 文字 14px；条目间距 2px；底部版本区 `padding: 12px`，12px/18 `text/tertiary`。

## 5. Ant Design 5 主题映射

深浅两套只替换调色板，组件覆写共用一份，避免两套主题漂移。

```ts
import { theme, type ThemeConfig } from 'antd';

const SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", "Yu Gothic UI", Meiryo, sans-serif';
const MONO = 'ui-monospace, "Cascadia Mono", "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace';

const P = {
  light: {
    app: '#EEF1F5', canvas: '#F6F8FA', surface: '#FFFFFF', raised: '#FFFFFF', hover: '#F1F5F9', selected: '#EAF0FD',
    borderSubtle: '#EEF1F5', border: '#DDE3EA', borderStrong: '#B6C2D1', borderControl: '#7F8DA0',
    textPrimary: '#0F172A', textSecondary: '#475569', textTertiary: '#64748B', textDisabled: '#94A3B8', textInverse: '#FFFFFF',
    brandFill: '#1D4ED8', brandText: '#1D4ED8', brandSoft: '#EAF0FD', focusRing: 'rgba(29, 78, 216, 0.35)',
    successBg: '#ECFDF3', successText: '#166534', warnBg: '#FFF7E6', warnText: '#92400E',
    dangerBg: '#FEF2F2', dangerText: '#B91C1C', infoBg: '#EEF4FF', infoText: '#1D4ED8',
    neutralBg: '#F1F5F9', neutralText: '#334155', blockedBg: '#FFF4E5', blockedText: '#92400E', mask: 'rgba(15, 23, 42, 0.45)',
    shadow1: '0 1px 2px rgba(15, 23, 42, 0.06)', shadow2: '0 4px 12px rgba(15, 23, 42, 0.10)',
  },
  dark: {
    app: '#0B0F16', canvas: '#10151D', surface: '#161C26', raised: '#1D2531', hover: '#1E2633', selected: '#17233A',
    borderSubtle: '#1C2532', border: '#232D3B', borderStrong: '#46566B', borderControl: '#62748A',
    textPrimary: '#E6EDF7', textSecondary: '#A7B4C6', textTertiary: '#8291A6', textDisabled: '#5C6B80', textInverse: '#FFFFFF',
    brandFill: '#2F6AD8', brandText: '#6D9BFF', brandSoft: '#17233A', focusRing: 'rgba(109, 155, 255, 0.45)',
    successBg: '#10251A', successText: '#6EE7A0', warnBg: '#2A2011', warnText: '#F0B96B',
    dangerBg: '#2C1518', dangerText: '#FCA5A5', infoBg: '#121E33', infoText: '#7FA9FF',
    neutralBg: '#1E2633', neutralText: '#A7B4C6', blockedBg: '#2B1D12', blockedText: '#E0A06A', mask: 'rgba(0, 0, 0, 0.55)',
    shadow1: '0 1px 2px rgba(0, 0, 0, 0.50)', shadow2: '0 4px 12px rgba(0, 0, 0, 0.55)',
  },
} as const;

type Palette = { [K in keyof typeof P.light]: string };

const baseToken = {
  fontFamily: SANS, fontFamilyCode: MONO, fontSize: 13, fontSizeSM: 12, fontSizeLG: 14, fontSizeXL: 16,
  fontSizeHeading1: 24, fontSizeHeading2: 20, fontSizeHeading3: 16, fontWeightStrong: 600,
  lineHeight: 1.54, lineHeightSM: 1.5, lineHeightLG: 1.57,
  lineHeightHeading1: 1.33, lineHeightHeading2: 1.4, lineHeightHeading3: 1.5,
  borderRadius: 6, borderRadiusSM: 4, borderRadiusLG: 8, borderRadiusXS: 2,
  controlHeight: 32, controlHeightSM: 28, controlHeightLG: 40, lineWidth: 1, lineWidthBold: 2, wireframe: false,
  motionDurationFast: '0.12s', motionDurationMid: '0.16s', motionDurationSlow: '0.24s', motionEaseInOut: 'cubic-bezier(0.2, 0, 0, 1)',
  padding: 16, paddingSM: 12, paddingXS: 8, paddingLG: 24, paddingXL: 32,
} as const;

const mapToken = (p: Palette) => ({
  colorPrimary: p.brandFill, colorInfo: p.brandFill, colorLink: p.brandText, colorSuccess: p.successText,
  colorWarning: p.warnText, colorError: p.dangerText, colorTextBase: p.textPrimary, colorBgBase: p.canvas,
  colorBgLayout: p.app, colorBgContainer: p.surface, colorBgElevated: p.raised, colorBgMask: p.mask,
  colorBorder: p.border, colorBorderSecondary: p.borderSubtle, colorSplit: p.borderSubtle, colorText: p.textPrimary,
  colorTextSecondary: p.textSecondary, colorTextTertiary: p.textTertiary, colorTextQuaternary: p.textDisabled,
  colorTextLightSolid: '#FFFFFF', colorFillSecondary: p.hover, colorFillTertiary: p.neutralBg, colorFillQuaternary: p.canvas,
  colorPrimaryBg: p.brandSoft, colorPrimaryBorder: p.brandSoft, colorPrimaryText: p.brandText,
  colorErrorBg: p.dangerBg, colorSuccessBg: p.successBg, colorWarningBg: p.warnBg,
  boxShadow: p.shadow2, boxShadowTertiary: p.shadow1,
});

const componentsOf = (p: Palette): NonNullable<ThemeConfig['components']> => ({
  Layout: { bodyBg: p.canvas, headerBg: p.surface, siderBg: p.surface, footerBg: p.canvas, headerHeight: 56,
    headerPadding: '0 24px', triggerBg: p.surface, triggerColor: p.textSecondary },
  Menu: { itemBg: 'transparent', subMenuItemBg: 'transparent', itemHeight: 36, itemLineHeight: '36px', iconSize: 16,
    itemMarginInline: 8, itemMarginBlock: 2, itemBorderRadius: 6, collapsedIconSize: 18, groupTitleFontSize: 11,
    itemColor: p.textSecondary, itemHoverColor: p.textPrimary, itemHoverBg: p.hover, itemActiveBg: p.brandSoft,
    itemSelectedColor: p.brandText, itemSelectedBg: p.brandSoft, groupTitleColor: p.textTertiary, dangerItemColor: p.dangerText },
  Table: { headerBg: p.hover, headerColor: p.textSecondary, headerSplitColor: 'transparent', headerBorderRadius: 0,
    borderColor: p.borderSubtle, rowHoverBg: p.hover, rowSelectedBg: p.brandSoft, rowSelectedHoverBg: p.selected,
    cellPaddingBlock: 10, cellPaddingInline: 12, cellPaddingBlockMD: 10, cellPaddingInlineMD: 12,
    cellPaddingBlockSM: 6, cellPaddingInlineSM: 8, footerBg: 'transparent', stickyScrollBarBg: p.border },
  Card: { headerBg: 'transparent', headerFontSize: 14, headerHeight: 44, headerHeightSM: 36, headerPadding: '0 16px',
    bodyPadding: 16, bodyPaddingSM: 12, extraColor: p.textSecondary },
  Tag: { defaultBg: p.neutralBg, defaultColor: p.neutralText },
  Button: { fontWeight: 500, defaultShadow: 'none', primaryShadow: 'none', dangerShadow: 'none', contentFontSize: 13,
    paddingInline: 12, onlyIconSize: 14, defaultBg: p.surface, defaultColor: p.textPrimary, defaultBorderColor: p.border,
    defaultHoverBg: p.hover, defaultHoverColor: p.textPrimary, defaultHoverBorderColor: p.borderStrong,
    defaultActiveBg: p.selected, defaultActiveBorderColor: p.brandFill },
  Input: { paddingBlock: 4, paddingInline: 8, inputFontSize: 13, addonBg: p.hover, hoverBorderColor: p.borderStrong,
    activeBorderColor: p.brandFill, activeShadow: `0 0 0 3px ${p.focusRing}`, errorActiveShadow: '0 0 0 3px rgba(185, 28, 28, 0.14)' },
  Progress: { defaultColor: p.brandFill, remainingColor: p.neutralBg, lineBorderRadius: 2 },
  Descriptions: { labelBg: p.hover, titleColor: p.textPrimary, contentColor: p.textPrimary, titleMarginBottom: 12,
    itemPaddingBottom: 12, colonMarginRight: 8, colonMarginLeft: 0 },
  Tabs: { itemColor: p.textSecondary, itemHoverColor: p.textPrimary, itemSelectedColor: p.brandText, inkBarColor: p.brandFill,
    titleFontSize: 13, horizontalItemGutter: 24, horizontalItemPadding: '10px 0', horizontalMargin: '0 0 16px 0' },
  Timeline: { tailColor: p.border, dotBg: p.surface, dotBorderWidth: 2, itemPaddingBottom: 20 },
});

const makeTheme = (p: Palette, algorithm: ThemeConfig['algorithm']): ThemeConfig =>
  ({ algorithm, token: { ...baseToken, ...mapToken(p) }, components: componentsOf(p) });

export const lightTheme = makeTheme(P.light, theme.defaultAlgorithm);
export const darkTheme = makeTheme(P.dark, theme.darkAlgorithm);
```

- **不要改**：`fontSize` 不改到 12（表格会挤）、`borderRadius` 不超过 8、`wireframe` 不开、`motion` 不整体关闭（会杀掉焦点与展开反馈）、`colorBgMask` 遮罩不高于 0.6、`colorTextTertiary` 不调浅到 4.5:1 以下、不删 `:focus-visible` 轮廓、不给 `Table`/`Card` 加默认阴影、不改 `colorError` 用作装饰。
- **版本与未映射项**：若锁定的 antd 版本无 `bodyPadding`/`headerPadding`/`stickyScrollBarBg`，用 `styles.body` 或删除该键，其余均为 5.x 稳定 token；未映射到 antd 的 `blocked*`/`info*` 供 StatusTag 与告警条取用，`borderControl` 用于必须靠边界识别的控件（复选框、分段控件），`textInverse` 用于主按钮文字，均不要删。

## 6. 布局规范

**顶栏 56px**，左起顺序固定：产品名“字幕流水线”（14/600）→ 8px → 连接状态（8px 圆点 + 12px 文案：已连接/重连中/已断开）→ 16px → 1px 竖分隔（高 16）→ 16px → “更新于 23:58:12”（12px `text/tertiary`，tabular-nums）→ 8px → 鉴权模式 Tag（12px：“Token 已启用” / “无鉴权”，后者用 `warn` 色）。右侧依次：刷新图标按钮（32×32）→ 8px → “新建作业”主按钮 → 8px → 更多菜单（Token 模式为退出/清除本机 Token）。

**侧栏 208px**：不重复产品名（顶栏已有），顶部 `padding-top: 12px` 直接进入导航；6 项顺序与 SPEC §3.1 一致；选中态 = `bg/selected` + `brand/text` 文字与图标 + 左侧 2px `brand/fill` 指示条（与条目同高，圆角 2）；hover 只换底色，不移动、不放大。底部固定“v0.5.0 · 本机部署”，12px/18 `text/tertiary`。

**页面标题区**（总高 74 = 上 8 + 面包屑 18 + 间距 8 + 标题行 32 + 下 8）：面包屑 12px/18 `text/tertiary`（最后一节 `text/secondary`，不可点）→ 8px → 标题行：标题 20/28/600 + 12px 间距 + 状态 Tag（若有）+ 弹性空隙 + 操作区（按钮高 32，间距 8，主操作最右）。标题区与首个卡片间距 16；卡片之间 16；区块之间 24；内容 `padding: 24px`（≤1023px 为 16），底部额外 32px；表格页不套双层卡片，只保留一层 surface。

**标签页**：位于详情主卡片内，tab 头 44px，`sticky top: 0`，底色 `surface` + 1px 下边框；URL 记录当前 tab；未交付 tab 不隐藏，点开显示“未交付说明”空态。

## 7. 核心组件模式

### 7.1 StatusTag

高 22、`padding: 0 8`、圆角 4、字号 12/18/500、图标 12、图标与文字间距 4；不加边框（neutral 可加 1px `border/subtle`）。同一行内多个 Tag 间距 6。**Tag 内文字不得换行**，超长用 `…` 并在 `title` 给全文。

### 7.2 StageCard（阶段卡）

`padding: 16`、圆角 8、1px `border/default`、`bg/surface`、`min-height: 152`；三卡按 `grid-template-columns: repeat(auto-fit, minmax(280px, 1fr))`、间距 16。内部顺序：

1. 序号 chip（20×20，12px mono，`bg/hover`，圆角 4）+ 阶段中文名 14/500 + 右侧 StatusTag。
2. 元信息行（12/18 `text/tertiary`，`·` 分隔）：`attempt 1/2`、`worker w-3`、`耗时 12m 06s`；无值显示 `—`，**不显示 0**。
3. 进度区：6px 轨道 + 12px 说明 `本阶段 42% · 更新 23:58:12`。
4. 陈旧提示（仅 stale）：`WarningOutlined` + 12px `warn/text`，文案“进度 3 分钟未更新，任务仍为运行中”，不改变 Tag 与卡片底色。
5. 错误摘要（仅 failed）：12px `danger/text`，最多 2 行后 `展开`；错误码用 mono；附 `request_id` 复制按钮。
6. blocked：卡片左侧 2px `blocked/text` 竖条 + 文案“被上游「语音识别」阻断”，不显示本阶段的假进度与假耗时。

状态矩阵：`queued`（虚线轨道 + “尚未开始”）→ `running`（实心进度 + 时间）→ `succeeded`（进度替换为“已完成 · 12m 06s”，不再显示百分比）→ `failed`（进度条置灰保留最后值 + 错误摘要）→ `blocked`（无进度，显示阻断源）。

### 7.3 阶段进度条（不等于整片完成率）

- 顶部 **StageRail**：3 段 2px 高、段间 4px；已完成段 `text/secondary`，当前段 `brand/fill`，未来段 `border/default`；右侧 12px “已完成 2/3 阶段”。这是“阶段计数”，不是百分比。
- 当前阶段条：6px 高、圆角 2、无条纹、无渐变、无动画填充；文案固定为“**本阶段** 42%”，不与整片混用词。
- `percent == null` → 6px 虚线轨道 + “暂无进度”；`percent >= 100` 但状态非终态 → 显示“进度已满，等待状态确认”，不显示为成功。
- 陈旧时保留最后数值，仅在文本后追加“（3 分钟未更新）”，不重绘动画。
- **禁止**：把三阶段加权成一条总进度、显示 ETA、“预计剩余”。

### 7.4 数据表

| 项 | 规格 |
|---|---|
| 工具条 | 高 40，左：搜索框 240（含清除）、筛选下拉 160/120、已选筛选 chips；右：密度切换、列设置、刷新图标；与表格间距 12 |
| 表头 | 高 40，13px/500 `text/secondary`，`bg/hover`，无竖向分隔线；排序箭头 10px，单列排序 |
| 行 | 默认 40（`size="middle"`，cellPaddingBlockMD 10）；紧凑 36（`size="small"`）；`hover` 仅换底色，不位移 |
| 对齐/列宽 | 文本左对齐；数字/耗时/计数右对齐 + tabular-nums；操作列右对齐宽 120；状态 96、ASR 72、时间 168；文件名列 `min-width: 240`，中间省略保留扩展名 |
| 分页 | 高 56，左侧“共 128 条”，右侧页码 + `20/50/100`；切页保留筛选与排序 |
| 空表 | 保留表头，表体高 120：图标 32 + 标题 14/500 + 说明 12/18 + 一个主操作 |
| 加载 | 首次加载：5 行骨架（行高 40，1.4s 微光）；翻页：仅表格 `loading` 遮罩；**轮询：不显示任何 loading** |
| 错误 | 表内 44px 告警条（`danger/bg`）+ 重试；保留上次数据并在表头右侧标“数据可能过期” |
| 行内操作 | 文字按钮 13px，最多 3 个，其余进“更多”；禁用项必须给原因（`title` 或行内说明） |

### 7.5 三预置单选卡

三列（≥1024），`padding: 16`、`min-height: 148`、圆角 8、整卡可点，语义为 `role="radio"` + `aria-checked`，方向键切换。

- 默认 1px `border/default` + `bg/surface`；hover 换成 `border/strong`、底色不变、120ms，不加阴影、不上浮。
- 选中：1px `brand/fill` + `box-shadow: 0 0 0 1px #1D4ED8`（形成 2px 视觉边）+ 右上角 16px 实心勾选圆点；文字不变色。
- 不可用：`bg/canvas`、文字 `text/secondary`、右上角“不可用”Tag（neutral）+ 12px 原因（如“缺少 Qwen3 模型目录”）；仍可聚焦阅读，`aria-disabled="true"`，点击不选中但显示原因；**不隐藏、不排序**。
- 内容顺序：名称 14/600 + preset_id（12 mono `text/tertiary`）→ 阶段链 3 个 12px chip（`extract` → `stt` → `translate`，箭头 `text/tertiary`）→ 简述 12/18 两行 → 底部可用性一行。

### 7.6 媒体目录选择弹窗

- 弹窗 880×640（视口不足时 92vw/88vh），`padding: 0`，头部 56（标题“选择影片” + 关闭），底部 64；工具条 48：媒体根下拉 200 + 面包屑（flex，逐段可点）+ 返回上级 32×32（根目录禁用）+ 刷新 32×32 + 右侧文件名筛选 200。
- 列表行高 40：类型图标 16（目录 `FolderOutlined` / 视频 `VideoCameraOutlined`）+ 名称（flex，省略）+ 大小/修改时间（12 mono tabular，右对齐）+ 勾选框 16；目录行整行可点进入，视频行单击勾选、双击确认单片。
- 底部：左“已选 1 个 · `SAN-484-U.mp4`”（12，文件名 mono，超出省略，`title` 全文）；右“取消 / 确认选择”（确认在主操作位，选中 0 个时禁用）。
- 状态：加载中保留面包屑与工具条，仅列表区 8 行骨架；空目录/无匹配/根离线/权限不足各自独立文案 + 刷新；`skipped_count > 0` 显示“已跳过 3 个隐藏或越界项”，不显示具体路径。

### 7.7 Token 验证页

居中卡片宽 400、`padding: 32`、圆角 8、1px 边框、无阴影、无插图；标题 20/28/600“访问验证”，说明 13/20 `text/secondary` 两行（不透露 Token 规则细节）；输入框高 40、`type=password`、右侧显隐图标 16；主按钮 block 高 40“验证并进入”；错误时输入框下方 12px `danger/text` + `CloseCircleFilled`，文案“Token 无效”，**不清空输入、不抖动、不回显**。页面背景 `bg/canvas`，卡片垂直居中偏上（`padding-top: 12vh`）。

### 7.8 空态 / 错误态 / 离线态 / 陈旧态

| 态 | 标题 | 说明 | 操作 | 视觉 |
|---|---|---|---|---|
| 空态 | 还没有作业 | 提交第一部影片后，进度会显示在这里。 | 新建作业（主） | 图标 32 `text/disabled`，居中，块高 160 |
| 错误态 | 加载失败 | 服务返回错误，请稍后重试。`request_id` 可复制。 | 重试（默认）+ 查看系统状态（链接） | 保留页面框架；块内 `danger/bg` 48px 条或整块空态 |
| 离线态 | 连接已断开 | 正在重试（第 3 次）· 最后更新 12:03:11。 | 立即重试 | 顶栏下 32px 琥珀条；数据保留不灰化，仅时间戳变琥珀 |
| 陈旧态 | 数据可能过期 | 该区块 2 分钟未更新，状态可能已变化。 | 刷新 | 区块标题右侧 12px `warn/text` + `HistoryOutlined`，不覆盖内容 |

`M1` 未交付的日志/字幕 tab 使用空态变体：标题“日志尚未交付”，说明“M1 仅提供状态与阶段信息，M2 开放脱敏日志。”，操作位留空或“查看系统状态”。

### 7.9 告警条

- **就绪失败**：`warn/bg`、左侧 3px `warn/text`、`padding: 8 12`、圆角 6；标题 13/500 + 原因（mono 12）+ “查看系统状态”链接；不可自动消失。
- **无鉴权风险**：`warn/bg` 常驻顶栏下方，文案“当前未启用鉴权：所有可访问者均可操作与提交作业。”；可折叠为图标但不可永久关闭（刷新后恢复）。
- 页面内同时最多 1 条常驻告警；多条合并为“3 项需要注意”展开，不堆叠彩色条。

## 8. 动效与反馈

- 时长：hover 120ms、focus/press 160ms、下拉/气泡 200ms、抽屉/弹窗 240ms；缓动 `cubic-bezier(0.2, 0, 0, 1)` 进入、`cubic-bezier(0.4, 0, 1, 1)` 退出。
- **轮询不闪烁**：`keepPreviousData` 保留上一帧，到达后原位替换文本；不重建行 key、不加淡入/高亮闪烁、不改表格高度（固定列宽 + 省略号）；刷新反馈只体现在“更新于 hh:mm:ss”与 StatusTag 的 120ms 颜色过渡，不做缩放、位移、弹跳。
- Skeleton 仅在首屏或进入未见过的路由时出现（延迟 200ms 再显示，避免快速请求闪一下）；翻页用遮罩，轮询不用任何占位。
- **禁止**：数字滚动计数、表格行 flash、进度条呼吸/流光、骨架屏无限闪、鼠标跟随、入场位移超过 8px、超过 240ms 的列表动画、操作成功 toast 打断阅读（成功用行内状态变化表达）。
- `prefers-reduced-motion: reduce`：所有时长降为 0.01ms，停用旋转图标（改用静态 `SyncOutlined` + “运行中”文字）、停用骨架微光与所有位移。

## 9. 响应式

| 断点 | 侧栏 | 内容 padding | 表格 | 预设/阶段卡 | 顶栏 |
|---|---|---|---|---|---|
| ≥1280 | 208 固定 | 24 | 全列，不横向滚动 | 3 列 / 3 列 | 56，完整信息 |
| 1024–1279 | 208 固定（可手动折叠 64） | 24 | 隐藏“创建时间”，必要时 `scroll.x = 1100` | 3 列（min 220）/ 3 列 | 56，完整信息 |
| 768–1023 | 64 图标栏 + Tooltip | 16 | `scroll.x = 980`，状态列固定左侧 | 2 列 / 2 列 | 56，鉴权模式只留图标 |
| <768（375 基准） | 抽屉 280，汉堡触发 | 16 | `scroll.x = 960`，首列 sticky | 1 列 / 1 列 | 48，主操作变图标按钮 |

- 768 以下不缩小字号（仍 13px 正文），靠单列与横向滚动保可读性；触控目标 ≥40×40。
- 详情页 tab 在 <768 横向滚动，不折叠成下拉；KPI 卡 ≥1024 四列、768–1023 两列、<768 两列（数值 20px）。
- 任何断点都必须能完成：选片 → 提交 → 查状态 → 下载字幕；横向滚动容器不得吞掉页面纵向滚动。

## 10. 可访问性

- 焦点环：`outline: 2px solid #1D4ED8; outline-offset: 2px`（深色 `#6D9BFF`），仅 `:focus-visible` 生效；不用纯 `box-shadow` 替代（高对比模式下会丢失）。
- 键盘：Tab 顺序 顶栏 → 侧栏 → 页面标题操作 → 内容 → 分页；首元素提供“跳到主内容”链接（聚焦时可见）；表格行内操作可用 Tab 到达，方向键在预设卡 radio 组内切换；触控目标桌面 ≥32×32、<768 ≥40×40，图标按钮必须有 `aria-label`。
- 表单：`label` 必须 `htmlFor` 关联；必填 `aria-required`；错误 `aria-describedby` + `role="alert"`；提交失败聚焦首个错误字段并滚动到可视区。
- 状态三重冗余：文字 + 图标形状（圆/三角/叉/暂停/横线）+ 颜色；灰度或色盲模拟下仍可区分（不得只靠红绿）。
- `aria-live="polite"` 只用于“连接断开/恢复”和“作业状态进入终态”；轮询时间戳不加 live，避免读屏刷屏。
- 表格：`<caption class="sr-only">` 说明数据范围；`scope="col"`；排序列 `aria-sort`；空表与错误用 `role="status"`。

## 11. Do / Don't

**Do**

1. 用留白、1px 分隔线与字号层级建立秩序，而不是靠阴影和色块。
2. 每个状态都写“文字 + 图标 + 底色”，颜色只作第三重冗余。
3. 数字列右对齐并开 `tabular-nums`，时间统一 `HH:mm:ss`（跨天带日期）。
4. 没有进度就写“暂无进度”，宁可空着也不填 0% 或 100%。
5. 品牌色只出现在主操作、选中态、链接、当前阶段进度四处。
6. 长路径与 ID 用等宽字体 + 中间省略 + 复制按钮，不依赖 hover 才可见。
7. 轮询静默替换数据，旧数据保留到新数据到达，并显示最后刷新时间。
8. 深色模式单独校色，逐项复核对比度，不靠反色或 CSS filter。

**Don't**

1. 不用渐变、玻璃拟态、彩色光晕、大面积品牌色背景。
2. 不给表格同时上斑马纹、悬停底色、选中底色和重边框。
3. 阴影不超过 3 级；卡片默认无阴影，只用 1px 边框。
4. 不用颜色单独表达状态，也不用 emoji 充当状态图标。
5. 不做数字滚动、进度条呼吸、列表项入场位移、骨架无限闪烁。
6. 不在轮询或翻页时用骨架屏覆盖已有数据。
7. 不把 `danger` 用于普通提示；红色只给失败与破坏性确认。
8. 不为了“好看”新增 SPEC 没有的按钮、表单或图表。

## 12. 落地清单

- [ ] 全局注入 §5 的 `lightTheme` / `darkTheme`，`ConfigProvider` 包住路由与 `App` 组件。
- [ ] 把 §2 的 hex 收敛为 `src/styles/tokens.ts` 单一导出，组件不写裸色值。
- [ ] `PageHeader` 统一面包屑 + 标题 + 状态 + 操作区，顶栏连接状态与“更新于”由真实数据驱动。
- [ ] `StatusTag` 支持 7 种状态，文案与图标按 §2.4 固定，禁止调用方自传颜色。
- [ ] `StageCard` 覆盖 queued/running/succeeded/failed/blocked 五态与 stale 提示。
- [ ] `StageRail` 与“本阶段进度”分离，代码中不出现“总进度”字段。
- [ ] 表格首次加载骨架、翻页遮罩、轮询零 loading，三种加载态分别实现。
- [ ] 就绪失败与无鉴权风险两条告警条接入布局层，不可被页面覆盖。
- [ ] 焦点环、跳转链接、`aria-sort`、`aria-live` 按 §10 补齐并通过键盘走查。
- [ ] `prefers-reduced-motion` 分支在全局样式中实现并手测。
- [ ] 1280/1024/768/375 四档截图走查，确认表格可横向滚动且纵向不被劫持。
- [ ] 浅色与深色各跑一遍对比度脚本，正文与 12px 标签 ≥4.5:1 全部通过。

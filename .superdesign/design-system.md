# FinanceAgent — Technical Minimalist Design System

## Product Context

FinanceAgent 是中文金融智能投顾工作台。核心任务包括自然语言投顾对话、行情与基本面分析、股票推荐、资产配置、用户风险画像和历史会话管理。主要页面是登录/注册页和登录后的单页投顾工作台。

## Visual Direction

主风格为 Technical Minimalist：高端金融机构的可信感与 AI 数据工作台的结构感结合。使用明确网格、1px hairline、充足留白和扁平色块。禁止厚重阴影、玻璃拟态、霓虹、高饱和渐变、装饰性插画和 emoji。

## Color Tokens

- Paper / page background: `#F7F7F5`
- Surface: `#FFFFFF`
- Forest / primary: `#1A3C2B`
- Forest hover: `#24533B`
- Ink / main text: `#202320`
- Secondary text: `#62665F`
- Muted text: `#8A8F87`
- Grid / borders: `rgba(58, 58, 56, 0.20)`
- Coral / risk and attention: `#FF8C69`
- Mint / success: `#9EFFBF`
- Gold / financial highlight: `#F4D35E`
- Error: `#B74432`

## Typography

- Chinese UI and body: `PingFang SC`, `Microsoft YaHei`, system sans-serif.
- English headings: Space Grotesk-like geometric sans; fall back to system sans.
- Labels, status, stock codes and metadata: JetBrains Mono-like monospace; fall back to `SFMono-Regular`, `Consolas`, monospace.
- Page/title weight 700; panel title 600; body 400–500.
- Metadata uses 10–12px, uppercase where English, letter-spacing `0.08em`.

## Structure and Spacing

- Base spacing scale: 4, 8, 12, 16, 24, 32px.
- Desktop header: 60–64px.
- Main workspace: conversation 68–72%, intelligence sidebar 28–32%.
- Use 1px dividers and grid gaps instead of floating-card shadows.
- Component radius: 0px or 2px; form controls may use 4px for usability.
- No box shadow by default; drawers may use one subtle directional shadow.

## Components

- Brand mark: 32–36px square Forest block with a white ¥ symbol.
- Buttons: square/2px radius, 1px border; primary uses Forest fill and white text.
- Status badge: 1px border, 8px square status dot, monospace 10px label.
- Panels: Paper/white surface, 1px border, section title separated by hairline.
- Message bubbles: retain role distinction but avoid rounded chat-app styling; assistant uses white/paper with left marker, user uses Forest with white text.
- Form fields: white fill, 1px border, labels above fields, visible Forest focus outline.
- Data tags: monospace, 1px border, flat background using Mint/Gold/Coral at low opacity.

## Motion

- Interaction duration 140–220ms.
- Use standard ease-out; progress spinner may remain linear.
- Drawer uses 240ms transform.
- Avoid floating, parallax and decorative infinite animations.

## Responsive Rules

- At `768px`, intelligence sidebar becomes the existing right drawer and chat fills width.
- At `480px`, login page becomes one column and reduces decorative/secondary content.
- Keep touch targets at least 40px and preserve input/send actions above mobile viewport controls.

## Fidelity Constraints

Use ONLY the fonts, colors, spacing, and component styles defined here. Do not introduce additional fonts, colors, gradients, rounded-pill card systems, or unrelated visual styles. Preserve all existing user flows, Chinese labels, Element Plus icon semantics, and API-driven UI states.

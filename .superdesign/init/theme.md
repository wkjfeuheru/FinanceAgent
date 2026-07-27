# 主题

## 紧凑 Token 摘要

- 主色：`#1e3a8a`；亮主色：`#3b5bdb`；柔和主色：`#dbeafe`
- 强调色：`#fbbf24`
- 页面背景：`#f5f7fb`；表面：`#ffffff`；次表面：`#f8fafc`
- 边框：`#e2e8f0`
- 主文本：`#1e293b`；次文本：`#64748b`；弱文本：`#94a3b8`
- 成功：`#10b981`；危险：`#ef4444`
- 中文字体：PingFang SC、Microsoft YaHei、Hiragino Sans GB
- 圆角：8px / 12px / 16px
- 卡片阴影：`0 1px 3px rgba(15,23,42,.06), 0 1px 2px rgba(15,23,42,.04)`
- 浮层阴影：`0 10px 25px -5px rgba(15,23,42,.1)`
- 响应断点：768px；登录卡补充断点 480px

## 原始全局变量

```css
:root {
  --color-primary: #1e3a8a;
  --color-primary-light: #3b5bdb;
  --color-primary-soft: #dbeafe;
  --color-accent: #fbbf24;
  --color-bg: #f5f7fb;
  --color-surface: #ffffff;
  --color-surface-alt: #f8fafc;
  --color-border: #e2e8f0;
  --color-text: #1e293b;
  --color-text-secondary: #64748b;
  --color-text-muted: #94a3b8;
  --color-success: #10b981;
  --color-danger: #ef4444;
  --color-user-bubble: #1e3a8a;
  --color-assistant-bubble: #f1f5f9;
  --shadow-card: 0 1px 3px rgba(15,23,42,.06), 0 1px 2px rgba(15,23,42,.04);
  --shadow-elevated: 0 10px 25px -5px rgba(15,23,42,.1), 0 8px 10px -6px rgba(15,23,42,.05);
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --el-color-primary: #1e3a8a;
  --el-border-radius-base: 8px;
}
```

完整原始样式：`frontend/src/style.css`，组件 scoped CSS 位于各 `.vue` 文件。

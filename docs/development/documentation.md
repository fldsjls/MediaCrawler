# 文档维护

> 文档类型：文档开发契约；保留 VitePress。

README 定位和启动，docs 长期说明。新增页面进入 getting-started、guides、architecture、development、operations、history、adr 或 about；未来目标进入 roadmap。

每区有 index.md 并列直接子页。架构保存职责，指南保存操作，ADR 保存决策，history 必须带日期和范围。旧数字不因搬迁变成当前事实。

移动页面更新内部链接；必要的旧网址集中记录在 `.vitepress/redirects.json`，构建时生成跳转 HTML，不保留占位 Markdown。上游 CLI、存储、作者、许可、推广分类保留，推广不进主导航。本站移除上游 GA 和错误编辑链接。

```powershell
npm run docs:check
npm run docs:build
npm run docs:dev
```

`check-docs.mjs` 检查分区、索引可达性、迁移、内部链接和导航边界。build 先检查再构建，不能忽略死链。开发与预览只绑定回环地址；部署子路径用 `DOCS_BASE` 明确指定。

主题保留深浅切换、本地搜索、手机导航和键盘行为。信息架构决策见 [ADR 0001](../adr/0001-documentation-architecture.md)。

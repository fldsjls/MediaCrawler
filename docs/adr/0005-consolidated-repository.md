# ADR 0005：集中源码与本机文件

> 状态：已接受
> 日期：2026-09-07

原根目录同时包含采集源码、前端、worker、数据库文件和构建结果；重复的测试目录和文档迁移占位页进一步增加噪音。

采用 `src/mediacrawler`、`src/webui`、`src/browser-worker` 作为源码入口。脚本按 setup、runtime、build、validation、maintenance 分类，测试统一到 tests。本机文件位于 `.local`，可重新构建的产物位于 `.build`。

沿用 Office_Portal 的职责判断和文档分层，继续使用 FastAPI、React、Node 与 VitePress。通过正式 Python 包和明确资源路径解除工作目录依赖。

本文替代 ADR 0001 中“旧路径保留 Markdown 提示页”的决策：旧网址集中记录在 `.vitepress/redirects.json`，发布构建生成跳转 HTML；正文只维护一个位置。历史记录仍保留原时点路径与验证边界。

目录移动必须同时修改导入、子进程、脚本、构建、测试和当前文档。迁移不得丢失任务索引、媒体、已有会话资料或来源许可证。

见[目录契约](../architecture/repository-layout.md)和[文档维护](../development/documentation.md)。

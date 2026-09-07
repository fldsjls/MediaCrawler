# 开发与扩展约定

先读[职责边界](/architecture/layer-boundaries.md)，再选择改动位置。一个模块被两个调用方使用，不自动意味着它应成为公共平台；只有共享稳定机制时才抽取，平台规则仍归适配器。

## 当前目录

```text
api/workbench/
  platforms/         catalog、registry、contracts：类型、定义、注册和扩展契约
  adapters/          平台专属媒体解析与原存储接入
  media/             capture、identity、downloader：候选、身份和传输
  preview/           native 原生捕获信令、native_sender 浏览器 RTC、internal 辅助页边界
                     viewport 物理内容区对齐、frames 单生产者低刷 JPEG、cdp 画面通道
                     rtc 保留旧转码回归
  settings.py        浏览器默认值、严格校验与 SQLite 保存
  settings_router.py 设置入口，使用 Repository provider
  router.py          对外 HTTP / WebSocket
  service.py         任务和下载调度
  repository.py      SQLite 与任务目录
  models.py          请求、状态和兼容模型
  browser.py         会话、页面、画面与输入
  runtime.py         worker 操作屏障与事件
  platform_worker.py 原生平台执行入口
  template_worker.py 声明式网站模板执行入口
  migration.py       显式数据/Profile 导入
  compat.py          原 API 兼容桥
webui/src/workbench/ React 页面、配置、平台管理、工作区和结果
  SettingsCenter.tsx 分类、子项、详情与设置动作
  useBrowserPresentation.ts RTC / JPEG 切换、清理与降级
media_platform/      上游平台发现、登录、详情与评论
store/               上游内容字段、脱敏与存储
workers/browser-capture/
  src/workbench/     内部 Node 入口与协议
  src/sites/         迁入课程及历史网页采集
scripts/             统一安装、启动、环境和工具校验
tests/               本地样本、协议、真实本地浏览器和流程测试
```

## 新增网站还是新增适配器

入口、标签和 DOM 视频配置可以描述的网站，使用 registry 新建配置，不修改 React 分支。需要原生搜索、登录检测、章节结构或商品字段的网站，需要适配器实现和相应测试，然后声明真实能力。

内置定义在 `catalog.py` 维护。模板字段也在 catalog 声明，由 registry 校验。模板实现进入 worker；不要让配置携带可执行代码。未来适配器可采用 `WebsiteAdapter` 的发现、读取内容、解析资源契约，但此协议本身不是自动执行器。

每个新能力同时检查：输入模式是否可执行、登录是否可恢复、数量是否有界、内容是否即时保存、资源是否属于当前内容、无资源是否可区分失败。未实现的组合不进入能力列表。

## worker 事件与媒体契约

worker 通过 JSON 行发送 `record`、`resource`、`phase`、`state`、`failure`、`done` 等结构化事件。普通日志不能作为状态协议。浏览器操作和 API 请求经过 Runtime 屏障，接管确认前必须等待当前自动操作结束，恢复时重新检查登录与目标。

公共内容统一身份、来源、标题、父子关系、采集时间与资源关联，平台专属字段保留在 `fields`。原始响应只在平台解析上下文短暂持有，保存仍走原脱敏流程。

资源的内部结构示例：

```json
{
  "kind": "video",
  "url": "https://example.com/video-track",
  "streams": [
    {"url": "https://example.com/video-track", "role": "video"},
    {"url": "https://example.com/audio-track", "role": "audio"}
  ],
  "format": "dash",
  "quality": "1080p",
  "height": 1080,
  "width": 1920,
  "parent_id": "content:42",
  "title": "示例视频",
  "page_url": "https://example.com/content/42",
  "source": "example",
  "origin": "adapter",
  "key": "example:42:video:0",
  "headers": {"Referer": "https://example.com/content/42"}
}
```

`kind` 区分视频和图片；分段用 `role: "segment"`，多个清晰度只选择当前可取得的最高一档。稳定 key 表示逻辑资源，不能直接使用会变化的签名 URL。适配器请求头只传允许的 Referer / User-Agent，不把 Cookie 或授权字段写入公开事件。

同页网络请求只是候选证据，不能据此绑定最后一条内容。浏览器后备只读取明确当前内容容器内的 video 或播放控件；模糊归属交由会话捕获列表手选。传输和清单解析进入 media 模块，平台语义留在 adapters。

## React 与公共布局

`Workbench` 组合页面和服务数据；`ConfigurationPanel`、`PlatformManager` 解释平台能力和保存动作；`Workspace` 只处理标签、平铺、比例与最大化；`BrowserPanel` 处理会话展示和用户操作；`ResultsPanel` 展示结果与选择。

主题、间距、边框、折叠、焦点和 ARIA 属于展示机制。共享组件接受明确字段和回调，不按平台名称猜测能力，不直接操作数据库或启动下载。成功反馈不挤压工作区；需要处理的错误使用可关闭且能恢复焦点的对话框。

## 检查命令

在项目根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check-workbench.ps1
.venv\Scripts\python.exe -m pytest tests/test_workbench_media_adapters.py tests/test_workbench_media_node.py -q
npm --prefix workers/browser-capture run check
npm --prefix webui run build
npm run docs:build
```

根据改动选择有意义的流程回归；文档构建通过只证明站点可构建和链接可解析，不证明 API、真实网站或界面已经验收。验收边界见[验证文档](/history/2026-09-07-platform-media-validation.md)。

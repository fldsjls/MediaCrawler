# 开发与扩展约定

先读[职责边界](/architecture/layer-boundaries.md)，再选择改动位置。一个模块被两个调用方使用，不自动意味着它应成为公共平台；只有共享稳定机制时才抽取，平台规则仍归适配器。

## 当前目录

```text
src/mediacrawler/workbench/
  workflows/     models、rules、engine、service、runtime：契约、规则与统一调度
  settings/      默认值、继承解析与工具设置接口
  browser/       会话、capture 资源监听、preview 画面和输入
  downloads/     HTTP、FFmpeg、N_m3u8DL-RE 和 URL 范围传输
  results/       产物索引、导出和分页预览
  persistence/   repository SQLite 与 migration 显式资料导入
  platforms/     catalog、registry、contracts、适配器与 worker
  router.py      HTTP / WebSocket 边界组合
  compat.py      旧 API 接入同一服务
src/webui/src/workbench/
  workflows/     方案、窄栏卡片和弹窗
  runs/          运行中心和详情抽屉
  browser/       网站预览及画面生命周期
  results/       发现资源与共用产物预览
  settings/      分类和详细默认值
  shared/        弹窗、焦点与溢出提示
src/mediacrawler/platforms/ 上游平台采集实现
src/mediacrawler/storage/stores/ 上游存储
src/browser-worker/        课程和通用网页执行器，沿用原入口
scripts/                   安装、启动、构建、校验及维护
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

同页网络请求只是候选证据，不能据此绑定最后一条内容。浏览器后备只读取明确当前内容容器内的 video 或播放控件；模糊归属交由会话捕获列表手选。传输和清单解析进入 downloads，平台语义留在 platforms/adapters。

## React 与公共布局

`Workbench` 组合页面和服务数据；`WorkflowPanel` 使用后端方案校验与可用卡片，`PlatformManager` 负责平台保存动作；`Workspace` 只处理标签、平铺、比例与最大化；`BrowserPanel` 处理会话展示和用户操作；`DiscoveryPanel` 与 `Artifacts` 分别展示发现资源和运行产物。

主题、间距、边框、折叠、焦点和 ARIA 属于展示机制。共享组件接受明确字段和回调，不按平台名称猜测能力，不直接操作数据库或启动下载。成功反馈不挤压工作区；需要处理的错误使用可关闭且能恢复焦点的对话框。

## 检查命令

在项目根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\validation\check-workbench.ps1
.venv\Scripts\python.exe -m pytest tests/test_workbench_media_adapters.py tests/test_workbench_media_node.py -q
npm --prefix src/browser-worker run check
npm --prefix src/webui run build
npm run docs:build
```

根据改动选择有意义的流程回归；文档构建通过只证明站点可构建和链接可解析，不证明 API、真实网站或界面已经验收。验收边界见[验证文档](/history/2026-09-07-platform-media-validation.md)。

新增步骤先在 workflows 声明输入、输出、覆盖字段和执行器，再由 rules 开放；没有执行器不开放卡片。所有新增参数必须在设置中定义默认值与生效范围，不能只做可点击但未接入执行器的控件。

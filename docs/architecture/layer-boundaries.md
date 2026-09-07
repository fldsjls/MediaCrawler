# 架构与职责边界

> 当前架构契约；核对日期：2026-09-07。代码依据为 `src/mediacrawler/workbench`、`src/webui/src/workbench`、`src/mediacrawler/platforms`、`src/mediacrawler/storage/stores` 与 `src/browser-worker`。

本工作台采用 Office_Portal 文档中的职责判断方式：分别确定数据、规则、页面、文件的 owner，并规定依赖方向。这里沿用 MediaCrawler 的 FastAPI、React 与 worker 结构，不引入 Django 的应用目录或模型体系。

## 职责矩阵

| 归属 | 源码 owner | 负责 | 不应承担 |
| --- | --- | --- | --- |
| 平台定义和类型 | `platforms/catalog.py` | 内置网站、类型、模板和声明的能力 | 浏览器操作、任务状态、页面布局 |
| 自定义平台 | `platforms/registry.py` | 配置校验、注册、禁用和能力描述 | 执行用户脚本、推断未实现的采集能力 |
| 扩展契约 | `platforms/contracts.py` | 适配接口、商品及价格观察的数据契约 | 价格抓取、价格比较执行器或页面 |
| 请求模型 | `models.py` | 任务、会话、控制字段和兼容校验 | SQL、文件下载、浏览器控制 |
| 任务用例与状态 | `service.py` | 排队、控制、worker 生命周期、资源入队、结果汇总 | 平台响应字段解析、平台特有登录规则 |
| 数据持久化 | `repository.py` | SQLite 任务、事件、内容、文件索引及任务目录定位 | 界面文案、平台采集判断 |
| HTTP / WebSocket | `router.py` | 请求和响应边界、会话身份、公开字段裁剪 | 复制状态机、直接运行爬虫逻辑 |
| 浏览器会话 | `browser.py` | Chromium 所有权、页面列表、预览、输入、进程清理 | 判断视频属于哪条平台内容、采集价格规则 |
| 实时画面传输 | `preview/native.py`、`preview/native_sender.js` | 原生标签页捕获、CaptureHandle 身份、RTC 信令及释放 | 接管许可、平台内容规则、任务或下载凭据 |
| 捕获视口 | `preview/viewport.py` | 实测物理内容区、所属窗口尺寸与输入坐标对齐 | 任意系统窗口控制、拉伸错误画面、平台布局规则 |
| 低刷新画面与内部页 | `preview/frames.py`、`preview/cdp.py`、`preview/internal.py` | 单生产者最新 JPEG、截图后备、内部页统一识别 | 平台资源归属、创建第二采集浏览器 |
| 项目设置 | `settings.py`、`settings_router.py` | 浏览器默认值、枚举校验、SQLite 合并保存 | 页面层级、运行任务或已有会话状态 |
| 操作屏障与事件 | `runtime.py` | worker 暂停、恢复校验、结构化事件 | 从日志猜测任务状态、持久化业务对象 |
| 平台采集 | `platform_worker.py`、`src/mediacrawler/platforms/*`、`src/mediacrawler/storage/stores/*` | 原生登录、发现、读取、分页约束、原存储与脱敏 | 直接写公共任务表、另建公共下载队列 |
| 平台媒体解析 | `adapters/media.py`、`adapters/media_worker.py` | 当前内容的资源归属、清晰度选择、原始字段临时上下文 | 根据任意同页请求自动关联广告或其他帖子 |
| 声明式网页采集 | `template_worker.py` | 现有会话中的网页视频 DOM 解析 | 任意 Python / JavaScript 执行 |
| 课程内部执行模块 | `src/browser-worker/src/workbench` | 迁入课程发现与播放捕获、结构化协议 | 独立 Node Web 服务、接管公共索引 |
| 媒体机制 | `media/capture.py`、`media/identity.py`、`media/downloader.py` | 被动发现、稳定身份、媒体传输及合并机制 | 把网络候选当作已确认内容、绕过任务入队 |
| 页面与交互 | `src/webui/src/workbench` | 配置、平台管理、工作区、预览、结果和操作反馈 | 连接 CDP、访问 SQLite、判定任务最终状态 |

## 四种 owner

数据 owner 管理结构与持久化：平台配置校验在 registry，平台配置与任务索引落在项目 SQLite；平台原有内容字段继续由原适配器和 store 解释。新任务保存 `platform_snapshot`，之后编辑或禁用自定义网站不改写任务的历史定义。

规则 owner 解释“为何允许”：平台定义声明输入和内容能力，适配器解释登录、目标、资源归属；service 决定何时执行、暂停、重试与汇总。购物网站的 SKU 与价格口径未来应留在对应适配器或规则模块，不能塞进通用浏览器与下载器。

页面 owner 是 React 工作台。页面组合字段、按钮、业务文案与 API 调用；通用布局、分隔条、焦点、主题和折叠只负责展示机制，不自行保存平台或创建任务。

文件 owner 是公共任务与下载链路。service 通过 repository 确定任务目录，下载器写入受管文件并报告状态，router 限制文件访问范围。worker 可以在分配的任务目录生成原始采集输出，但不能另建全局结果桶或操作其他任务文件。

## 依赖与事件方向

```text
React 页面 → HTTP / WebSocket router → service
                                     ├─ registry / models / repository
                                     ├─ browser / media 机制
                                     └─ 独立 worker 进程
worker → 平台适配器 / 声明式模板 → Runtime 结构化事件 → service
```

任务事件、媒体候选与画面是独立传输通道。慢速预览不应阻塞日志、取消或采集。worker 用结构化事件报告内容、资源、阶段、失败和完成；普通日志只供阅读。

运行文件按任务编号归档。第一版一个任务执行，其余排队；异常退出的未完成任务在重启后标记中断，不自动重跑。下载数量与内容、评论数量分别统计，未知总量不生成百分比。

## 禁止跨层

- 前端直连浏览器调试端口、读 SQLite 或自行拼接本机文件路径。
- 公共浏览器或下载器按平台名称加入内容归属、价格、章节规则。
- 适配器直接修改公共任务状态或建立第二套下载调度器。
- 捕获监听器在预览播放时自动下载，或把同页全部请求归属到最后保存的一条内容。
- 在共享 UI 中根据平台名称隐藏业务能力；调用页面应传入已声明的能力。
- 把尚无执行器的书籍、购物分类展示为已支持正文或价格采集。
- 为统一目录外观搬动上游 CLI、覆盖既有数据/Profile，或恢复旧 Node Web 服务为运行依赖。

部署和操作见[工作台指南](/getting-started/local-setup.md)，新增代码的具体约定见[开发与扩展](/development/extensions.md)。

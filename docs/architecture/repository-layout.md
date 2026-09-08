# 仓库目录与路径

> 文档类型：当前目录契约；核对日期：2026-09-07。依据：`src/mediacrawler/paths.py`、项目构建配置和 `scripts/`。

所有应用源码集中在 `src/`，维护入口集中在 `scripts/`。Python、React 和 Node 仍各自拥有明确职责。

```text
src/
  mediacrawler/
    api/               HTTP / WebSocket 入口
    workbench/
      workflows/       方案、步骤、校验、运行与统一调度
      settings/        默认设置、工具配置、解析与设置接口
      browser/         会话、预览、输入与资源捕获
      downloads/       HTTP、FFmpeg、N_m3u8DL-RE 和公共传输
      results/         产物索引、导出与分页预览
      persistence/     SQLite、迁移与资料归档
      platforms/       平台能力、worker 和适配桥接
    platforms/         平台采集器、平台字段和常量
    storage/           database 数据库机制、stores 平台存储适配
    infrastructure/    cache、proxy、helpers 浏览器及传输机制
    common/            基础契约和执行上下文
    config/            配置定义和默认值
    resources/js/      随包提供的运行资源
    cli/               命令行入口
  webui/src/workbench/
    workflows/         卡片、编辑弹窗和方案草稿
    runs/              任务中心与运行详情
    browser/           浏览器工作区
    results/           发现资源、任务产物与共用预览
    settings/          设置页面
    shared/            弹窗和溢出提示
  browser-worker/      Node 课程和网页执行模块
scripts/
  setup/               安装、环境和下载工具检查
  runtime/             工作台启动；终端 Ctrl+C 停止
  build/               构建入口与文档跳转生成
  validation/          自动检查
  maintenance/         显式维护操作
tests/                 Python 自动测试
  fixtures/            测试素材
  integration/         基础设施测试；外部服务需显式选择
docs/                  文档、来源和设计稿
.local/                本机数据、浏览器状态、工具、缓存、日志
.build/                WebUI 和文档站构建结果
```

## 路径的唯一来源

Python 使用 `mediacrawler.paths`，Node 使用 `src/browser-worker/src/paths.ts`。资源定位不能依赖当前工作目录，也不能通过旧的 `api/` 层级推算根目录。

默认工作台数据为 `.local/data/workbench`，其中 `index.sqlite3` 保存公共索引，`tasks/` 保存任务文件，浏览器会话目录跟随工作台存储。旧 CLI 浏览器目录为 `.local/browser-data`；CLI 输出默认为 `.local/data/<平台>`。显式指定的输出路径仍优先。

设置环境变量 `MC_LOCAL_DIR` 可指定整个本机数据目录。它同时约束 Python 和 Node 的默认位置；运行中不要变更。下载工具默认位于 `.local/tools`，构建结果位于 `.build/webui` 和 `.build/docs`。

Python 使用 `src` 布局安装为正式包；命令行入口为 `python -m mediacrawler.cli.main` 或安装后的 `mediacrawler`。不提供根目录旧模块别名，不依赖将整棵源码加入 `sys.path` 来伪装旧结构。

## 依赖方向

API 接口调用工作台服务；工作台统一持久化任务事实，并通过 Python / Node worker 调用平台实现。平台规则归平台模块，下载传输归媒体机制，公共组件只负责展示及交互。

`config` 保存配置代码，用户设置保存在本机索引或浏览器 localStorage；`storage` 保存持久化实现，文件字节位于 `.local`。目录名称不能代替数据职责。

根目录保留 README、许可证、依赖清单、锁文件和工具配置。依赖目录按包管理器约定保留；编辑器资源管理器显示依赖、缓存和生成目录，不通过隐藏目录精简列表；不移动现有 `.venv`。

详细职责见[分层边界](layer-boundaries.md)，安装和运行见[本机安装](../getting-started/local-setup.md)。

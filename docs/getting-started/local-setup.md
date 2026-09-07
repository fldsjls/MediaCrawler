# 本机安装与启动

目录调整会继续使用根目录现有 `.venv`，无需手动删除或重建。安装器按锁文件同步依赖并重新注册 Python 包；缺少虚拟环境时会创建。日常启动不会重新安装依赖。

> 文档类型：入门操作
> 环境：当前 Windows 本机主项目；代码依据：`scripts/setup/install-workbench.ps1`、`scripts/runtime/start-workbench.ps1`。

## 安装、启动与检查

使用 Windows 10/11 x64、PowerShell 和 Node.js 22 或 24 LTS。首次安装需要访问 Python/npm/Playwright 及工具发行站点；脚本会查找当前用户的 uv，缺失时安装官方固定版本 uv 0.12.10。

在 MediaCrawler 目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup\install-workbench.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\runtime\start-workbench.ps1
```

打开 [本机工作台](http://127.0.0.1:8080)。在启动终端按 Ctrl+C 关闭应用，服务负责清理所属任务进程和浏览器。端口被占用时先关闭已有 MediaCrawler 服务；不要启动第二个服务写入同一结果索引。

安装入口依次执行 `uv sync --locked`、Python Playwright Chromium 安装、根目录 / webui / browser-capture 三份 `npm ci`、下载工具校验或补齐、worker 类型检查、前端构建及自动化检查。`PLAYWRIGHT_SKIP_BROWSER_GC=1` 防止安装时清除其他项目使用的浏览器。Node worker 连接同一个 Python 管理的 Chromium，无需再安装一套 Node Playwright 浏览器。

```powershell
# 只检查现有环境；不会启动服务器，也不会下载缺失工具
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\validation\check-workbench.ps1
# 开发时仅校验环境和构建，不运行 pytest（不能代替完整验收）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\validation\check-workbench.ps1 -SkipTests
# 单独补齐下载工具；已有且哈希匹配的版本保留
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup\install-workbench-tools.ps1
```

统一入口固定单进程、127.0.0.1:8080，并保留 Windows Proactor 事件循环。不要为此入口加 `--reload` 或多 worker；Windows Selector 事件循环不能启动 Playwright 子进程。根目录的文档依赖一并安装，文档站可另外使用 `npm run docs:dev`。

安装工具源和 SHA256 固定在 `scripts/setup/workbench-tools.json`。FFmpeg 当前迁入版本与固定安装版本均在许可和来源清单中记录。缺失工具从固定官方发行地址下载，先验压缩包哈希再验可执行文件哈希；已有未知哈希文件报错并保留，不自动覆盖。下载缓存位于 `.local/data/workbench/setup-cache`，版本升级需明确更新清单。


下一步：[完成一次采集](/guides/collection.md)。需要旧平台 CLI 时阅读[CLI 参考](/guides/cli/index.md)。

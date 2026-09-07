# MediaCrawler · 网站采集工作台

通过同一工作台配置采集、预览网站、管理任务、选择媒体并导出结果。后端使用 FastAPI，前端使用 React，课程执行模块使用 Node。

## 安装与启动

在仓库根目录执行：

```powershell
./scripts/setup/install-workbench.ps1
./scripts/runtime/start-workbench.ps1
```

打开 [本机工作台](http://127.0.0.1:8080)。已有环境可先运行 `./scripts/setup/check-environment.ps1`；日常启动直接使用 `.venv`，无需全局 `uv` 命令。安装器会查找用户目录中的 uv。

## 目录

| 入口 | 职责 |
| --- | --- |
| `src/mediacrawler` | Python API、任务服务、平台、存储与 CLI |
| `src/webui` | React 界面 |
| `src/browser-worker` | Node 浏览器执行模块 |
| `scripts` | 安装、运行、构建、检查与维护 |
| `tests` | 自动测试和样本 |
| `docs` | 文档站及设计稿 |
| `.local` | 本机数据、登录状态、日志、工具；不提交 |
| `.build` | 可重新生成的网页与文档；不提交 |

完整规则见[目录与路径](docs/architecture/repository-layout.md)。

## 开发与检查

```powershell
npm run dev:web
npm run build:web
npm run check:worker
./scripts/validation/check-workbench.ps1
npm run docs:build
npm run docs:dev
```

CLI：`.venv/Scripts/python.exe -m mediacrawler.cli.main --help`。输出默认为 `.local/data`；`MC_LOCAL_DIR` 可配置本机文件根目录。

## 文档与来源

- [文档首页](docs/index.md) · [安装](docs/getting-started/local-setup.md) · [操作指南](docs/guides/index.md)
- [架构](docs/architecture/index.md) · [开发与验证](docs/development/quality.md) · [运维](docs/operations/index.md)
- [原始说明与来源](docs/about/upstream/index.md) · [许可证](LICENSE)

网站类型用于分类，真实能力以平台声明为准。书籍正文和购物价格采集尚未接入。打开网站只发现资源，开始采集或手动选择后才下载；本地样本验证不代表真实平台登录和下载已验收。

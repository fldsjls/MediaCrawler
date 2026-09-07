# CLI 代码位置

CLI 已迁入统一 Python 包，命令入口为 `python -m mediacrawler.cli.main`。完整目录规则见[仓库目录与路径约定](/architecture/repository-layout.md)。

```text
src/mediacrawler/
├── cli/                 # 命令行入口、参数、短信转发
├── common/              # 抽象基类、上下文
├── config/              # CLI 与平台配置
├── platforms/           # 各平台采集器、模型、常量
├── storage/             # 数据库与各平台存储实现
├── infrastructure/      # 缓存、代理、浏览器与文件工具
├── resources/js/        # JavaScript 静态资源
├── api/                 # HTTP API
└── workbench/           # 任务、浏览器会话、预览、结果
```

数据库同步工具位于 `scripts/maintenance/sync_database.py`；测试集中在 `tests/`。

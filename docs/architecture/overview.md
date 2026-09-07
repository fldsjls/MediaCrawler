# 系统总览

> 文档类型：当前架构；依据：FastAPI、React、独立 worker 与项目 SQLite。

MediaCrawler 是唯一主项目。FastAPI 提供页面、任务和会话服务；React 提供用户流程。Python 平台/模板 worker 与 Node 课程 worker 执行采集，公共队列负责下载和结果，旧项目目录不参与运行。

```text
用户网页：React 页面 + RTC / JPEG 画面 + HTTP / WebSocket
    ↓
FastAPI：平台注册 / 任务 service / SQLite repository
    ├─ 同一 Chromium 与控制屏障
    ├─ 媒体捕获 / 下载 / 文件
    └─ Python 或 Node 内部 worker
```

实时与低刷新是同一浏览器的画面传输方式。前端不直连 CDP、不原生嵌入第三方网页，也不管理 worker 进程。任务当前串行调度；采集产生记录，确定归属的资源入队，service 汇总状态。预览不会因播放而自动下载。

书籍和购物目前提供分类/配置/预览，没有正文或价格执行器。模块归属见[职责矩阵](layer-boundaries.md)。

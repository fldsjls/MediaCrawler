---
layout: home
title: MediaCrawler 文档
hero:
  name: MediaCrawler
  text: 网站采集，从这里开始。
  tagline: 一个工作台管理网站、浏览器会话、内容与媒体。按任务查找操作，按职责理解代码。
  actions:
    - theme: brand
      text: 安装与启动
      link: /getting-started/local-setup
    - theme: alt
      text: 完成一次采集
      link: /guides/collection
    - theme: alt
      text: 架构与扩展
      link: /architecture/
features:
  - title: 使用工作台
    details: 选择网站、完成登录、采集内容，再按需下载媒体。预览播放不等于下载。
    link: /guides/
  - title: 理解职责
    details: 任务、浏览器、适配器与文件各有明确归属。共享流程与平台规则分别维护。
    link: /architecture/layer-boundaries
  - title: 核对证据
    details: 当前事实、验收方法、历史结果与未来计划分别记录。
    link: /development/quality
---

<div class="docs-home-body">

## 按任务阅读

| 你要做什么 | 从这里开始 | 下一步 |
| --- | --- | --- |
| 首次安装或恢复环境 | [本机安装](getting-started/local-setup.md) | [运行排查](operations/runtime.md) |
| 新增网站或切换类型 | [平台管理](guides/platforms.md) | [采集与下载](guides/collection.md) |
| 接管、输入或查看页面 | [浏览器交互](guides/browser.md) | [双模式架构](architecture/browser-workspace.md) |
| 调整界面或会话选项 | [设置中心](guides/settings.md) | [设置职责](architecture/settings.md) |
| 查找文件或重试失败 | [结果管理](guides/results.md) | [数据导入](operations/migration.md) |
| 修改适配器或界面 | [开发入口](development/index.md) | [职责边界](architecture/layer-boundaries.md) |
| 查以前的测试结果 | [历史快照](history/index.md) | [当前验收方法](development/quality.md) |
| 使用原平台命令行 | [CLI 参考](guides/cli/index.md) | [CLI 存储](guides/cli/storage.md) |

## 文档的事实边界

当前代码与配置是运行事实；架构文档说明稳定职责；ADR 解释已经接受的决策；路线图只描述未完成目标；历史记录只证明指定阶段、环境和样本的结果。真实网站登录、内容和媒体输出需逐项验收。

工作台是纯网页应用。预览在远端 Chromium 中运行，通过实时或低刷新画面交互，并非把目标网站原生嵌入页面；不需要 Electron。书籍、购物目前提供分类、配置与预览，正文及价格采集尚未实现。

[文档地图](documentation-map.md) · [决策记录](adr/index.md) · [路线图](roadmap.md) · [来源与许可](about/index.md)

</div>

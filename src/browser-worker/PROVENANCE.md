# 来源、版本与许可证记录

## 合并来源

- 主项目上游：[MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)。本机 checkout 迁移基线提交 `d6f7c5bb906b6dac40ddf343ef9e26438a3de092`，当前远程为 `https://github.com/fldsjls/MediaCrawler.git`。根目录 `LICENSE` 为 **NON-COMMERCIAL LEARNING LICENSE 1.1**，原著作权及限制保留。
- 迁入用户本地 `playwright_crawler` 的 TypeScript 采集/下载模块，来源提交 `ef26973735dbeab124b8e565850e66d44a1d3915`。源项目未提供独立 LICENSE，因此本次迁移不推定该代码具有 MIT 等公开再分发授权。
- 迁入 `src` 中 browser / config / downloader / routes / sites / types / utils，以及依赖锁和 TypeScript 配置；没有迁入旧 GUI 服务、`.git`、`node_modules` 或 Python 虚拟环境。新加 `src/workbench` 为 FastAPI 内部结构化事件 worker；保留课程和 m3u8 CLI 作为源代码级诊断入口。
- Python 平台适配器继续保留 MediaCrawler 自身结构、字段处理与脱敏规则。Node/Python 通过内部进程协议协作；运行时不访问旧项目所在目录。

## Node 依赖

依赖的具体解析版本和完整性哈希由同目录 `package-lock.json` 固定，使用 `npm ci` 还原。Playwright 与 Crawlee 的上游均采用 Apache-2.0；各传递依赖保留其原包内许可证。本地 package 标记为 private，不形成新的发布授权。

## 下载工具

可执行文件放在本目录 `tools/ffmpeg`、`tools/n-m3u8dl-re`，不提交版本库。安装脚本只从以下上游固定发行包补齐缺失文件，并校验压缩包与可执行文件 SHA256。已有校验通过的本机迁入工具不会自动升级或覆盖。

| 工具 | 本机迁入版本 | 固定安装来源 |
| --- | --- | --- |
| FFmpeg / ffprobe | `N-124881-g6028720d70-20260608` | [BtbN FFmpeg-Builds autobuild-2026-09-06-13-06](https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-09-06-13-06)，`N-126435-gf93cd72dde` Windows x64 GPL 静态构建 |
| N_m3u8DL-RE | `0.5.1+c1f6db5639397dde362c31b31eebd88c796c90da` | [nilaoda v0.5.1-beta](https://github.com/nilaoda/N_m3u8DL-RE/releases/tag/v0.5.1-beta)，Windows x64，20251029 发行包 |

完整 SHA256 清单在 `../../scripts/workbench-tools.json`。FFmpeg 发行包哈希核对上游 `checksums.sha256`；N_m3u8DL-RE 发行包和各可执行文件哈希由固定发行包本地计算核验。本机旧 FFmpeg 已记录版本及二进制哈希，但原下载包来源记录不完整，不声称已恢复其原始构建包。

FFmpeg 本机与固定安装构建都启用了 GPL 组件，不能按普通 LGPL-only 构建描述。许可证说明见 [FFmpeg 官方说明](https://ffmpeg.org/legal.html)，源码见 [FFmpeg](https://github.com/FFmpeg/FFmpeg)，构建脚本与依赖来源见 [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds)。固定包中的许可文本保存在 `licenses/FFmpeg-GPL-3.0.txt`；这只是原始许可文本保留，不代表已打包全部对应源码。

N_m3u8DL-RE 使用 [MIT License](https://github.com/nilaoda/N_m3u8DL-RE/blob/v0.5.1-beta/LICENSE)，原文保存在 `licenses/N_m3u8DL-RE-MIT.txt`，著作权为 `Copyright (c) 2022 nilaoda`。

本次范围是 Windows 本机安装和合并使用，不发布源码或二进制。后续若分发，需独立确认未附许可证的迁入源码授权，以及所分发下载工具及其对应源码、依赖和许可证要求；本记录不会替代上游条款。

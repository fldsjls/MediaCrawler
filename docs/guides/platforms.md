# 平台管理与接口

## 类型、网站、模板分别表示什么

| 概念 | 示例 | 决定什么 |
| --- | --- | --- |
| 类型 | `video`、`books`、`shopping`、`community`、`other` | 导航筛选和分类 |
| 网站定义 | Bilibili、美石建工、自定义网站 | 名称、入口、标签、启用状态、模板与能力 |
| 模板 | `video_capture`、`preview_only` | 实际允许执行的操作与可配置字段 |

内置网站由源码维护，不允许在配置界面编辑或删除。自定义网站保存在项目 SQLite，删除操作将其禁用，保留历史任务。平台列表默认只返回启用项，管理时可请求禁用项。

`generic` 提供通用网页适配，是未匹配网址的默认入口；需要保存特定选择器和等待规则的网站可以通过平台管理注册。课程网站现名为“美石建工”，内部标识继续使用 `meishiwang`，避免破坏历史任务与 Profile。

## 新增与使用

1. 在平台管理中填写名称、类型、HTTP / HTTPS 网站入口、标签和模板。
2. 网页视频选择“网页视频捕获”，可填写播放或目录元素选择器与等待时间；只需浏览的网站选择“网站预览”。
3. 选择网站并打开预览，在同一浏览器完成必要登录或播放操作。
4. 有采集能力的网站可创建采集任务。预览模板不能开始采集，但可浏览并从捕获列表选择可下载资源，创建下载任务。
5. 在结果中检查下载状态和导出文件。候选资源出现不代表已下载成功。

分类为书籍或购物不会自动添加正文、价格功能。本轮不执行用户上传脚本，模板只接受声明的参数；选择器是 DOM 配置，不是代码执行入口。

## 视频与图片

`download_video` 与 `download_images` 独立控制。所有内置平台声明视频能力；图片选项仅在平台定义允许时显示。旧 `media` 请求继续按兼容规则转换，新调用方应明确传两个字段。

适配器自动选择已取得响应中最高可用清晰度，不承诺会员、付费或当前会话无权取得的质量。B站每个分 P 是一个逻辑视频；DASH 音视频轨道及 progressive 分段保持为同一资源，交公共下载器合并。图片不受视频开关影响。

内容的 `fields.video_status` 表示：`none` 为明确无视频，`available` 为已取得可确认地址，`unresolved` 为尚未完成解析。明确无视频不会作为视频下载失败；确认存在视频而无法解析时，选了视频下载的任务会记录失败原因。

预览捕获列表可包含视频、音频或图片候选。是否可下载取决于解析结果；blob、DRM、不支持的加密或无限直播资源不能视作普通文件。无法确认属于当前内容的候选需人工选择，不自动归属。

## API 地图

以下路径均以 `/api` 为前缀，具体请求校验以 `router.py` 和 `models.py` 为准。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /platform-types` | 类型列表 |
| `GET /settings/sections` | 设置分类与保存范围 |
| `GET /settings/browser`、`PATCH /settings/browser` | 项目浏览器默认值与局部更新 |
| `GET /platform-templates` | 模板、字段和能力 |
| `GET /platforms?include_disabled=true` | 平台及实际能力 |
| `POST /platforms` | 新建自定义网站 |
| `PUT /platforms/{id}` | 更新自定义网站的完整定义 |
| `DELETE /platforms/{id}` | 禁用自定义网站 |
| `GET /tasks`、`POST /tasks` | 列出、创建任务 |
| `GET /tasks/{id}` | 任务状态与配置快照 |
| `POST /tasks/{id}/control` | `pause`、`takeover`、`resume`、`cancel`、`retry` |
| `GET /tasks/{id}/events?after=序号` | 补取事件；同路径 WebSocket 订阅 |
| `GET /tasks/{id}/results` | 内容、文件、导出结果 |
| `POST /tasks/{id}/downloads` | 将选中的会话资源加入任务 |
| `POST /tasks/{id}/export` | 生成导出文件 |
| `GET /tasks/{id}/file?path=相对路径` | 下载该任务目录内的文件 |
| `GET /browser-sessions`、`POST /browser-sessions` | 列出、建立会话 |
| `GET /browser-sessions/{id}`、`DELETE /browser-sessions/{id}` | 查询、关闭会话 |
| `GET /browser-sessions/{id}/resources?after=序号` | 会话捕获资源；同路径支持 WebSocket |
| `WS /browser-sessions/{id}/frames` | 画面传输 |
| `PATCH /browser-sessions/{id}/presentation` | 当前会话 `auto` / `realtime` / `snapshot` 偏好；请求携带 token |
| `POST /browser-sessions/{id}/rtc` | RTC offer / answer 协商，请求含 token、type、sdp |
| `DELETE /browser-sessions/{id}/rtc/{peer_id}` | 释放 RTC；Bearer 会话 token |
| `WS /browser-sessions/{id}/control` | 页面选择、接管、输入 |
| `POST /imports` | 显式导入资料或 Profile |

自定义平台示例：

```json
{
  "name": "示例视频网站",
  "category": "video",
  "url": "https://example.com",
  "template": "video_capture",
  "template_config": {"selector": "", "wait_ms": 5000},
  "tags": ["示例"],
  "enabled": true
}
```

仅下载任务使用 `operation: "download"`，提供同一会话的 `session_id` 和 `resource_ids`，不会启动内容采集。向已有任务添加下载的请求体同样使用这两个字段。会话资源与控制连接检查来源和会话身份；调试端点、内部请求头和完整媒体地址不作为公开结果字段返回。

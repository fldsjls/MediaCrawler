# 设置中心职责

> 文档类型：当前设置架构；依据 `settings.py`、`settings_router.py`、`repository.py` 和 `SettingsCenter.tsx`。

分类入口、子项列表、详情分别负责定位类别、选择设置和编辑内容。详情必须说明默认值、允许值、保存位置、作用域和生效时机，不能把所有表单无边界平铺。

| 性质 | owner | 边界 |
| --- | --- | --- |
| 主题、布局、折叠 | 前端设置与布局 | 不改变任务和平台能力 |
| 会话创建与画面 | 设置入口 + 浏览器服务 | 后端决定生命周期和应用时机 |
| 网站定义 | registry | 不与主题混存、不依赖页面 |
| 单次任务 | TaskConfig / service | 创建时保存快照，不暗改运行任务 |
| 资料与 Profile 导入 | migration / session | 显式操作，不静默保存 |

页面负责字段、文案、保存和反馈。共享外壳仅负责导航、返回、滚动、选中和焦点。需重建的选项应说明生效条件，不能悄悄关闭任务；无实现的设置不能成为可操作开关。

`SettingsRegistry` 拥有浏览器默认值，使用 SQLite `settings(section,payload,updated)`。PATCH 只合并显式字段，严格校验类型与枚举，不允许空值替代默认值。新会话读取并保存快照，不修改现有会话。设置 router 通过 Repository provider 获取数据，不反向导入 service。外观由 localStorage 管理，平台继续归 PlatformRegistry。

当前索引使用 SQLite `user_version=3`。已有索引升级前通过 SQLite 备份 API 保存一致性副本，包含 WAL 中的数据；这份升级备份不替代用户的定期任务文件备份。

见[操作指南](../guides/settings.md)与 [ADR 0003](../adr/0003-settings-navigation.md)。

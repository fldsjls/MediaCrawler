export const sections = [
  { dir: 'getting-started', text: '快速开始', pages: [['local-setup', '本机安装与启动'], ['cli-environment', 'CLI 环境参考']] },
  { dir: 'guides', text: '操作指南', pages: [['collection', '采集与下载'], ['platforms', '平台管理与 API'], ['browser', '浏览器交互'], ['settings', '设置中心'], ['results', '结果与重试'], ['cli', 'CLI 参考'], ['cli-cdp', 'CLI CDP'], ['cli-storage', 'CLI 存储'], ['cli-excel', 'CLI Excel'], ['cli-wordcloud', 'CLI 词云'], ['cli-phone-login', 'CLI 手机号登录']] },
  { dir: 'architecture', text: '架构', pages: [['overview', '系统总览'], ['layer-boundaries', '职责边界'], ['browser-workspace', '浏览器双模式'], ['settings', '设置职责'], ['upstream-cli', '上游 CLI 架构']] },
  { dir: 'development', text: '开发', pages: [['extensions', '目录与扩展'], ['shared-ui', '共享 UI'], ['quality', '质量与验收'], ['documentation', '文档维护'], ['upstream-tree', '上游 CLI 目录']] },
  { dir: 'operations', text: '运维', pages: [['runtime', '启动与排查'], ['migration', '显式导入'], ['backup', '备份恢复'], ['cli-proxy', 'CLI 代理'], ['cli-faq', 'CLI 常见问题']] },
  { dir: 'history', text: '历史', pages: [['2026-09-07-platform-media-validation', '平台媒体阶段'], ['2026-09-07-jpeg-preview', 'JPEG 预览阶段'], ['2026-09-07-documentation-restructure', '文档重构验收'], ['2026-09-07-rtc-performance', 'RTC 双模式测量'], ['2026-09-07-preview-route-comparison', '实时预览路线比较'], ['2026-09-07-native-preview-validation', '原生预览功能验收']] },
  { dir: 'adr', text: '决策记录', pages: [['0001-documentation-architecture', '0001 文档信息架构'], ['0002-browser-dual-mode', '0002 浏览器双模式'], ['0003-settings-navigation', '0003 设置层级'], ['0004-native-tab-capture', '0004 原生捕获身份']] },
  { dir: 'about', text: '关于', pages: [['author', '上游作者'], ['learning', '学习资料'], ['pro', '上游 Pro 说明'], ['community', '社区'], ['supporters', '支持者'], ['providers/', '代理资料']] },
];
export const nav = [
  { text: '开始使用', link: '/getting-started/' },
  { text: '指南', link: '/guides/' },
  { text: '架构', link: '/architecture/' },
  { text: '开发', link: '/development/' },
  { text: '更多', items: [{ text: '运维', link: '/operations/' }, { text: '历史', link: '/history/' }, { text: '决策记录', link: '/adr/' }, { text: '路线图', link: '/roadmap' }, { text: '文档地图', link: '/documentation-map' }, { text: '关于与来源', link: '/about/' }] },
];
export const sidebar = sections.map(section => ({
  text: section.text, link: `/${section.dir}/`, collapsed: true,
  items: section.pages.map(([slug, text]) => ({ text, link: `/${section.dir}/${slug}` })),
}));

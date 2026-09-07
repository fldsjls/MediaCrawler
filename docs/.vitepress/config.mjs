import { defineConfig } from 'vitepress';
import { withMermaid } from 'vitepress-plugin-mermaid';
import { fileURLToPath } from 'node:url';
import { nav, sidebar } from './site-map.mjs';

export default withMermaid(defineConfig({
  lang: 'zh-CN',
  title: 'MediaCrawler 文档',
  description: '通用网站采集工作台：操作、架构、开发与验收。',
  base: process.env.DOCS_BASE || '/MediaCrawler/',
  appearance: true,
  outDir: fileURLToPath(new URL('../../.build/docs', import.meta.url)),
  cacheDir: fileURLToPath(new URL('../../.local/cache/docs', import.meta.url)),
  lastUpdated: true,
  cleanUrls: false,
  themeConfig: {
    siteTitle: 'MediaCrawler / 文档',
    nav, sidebar,
    search: { provider: 'local', options: { translations: {
      button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
      modal: { displayDetails: '显示详情', resetButtonTitle: '清空搜索', backButtonTitle: '返回',
        noResultsText: '没有找到相关文档', footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' } },
    } } },
    outline: { level: [2, 3], label: '本页内容' },
    docFooter: { prev: '上一篇', next: '下一篇' },
    lastUpdated: { text: '最后更新' },
    darkModeSwitchLabel: '深浅主题',
    sidebarMenuLabel: '文档导航',
    returnToTopLabel: '回到顶部',
    footer: { message: '当前事实、使用方法与历史证据分开维护。来源与许可见关于页面。', copyright: 'MediaCrawler · 本机网站采集工作台' },
  },
}));

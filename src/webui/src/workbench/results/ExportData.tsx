import { Download, FileText, X } from 'lucide-react'
import { fileUrl } from '../api'

const formats: Record<string, [string, string]> = {
  jsonl: ['JSONL', '适合程序处理，每行一条采集记录。'],
  json: ['JSON', '适合程序读取完整的数据结构。'],
  csv: ['CSV', '可使用表格软件打开和分析。'],
  xlsx: ['Excel', '可使用 Excel 打开和分析。'],
}

interface Props { id: string; taskId: string; files: string[]; busy: boolean; onGenerate: () => void; onClose: () => void }

export function ExportData({ id, taskId, files, busy, onGenerate, onClose }: Props) {
  return <section id={id} className="wb-export-data" aria-label="采集数据导出">
    <div className="wb-export-heading"><div><strong>采集数据</strong><p>包含本任务已保存的采集记录；视频请在“文件”中下载。</p></div><button aria-label="收起数据导出" onClick={onClose}><X size={17} /></button></div>
    <div className="wb-export-downloads">{files.map(path => {
      const extension = path.split('.').pop()?.toLowerCase() || ''
      const [label, description] = formats[extension] || ['数据文件', '本任务生成的采集数据。']
      return <a key={path} download href={fileUrl(taskId, path)}><FileText size={20} /><span><strong>采集数据 · {label}</strong><small>{description}</small><small>{path}</small></span><Download size={17} aria-label="下载数据" /></a>
    })}</div>
    {!files.length && <p>尚未生成数据文件，将使用此任务设置的导出格式。</p>}
    <button disabled={busy} onClick={onGenerate}>{busy ? '正在处理…' : files.length ? '重新生成数据' : '生成数据文件'}</button>
  </section>
}

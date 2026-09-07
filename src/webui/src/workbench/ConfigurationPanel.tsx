import { Dispatch, SetStateAction } from 'react'
import { Config, Platform, Task, ended, states } from './api'
import { PlatformType } from './PlatformManager'

interface Props {
  config: Config; setConfig: Dispatch<SetStateAction<Config>>; platforms: Platform[]; platform?: Platform; task?: Task;
  busy: boolean; onPlatform: () => void;
  onOpen: () => void; onStart: () => void; onControl: (action: string) => void; onError: (message: string) => void;
  category: string; types: PlatformType[]; onCategory: (value: string) => void;
}
export function ConfigurationPanel({ config, setConfig, platforms, platform, task, busy, onPlatform, onOpen, onStart, onControl, onError, category, types, onCategory }: Props) {
  const change = <K extends keyof Config>(key: K, value: Config[K]) => setConfig(old => ({ ...old, [key]: value }))
  const videoSupported = Boolean(platform?.video && (platform.video_modes || platform.inputs).includes(config.mode))
  const controls = task && !ended.has(task.state) && <div className="wb-controls">
    <button disabled={busy || !['running', 'waiting_login'].includes(task.state)} onClick={() => onControl('takeover')}>接管</button>
    <button disabled={busy || task.state !== 'running'} onClick={() => onControl('pause')}>暂停</button>
    <button disabled={busy || !['paused', 'waiting_login'].includes(task.state)} onClick={() => onControl('resume')}>继续采集</button>
    <button disabled={busy || task.state === 'cancelling'} onClick={() => onControl('cancel')}>取消</button>
  </div>
  return <aside className="wb-config" aria-label="采集配置">
    <div className="wb-config-heading"><h1>采集配置</h1></div>
    <div className="wb-config-scroll">
      <fieldset><legend>来源与目标</legend>
        <label>网站类型<select aria-label="网站类型筛选" value={category} onChange={e => onCategory(e.target.value)}><option value="all">全部类型</option>{types.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
        <label>平台<select aria-label="平台" value={config.platform} onChange={e => { const next = platforms.find(p => p.id === e.target.value)!; setConfig(old => ({ ...old, platform: next.id, mode: next.inputs[0], comments: next.comments, subcomments: false, download_video: false, download_images: false, media: false, output: next.outputs.includes(old.output) ? old.output : next.outputs[0], target: '', start: 1, wait_ms: Number(next.template_config?.wait_ms || 5000), selector: String(next.template_config?.selector || ''), session_id: undefined })); onPlatform() }}>{platforms.map(p => <option key={p.id} value={p.id} disabled={p.enabled === false}>{p.id === 'meishiwang' ? '美石建工' : p.name}{p.enabled === false ? '（已停用）' : ''}</option>)}</select></label>
        <label>输入方式<select aria-label="输入方式" value={config.mode} onChange={e => setConfig(old => ({ ...old, mode: e.target.value, download_video: (platform?.video_modes || platform?.inputs || []).includes(e.target.value) ? old.download_video : false }))}>{platform?.inputs.map(mode => <option key={mode} value={mode}>{{ detail: '指定内容 / 链接', search: '关键词搜索', creator: '创作者页面' }[mode] || mode}</option>)}</select></label>
        <div className="wb-tags">{platform?.category && <span>{types.find(t => t.id === platform.category)?.name || platform.category}</span>}{platform?.tags?.map(tag => <span key={tag}>{tag}</span>)}</div>
        <label>{config.mode === 'search' ? '关键词' : '目标地址或 ID'}<textarea aria-label="目标地址或关键词" rows={2} value={config.target} onChange={e => change('target', e.target.value)} placeholder={platform?.url || '填写目标地址'} /></label>
      </fieldset>
      <fieldset hidden={platform?.collect === false}><legend>内容与范围</legend><div className="wb-fields"><label>内容上限<input aria-label="采集内容上限" type="number" min={1} max={10000} value={config.max_items} onChange={e => change('max_items', Number(e.target.value))} /></label><label>{config.platform === 'meishiwang' ? '起始课时' : '起始页'}<input type="number" min={1} value={config.start} onChange={e => change('start', Number(e.target.value))} /></label></div>
        {platform?.comments && <><label className="wb-check"><input type="checkbox" checked={config.comments} onChange={e => change('comments', e.target.checked)} />采集评论</label>{config.comments && <><label>每条内容评论上限<input type="number" min={0} max={10000} value={config.max_comments} onChange={e => change('max_comments', Number(e.target.value))} /></label><label className="wb-check"><input type="checkbox" checked={config.subcomments} onChange={e => change('subcomments', e.target.checked)} />包含子评论</label></>}</>}
      </fieldset>
      <fieldset hidden={!platform?.video && !platform?.images}><legend>视频与图片</legend><p className="wb-muted">打开网站会发现资源。勾选后，采集时自动下载；也可在结果中手动选择。</p>
        <label className="wb-check"><input type="checkbox" checked={config.download_video} disabled={!videoSupported} onChange={e => change('download_video', e.target.checked)} />下载视频</label>
        {!videoSupported && <p className="wb-muted">此输入方式暂未提供视频下载。</p>}
        {platform?.images && <label className="wb-check"><input type="checkbox" checked={config.download_images} onChange={e => change('download_images', e.target.checked)} />下载图片</label>}
        <label>文件下载上限<input aria-label="文件下载上限" type="number" min={0} max={10000} value={config.max_downloads} onChange={e => change('max_downloads', Number(e.target.value))} /><small>与内容数量分别控制。</small></label>
      </fieldset>
      <fieldset><legend>{platform?.collect === false ? '浏览会话' : '登录与保存'}</legend>{config.platform === 'meishiwang' || platform?.template === 'video_capture' || platform?.collect === false ? <><label hidden={platform?.collect === false}>播放后等待（毫秒）<input type="number" min={100} value={config.wait_ms} onChange={e => change('wait_ms', Number(e.target.value))} /></label><p className="wb-muted">请在网站预览中完成登录或验证码。</p></> : <><label>登录方式<select aria-label="登录方式" value={config.login} onChange={e => change('login', e.target.value)}><option value="qrcode">二维码 / 已有会话</option><option value="cookie">Cookie</option></select></label>{config.login === 'cookie' && <label>Cookie（仅本次任务）<textarea rows={2} value={config.cookies} onChange={e => change('cookies', e.target.value)} autoComplete="off" /></label>}</>}
        <label hidden={platform?.collect === false}>导出格式<select aria-label="导出格式" value={config.output} onChange={e => change('output', e.target.value)}>{(platform?.outputs || ['jsonl']).map(output => <option key={output} value={output}>{output.toUpperCase()}</option>)}</select></label>
      </fieldset>
      {task && <div className="wb-current"><span className={`wb-state ${task.state}`}>{states[task.state]}</span><small>{task.id.slice(0, 8)}</small><p>内容 {task.counts.content} · 评论 {task.counts.comments}</p><p>文件完成 {task.counts.files_succeeded} · 失败 {task.counts.files_failed}</p>{task.error && <button onClick={() => onError(task.error)}>查看任务说明</button>}</div>}
    </div>
    {platform?.collect === false && <p className="wb-capability-note">此平台仅支持预览。正文、价格等采集能力待接入。</p>}
    <div className="wb-config-actions"><button disabled={busy} onClick={onOpen}>打开网站</button><button className="wb-primary" disabled={busy || !config.target.trim() || !platform || platform.enabled === false || platform.collect === false} onClick={onStart}>开始采集</button>{controls}{busy && <small role="status">正在处理…</small>}</div>
  </aside>
}

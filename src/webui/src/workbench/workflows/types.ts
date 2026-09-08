export type StepKind='session'|'discover'|'content'|'comments'|'media'|'files'|'export'
export interface Step {id:string;kind:StepKind;name:string;enabled:boolean;input:string;overrides:Record<string,string|number|boolean>}
export interface Plan {name:string;platform:string;target:string;source:'website'|'direct'|'selection'|'history';mode:'detail'|'search'|'creator';session_id?:string;resource_ids:string[];history_id?:string;steps:Step[]}
export interface Definition {id:StepKind;title:string;inputs:string[];output:string;fields:string[];sources:string[]}
export interface Validation {valid:boolean;errors:string[];available:Definition[];options:(Definition&{enabled:boolean;reason:string})[];definitions:Definition[];step_inputs:Record<string,string[]>;defaults:Record<string,string|number|boolean>}
export const titles:Record<StepKind,string>={session:'准备浏览会话',discover:'发现资源',content:'采集内容',comments:'采集评论',media:'下载媒体',files:'下载文件',export:'导出数据'}
export const labels:Record<string,string>={max_items:'内容 / 课时数量',start:'起始页 / 课时',max_comments:'评论数量',subcomments:'包含回复',engine:'下载引擎',quality:'清晰度',audio:'音轨',output:'导出格式',filename:'导出名称',subdirectory:'保存子目录',selector:'播放 / 目录选择器',wait_ms:'页面等待（毫秒）',timeout:'请求超时（秒）',retries:'失败重试次数',concurrency:'分片并发数',ffmpeg_path:'FFmpeg 路径',n_m3u8dl_path:'N_m3u8DL-RE 路径',output_dir:'默认输出目录',collision:'文件重名策略',export_fields:'导出字段（逗号分隔，留空为全部）'}
export const choices:Record<string,string[]>={collision:['rename','error'],engine:['auto','http','ffmpeg','n_m3u8dl'],quality:['best','720','1080','2160'],audio:['default','all'],output:['jsonl','json','csv','excel']}
export const values:Record<string,string>={rename:'自动增加后缀',error:'报告重名错误',auto:'自动选择',http:'HTTP',ffmpeg:'FFmpeg',n_m3u8dl:'N_m3u8DL-RE',best:'最佳可用',default:'默认音轨',all:'全部音轨'}

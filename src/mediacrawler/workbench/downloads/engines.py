"""Download engine capability and process boundary; no second queue."""
import asyncio
import os
from pathlib import Path
import subprocess
import tempfile


def select_engine(settings, item):
    composite = bool(item.get('streams') or item.get('segments'))
    manifest = item.get('format') in ('hls', 'dash', 'm3u8', 'mpd')
    engine = settings.get('engine', 'ffmpeg' if manifest or composite else 'http')
    if engine == 'auto':
        engine = 'ffmpeg' if composite else ('n_m3u8dl' if Path(settings['n_m3u8dl_path']).is_file() else 'ffmpeg') if manifest else 'http'
    if engine == 'http' and (manifest or composite): raise ValueError('HTTP 引擎不能合并流媒体')
    if engine == 'n_m3u8dl' and (not manifest or composite): raise ValueError('N_m3u8DL-RE 仅用于完整 HLS/DASH 清单')
    if engine in ('ffmpeg', 'n_m3u8dl'):
        key = 'ffmpeg_path' if engine == 'ffmpeg' else 'n_m3u8dl_path'
        if not Path(settings[key]).is_file(): raise ValueError(f'{engine} 工具不可用，请在设置中检查路径')
        if not Path(settings['ffmpeg_path']).is_file(): raise ValueError('媒体合并需要可用的 FFmpeg')
    return engine


async def inspect_tools(settings):
    async def probe(engine, flag):
        path = settings[engine + '_path']
        if not Path(path).is_file(): return dict(engine=engine, path=path, available=False, version='未安装')
        try:
            result = await asyncio.to_thread(subprocess.run, [path, flag], capture_output=True, timeout=8,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            text = (result.stdout + result.stderr).decode('utf-8', errors='replace')
            version = next((s.strip() for s in text.splitlines() if ('version' in s.lower() or 'N_m3u8DL' in s)), '')[:180]
            return dict(engine=engine, path=path, available=result.returncode == 0, version=version)
        except (OSError, subprocess.TimeoutExpired): return dict(engine=engine, path=path, available=False, version='工具检查失败')
    return await asyncio.gather(probe('ffmpeg', '-version'), probe('n_m3u8dl', '--help'))


async def n_m3u8dl(run, item, partial, settings):
    from .downloader import MediaProxy, clean_error, check_cancel
    from mediacrawler.workbench.browser import kill_tree
    with tempfile.TemporaryDirectory(prefix='n-m3u8dl-', dir=partial.parent) as temp:
        output = Path(temp)
        async with MediaProxy(run, item) as proxy:
            command = [settings['n_m3u8dl_path'], proxy.register(item['url'], item), '--save-dir', str(output),
                       '--tmp-dir', str(output / 'segments'), '--save-name', 'result', '--auto-select',
                       '--ffmpeg-binary-path', settings['ffmpeg_path'], '--no-ansi-color', '--no-log',
                       '--write-meta-json', 'false', '--thread-count', str(settings['concurrency']),
                       '--download-retry-count', str(settings['retries']), '--http-request-timeout', str(settings['timeout']),
                       '-M', 'format=mp4:muxer=ffmpeg']
            if settings['quality'] != 'best': command += ['-sv', f'res=".*x{settings["quality"]}":for=best']
            if settings['audio'] == 'all': command += ['-sa', 'all']
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            run.download_process = process
            communication = asyncio.create_task(asyncio.to_thread(process.communicate))
            try:
                while not communication.done():
                    check_cancel(run)
                    await asyncio.wait([communication], timeout=.15)
                stdout, _ = await communication
                check_cancel(run)
                if process.returncode or proxy.errors:
                    raise RuntimeError(clean_error(proxy.errors[-1] if proxy.errors else stdout.decode('utf-8', errors='replace')))
                candidates = list(output.glob('result*.mp4'))
                if len(candidates) != 1 or candidates[0].stat().st_size == 0: raise RuntimeError('下载器未生成唯一完整媒体文件')
                candidates[0].replace(partial)
            finally:
                await kill_tree(process)
                await communication
                run.download_process = None

// Trusted loopback page. Only backend Playwright calls this API; HTTP exposes no controls.
(() => {
  let stream = null, expected = null, generation = 0, needsIdentity = false, paused = false, lastError = '';
  const peers = new Map();
  const stopCapture = () => {
    if (stream) for (const track of stream.getTracks()) track.stop();
    stream = null; expected = null; needsIdentity = false; paused = false;
  };
  const closePeer = id => {
    const item = peers.get(id);
    if (!item) return;
    peers.delete(id); clearTimeout(item.timer); item.pc.onconnectionstatechange = null; item.pc.close();
    if (!peers.size) stopCapture();
  };
  const reset = () => { generation++; for (const id of [...peers.keys()]) closePeer(id); stopCapture(); };
  const matches = value => {
    const track = stream?.getVideoTracks()[0], handle = track?.getCaptureHandle?.();
    return track?.readyState === 'live' && track.getSettings().displaySurface === 'browser' &&
      handle?.handle === value?.handle && handle?.origin === value?.origin;
  };
  const pauseIdentity = () => {
    if (!stream) return;
    const valid = matches(expected) && !paused; needsIdentity = !valid;
    for (const track of stream.getTracks()) track.enabled = valid;
  };
  window.NativePreview = {
    prepare(value) { window.captureConfig = value; window.captureResult = { phase: 'ready' }; },
    async capture(value) {
      const ownGeneration = generation;
      window.captureResult = { phase: 'requesting' };
      try {
        const fresh = await navigator.mediaDevices.getDisplayMedia({
          video: { displaySurface: 'browser', width: { ideal: 1280 }, height: { ideal: 720 },
            frameRate: { ideal: value.sourceFps, max: value.sourceFps } },
          audio: false, selfBrowserSurface: 'exclude', monitorTypeSurfaces: 'exclude',
          surfaceSwitching: 'exclude', systemAudio: 'exclude',
        });
        if (ownGeneration !== generation) { fresh.getTracks().forEach(track => track.stop()); throw new Error('捕获已取消'); }
        stream = fresh; expected = value;
        if (!matches(value)) { stopCapture(); throw new Error('捕获来源身份校验失败，未传输画面'); }
        const track = stream.getVideoTracks()[0];
        track.addEventListener('capturehandlechange', pauseIdentity);
        track.addEventListener('ended', () => { lastError = '浏览器标签页捕获已结束'; reset(); });
        lastError = ''; needsIdentity = false;
        window.captureResult = { phase: 'captured', settings: track.getSettings() };
      } catch (error) {
        window.captureResult = { phase: 'error', message: error.message || String(error) };
      }
    },
    async answer(value) {
      if (!matches(expected) || needsIdentity) throw new Error('标签页身份尚未验证');
      const size = stream.getVideoTracks()[0].getSettings();
      if (size.width !== 1280 || size.height !== 720) throw new Error('标签页捕获尺寸不匹配，使用低刷新预览');
      const ownGeneration = generation, pc = new RTCPeerConnection({ iceServers: [] });
      const item = { pc, timer: null }; peers.set(value.id, item);
      item.timer = setTimeout(() => { if (pc.connectionState !== 'connected') closePeer(value.id); }, 20000);
      pc.onconnectionstatechange = () => {
        if (['failed', 'closed'].includes(pc.connectionState)) closePeer(value.id);
        if (pc.connectionState === 'connected') clearTimeout(item.timer);
        if (pc.connectionState === 'disconnected') {
          clearTimeout(item.timer);
          item.timer = setTimeout(() => { if (pc.connectionState !== 'connected') closePeer(value.id); }, 3000);
        }
      };
      try {
        await pc.setRemoteDescription({ sdp: value.sdp, type: 'offer' });
        if (!pc.getTransceivers().some(t => t.receiver.track.kind === 'video')) throw new Error('实时预览需要视频接收通道');
        const sender = pc.addTrack(stream.getVideoTracks()[0], stream);
        await pc.setLocalDescription(await pc.createAnswer());
        const parameters = sender.getParameters();
        for (const encoding of parameters.encodings) {
          encoding.maxBitrate = 8000000; encoding.maxFramerate = value.sourceFps;
        }
        await sender.setParameters(parameters);
        if (pc.iceGatheringState !== 'complete') await new Promise((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error('本机实时连接地址收集超时')), 8000);
          const ready = () => {
            if (pc.iceGatheringState === 'complete') { clearTimeout(timeout); pc.removeEventListener('icegatheringstatechange', ready); resolve(); }
            if (pc.connectionState === 'closed') { clearTimeout(timeout); reject(new Error('连接已取消')); }
          };
          pc.addEventListener('icegatheringstatechange', ready); ready();
        });
        if (ownGeneration !== generation || !peers.has(value.id) || !matches(expected)) throw new Error('实时预览页面已变化');
        return { id: value.id, sdp: pc.localDescription.sdp, type: pc.localDescription.type };
      } catch (error) { closePeer(value.id); throw error; }
    },
    async revalidate(value) {
      expected = value;
      for (let attempt = 0; attempt < 20; attempt++) {
        const size = stream?.getVideoTracks()[0]?.getSettings();
        if (matches(value) && size?.width === 1280 && size?.height === 720) {
          paused = false; needsIdentity = false;
          stream.getTracks().forEach(track => { track.enabled = true; }); return true;
        }
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      throw new Error('导航后的标签页身份无法验证');
    },
    pause() {
      paused = true; needsIdentity = true;
      if (stream) stream.getTracks().forEach(track => { track.enabled = false; });
    },
    closePeer, reset,
    async stats() {
      return Promise.all([...peers.values()].map(async ({ pc }) =>
        [...(await pc.getStats()).values()].filter(value =>
          ['outbound-rtp', 'codec', 'candidate-pair', 'media-source'].includes(value.type))));
    },
    state() {
      return { ids: [...peers.keys()], capture: Boolean(stream), needsIdentity, error: lastError,
        settings: stream?.getVideoTracks()[0]?.getSettings() || null };
    },
  };
  document.querySelector('#capture').onclick = () => window.NativePreview.capture(window.captureConfig);
})();

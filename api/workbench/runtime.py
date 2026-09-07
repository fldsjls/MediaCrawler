"""Private JSON-lines worker protocol and cooperative operation barrier."""
import asyncio
import contextvars
import functools
import json
import sys
import threading

class Runtime:
    def __init__(self):
        self.output = sys.stdout
        self.loop = asyncio.get_running_loop()
        self.ready = asyncio.Event()
        self.ready.set()
        self.active = 0
        self.reason = 'paused'
        self.acknowledged = False
        self.depth = contextvars.ContextVar('workbench_operation_depth', default=0)
        self.resume_check = None
        self.resuming = False
        self.pause_generation = 0

    def emit(self, kind, **payload):
        self.output.write(json.dumps({'type': kind, **payload}, ensure_ascii=False, default=str) + '\n')
        self.output.flush()

    def pause(self, reason='paused'):
        self.pause_generation += 1
        self.reason = reason
        self.ready.clear()
        self.acknowledged = False
        self.ack()

    def ack(self):
        if not self.ready.is_set() and self.active == 0 and not self.acknowledged:
            self.acknowledged = True
            self.emit('state', state=self.reason)

    async def resume(self):
        if self.resuming or self.ready.is_set():
            return
        self.resuming = True
        generation = self.pause_generation
        self.active += 1
        token = self.depth.set(1)  # validation is the only operation permitted while paused
        try:
            valid = not self.resume_check or await self.resume_check()
            if generation != self.pause_generation:
                return  # a newer takeover/pause superseded this resume request
            if not valid:
                self.emit('state', state='waiting_login')
                return
            self.ready.set()
            self.emit('state', state='running')
        except Exception as exc:
            self.emit('log', level='error', message=f'恢复检查失败：{exc}')
            self.emit('state', state='paused')
        finally:
            self.depth.reset(token)
            self.active -= 1
            self.resuming = False
            self.ack()

    async def wait_login(self):
        self.pause('waiting_login')
        await self.checkpoint()

    async def checkpoint(self):
        # Event.set() wakes existing waiters even when pause() clears it before they
        # resume. Recheck the current state before dispatching a new operation.
        while not self.ready.is_set():
            await self.ready.wait()

    def wrap(self, function):
        @functools.wraps(function)
        async def call(*args, **kwargs):
            if self.depth.get():
                return await function(*args, **kwargs)
            await self.checkpoint()
            self.active += 1
            token = self.depth.set(1)
            try:
                return await function(*args, **kwargs)
            finally:
                self.depth.reset(token)
                self.active -= 1
                self.ack()
        return call

    def listen(self):
        def received(message):
            if message['action'] in ('pause', 'takeover'):
                self.pause()
            elif message['action'] == 'resume':
                asyncio.create_task(self.resume())
        def read():
            for line in sys.stdin:
                try:
                    self.loop.call_soon_threadsafe(received, json.loads(line))
                except (ValueError, RuntimeError):
                    break
        threading.Thread(target=read, daemon=True).start()

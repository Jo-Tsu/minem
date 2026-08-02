from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable, Mapping


class JobRuntimeError(RuntimeError):
    pass


class JobQueueFullError(JobRuntimeError):
    def __init__(self, channel: str):
        super().__init__(f"job queue is full: {channel}")
        self.channel = channel


@dataclass(frozen=True)
class ChannelConfig:
    workers: int = 1
    max_pending: int = 32

    def __post_init__(self):
        if self.workers < 1:
            raise ValueError("channel workers must be positive")
        if self.max_pending < self.workers:
            raise ValueError("max_pending must be at least the worker count")


@dataclass(frozen=True)
class JobSubmission:
    channel: str
    key: str
    future: Future
    duplicate: bool = False


@dataclass
class _Job:
    key: str
    callback: Callable[..., Any]
    args: tuple
    kwargs: dict
    future: Future


class _Channel:
    def __init__(self, name: str, config: ChannelConfig):
        self.name = name
        self.config = config
        self.queue: queue.Queue[_Job | None] = queue.Queue(maxsize=config.max_pending)
        self.lock = threading.RLock()
        self.pending: dict[str, Future] = {}
        self.workers: list[threading.Thread] = []
        self.started = False
        self.stopping = False
        self.completed = 0
        self.failed = 0

    def start(self, worker_target: Callable[["_Channel"], None]) -> None:
        with self.lock:
            if self.started:
                return
            self.started = True
            for index in range(self.config.workers):
                worker = threading.Thread(
                    target=worker_target,
                    args=(self,),
                    name=f"minem-job-{self.name}-{index + 1}",
                    daemon=True,
                )
                self.workers.append(worker)
                worker.start()


class JobRuntime:
    def __init__(self, channels: Mapping[str, ChannelConfig]):
        if not channels:
            raise ValueError("at least one job channel is required")
        self.channels = {
            str(name): _Channel(str(name), config)
            for name, config in channels.items()
        }

    def submit(
        self,
        channel_name: str,
        key: str,
        callback: Callable[..., Any],
        *args,
        **kwargs,
    ) -> JobSubmission:
        channel = self.channels.get(channel_name)
        if not channel:
            raise JobRuntimeError(f"unknown job channel: {channel_name}")
        normalized_key = str(key or "").strip()
        if not normalized_key:
            raise ValueError("job key is required")
        if not callable(callback):
            raise TypeError("job callback must be callable")

        channel.start(self._worker_loop)
        with channel.lock:
            if channel.stopping:
                raise JobRuntimeError(f"job channel is stopping: {channel_name}")
            existing = channel.pending.get(normalized_key)
            if existing:
                return JobSubmission(channel_name, normalized_key, existing, duplicate=True)
            future = Future()
            channel.pending[normalized_key] = future
            job = _Job(normalized_key, callback, args, kwargs, future)
            try:
                channel.queue.put_nowait(job)
            except queue.Full as error:
                channel.pending.pop(normalized_key, None)
                raise JobQueueFullError(channel_name) from error
            return JobSubmission(channel_name, normalized_key, future)

    def _worker_loop(self, channel: _Channel) -> None:
        while True:
            job = channel.queue.get()
            if job is None:
                channel.queue.task_done()
                return
            try:
                if not job.future.set_running_or_notify_cancel():
                    continue
                result = job.callback(*job.args, **job.kwargs)
                job.future.set_result(result)
                with channel.lock:
                    channel.completed += 1
            except BaseException as error:
                job.future.set_exception(error)
                with channel.lock:
                    channel.failed += 1
            finally:
                with channel.lock:
                    channel.pending.pop(job.key, None)
                channel.queue.task_done()

    def snapshot(self) -> dict:
        result = {}
        for name, channel in self.channels.items():
            with channel.lock:
                result[name] = {
                    "workers": channel.config.workers,
                    "maxPending": channel.config.max_pending,
                    "queued": channel.queue.qsize(),
                    "pending": len(channel.pending),
                    "completed": channel.completed,
                    "failed": channel.failed,
                    "started": channel.started,
                }
        return result

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0, timeout)
        while time.monotonic() <= deadline:
            if all(
                channel.queue.unfinished_tasks == 0
                and not channel.pending
                for channel in self.channels.values()
            ):
                return True
            time.sleep(0.01)
        return False

    def shutdown(self, wait: bool = False) -> None:
        for channel in self.channels.values():
            with channel.lock:
                if channel.stopping:
                    continue
                channel.stopping = True
                if not channel.started:
                    continue
                for _ in channel.workers:
                    channel.queue.put(None)
        if wait:
            for channel in self.channels.values():
                for worker in channel.workers:
                    worker.join(timeout=5)

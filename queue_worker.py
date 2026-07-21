import asyncio
from typing import Awaitable, Callable


class GenerationQueue:
    """Bir vaqtda ko'p user rasm so'raganda hech kim xato olmasin deb,
    so'rovlar FIFO navbatga qo'yiladi va bittadan ketma-ket bajariladi.
    Bittasi tugashi (rasm userga yetkazilishi) bilan navbatdagi keyingisi boshlanadi."""

    def __init__(self):
        self.queue: asyncio.Queue[Callable[[], Awaitable[None]]] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self.processing = False

    def start(self):
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    async def _worker(self):
        while True:
            job = await self.queue.get()
            self.processing = True
            try:
                await job()
            except Exception as e:
                print(f"[queue] job bajarishda xato: {e}")
            finally:
                self.processing = False
                self.queue.task_done()

    def peek_position(self) -> int:
        """Hozir navbatga qo'shilsa, sizdan oldin nechta so'rov bo'lishini qaytaradi (0 = navbatdagi keyingisi siz)."""
        return self.queue.qsize() + (1 if self.processing else 0)

    async def enqueue(self, job: Callable[[], Awaitable[None]]):
        await self.queue.put(job)


gen_queue = GenerationQueue()

import asyncio
from typing import Awaitable, Callable

from config import GEN_QUEUE_WORKERS


class GenerationQueue:
    """Bir vaqtda `workers` tagacha rasm generatsiyasi PARALLEL bajariladi.
    Shu sondan ortiq so'rov kelsa, qolganlari FIFO navbatda kutadi. Masalan
    workers=10 bo'lsa: 10 kishi bir vaqtda yozsa - hammasi darhol boshlanadi;
    11-si kelsa - eng oldin bo'shagan workerga navbat bilan tushadi."""

    def __init__(self, workers: int = GEN_QUEUE_WORKERS):
        self.workers = max(1, workers)
        self.queue: asyncio.Queue[Callable[[], Awaitable[None]]] = asyncio.Queue()
        self._worker_tasks: list[asyncio.Task] = []
        self.active = 0  # hozir aynan bajarilayotgan (parallel) joblar soni

    def start(self):
        # allaqachon ishga tushgan bo'lsa qayta boshlamaymiz
        self._worker_tasks = [t for t in self._worker_tasks if not t.done()]
        while len(self._worker_tasks) < self.workers:
            self._worker_tasks.append(asyncio.create_task(self._worker()))

    async def _worker(self):
        while True:
            job = await self.queue.get()
            self.active += 1
            try:
                await job()
            except Exception as e:
                print(f"[queue] job bajarishda xato: {e}")
            finally:
                self.active -= 1
                self.queue.task_done()

    def free_slots(self) -> int:
        return max(0, self.workers - self.active)

    def peek_position(self) -> int:
        """Hozir navbatga qo'shilsa, sizdan oldin nechta so'rov bo'lishini
        qaytaradi (0 = bo'sh worker bor, darhol boshlanadi)."""
        if self.free_slots() > 0:
            return 0
        return self.queue.qsize() + 1

    async def enqueue(self, job: Callable[[], Awaitable[None]]):
        await self.queue.put(job)


gen_queue = GenerationQueue()

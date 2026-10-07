import asyncio
from collections import defaultdict

_user_queues: dict[int, asyncio.Queue] = {}


def get_or_create_queue(user_id: int) -> asyncio.Queue:
    if user_id not in _user_queues:
        _user_queues[user_id] = asyncio.Queue()
    return _user_queues[user_id]


async def put_event_for_user(user_id: int, payload: dict) -> None:
    queue = get_or_create_queue(user_id)
    await queue.put(payload)


def drop_queue(user_id: int) -> None:
    _user_queues.pop(user_id, None)

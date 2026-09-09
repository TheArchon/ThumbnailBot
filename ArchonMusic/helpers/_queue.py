from collections import defaultdict, deque
from typing import Union

from ._dataclass import Media, Track

MediaItem = Union[Media, Track]


class Queue:
    """Per-chat playback queue.

    The first item is always the currently playing item.
    All queue mutations are kept in one place so Skip/Force/Autoplay
    cannot accidentally remove two items.
    """

    def __init__(self):
        self.queues: dict[int, deque[MediaItem]] = defaultdict(deque)

    def add(self, chat_id: int, item: MediaItem) -> int:
        """Append an item and return its 1-based queue position."""
        queue = self.queues[chat_id]
        queue.append(item)
        return len(queue)

    def check_item(
        self, chat_id: int, item_id: str
    ) -> tuple[int, MediaItem | None]:
        """Return (0-based index, item), or (-1, None) if not found."""
        for pos, item in enumerate(self.queues[chat_id]):
            if item.id == item_id:
                return pos, item
        return -1, None

    def force_add(
        self,
        chat_id: int,
        item: MediaItem,
        remove: int | bool = False,
    ) -> None:
        """Put *item* at the front without corrupting the remaining queue.

        The current item is removed first.  ``remove`` can optionally
        remove additional items after the forced item is inserted.
        """
        queue = self.queues[chat_id]

        if queue:
            queue.popleft()

        queue.appendleft(item)

        if isinstance(remove, bool):
            remove_count = 0
        else:
            remove_count = max(0, int(remove))

        # Never remove the newly forced item.
        for _ in range(remove_count):
            if len(queue) > 1:
                queue.rotate(-1)
                queue.popleft()
                queue.rotate(1)

    def get_current(self, chat_id: int) -> MediaItem | None:
        """Return the current item without changing the queue."""
        queue = self.queues[chat_id]
        return queue[0] if queue else None

    def get_next(
        self,
        chat_id: int,
        check: bool = False,
    ) -> MediaItem | None:
        """Advance exactly once and return the new current item.

        With ``check=True`` this is read-only and returns the item after
        the current item.
        """
        queue = self.queues[chat_id]

        if not queue:
            return None

        if check:
            return queue[1] if len(queue) > 1 else None

        queue.popleft()
        return queue[0] if queue else None

    def get_queue(self, chat_id: int) -> list[MediaItem]:
        """Return a snapshot; modifying it will not modify the real queue."""
        return list(self.queues[chat_id])

    def remove_current(self, chat_id: int) -> MediaItem | None:
        """Remove and return the current item."""
        queue = self.queues[chat_id]
        return queue.popleft() if queue else None

    def clear(self, chat_id: int) -> None:
        """Clear the entire queue for this chat."""
        self.queues[chat_id].clear()

    def remove(self, chat_id: int, item_id: str) -> bool:
        """Remove a specific queued item by ID."""
        queue = self.queues[chat_id]

        for index, item in enumerate(queue):
            if item.id == item_id:
                del queue[index]
                return True

        return False

    def __len__(self) -> int:
        return sum(len(items) for items in self.queues.values())
        

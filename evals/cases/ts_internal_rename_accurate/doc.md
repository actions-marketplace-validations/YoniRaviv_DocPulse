# TaskQueue

`TaskQueue` is a FIFO queue for zero-argument callbacks.

| Method | Description |
|--------|-------------|
| `enqueue(task)` | Appends `task` to the end of the queue. |
| `dequeue()` | Runs and removes the oldest task. No-ops when empty. |
| `size` (getter) | Returns the number of pending tasks. |

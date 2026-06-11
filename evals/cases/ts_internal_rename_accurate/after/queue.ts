export class TaskQueue {
  private _items: (() => void)[] = [];

  /** Add a task to the queue. */
  enqueue(task: () => void): void {
    this._items.push(task);
  }

  /** Execute and remove the next task. */
  dequeue(): void {
    const next = this._items.shift();
    if (next) next();
  }

  /** Number of tasks waiting in the queue. */
  get size(): number {
    return this._items.length;
  }
}

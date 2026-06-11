export class TaskQueue {
  private pendingTasks: (() => void)[] = [];

  /** Add a task to the queue. */
  enqueue(task: () => void): void {
    this.pendingTasks.push(task);
  }

  /** Execute and remove the next task. */
  dequeue(): void {
    const next = this.pendingTasks.shift();
    if (next) next();
  }

  /** Number of tasks waiting in the queue. */
  get size(): number {
    return this.pendingTasks.length;
  }
}

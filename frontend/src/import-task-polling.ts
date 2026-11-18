import type { ImportTask } from "./types";

export function startImportTaskPolling(
  load: (signal: AbortSignal) => Promise<ImportTask[]>,
  receive: (tasks: ImportTask[]) => void,
  reportError: (error: unknown) => void
) {
  const controller = new AbortController();
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function poll() {
    let delay = 5000;
    try {
      const tasks = await load(controller.signal);
      if (stopped) return;
      receive(tasks);
      delay = tasks.some((task) => task.status === "queued" || task.status === "running") ? 1200 : 10000;
    } catch (error) {
      if (stopped) return;
      reportError(error);
    }
    if (!stopped) timer = setTimeout(() => void poll(), delay);
  }

  void poll();
  return () => {
    stopped = true;
    controller.abort();
    clearTimeout(timer);
  };
}

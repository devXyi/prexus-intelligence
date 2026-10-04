// Minimal FIFO async mutex: serialises read-modify-write sequences (v1 could lose events
// when two requests interleaved between mutation and save()).
export class Mutex {
  #tail = Promise.resolve();
  run(fn) {
    const result = this.#tail.then(fn, fn);
    this.#tail = result.then(() => undefined, () => undefined);
    return result;
  }
}

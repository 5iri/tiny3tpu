"""Bounded handoff from UART acquisition to a slower display consumer."""
import threading


class LatestResults:
    """Keep one result per mode; verify every response before publishing it.

    Slow rendering may skip displayed frames, but can never queue old frames or
    block the UART producer. Published objects belong to the consumer and must
    not subsequently be mutated by the producer. Errors reach the consumer.
    """
    def __init__(self, producer, keys):
        self.keys = frozenset(keys)
        self.stopped = threading.Event()
        self._condition = threading.Condition()
        self._pending = {}
        self._closed = False
        self._error = None
        self._thread = threading.Thread(target=self._run, args=(producer,), daemon=True)

    def _run(self, producer):
        error = None
        try:
            producer(self)
        except Exception as exception:
            if not self.stopped.is_set():
                error = exception
        finally:
            with self._condition:
                self._error = error
                self._closed = True
                self._condition.notify_all()

    def publish(self, key, result):
        if key not in self.keys:
            raise ValueError(f'Unknown stream mode: {key}')
        with self._condition:
            if not self.stopped.is_set():
                self._pending[key] = result
                self._condition.notify()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *unused):
        self.stopped.set()
        # UART readers check stopped between bounded reads. A disconnected
        # device cannot prevent the display process from shutting down.
        self._thread.join(timeout=2)
        if self._thread.is_alive() and unused[0] is None:
            raise RuntimeError('UART worker did not stop within two seconds')

    def __iter__(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending or self._closed)
                pending, self._pending = self._pending, {}
                closed, error = self._closed, self._error
            if pending:
                yield pending
            if closed:
                if error is not None:
                    raise error
                return


def read_exact(uart, size, *, deadline, stop=None):
    """Read with one transaction deadline and a bounded serial read timeout."""
    import time
    data = bytearray()
    while len(data) < size:
        if stop is not None and stop.is_set():
            raise InterruptedError('UART acquisition stopped')
        if time.monotonic() >= deadline:
            raise TimeoutError('Board response timed out')
        data.extend(uart.read(size - len(data)))
    return bytes(data)


def read_magic(uart, magic, *, deadline, stop=None):
    """Discard boot noise without allowing it to extend the deadline."""
    found = read_exact(uart, len(magic), deadline=deadline, stop=stop)
    while found != magic:
        found = found[1:] + read_exact(uart, 1, deadline=deadline, stop=stop)

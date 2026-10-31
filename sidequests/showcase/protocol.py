"""Demo packet client over UART; no model execution on the host."""
import struct
import time

import numpy as np

try:
    from .stream import read_exact, read_magic
except ImportError:  # Direct invocation of scripts in this directory.
    from stream import read_exact, read_magic


COMPACT_FLAG = 0x80000000


def transact(uart, sequence, mode, repeats=1, *, stop=None, timeout=30, compact=False):
    """Receive exact float words, optionally negotiating packed banana coordinates.

    The compact representation stores three signed bases and unsigned 16-bit
    deltas. It changes only the wire encoding; checksums cover decoded words.
    Legacy firmware rejects the flagged request before changing banana state.
    """
    if compact and mode != 3:
        raise ValueError('Compact UART encoding is only defined for banana mode 3')
    start = time.perf_counter(); deadline = time.monotonic() + timeout
    request_bytes = 0; response_bytes_total = 0; legacy_retry = False
    requested_compact = compact
    def exact(size):
        return read_exact(uart, size, deadline=deadline, stop=stop)
    while True:
        if stop is not None and stop.is_set():
            raise InterruptedError('UART acquisition stopped')
        uart.write(b'IFQ1' + struct.pack('<III', sequence, mode | (COMPACT_FLAG if compact else 0), repeats))
        request_bytes += 16
        # Serial.write submits the request. A blocking flush can stall shutdown
        # indefinitely on a disconnected USB adapter.
        read_magic(uart, b'IFR1', deadline=deadline, stop=stop)
        seq, status, cycles, calls, encoded_words, checksum = struct.unpack('<IiIIII', exact(24))
        encoded_compact = bool(encoded_words & COMPACT_FLAG)
        words = encoded_words & ~COMPACT_FLAG
        if seq != sequence or words > 613:
            raise RuntimeError('Bad inference response header')
        if encoded_compact:
            if not compact or status or words < 4 or (words - 1) % 3:
                raise RuntimeError('Bad compact coordinate header')
            raw = exact(16 + (words - 1) * 2)
            bases = np.frombuffer(raw[4:16], dtype='<i4').astype(np.int64)
            offsets = np.frombuffer(raw[16:], dtype='<u2').astype(np.int64).reshape(-1, 3)
            coordinates = bases + offsets
            if (coordinates < -2147483648).any() or (coordinates > 2147483647).any():
                raise RuntimeError('Compact coordinate exceeds int32 range')
            data = np.empty(words, dtype='<f4')
            data[:1] = np.frombuffer(raw[:4], dtype='<f4')
            data[1:] = coordinates.ravel()
            if not np.array_equal(data[1:].astype(np.float64), coordinates.ravel()):
                raise RuntimeError('Compact coordinates are not exactly representable as float32')
        else:
            raw = exact(words * 4)
            data = np.frombuffer(raw, dtype='<f4').copy()
        got = int(np.bitwise_xor.reduce(data.view(np.uint32))) if words else 0
        if got != checksum:
            raise RuntimeError('Inference response checksum mismatch')
        response_bytes = 28 + len(raw); response_bytes_total += response_bytes
        if compact and status == -1 and words == 0 and calls == 0:
            compact = False; legacy_retry = True
            continue
        roundtrip_ms = (time.perf_counter() - start) * 1000
        record = dict(sequence=seq, mode=mode, status=status, cycles=cycles,
                    compute_ms=cycles / 100000., backend_calls=calls, words=words,
                    transport='uart', roundtrip_ms=roundtrip_ms,
                    outside_compute_ms=max(0., roundtrip_ms - cycles / 100000.),
                    response_bytes=response_bytes, transaction_response_bytes=response_bytes_total,
                    request_bytes=request_bytes, compact=encoded_compact,
                    compact_supported=(not legacy_retry) if requested_compact else None)
        record['uart_wire_min_ms'] = (request_bytes + response_bytes_total) * 10 / uart.baudrate * 1000
        return record, data

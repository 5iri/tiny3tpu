#!/usr/bin/env python3
"""Deterministic host-pipeline and wire-format checks; no serial device needed."""
from collections import deque
from pathlib import Path
import struct
import sys
import threading
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequests.showcase.protocol import COMPACT_FLAG, transact
from sidequests.showcase.stream import LatestResults


class StreamTests(unittest.TestCase):
    def test_slow_display_drops_old_frames_without_dropping_modes(self):
        first = threading.Event(); continue_acquisition = threading.Event(); complete = threading.Event()
        checked = []
        def acquire(stream):
            stream.publish('banana', 0); first.set()
            if not continue_acquisition.wait(2): raise RuntimeError('Test consumer did not start')
            for sequence in range(1, 1001):
                checked.append(sequence)  # Verification happens before publishing.
                stream.publish('banana', sequence)
                if sequence == 2: stream.publish('inference', 'rare verified sample')
            complete.set()
        with LatestResults(acquire, ['banana', 'inference']) as stream:
            self.assertTrue(first.wait(2))
            iterator = iter(stream); self.assertEqual(next(iterator), {'banana': 0})
            continue_acquisition.set()
            # Emulate arbitrarily slow rendering, using a gate instead of sleep.
            self.assertTrue(complete.wait(2))
            self.assertEqual(len(stream._pending), 2)
            self.assertEqual(list(iterator), [{'banana': 1000, 'inference': 'rare verified sample'}])
        self.assertEqual(checked, list(range(1, 1001)))
        self.assertFalse(stream._thread.is_alive())

    def test_worker_exception_arrives_after_last_valid_result(self):
        error = ValueError('Bad checksum')
        def acquire(stream):
            stream.publish(0, 'verified')
            raise error
        with LatestResults(acquire, [0]) as stream:
            iterator = iter(stream)
            self.assertEqual(next(iterator), {0: 'verified'})
            with self.assertRaisesRegex(ValueError, 'Bad checksum'):
                next(iterator)

    def test_invalid_mode_is_not_silently_dropped(self):
        with LatestResults(lambda stream: stream.publish('wrong', 1), ['right']) as stream:
            with self.assertRaisesRegex(ValueError, 'Unknown stream mode'):
                list(stream)

    def test_early_display_exit_stops_and_joins_worker(self):
        closed = threading.Event()
        def acquire(stream):
            try:
                stream.publish(0, 1)
                stream.stopped.wait(2)
            finally: closed.set()
        with LatestResults(acquire, [0]) as stream:
            self.assertEqual(next(iter(stream)), {0: 1})
        self.assertTrue(closed.is_set())
        self.assertFalse(stream._thread.is_alive())

    def test_empty_producer_terminates(self):
        with LatestResults(lambda stream: None, [0]) as stream:
            self.assertEqual(list(stream), [])


class FakeUART:
    baudrate = 921600
    def __init__(self, *responses, on_read=None):
        self.responses = deque(responses); self.incoming = bytearray(); self.requests = []; self.on_read = on_read
    def write(self, request):
        self.requests.append(request)
        if self.responses: self.incoming.extend(self.responses.popleft())
        return len(request)
    def read(self, size):
        if self.on_read: self.on_read()
        size = min(size, 7)  # Exercise headers and words split across reads.
        result = bytes(self.incoming[:size]); del self.incoming[:size]
        return result


def response(data=(), *, sequence=9, status=0, calls=0, raw=None, words=None, checksum=None):
    data = np.asarray(data, dtype='<f4')
    if checksum is None: checksum = int(np.bitwise_xor.reduce(data.view(np.uint32))) if data.size else 0
    if words is None: words = data.size
    return b'IFR1' + struct.pack('<IiIIII', sequence, status, 12345, calls, words, checksum) + (data.tobytes() if raw is None else raw)


def compact_response(bases, offsets, angle=.125, **kwargs):
    bases = np.asarray(bases, dtype='<i4'); offsets = np.asarray(offsets, dtype='<u2')
    data = np.concatenate((np.array([angle], dtype='<f4'), (bases.astype(np.int64) + offsets).ravel().astype('<f4')))
    raw = struct.pack('<f', angle) + bases.tobytes() + offsets.tobytes()
    return response(data, words=COMPACT_FLAG | data.size, raw=raw, **kwargs), data


class ProtocolTests(unittest.TestCase):
    def test_raw_noise_partial_reads_and_wire_accounting(self):
        expected = np.array([1., -2.5, -0.], dtype='<f4')
        uart = FakeUART(b'boot noise\n' + response(expected))
        rec, data = transact(uart, 9, 0)
        np.testing.assert_array_equal(data.view(np.uint32), expected.view(np.uint32))
        self.assertEqual(rec['response_bytes'], 40)
        self.assertEqual(rec['request_bytes'], 16)
        self.assertAlmostEqual(rec['uart_wire_min_ms'], 56 * 10 / uart.baudrate * 1000)
        self.assertIsNone(rec['compact_supported'])

    def test_compact_signed_bases_max_offsets_and_tail(self):
        raw, expected = compact_response([-123456, 40000, -8], [[0, 65535, 8], [65535, 0, 65535]])
        uart = FakeUART(raw); rec, data = transact(uart, 9, 3, compact=True)
        np.testing.assert_array_equal(data.view(np.uint32), expected.view(np.uint32))
        self.assertEqual(rec['response_bytes'], 28 + 16 + 12)
        self.assertTrue(rec['compact']); self.assertTrue(rec['compact_supported'])
        self.assertEqual(struct.unpack('<III', uart.requests[0][4:]), (9, COMPACT_FLAG | 3, 1))

    def test_full_banana_compact_packet(self):
        offsets = np.arange(612, dtype=np.uint16).reshape(204, 3)
        raw, expected = compact_response([-40000, -50000, 70000], offsets)
        rec, data = transact(FakeUART(raw), 9, 3, compact=True)
        self.assertEqual(rec['words'], 613)
        self.assertEqual(rec['response_bytes'], 1268)
        np.testing.assert_array_equal(data.view(np.uint32), expected.view(np.uint32))

    def test_legacy_rejection_retries_once_without_advancing_sequence(self):
        expected = [0.1, 1., 2., 3.]
        uart = FakeUART(response(status=-1), response(expected))
        rec, data = transact(uart, 9, 3, compact=True)
        self.assertFalse(rec['compact_supported']); self.assertFalse(rec['compact'])
        self.assertEqual(len(uart.requests), 2)
        self.assertEqual(struct.unpack('<III', uart.requests[1][4:]), (9, 3, 1))
        self.assertEqual(rec['response_bytes'], 44)
        self.assertEqual(rec['transaction_response_bytes'], 72)
        self.assertEqual(rec['request_bytes'], 32)
        self.assertAlmostEqual(rec['uart_wire_min_ms'], 104 * 10 / uart.baudrate * 1000)
        np.testing.assert_array_equal(data, np.array(expected, dtype=np.float32))

    def test_supported_firmware_may_fall_back_to_exact_raw(self):
        rec, data = transact(FakeUART(response([.1, .5, .75, 1.25])), 9, 3, compact=True)
        self.assertTrue(rec['compact_supported']); self.assertFalse(rec['compact'])
        self.assertEqual(data.size, 4)

    def test_repeated_legacy_rejection_does_not_loop(self):
        uart = FakeUART(response(status=-1), response(status=-1))
        rec, _ = transact(uart, 9, 3, compact=True)
        self.assertEqual(rec['status'], -1); self.assertEqual(len(uart.requests), 2)

    def test_bad_checksum_and_sequence_fail(self):
        with self.assertRaisesRegex(RuntimeError, 'checksum'):
            transact(FakeUART(response([1.], checksum=0)), 9, 0)
        with self.assertRaisesRegex(RuntimeError, 'header'):
            transact(FakeUART(response(sequence=8)), 9, 0)
        raw, _ = compact_response([1, 2, 3], [[1, 2, 3]], checksum=0)
        with self.assertRaisesRegex(RuntimeError, 'checksum'):
            transact(FakeUART(raw), 9, 3, compact=True)

    def test_malformed_compact_counts_and_unsolicited_format_fail(self):
        for words in (0, 1, 2, 3, 5, 614):
            with self.subTest(words=words), self.assertRaisesRegex(RuntimeError, 'header'):
                transact(FakeUART(response(words=COMPACT_FLAG | words, raw=b'')), 9, 3, compact=True)
        raw, _ = compact_response([0, 0, 0], [[0, 0, 0]])
        with self.assertRaisesRegex(RuntimeError, 'header'):
            transact(FakeUART(raw), 9, 3)
        with self.assertRaises(ValueError): transact(FakeUART(), 9, 0, compact=True)

    def test_invalid_compact_ranges_fail_before_float_rounding(self):
        for base, offset, message in ((2147483647, 1, 'int32'), (16777216, 1, 'float32')):
            raw, _ = compact_response([base, 0, 0], [[offset, 0, 0]])
            with self.subTest(base=base), self.assertRaisesRegex(RuntimeError, message):
                transact(FakeUART(raw), 9, 3, compact=True)

    def test_stop_before_request_and_during_partial_read(self):
        stop = threading.Event(); stop.set(); uart = FakeUART()
        with self.assertRaises(InterruptedError): transact(uart, 9, 0, stop=stop)
        self.assertEqual(uart.requests, [])
        stop.clear(); uart = FakeUART(response([1.]), on_read=stop.set)
        with self.assertRaises(InterruptedError): transact(uart, 9, 0, stop=stop)

    def test_noise_cannot_extend_transaction_deadline(self):
        clock = [0.]
        def advance(): clock[0] += .1
        uart = FakeUART(b'noise' * 10000, on_read=advance)
        with patch('time.monotonic', side_effect=lambda: clock[0]), self.assertRaises(TimeoutError):
            transact(uart, 9, 0, timeout=.5)
        self.assertLess(clock[0], .7)

    def test_truncated_response_times_out(self):
        clock = [0.]
        def advance(): clock[0] += .1
        uart = FakeUART(response([1.])[:-2], on_read=advance)
        with patch('time.monotonic', side_effect=lambda: clock[0]), self.assertRaises(TimeoutError):
            transact(uart, 9, 0, timeout=1)


if __name__ == '__main__': unittest.main()

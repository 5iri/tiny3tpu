#!/usr/bin/env python3
"""Loopback-only checks for UDP framing, exact replies, timeouts and no retries."""
from contextlib import contextmanager
from pathlib import Path
import socket
import struct
import subprocess
import json
import sys
import threading
import time
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequests.showcase.udp_transport import (HEADER, MAGIC, MAX_CHUNK, MAX_MESSAGE,
    DatagramError, RemoteError, LatencyWindow, Reassembly, UDPTransport, encode_chunk, open_transport)
from sidequests.showcase.protocol import COMPACT_FLAG, transact
from sidequests.showcase.stream import read_exact


@contextmanager
def endpoint(handler):
    """Run an explicitly loopback-bound peer; expose received requests."""
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(('127.0.0.1', 0)); server.settimeout(.05)
    stop = threading.Event(); received = []; errors = []
    def run():
        while not stop.is_set():
            try: packet, peer = server.recvfrom(8192)
            except socket.timeout: continue
            except OSError:
                if not stop.is_set(): raise
                return
            received.append(packet)
            try:
                for reply in handler(packet): server.sendto(reply, peer)
            except Exception as exc:
                errors.append(exc); return
    worker = threading.Thread(target=run, daemon=True); worker.start()
    try: yield f'127.0.0.1:{server.getsockname()[1]}', received
    finally:
        stop.set(); worker.join(1); server.close()
        if worker.is_alive(): raise RuntimeError('Loopback test server did not stop')
        if errors: raise errors[0]


def chunks(transaction, data):
    return [encode_chunk(transaction, len(data), offset, data[offset:offset+MAX_CHUNK])
            for offset in range(0, len(data), MAX_CHUNK)]


def inference(data, *, sequence=9, calls=0, compact=False):
    data = np.asarray(data, dtype='<f4')
    checksum = int(np.bitwise_xor.reduce(data.view(np.uint32)))
    header = b'IFR1' + struct.pack('<IiIIII', sequence, 0, 12345, calls,
                                 len(data) | (COMPACT_FLAG if compact else 0), checksum)
    if not compact: return header + data.tobytes()
    coords = data[1:].astype(np.int32).reshape(-1, 3); bases = coords.min(axis=0)
    return header + data[:1].tobytes() + bases.astype('<i4').tobytes() + (coords-bases).astype('<u2').tobytes()


class ReassemblyTests(unittest.TestCase):
    def test_out_of_order_identical_duplicates_and_maximum_size(self):
        data = bytes(i % 251 for i in range(MAX_MESSAGE)); packets = chunks(42, data)
        assembly = Reassembly(42)
        self.assertIsNone(assembly.add(packets[2]))
        self.assertIsNone(assembly.add(packets[0]))
        self.assertIsNone(assembly.add(packets[0]))
        self.assertEqual(assembly.add(packets[1]), data)
        self.assertEqual(assembly.duplicates, 1)
        self.assertEqual(assembly.datagrams, 4)
        self.assertEqual(len(assembly.data), MAX_MESSAGE)

    def test_stale_transaction_does_not_allocate_or_change_response(self):
        assembly = Reassembly(2)
        self.assertIsNone(assembly.add(encode_chunk(1, 3, 0, b'old')))
        self.assertIsNone(assembly.data)
        self.assertEqual(assembly.add(encode_chunk(2, 3, 0, b'new')), b'new')
        self.assertEqual(assembly.ignored, 1)

    def test_overlaps_accept_only_identical_bytes(self):
        assembly = Reassembly(1)
        assembly.add(encode_chunk(1, 8, 0, b'abcd'))
        self.assertEqual(assembly.add(encode_chunk(1, 8, 2, b'cdefgh')), b'abcdefgh')
        bad = Reassembly(1); bad.add(encode_chunk(1, 8, 0, b'abcd'))
        with self.assertRaisesRegex(DatagramError, 'Conflicting'):
            bad.add(encode_chunk(1, 8, 2, b'XXefgh'))

    def test_invalid_envelopes_fail_before_unbounded_allocation(self):
        cases = [b'T3U1', HEADER.pack(b'bad!', 1, 1, 0, 1)+b'x',
                 HEADER.pack(MAGIC, 1, 4097, 0, 1)+b'x',
                 HEADER.pack(MAGIC, 1, 0, 0, 0),
                 HEADER.pack(MAGIC, 1, 4, 3, 2)+b'ab',
                 HEADER.pack(MAGIC, 1, 4, 0, 3)+b'ab',
                 HEADER.pack(MAGIC, 1, 1401, 0, 1401)+b'x'*1401]
        for packet in cases:
            with self.subTest(packet=packet[:20]), self.assertRaises(DatagramError):
                Reassembly(1).add(packet)

    def test_changed_total_rejected(self):
        assembly = Reassembly(1); assembly.add(encode_chunk(1, 4, 0, b'ab'))
        with self.assertRaisesRegex(DatagramError, 'Inconsistent'):
            assembly.add(encode_chunk(1, 5, 2, b'cde'))


class LoopbackTests(unittest.TestCase):
    def test_echo_benchmark_cli_reports_transport_scope_and_percentiles(self):
        def handler(request):
            transaction = HEADER.unpack_from(request)[1]; payload = request[HEADER.size:]
            if payload == b'EHQ1':
                return chunks(transaction, struct.pack('<4sIIII', b'EHR1', 1, 0, 0, 0))
            self.assertEqual(payload[:4], b'ECQ1')
            return chunks(transaction, b'ECR1'+payload[4:])
        with endpoint(handler) as (address, requests):
            result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]/'sidequests/showcase/udp_transport.py'),
                '--udp', address, '--udp-bind-port', '0', '--requests', '3', '--payload-bytes', '1396'],
                capture_output=True, text=True, check=True, timeout=5)
            report = json.loads(result.stdout)
            self.assertIn('no inference', report['scope'])
            self.assertEqual(report['requests'], 3)
            self.assertEqual(report['latency']['samples'], 3)
            self.assertEqual(report['latency']['compute_ms']['p99'], 0)
            self.assertGreater(report['latency']['roundtrip_ms']['p50'], 0)
            self.assertEqual(len(requests), 4)

    def test_session_reconnect_uses_next_accepted_transaction(self):
        def handler(request):
            transaction = HEADER.unpack_from(request)[1]
            if request[HEADER.size:] == b'EHQ1':
                return chunks(transaction, struct.pack('<4sIIII', b'EHR1', 1, 1, 0xffffffff, 1))
            self.assertEqual(transaction, 0)
            return chunks(transaction, inference([1.]))
        with endpoint(handler) as (address, requests), open_transport(None, udp=address, udp_bind_port=0) as transport:
            self.assertEqual(transport.session['last_transaction'], 0xffffffff)
            transact(transport, 9, 0)
            self.assertEqual(len(requests), 2)

    def test_unclaimed_session_retains_random_application_id(self):
        def handler(request):
            return chunks(HEADER.unpack_from(request)[1], struct.pack('<4sIIII', b'EHR1', 1, 0, 0, 0))
        with endpoint(handler) as (address, _), UDPTransport(address, transaction=41) as transport:
            self.assertEqual(transport.negotiate()['ownership'], 0)
            self.assertEqual(transport.transaction, 42)

    def test_other_peer_session_is_rejected_without_app_request(self):
        def handler(request):
            return chunks(HEADER.unpack_from(request)[1], struct.pack('<4sIIII', b'EHR1', 1, 2, 5, 1))
        with endpoint(handler) as (address, requests):
            with self.assertRaisesRegex(RemoteError, 'another peer'):
                open_transport(None, udp=address, udp_bind_port=0)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0][HEADER.size:], b'EHQ1')

    def test_endpoint_error_explains_stale_request_without_retry(self):
        def handler(request):
            return chunks(HEADER.unpack_from(request)[1], struct.pack('<4sII', b'EER1', 2, 123))
        with endpoint(handler) as (address, requests), UDPTransport(address) as transport:
            with self.assertRaisesRegex(RemoteError, 'Stale.*not retried'):
                transact(transport, 9, 0)
            self.assertEqual(len(requests), 1)

    def test_raw_banana_full_packet_out_of_order_and_duplicate(self):
        expected = np.arange(613, dtype=np.float32) / 2
        def handler(request):
            transaction = HEADER.unpack_from(request)[1]
            self.assertEqual(request[HEADER.size:], b'IFQ1'+struct.pack('<III', 9, 3, 1))
            packets = chunks(transaction, inference(expected))
            return [chunks(transaction-1, b'stale')[0], packets[1], packets[1], packets[0]]
        with endpoint(handler) as (address, requests), UDPTransport(address, transaction=100) as transport:
            record, actual = transact(transport, 9, 3)
            np.testing.assert_array_equal(actual.view(np.uint32), expected.view(np.uint32))
            self.assertEqual(record['transport'], 'udp')
            self.assertEqual(record['response_bytes'], 2480)
            self.assertEqual(record['udp_response_datagrams'], 3)
            self.assertEqual(record['udp_duplicate_datagrams'], 1)
            self.assertEqual(record['udp_ignored_transactions'], 1)
            self.assertNotIn('uart_wire_min_ms', record)
            self.assertEqual(len(requests), 1)

    def test_compact_banana_full_packet_preserves_every_float_bit(self):
        expected = np.concatenate((np.array([.125], np.float32), np.arange(612, dtype=np.float32)-40000))
        def handler(request):
            transaction = HEADER.unpack_from(request)[1]
            self.assertEqual(struct.unpack_from('<I', request, HEADER.size+8)[0], 3|COMPACT_FLAG)
            return chunks(transaction, inference(expected, compact=True))
        with endpoint(handler) as (address, _), UDPTransport(address) as transport:
            record, actual = transact(transport, 9, 3, compact=True)
            np.testing.assert_array_equal(actual.view(np.uint32), expected.view(np.uint32))
            self.assertEqual(record['response_bytes'], 1268)
            self.assertEqual(record['udp_response_datagrams'], 1)

    def test_cloth_packet_keeps_inner_sequence_steps_and_checksum(self):
        coords = np.arange(84, dtype='<i4')-21
        checksum = int(np.bitwise_xor.reduce(coords.view(np.uint32)))
        packet = b'CLR3'+struct.pack('<8I', 9, 0, 35000, 28, checksum, 8000000, 2, 0)+coords.tobytes()
        request = b'CLQ3'+struct.pack('<II', 9, 258)
        def handler(data):
            self.assertEqual(data[HEADER.size:], request)
            return chunks(HEADER.unpack_from(data)[1], packet)
        with endpoint(handler) as (address, _), UDPTransport(address) as transport:
            transport.write(request)
            actual = read_exact(transport, len(packet), deadline=time.monotonic()+1)
            transport.assert_consumed(); self.assertEqual(actual, packet)

    def test_loss_times_out_without_retry_or_reuse_of_outstanding_transaction(self):
        with endpoint(lambda request: []) as (address, requests), UDPTransport(address, poll_timeout=.01) as transport:
            with self.assertRaises(TimeoutError): transact(transport, 9, 3, timeout=.04)
            self.assertEqual(len(requests), 1)
            with self.assertRaisesRegex(RuntimeError, 'outstanding'): transport.write(b'next')
            self.assertEqual(len(requests), 1)

    def test_stop_during_missing_reply(self):
        stop = threading.Event()
        def handler(request): stop.set(); return []
        with endpoint(handler) as (address, requests), UDPTransport(address, poll_timeout=.01) as transport:
            with self.assertRaises(InterruptedError): transact(transport, 9, 3, stop=stop, timeout=1)
            self.assertEqual(len(requests), 1)

    def test_extra_inner_bytes_rejected(self):
        def handler(request): return chunks(HEADER.unpack_from(request)[1], inference([1.])+b'extra')
        with endpoint(handler) as (address, _), UDPTransport(address) as transport:
            with self.assertRaisesRegex(DatagramError, 'trailing'): transact(transport, 9, 0)

    def test_sequence_and_checksum_validation_remain_active(self):
        for wrong in (inference([1.], sequence=10), inference([1.])[:-1]+b'\xff'):
            with self.subTest(wrong=wrong):
                with endpoint(lambda request: chunks(HEADER.unpack_from(request)[1], wrong)) as (address, requests), UDPTransport(address) as transport:
                    with self.assertRaises(RuntimeError): transact(transport, 9, 0)
                    self.assertEqual(len(requests), 1)

    def test_repeated_echo_transactions_wrap_and_preserve_exact_bytes(self):
        payload = b'ECQ1'+bytes(range(256))
        def handler(request):
            self.assertEqual(request[HEADER.size:], payload)
            return chunks(HEADER.unpack_from(request)[1], b'ECR1'+payload[4:])
        with endpoint(handler) as (address, requests), UDPTransport(address, transaction=0xffffffff) as transport:
            for _ in range(2):
                transport.write(payload)
                actual = read_exact(transport, len(payload), deadline=time.monotonic()+1)
                transport.assert_consumed(); self.assertEqual(actual, b'ECR1'+payload[4:])
            self.assertEqual([HEADER.unpack_from(r)[1] for r in requests], [0xffffffff, 0])

    def test_oversized_request_does_not_send(self):
        with endpoint(lambda request: []) as (address, requests), UDPTransport(address) as transport:
            with self.assertRaises(ValueError): transport.write(b'x'*(MAX_CHUNK+1))
            self.assertEqual(requests, [])


class LatencyTests(unittest.TestCase):
    def test_rolling_percentiles_and_compute_separation(self):
        window = LatencyWindow(3)
        for value in (1., 2., 3., 4.): window.observe(value, value/2)
        summary = window.summary()
        self.assertEqual(summary['samples'], 3)
        self.assertEqual(summary['roundtrip_ms']['p50'], 3.)
        self.assertAlmostEqual(summary['roundtrip_ms']['p95'], 3.9)
        self.assertAlmostEqual(summary['roundtrip_ms']['p99'], 3.98)
        self.assertEqual(summary['compute_ms']['p50'], 1.5)
        self.assertEqual(summary['outside_compute_ms']['p50'], 1.5)
        self.assertEqual(len(window.samples), 3)


if __name__ == '__main__': unittest.main()

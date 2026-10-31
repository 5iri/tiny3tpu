"""Bounded UDP transport for the existing demo packets; never retries a request.

Wire header (little endian): 'T3U1', transaction, total bytes, offset, chunk bytes.
A request is one datagram; replies may arrive in any order in <=1400-byte chunks.
The FPGA must suppress duplicate/stale requests before advancing application state.
EHQ1/EHR1 reads version, peer ownership, last accepted transaction and flags.
The fixed default source port 9002 permits same-peer reconnect; changing peers
requires a firmware reset in v1. ECQ1/ECR1 echoes bytes without running a model.
"""
from collections import deque
import argparse
import json
import math
import secrets
import socket
import struct
import time

MAGIC = b'T3U1'
HEADER = struct.Struct('<4sIIII')
MAX_CHUNK = 1400
MAX_MESSAGE = 4096
MAX_DATAGRAM = HEADER.size + MAX_CHUNK


class DatagramError(RuntimeError):
    pass


class RemoteError(DatagramError):
    pass


def encode_chunk(transaction, total, offset, payload):
    payload = bytes(payload)
    if not 0 <= transaction <= 0xffffffff:
        raise ValueError('Transaction must fit uint32')
    if not 1 <= total <= MAX_MESSAGE or not 1 <= len(payload) <= MAX_CHUNK or offset < 0 or offset + len(payload) > total:
        raise ValueError('Invalid UDP chunk bounds')
    return HEADER.pack(MAGIC, transaction, total, offset, len(payload)) + payload


class Reassembly:
    """One fixed-size response; conflicting overlaps are protocol errors."""
    def __init__(self, transaction):
        self.transaction = transaction
        self.data = None
        self.present = None
        self.received = 0
        self.datagrams = 0
        self.duplicates = 0
        self.payload_bytes = 0
        self.ignored = 0

    def add(self, packet):
        if len(packet) < HEADER.size:
            raise DatagramError('Truncated UDP envelope')
        magic, transaction, total, offset, size = HEADER.unpack_from(packet)
        if magic != MAGIC:
            raise DatagramError('Unknown UDP envelope magic')
        if transaction != self.transaction:
            self.ignored += 1
            return None
        if len(packet) > MAX_DATAGRAM or size != len(packet) - HEADER.size or not 1 <= size <= MAX_CHUNK:
            raise DatagramError('Invalid UDP chunk length')
        if not 1 <= total <= MAX_MESSAGE or offset + size > total:
            raise DatagramError('Invalid UDP response bounds')
        if self.data is None:
            self.data = bytearray(total); self.present = bytearray(total)
        elif total != len(self.data):
            raise DatagramError('Inconsistent UDP response size')
        self.datagrams += 1; self.payload_bytes += len(packet)
        new_bytes = 0
        for i, value in enumerate(packet[HEADER.size:], offset):
            if self.present[i]:
                if self.data[i] != value:
                    raise DatagramError('Conflicting duplicate UDP response bytes')
            else:
                self.present[i] = 1; self.data[i] = value; new_bytes += 1
        if not new_bytes: self.duplicates += 1
        self.received += new_bytes
        return bytes(self.data) if self.received == len(self.data) else None


class UDPTransport:
    """Serial-like read/write interface with a single outstanding transaction.

    A timeout is ambiguous for stateful inference: the board may have completed
    the request. The caller must stop, rather than silently send it again.
    """
    transport = 'udp'
    baudrate = None

    def __init__(self, endpoint, *, bind_port=0, transaction=None, poll_timeout=.1):
        host, separator, port = endpoint.rpartition(':')
        if not separator or not host:
            raise ValueError('UDP endpoint must be IPv4-address:port')
        port = int(port)
        if not 1 <= port <= 65535 or not 0 <= bind_port <= 65535:
            raise ValueError('UDP port out of range')
        if not 0 < poll_timeout <= 1:
            raise ValueError('UDP poll timeout must be in (0, 1] seconds')
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind(('0.0.0.0', bind_port))
            self.socket.connect((host, port))
        except Exception:
            self.socket.close(); raise
        self.poll_timeout = poll_timeout
        self.transaction = secrets.randbits(32) if transaction is None else transaction
        if not 0 <= self.transaction <= 0xffffffff:
            self.socket.close(); raise ValueError('Transaction must fit uint32')
        self._assembly = None
        self._buffer = b''
        self._offset = 0
        self._started = 0.
        self._request_bytes = 0
        self.last_metrics = {}
        self.session = None

    def __enter__(self): return self
    def __exit__(self, *unused): self.close()
    def close(self): self.socket.close()

    def negotiate(self, *, timeout=2, stop=None):
        """Read ownership/last transaction without changing board state.

        Firmware v1 retains one peer until reset. Keeping the local source port
        lets a restarted viewer resume after the last accepted application
        request, including a request whose response was lost.
        """
        try:
            from .stream import read_exact
        except ImportError:
            from stream import read_exact
        if stop is not None and stop.is_set():
            raise InterruptedError('UDP acquisition stopped')
        self.write(b'EHQ1')
        reply = read_exact(self, 20, deadline=time.monotonic()+timeout, stop=stop)
        self.assert_consumed()
        magic, version, ownership, last_transaction, flags = struct.unpack('<4sIIII', reply)
        if magic != b'EHR1' or version != 1 or ownership not in (0, 1, 2) or flags & ~1:
            raise DatagramError('Unsupported UDP session response')
        if ownership == 2:
            raise RemoteError('UDP firmware is owned by another peer; v1 requires the same host/source port or a firmware reset')
        if ownership == 0 and flags:
            raise DatagramError('Unclaimed UDP session has a previous transaction')
        if ownership == 1 and flags & 1:
            self.transaction = (last_transaction + 1) & 0xffffffff
        self.session = dict(protocol_version=version, ownership=ownership,
                            last_transaction=last_transaction if flags & 1 else None,
                            local_port=self.socket.getsockname()[1])
        return dict(self.session)

    def reset_input_buffer(self):
        if self._assembly is not None or self._offset < len(self._buffer):
            raise RuntimeError('Cannot discard an outstanding UDP transaction')
        self.socket.setblocking(False)
        try:
            for _ in range(256): self.socket.recv(MAX_DATAGRAM + 1)
        except BlockingIOError:
            pass
        finally:
            self.socket.settimeout(self.poll_timeout)

    def write(self, data):
        if self._assembly is not None or self._offset < len(self._buffer):
            raise RuntimeError('Only one outstanding UDP transaction is allowed')
        data = bytes(data)
        if not 1 <= len(data) <= MAX_CHUNK:
            raise ValueError('UDP request must fit one <=1400-byte chunk')
        transaction = self.transaction
        self.transaction = (transaction + 1) & 0xffffffff
        packet = encode_chunk(transaction, len(data), 0, data)
        self._request_bytes = len(packet)
        self._assembly = Reassembly(transaction); self._buffer = b''; self._offset = 0
        self.last_metrics = {}; self._started = time.perf_counter()
        self.socket.settimeout(self.poll_timeout)
        try:
            if self.socket.send(packet) != len(packet):
                raise DatagramError('Incomplete UDP request send')
        except Exception:
            self._assembly = None; raise
        return len(data)

    def read(self, size):
        if size <= 0: return b''
        if self._offset < len(self._buffer):
            data = self._buffer[self._offset:self._offset + size]; self._offset += len(data)
            return data
        if self._assembly is None:
            raise DatagramError('UDP response ended before the expected inner packet')
        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            self.socket.settimeout(max(.000001, deadline - time.monotonic()))
            try: packet = self.socket.recv(MAX_DATAGRAM + 1)
            except socket.timeout: return b''
            complete = self._assembly.add(packet)
            if complete is not None:
                assembly = self._assembly
                self.last_metrics = dict(transport='udp', transaction=assembly.transaction,
                    udp_request_payload_bytes=self._request_bytes,
                    udp_response_datagrams=assembly.datagrams, udp_duplicate_datagrams=assembly.duplicates,
                    udp_ignored_transactions=assembly.ignored, udp_response_payload_bytes=assembly.payload_bytes,
                    udp_receive_ms=(time.perf_counter() - self._started) * 1000)
                self._assembly = None; self._buffer = complete; self._offset = 0
                if complete[:4] == b'EER1':
                    if len(complete) != 12:
                        raise DatagramError('Malformed UDP endpoint error')
                    code, detail = struct.unpack_from('<II', complete, 4)
                    message = {1:'UDP firmware is owned by another peer',
                               2:'Stale UDP transaction rejected; reconnect to query the last accepted request',
                               3:'UDP transaction ID reused with a different request'}.get(code, 'Unknown UDP endpoint error')
                    raise RemoteError(f'{message} (code={code}, detail={detail}); request was not retried')
                return self.read(size)
        return b''

    def assert_consumed(self):
        if self._assembly is not None or self._offset != len(self._buffer):
            raise DatagramError('Unexpected trailing bytes in UDP inner packet')


def open_transport(port, *, udp=None, udp_bind_port=9002, baudrate=921600, stop=None):
    if udp is not None:
        transport = UDPTransport(udp, bind_port=udp_bind_port)
        try:
            transport.negotiate(stop=stop)
            return transport
        except Exception:
            transport.close(); raise
    import serial
    return serial.Serial(port, baudrate, timeout=.1, write_timeout=1)


def add_transport_arguments(parser):
    parser.add_argument('--udp', metavar='HOST:PORT', help='Use the Ethernet UDP image instead of the serial port; stateful requests are never retried')
    parser.add_argument('--udp-bind-port', type=int, default=9002, help='Local UDP port (default: 9002); v1 retains one peer until firmware reset')


class LatencyWindow:
    """Bounded rolling latency percentiles; overhead includes firmware and host."""
    def __init__(self, size=256):
        if size < 1: raise ValueError('Latency window must be positive')
        self.samples = deque(maxlen=size)

    def observe(self, roundtrip_ms, compute_ms):
        if not all(math.isfinite(v) and v >= 0 for v in (roundtrip_ms, compute_ms)):
            raise ValueError('Latency samples must be finite and nonnegative')
        self.samples.append((roundtrip_ms, compute_ms, max(0., roundtrip_ms - compute_ms)))

    def summary(self):
        def stats(values):
            values = sorted(values)
            def percentile(q):
                position = (len(values)-1)*q; low = int(position); high = min(low+1, len(values)-1)
                return values[low] + (values[high]-values[low])*(position-low)
            return dict(p50=percentile(.5), p95=percentile(.95), p99=percentile(.99))
        return dict(samples=len(self.samples), **({name:stats(row[index] for row in self.samples)
            for index, name in enumerate(('roundtrip_ms','compute_ms','outside_compute_ms'))} if self.samples else {}))


def main():
    parser = argparse.ArgumentParser(description='UDP echo benchmark: transport and firmware framing only; no inference runs.')
    parser.add_argument('--udp', required=True, metavar='HOST:PORT')
    parser.add_argument('--udp-bind-port', type=int, default=9002)
    parser.add_argument('--requests', type=int, default=100)
    parser.add_argument('--payload-bytes', type=int, default=256)
    parser.add_argument('--timeout', type=float, default=2)
    args = parser.parse_args()
    if args.requests < 1 or not 0 <= args.payload_bytes <= MAX_CHUNK-4 or args.timeout <= 0:
        parser.error('requests and timeout must be positive; payload-bytes must be 0..1396')
    try:
        from .stream import read_exact
    except ImportError:
        from stream import read_exact
    latencies = LatencyWindow(min(args.requests, 100000))
    payload = bytes((i*17+3)&255 for i in range(args.payload_bytes))
    with UDPTransport(args.udp, bind_port=args.udp_bind_port) as transport:
        transport.negotiate(timeout=args.timeout)
        start = time.perf_counter()
        for _ in range(args.requests):
            before = time.perf_counter(); transport.write(b'ECQ1'+payload)
            actual = read_exact(transport, 4+len(payload), deadline=time.monotonic()+args.timeout)
            transport.assert_consumed()
            if actual != b'ECR1'+payload: raise DatagramError('Echo payload mismatch')
            latencies.observe((time.perf_counter()-before)*1000, 0.)
        elapsed = time.perf_counter()-start
    print(json.dumps(dict(scope='UDP echo only: no inference, accelerator, or fresh model output',
                         requests=args.requests, payload_bytes=args.payload_bytes, elapsed_seconds=elapsed,
                         requests_per_second=args.requests/elapsed, latency=latencies.summary()), indent=2))


if __name__ == '__main__': main()

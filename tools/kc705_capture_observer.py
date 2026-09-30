#!/usr/bin/env python3
"""Explicitly SRAM-program a KC705 observer image and capture its status UART."""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import termios
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--bit', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--seconds', type=float, default=40)
p.add_argument('--port', default='/dev/cu.usbserial-0001')
p.add_argument('--serial', default='210203A3CFBC')
p.add_argument('--baud', type=int, choices=[57600,115200], default=115200)
a = p.parse_args()
assert a.bit.is_file() and a.seconds >= 25
a.out.mkdir(parents=True, exist_ok=True)
fd = os.open(a.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
config = termios.tcgetattr(fd)
config[0:4] = [0, 0, termios.CS8 | termios.CREAD | termios.CLOCAL, 0]
speed = getattr(termios, "B" + str(a.baud))
config[4:6] = [speed, speed]
config[6][termios.VMIN] = config[6][termios.VTIME] = 0
termios.tcsetattr(fd, termios.TCSANOW, config)
termios.tcflush(fd, termios.TCIFLUSH)
data = bytearray()
with (a.out / 'program.log').open('w') as log:
    proc = subprocess.Popen(['openFPGALoader', '-b', 'kc705', '--ftdi-serial', a.serial,
                             '--write-sram', str(a.bit)], stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + a.seconds
    programming_finished = False
    while time.monotonic() < deadline:
        if not programming_finished and proc.poll() is not None:
            (a.out / "pre-completion-uart.bin").write_bytes(data)
            data.clear()
            termios.tcflush(fd, termios.TCIFLUSH)
            programming_finished = True
        if select.select([fd], [], [], 0.25)[0]:
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                continue
            if chunk and not data:
                print('First bytes:', chunk[:64].hex(), flush=True)
            data.extend(chunk)
    rc = proc.wait()
os.close(fd)
(a.out / 'uart.bin').write_bytes(data)
counts = collections.Counter()
i = skipped = 0
while i + 16 <= len(data):
    if data[i:i+2] != b'\xa5\x5a':
        i += 1
        skipped += 1
        continue
    packet = data[i:i+16]
    counts[(packet[2], packet[3], *(int.from_bytes(packet[j:j+4], 'little')
                                  for j in (4, 8, 12)))] += 1
    i += 16
result = dict(program_exit=rc, bytes=len(data), packets=sum(counts.values()),
              skipped_bytes=skipped, trailing_bytes=len(data)-i,
              states=[dict(zip(['flags', 'live', 'pc', 'instr', 'req_addr'], map(hex, k)),
                           count=v) for k, v in counts.most_common()],
              capture_seconds=a.seconds, device=a.port, baud=a.baud,
              bitstream_sha256=hashlib.sha256(a.bit.read_bytes()).hexdigest(),
              scope='Status packet capture; application success must be interpreted for the loaded diagnostic.')
(a.out / 'hardware-result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
raise SystemExit(rc)

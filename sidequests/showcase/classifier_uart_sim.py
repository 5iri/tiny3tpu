#!/usr/bin/env python3
"""Check all twenty classifier samples and declared backend counts through UART RTL."""
import argparse
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sidequests.showcase.build_support import load_expected_modes
from sidequests.showcase.uart_sim import simulate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', type=Path, default=ROOT / 'build-classifier/board')
    parser.add_argument('--out', type=Path, default=ROOT / 'build-classifier/uart-rtl')
    parser.add_argument('--tpu-transport', choices=('mailbox', 'direct'))
    args = parser.parse_args(); board = args.board.resolve()
    counts, manifest = load_expected_modes(board, {index: 1 for index in range(20)})
    path = board / 'classifier-expected.npy'
    if not path.exists():
        path = ROOT / 'build-classifier/expected.npy'
    scores = np.load(path)
    cases = [{'request_mode': index,
              'expected': np.concatenate((row, np.array([np.argmax(row)], np.float32))),
              'expected_calls': counts[index]} for index, row in enumerate(scores)]
    cases += [{'request_mode': 0, 'repeats': 3, 'expected': cases[0]['expected'], 'expected_calls': 3 * counts[0]},
              {'request_mode': 20, 'expected': np.empty(0, np.float32), 'expected_calls': 0, 'status': -1}]
    simulate(board, args.out.resolve(), cases, manifest, args.tpu_transport)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Unit and integration tests for the tinygrad -> tiny3tpu frontend and OpenPilot ONNX policy."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import numpy as np

try:
    import tinygrad
    from tinygrad import Tensor, dtypes
    from tinygrad.nn.onnx import OnnxRunner
except ImportError:
    print('SKIP: install tinygrad to run tinygrad frontend tests')
    raise SystemExit(77)

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from tools.program import (
    CompileOptions,
    CPU,
    KC705,
    KC705_DIRECT,
    KC705_DIRECT_CORDIC,
    compile_onnx_via_tinygrad,
    compile_stablehlo,
    compile_tinygrad,
)
from test_stablehlo_compiler import Compiled
from sidequests.openpilot.prepare import build_openpilot_policy_onnx


class TinygradFrontendTests(unittest.TestCase):
    def check_tinygrad(self, fn, inputs, options=None, *, rtol=1e-5, atol=1e-5, mode=3):
        options = options or CompileOptions(
            target=KC705_DIRECT,
            math_mode='freestanding',
            allow_approximation=True,
            gemm_policy='tpu',
        )
        tg_inputs = [Tensor(x) for x in inputs]
        expected_res = fn(*tg_inputs) if len(tg_inputs) > 1 else fn(tg_inputs[0])
        if not isinstance(expected_res, (tuple, list)):
            expected_list = [expected_res.numpy()]
        else:
            expected_list = [t.numpy() for t in expected_res]

        with tempfile.TemporaryDirectory() as tmp:
            hdr = Path(tmp) / 'program.h'
            report = compile_tinygrad(fn, inputs, hdr, options)
            # Also verify via Compiled harness
            from tools.program.tinygrad_frontend import TinygradLowering, _import_tinygrad
            _, T, dt, Ops, _ = _import_tinygrad()
            sym_inputs = [T.empty(*x.shape, dtype=getattr(dt, str(x.dtype))) for x in inputs]
            sym_out = fn(*sym_inputs) if len(sym_inputs) > 1 else fn(sym_inputs[0])
            sym_outs = list(sym_out) if isinstance(sym_out, (tuple, list)) else [sym_out]
            plan = TinygradLowering(T, dt, Ops).lower([t.uop for t in sym_outs], sym_inputs)
            c = Compiled(None, options, plan=plan)
            self.addCleanup(c.close)
            status, got = c.run(*inputs, mode=mode)
            self.assertEqual(status, 0)
            for g, e in zip(got, expected_list):
                np.testing.assert_allclose(g, e, rtol=rtol, atol=atol)
            return c, report

    def test_elementwise_and_activations(self):
        rng = np.random.default_rng(42)
        x = rng.uniform(-3.0, 3.0, size=(4, 8)).astype(np.float32)
        y = rng.uniform(-2.0, 2.0, size=(4, 8)).astype(np.float32)
        self.check_tinygrad(
            lambda a, b: ((a + b).relu() * a.sigmoid() - b.tanh(), a.softmax(axis=-1)),
            [x, y],
            rtol=1e-4,
            atol=1e-4,
        )

    def test_int8_matmul_and_batched_matmul_on_tpu(self):
        rng = np.random.default_rng(705)
        x = rng.integers(-32, 33, size=(6, 12), dtype=np.int8)
        w = rng.integers(-8, 9, size=(12, 8), dtype=np.int8)
        w_t = Tensor(w)
        c, report = self.check_tinygrad(
            lambda a: (a.int() @ w_t.int()).cast(dtypes.float32) * 0.25,
            [x],
        )
        self.assertEqual(report['packed_matmuls'], 1)
        self.assertEqual(len(report['specialized_matmuls']), 1)
        self.assertEqual(c.library.packed_backend_calls(), 1)

        bx = rng.integers(-16, 17, size=(2, 4, 8), dtype=np.int8)
        bw = rng.integers(-4, 5, size=(2, 8, 5), dtype=np.int8)
        bw_t = Tensor(bw)
        c_b, report_b = self.check_tinygrad(
            lambda a: (a.int() @ bw_t.int()),
            [bx],
        )
        self.assertEqual(report_b['packed_matmuls'], 1)
        self.assertEqual(c_b.library.packed_backend_calls(), 2)

    def test_int8_conv2d_stride_and_padding_on_tpu(self):
        rng = np.random.default_rng(101)
        x = rng.integers(-20, 21, size=(1, 3, 6, 8), dtype=np.int8)
        w1 = rng.integers(-4, 5, size=(8, 3, 3, 3), dtype=np.int8)
        w2 = rng.integers(-3, 4, size=(12, 8, 3, 3), dtype=np.int8)
        w1_t, w2_t = Tensor(w1), Tensor(w2)

        def conv_net(inp):
            h1 = inp.int().conv2d(w1_t.int(), stride=2, padding=1).relu().clip(0, 127).cast(dtypes.int8)
            h2 = h1.int().conv2d(w2_t.int(), stride=2, padding=1).cast(dtypes.float32)
            return h2

        c, report = self.check_tinygrad(conv_net, [x])
        self.assertEqual(report['packed_matmuls'], 2)
        self.assertEqual(len(report['specialized_matmuls']), 2)
        self.assertEqual(c.library.packed_backend_calls(), 2)

    def test_openpilot_driving_policy_onnx_end_to_end(self):
        onnx_bytes, sample_input = build_openpilot_policy_onnx(seed=705)
        with tempfile.TemporaryDirectory() as tmp:
            onnx_path = Path(tmp) / 'openpilot_driving_policy.onnx'
            onnx_path.write_bytes(onnx_bytes)

            runner = OnnxRunner(onnx_path)
            expected = runner({'input_state': sample_input})['plan_output'].numpy()
            self.assertEqual(expected.shape, (1, 33))

            options = CompileOptions(
                target=KC705_DIRECT,
                math_mode='freestanding',
                allow_approximation=True,
                gemm_policy='tpu',
            )
            c = Compiled(onnx_path, options)
            self.addCleanup(c.close)
            status, outputs = c.run(sample_input, mode=3)
            self.assertEqual(status, 0)
            np.testing.assert_allclose(outputs[0], expected, rtol=1e-5, atol=1e-5)

            self.assertEqual(c.report['input_format'], 'tinygrad-onnx')
            self.assertEqual(c.report['packed_matmuls'], 5)
            self.assertEqual(len(c.report['specialized_matmuls']), 5)
            self.assertEqual(c.library.packed_backend_calls(), 5)

            # Also verify CORDIC target header emission compiles cleanly
            cordic_hdr = Path(tmp) / 'openpilot_cordic.h'
            cordic_report = compile_stablehlo(
                onnx_path,
                cordic_hdr,
                replace(options, target=KC705_DIRECT_CORDIC, symbol='openpilot_policy'),
            )
            self.assertIn('cordic', [p['device'] for p in cordic_report['placement']])


if __name__ == '__main__':
    unittest.main()

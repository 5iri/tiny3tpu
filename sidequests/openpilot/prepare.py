#!/usr/bin/env python3
"""Build and compile a compact OpenPilot driving policy ONNX model via tinygrad -> tiny3tpu."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import struct
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from tools.program import (
    CompileOptions,
    KC705,
    KC705_DIRECT,
    KC705_DIRECT_CORDIC,
    compile_onnx_via_tinygrad,
    compile_stablehlo,
)
from test_stablehlo_compiler import Compiled


# --- Minimal zero-dependency ONNX Protobuf encoder (matches onnx.proto3) ---

def _encode_varint(val: int) -> bytes:
    if val < 0:
        val += 1 << 64
    out = bytearray()
    while True:
        byte = val & 0x7F
        val >>= 7
        if val:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def _tag(field_num: int, wire_type: int) -> bytes:
    return _encode_varint((field_num << 3) | wire_type)


def _field_varint(field_num: int, val: int) -> bytes:
    return _tag(field_num, 0) + _encode_varint(val)


def _field_float(field_num: int, val: float) -> bytes:
    return _tag(field_num, 5) + struct.pack('<f', float(val))


def _field_bytes(field_num: int, data: bytes) -> bytes:
    return _tag(field_num, 2) + _encode_varint(len(data)) + data


def _field_str(field_num: int, text: str) -> bytes:
    return _field_bytes(field_num, text.encode('utf-8'))


# ONNX TensorProto DataType enum values
ONNX_FLOAT = 1
ONNX_UINT8 = 2
ONNX_INT8 = 3
ONNX_INT32 = 6
ONNX_INT64 = 7

_NP_TO_ONNX_DTYPE = {
    np.dtype('float32'): ONNX_FLOAT,
    np.dtype('uint8'): ONNX_UINT8,
    np.dtype('int8'): ONNX_INT8,
    np.dtype('int32'): ONNX_INT32,
    np.dtype('int64'): ONNX_INT64,
}


def onnx_tensor(name: str, arr: np.ndarray) -> bytes:
    arr = np.ascontiguousarray(arr)
    dtype_id = _NP_TO_ONNX_DTYPE[arr.dtype]
    buf = bytearray()
    for d in arr.shape:
        buf += _field_varint(1, int(d))  # dims
    buf += _field_varint(2, dtype_id)    # data_type
    buf += _field_str(8, name)           # name
    buf += _field_bytes(9, arr.tobytes())  # raw_data
    return bytes(buf)


def onnx_value_info(name: str, dtype_id: int, shape: tuple[int, ...]) -> bytes:
    dim_msgs = b''.join(_field_bytes(1, _field_varint(1, int(d))) for d in shape)
    tensor_type = _field_varint(1, dtype_id) + _field_bytes(2, dim_msgs)
    type_proto = _field_bytes(1, tensor_type)
    return _field_str(1, name) + _field_bytes(2, type_proto)


def onnx_attr(name: str, val) -> bytes:
    buf = bytearray(_field_str(1, name))
    if isinstance(val, float):
        buf += _field_float(2, val)
        buf += _field_varint(20, 1)  # FLOAT
    elif isinstance(val, int):
        buf += _field_varint(3, val)
        buf += _field_varint(20, 2)  # INT
    elif isinstance(val, str):
        buf += _field_bytes(4, val.encode('utf-8'))
        buf += _field_varint(20, 3)  # STRING
    elif isinstance(val, (list, tuple)):
        if all(isinstance(x, int) for x in val):
            for x in val:
                buf += _field_varint(8, int(x))
            buf += _field_varint(20, 7)  # INTS
        elif all(isinstance(x, float) for x in val):
            for x in val:
                buf += _field_float(7, float(x))
            buf += _field_varint(20, 6)  # FLOATS
        else:
            raise ValueError(f'Unsupported attribute list for {name}: {val}')
    else:
        raise ValueError(f'Unsupported attribute for {name}: {val}')
    return bytes(buf)


def onnx_node(op_type: str, inputs: list[str], outputs: list[str], name: str = '', **attrs) -> bytes:
    buf = bytearray()
    for inp in inputs:
        buf += _field_str(1, inp)
    for out in outputs:
        buf += _field_str(2, out)
    if name:
        buf += _field_str(3, name)
    buf += _field_str(4, op_type)
    for k, v in attrs.items():
        buf += _field_bytes(5, onnx_attr(k, v))
    return bytes(buf)


def onnx_model(graph_name: str, inputs: list[bytes], outputs: list[bytes],
               initializers: list[bytes], nodes: list[bytes], opset: int = 18) -> bytes:
    graph = bytearray()
    for n in nodes:
        graph += _field_bytes(1, n)
    graph += _field_str(2, graph_name)
    for init in initializers:
        graph += _field_bytes(5, init)
    for inp in inputs:
        graph += _field_bytes(11, inp)
    for out in outputs:
        graph += _field_bytes(12, out)

    opset_proto = _field_str(1, '') + _field_varint(2, opset)
    model = bytearray()
    model += _field_varint(1, 8)  # ir_version = 8
    model += _field_str(4, 'ai.tiny3tpu.openpilot')
    model += _field_varint(5, 1)  # model_version = 1
    model += _field_bytes(7, bytes(graph))
    model += _field_bytes(8, opset_proto)
    return bytes(model)


def build_openpilot_policy_onnx(seed: int = 705) -> tuple[bytes, np.ndarray]:
    """Construct the compact OpenPilot driving policy ONNX model and a deterministic sample input.

    Architecture (modeled on comma.ai OpenPilot supercombo / driving_policy):
      Input `input_state` (float32[1, 160]):
        - [0:144]   Road camera patch (1 x 3 x 6 x 8)
        - [144:152] Desire navigation logits (1 x 8)
        - [152:160] Ego kinematics + recurrent temporal state (1 x 8)
      Stage 1 (Vision Stem on TPU):
        - Conv1: ConvInteger(1x3x6x8, 8x3x3x3, stride=2, pad=1) + bias + ReLU -> (1, 8, 3, 4)
        - Conv2: ConvInteger(1x8x3x4, 16x8x3x3, stride=2, pad=1) + bias + ReLU -> (1, 16, 2, 2) -> (1, 64)
      Stage 2 (Vision Bottleneck + Desire Softmax):
        - Bottleneck: MatMulInteger(1x64, 64x16) + bias + ReLU -> (1, 16)
        - Desire gate: Softmax(desire_logits, axis=-1) -> quantized (1, 8)
      Stage 3 (Temporal Policy GRU/Gated Fusion):
        - Concat(vision_16, desire_8, temporal_8) -> (1, 32)
        - Hidden: MatMulInteger(1x32, 32x24) -> Sigmoid gate * Tanh activation -> quantized (1, 24)
      Stage 4 (Trajectory Planning Head):
        - Plan head: MatMulInteger(1x24, 24x33) * scale + anchor_trajectory -> float32[1, 33]
          (16 future (x, y) waypoints in meters + 1 desired speed / confidence)
    """
    rng = np.random.default_rng(seed)
    inits = []
    nodes = []

    def add_const(name: str, arr: np.ndarray) -> str:
        inits.append(onnx_tensor(name, arr))
        return name

    # Slice bounds & shape constants
    c_axis1 = add_const('axis1', np.array([1], dtype=np.int64))
    c_s0 = add_const('s0', np.array([0], dtype=np.int64))
    c_s144 = add_const('s144', np.array([144], dtype=np.int64))
    c_s152 = add_const('s152', np.array([152], dtype=np.int64))
    c_s160 = add_const('s160', np.array([160], dtype=np.int64))

    sh_vis = add_const('sh_vis', np.array([1, 3, 6, 8], dtype=np.int64))
    sh_flat64 = add_const('sh_flat64', np.array([1, 64], dtype=np.int64))

    c_neg127 = add_const('c_neg127', np.array(-127.0, dtype=np.float32))
    c_pos127 = add_const('c_pos127', np.array(127.0, dtype=np.float32))
    c_zero_f = add_const('c_zero_f', np.array(0.0, dtype=np.float32))

    # Unpack input_state (1, 160) -> vis_raw (1, 3, 6, 8), desire_raw (1, 8), ego_raw (1, 8)
    nodes.append(onnx_node('Slice', ['input_state', c_s0, c_s144, c_axis1], ['vis_slice'], name='slice_vis'))
    nodes.append(onnx_node('Reshape', ['vis_slice', sh_vis], ['vis_raw'], name='reshape_vis'))
    nodes.append(onnx_node('Slice', ['input_state', c_s144, c_s152, c_axis1], ['desire_raw'], name='slice_desire'))
    nodes.append(onnx_node('Slice', ['input_state', c_s152, c_s160, c_axis1], ['ego_raw'], name='slice_ego'))

    # Quantize vision patch -> int8
    nodes.append(onnx_node('Clip', ['vis_raw', c_neg127, c_pos127], ['vis_clip'], name='clip_vis'))
    nodes.append(onnx_node('Cast', ['vis_clip'], ['vis_i8'], name='cast_vis', to=ONNX_INT8))

    # Stage 1a: Conv1 (3 -> 8, 3x3, stride 2, pad 1)
    w_conv1 = add_const('w_conv1', rng.integers(-4, 5, size=(8, 3, 3, 3), dtype=np.int8))
    b_conv1 = add_const('b_conv1', rng.integers(-16, 17, size=(1, 8, 1, 1), dtype=np.int32))
    c_div1 = add_const('c_div1', np.array(0.25, dtype=np.float32))
    nodes.append(onnx_node('ConvInteger', ['vis_i8', w_conv1], ['conv1_i32'], name='conv1',
                           strides=[2, 2], pads=[1, 1, 1, 1]))
    nodes.append(onnx_node('Add', ['conv1_i32', b_conv1], ['conv1_b'], name='conv1_bias'))
    nodes.append(onnx_node('Cast', ['conv1_b'], ['conv1_f'], name='conv1_to_f', to=ONNX_FLOAT))
    nodes.append(onnx_node('Mul', ['conv1_f', c_div1], ['conv1_sc'], name='conv1_scale'))
    nodes.append(onnx_node('Relu', ['conv1_sc'], ['conv1_relu'], name='conv1_relu'))
    nodes.append(onnx_node('Clip', ['conv1_relu', c_zero_f, c_pos127], ['conv1_clip'], name='conv1_clip'))
    nodes.append(onnx_node('Cast', ['conv1_clip'], ['conv1_i8'], name='conv1_i8', to=ONNX_INT8))

    # Stage 1b: Conv2 (8 -> 16, 3x3, stride 2, pad 1) -> (1, 16, 2, 2) -> Reshape (1, 64)
    w_conv2 = add_const('w_conv2', rng.integers(-3, 4, size=(16, 8, 3, 3), dtype=np.int8))
    b_conv2 = add_const('b_conv2', rng.integers(-16, 17, size=(1, 16, 1, 1), dtype=np.int32))
    c_div2 = add_const('c_div2', np.array(0.125, dtype=np.float32))
    nodes.append(onnx_node('ConvInteger', ['conv1_i8', w_conv2], ['conv2_i32'], name='conv2',
                           strides=[2, 2], pads=[1, 1, 1, 1]))
    nodes.append(onnx_node('Add', ['conv2_i32', b_conv2], ['conv2_b'], name='conv2_bias'))
    nodes.append(onnx_node('Cast', ['conv2_b'], ['conv2_f'], name='conv2_to_f', to=ONNX_FLOAT))
    nodes.append(onnx_node('Mul', ['conv2_f', c_div2], ['conv2_sc'], name='conv2_scale'))
    nodes.append(onnx_node('Relu', ['conv2_sc'], ['conv2_relu'], name='conv2_relu'))
    nodes.append(onnx_node('Reshape', ['conv2_relu', sh_flat64], ['conv2_flat'], name='conv2_flat'))
    nodes.append(onnx_node('Clip', ['conv2_flat', c_zero_f, c_pos127], ['conv2_clip'], name='conv2_clip'))
    nodes.append(onnx_node('Cast', ['conv2_clip'], ['vis_feat_i8'], name='vis_feat_i8', to=ONNX_INT8))

    # Stage 2a: Vision Bottleneck MatMulInteger (1, 64) @ (64, 16) -> (1, 16)
    w_vis_fc = add_const('w_vis_fc', rng.integers(-3, 4, size=(64, 16), dtype=np.int8))
    b_vis_fc = add_const('b_vis_fc', rng.integers(-12, 13, size=(1, 16), dtype=np.int32))
    c_div_fc = add_const('c_div_fc', np.array(0.125, dtype=np.float32))
    nodes.append(onnx_node('MatMulInteger', ['vis_feat_i8', w_vis_fc], ['vis_fc_i32'], name='vis_fc'))
    nodes.append(onnx_node('Add', ['vis_fc_i32', b_vis_fc], ['vis_fc_b'], name='vis_fc_bias'))
    nodes.append(onnx_node('Cast', ['vis_fc_b'], ['vis_fc_f'], name='vis_fc_to_f', to=ONNX_FLOAT))
    nodes.append(onnx_node('Mul', ['vis_fc_f', c_div_fc], ['vis_fc_sc'], name='vis_fc_scale'))
    nodes.append(onnx_node('Relu', ['vis_fc_sc'], ['vis_fc_relu'], name='vis_fc_relu'))
    nodes.append(onnx_node('Clip', ['vis_fc_relu', c_zero_f, c_pos127], ['vis_fc_clip'], name='vis_fc_clip'))
    nodes.append(onnx_node('Cast', ['vis_fc_clip'], ['vis_bottleneck_i8'], name='vis_bottleneck_i8', to=ONNX_INT8))

    # Stage 2b: Desire Softmax + Quantize -> (1, 8) int8, and Ego Quantize -> (1, 8) int8
    c_scale_desire = add_const('c_scale_desire', np.array(64.0, dtype=np.float32))
    nodes.append(onnx_node('Softmax', ['desire_raw'], ['desire_prob'], name='desire_softmax', axis=-1))
    nodes.append(onnx_node('Mul', ['desire_prob', c_scale_desire], ['desire_sc'], name='desire_scale'))
    nodes.append(onnx_node('Clip', ['desire_sc', c_neg127, c_pos127], ['desire_clip'], name='desire_clip'))
    nodes.append(onnx_node('Cast', ['desire_clip'], ['desire_i8'], name='desire_i8', to=ONNX_INT8))

    nodes.append(onnx_node('Clip', ['ego_raw', c_neg127, c_pos127], ['ego_clip'], name='ego_clip'))
    nodes.append(onnx_node('Cast', ['ego_clip'], ['ego_i8'], name='ego_i8', to=ONNX_INT8))

    # Stage 3: Temporal Policy Fusion Concat (1, 16) + (1, 8) + (1, 8) -> (1, 32)
    nodes.append(onnx_node('Concat', ['vis_bottleneck_i8', 'desire_i8', 'ego_i8'], ['fused_i8'],
                           name='concat_fusion', axis=1))

    # Temporal Gated Hidden Projection MatMulInteger (1, 32) @ (32, 24) -> (1, 24)
    w_gru = add_const('w_gru', rng.integers(-3, 4, size=(32, 24), dtype=np.int8))
    b_gru = add_const('b_gru', rng.integers(-10, 11, size=(1, 24), dtype=np.int32))
    c_gru_in_scale = add_const('c_gru_in_scale', np.array(1.0 / 256.0, dtype=np.float32))
    c_gru_out_scale = add_const('c_gru_out_scale', np.array(64.0, dtype=np.float32))
    nodes.append(onnx_node('MatMulInteger', ['fused_i8', w_gru], ['gru_i32'], name='gru_matmul'))
    nodes.append(onnx_node('Add', ['gru_i32', b_gru], ['gru_b'], name='gru_bias'))
    nodes.append(onnx_node('Cast', ['gru_b'], ['gru_f'], name='gru_to_f', to=ONNX_FLOAT))
    nodes.append(onnx_node('Mul', ['gru_f', c_gru_in_scale], ['gru_act_in'], name='gru_scale_in'))
    nodes.append(onnx_node('Sigmoid', ['gru_act_in'], ['gru_gate'], name='gru_sigmoid'))
    nodes.append(onnx_node('Tanh', ['gru_act_in'], ['gru_cand'], name='gru_tanh'))
    nodes.append(onnx_node('Mul', ['gru_gate', 'gru_cand'], ['gru_gated'], name='gru_gated_mul'))
    nodes.append(onnx_node('Mul', ['gru_gated', c_gru_out_scale], ['gru_sc'], name='gru_scale_out'))
    nodes.append(onnx_node('Clip', ['gru_sc', c_neg127, c_pos127], ['gru_clip'], name='gru_clip'))
    nodes.append(onnx_node('Cast', ['gru_clip'], ['gru_i8'], name='gru_i8', to=ONNX_INT8))

    # Stage 4: Trajectory Planning Head MatMulInteger (1, 24) @ (24, 33) -> (1, 33)
    w_plan = add_const('w_plan', rng.integers(-4, 5, size=(24, 33), dtype=np.int8))
    c_plan_scale = add_const('c_plan_scale', np.array(1.0 / 128.0, dtype=np.float32))
    # Default forward trajectory anchor: 16 (x, y) waypoints + target velocity
    anchor = np.zeros((1, 33), dtype=np.float32)
    for t in range(16):
        anchor[0, 2 * t] = float((t + 1) * 1.5)      # longitudinal distance x_t (m)
        anchor[0, 2 * t + 1] = float(0.05 * t)       # slight lateral curve y_t (m)
    anchor[0, 32] = 14.5                             # target speed (m/s)
    b_anchor = add_const('b_anchor', anchor)

    nodes.append(onnx_node('MatMulInteger', ['gru_i8', w_plan], ['plan_i32'], name='plan_matmul'))
    nodes.append(onnx_node('Cast', ['plan_i32'], ['plan_f'], name='plan_to_f', to=ONNX_FLOAT))
    nodes.append(onnx_node('Mul', ['plan_f', c_plan_scale], ['plan_delta'], name='plan_scale'))
    nodes.append(onnx_node('Add', ['plan_delta', b_anchor], ['plan_output'], name='plan_add_anchor'))

    inputs = [onnx_value_info('input_state', ONNX_FLOAT, (1, 160))]
    outputs = [onnx_value_info('plan_output', ONNX_FLOAT, (1, 33))]
    model_bytes = onnx_model('openpilot_driving_policy', inputs, outputs, inits, nodes, opset=18)

    # Sample input state
    sample_vis = rng.integers(-32, 33, size=(1, 144)).astype(np.float32)
    sample_desire = np.array([[1.5, -0.5, -0.2, 0.1, -1.0, -1.0, 0.0, 0.2]], dtype=np.float32)
    sample_ego = np.array([[14.0, 0.2, -1.0, 0.5, 4.0, -3.0, 2.0, 1.0]], dtype=np.float32)
    sample_input = np.concatenate([sample_vis, sample_desire, sample_ego], axis=1).astype(np.float32)
    return model_bytes, sample_input


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, default=ROOT / 'build-openpilot')
    p.add_argument('--tpu-transport', choices=('mailbox', 'direct'), default='direct')
    p.add_argument('--cordic', action='store_true', default=True)
    p.add_argument('--gemm-policy', choices=('auto', 'cpu', 'tpu'), default='tpu')
    args = p.parse_args()

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    onnx_bytes, sample_input = build_openpilot_policy_onnx()
    onnx_path = out / 'openpilot_driving_policy.onnx'
    onnx_path.write_bytes(onnx_bytes)
    np.save(out / 'input.npy', sample_input)

    # 1. Run reference inference through tinygrad's OnnxRunner
    from tinygrad.nn.onnx import OnnxRunner
    runner = OnnxRunner(onnx_path)
    tg_out = runner({'input_state': sample_input})['plan_output'].numpy()
    np.save(out / 'expected-tinygrad.npy', tg_out)

    # 2. Compile via tinygrad -> tiny3tpu and verify native execution
    if args.tpu_transport == 'direct':
        target = KC705_DIRECT_CORDIC if args.cordic else KC705_DIRECT
        host_target = KC705_DIRECT
    else:
        target = KC705
        host_target = KC705
    from dataclasses import replace
    options = CompileOptions(
        target=target,
        math_mode='freestanding',
        allow_approximation=True,
        gemm_policy=args.gemm_policy,
    )
    native = Compiled(onnx_path, replace(options, target=host_target))
    try:
        status, outputs = native.run(sample_input, mode=3)
        assert status == 0, f'Native run failed with status {status}'
        np.testing.assert_allclose(outputs[0], tg_out, rtol=1e-4, atol=1e-4)
        np.save(out / 'expected-native.npy', outputs[0])
        packed_calls = native.library.packed_backend_calls()
    finally:
        native.close()

    report = compile_stablehlo(onnx_path, out / 'openpilot_policy.h', replace(options, symbol='openpilot_policy'))
    (out / 'compile-report.json').write_text(json.dumps(report, indent=2) + '\n')

    summary = {
        'model': str(onnx_path),
        'input_shape': list(sample_input.shape),
        'output_shape': list(outputs[0].shape),
        'workspace_bytes': report['workspace_bytes'],
        'packed_constant_bytes': report['packed_constant_bytes'],
        'packed_matmuls': report['packed_matmuls'],
        'specialized_matmuls': len(report['specialized_matmuls']),
        'packed_backend_calls': packed_calls,
        'max_abs_error_vs_tinygrad': float(np.max(np.abs(outputs[0] - tg_out))),
        'sample_plan_first3_xy': outputs[0][0, :6].round(3).tolist(),
        'sample_target_speed_mps': round(float(outputs[0][0, 32]), 3),
    }
    (out / 'manifest.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()

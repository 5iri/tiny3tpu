#!/usr/bin/env python3
"""
Train and export an int8 MNIST MLP for UART tiled 16x16 systolic inference.

Default architecture is a 4-layer MLP:
  input -> 128 -> 64 -> 32 -> 10
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

import numpy as np
import torch
import torch.nn as nn
import torchvision
import torchvision.transforms as T

FW_MAX_MODEL_LAYERS = 16
FW_MAX_MODEL_DIM = 256
DEFAULT_EPOCHS = 8
DEFAULT_EPOCHS_16L = 24

HIDDEN_DIM_PRESETS = {
    "default": "128,64,32",
    # 15 hidden layers + final output layer => 16 total layers.
    "16layer-npow": "191,173,157,149,137,131,127,113,109,101,97,89,83,79,73",
    # 15 hidden layers, all power-of-two.
    "16layer-pow2": "256,256,256,256,256,256,256,256,256,256,256,256,256,256,256",
}


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def parse_hidden_dims(spec: str) -> List[int]:
    dims: List[int] = []
    for tok in spec.replace("x", ",").split(","):
        t = tok.strip()
        if not t:
            continue
        v = int(t)
        if v <= 0:
            raise ValueError(f"hidden dim must be > 0, got {v}")
        dims.append(v)
    if not dims:
        raise ValueError("hidden dims cannot be empty")
    return dims


def validate_fw_dims(dims: Sequence[int]) -> None:
    if len(dims) < 2:
        raise ValueError("dims must include at least input and output")
    layer_count = len(dims) - 1
    if layer_count > FW_MAX_MODEL_LAYERS:
        raise ValueError(
            f"layer count {layer_count} exceeds firmware max {FW_MAX_MODEL_LAYERS}"
        )
    for i, d in enumerate(dims):
        if d <= 0:
            raise ValueError(f"dim[{i}] must be > 0, got {d}")
        if d > FW_MAX_MODEL_DIM:
            raise ValueError(
                f"dim[{i}]={d} exceeds firmware max dim {FW_MAX_MODEL_DIM}"
            )


class MiniMLP(nn.Module):
    def __init__(self, dims: Sequence[int]):
        super().__init__()
        if len(dims) < 2:
            raise ValueError("dims must include at least input and output")
        self.linears = nn.ModuleList()
        for i in range(len(dims) - 1):
            self.linears.append(nn.Linear(int(dims[i]), int(dims[i + 1])))
        self.relu = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.flatten(1)
        last = len(self.linears) - 1
        for i, lin in enumerate(self.linears):
            x = lin(x)
            if i != last:
                x = self.relu(x)
        return x


@dataclass
class LinearLayerExport:
    w: List[List[int]]
    b: List[int]
    scale_in: float
    scale_w: float
    scale_out: float
    zp_in: int = 0
    zp_w: int = 0
    zp_out: int = 0


@dataclass
class ExportModel:
    input_scale: float
    input_zp: int
    layers: List[LinearLayerExport]
    description: str
    resize: int
    hidden_dims: List[int]


def symmetric_scale(t: torch.Tensor) -> float:
    max_abs = float(t.abs().max().item())
    if max_abs <= 0.0:
        return 1.0
    return max_abs / 127.0


def quantize_i8_tensor(t: torch.Tensor, scale: float) -> torch.Tensor:
    q = torch.round(t / scale).clamp(-128, 127)
    return q.to(torch.int8)


def load_data(root: Path, resize: int, batch_size: int, num_workers: int) -> Tuple[torch.utils.data.DataLoader, torch.utils.data.DataLoader]:
    tfm = T.Compose([T.Resize((resize, resize)), T.ToTensor()])
    train_ds = torchvision.datasets.MNIST(root=str(root), train=True, download=False, transform=tfm)
    test_ds = torchvision.datasets.MNIST(root=str(root), train=False, download=False, transform=tfm)
    train_loader = torch.utils.data.DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=num_workers)
    test_loader = torch.utils.data.DataLoader(test_ds, batch_size=batch_size, shuffle=False, num_workers=num_workers)
    return train_loader, test_loader


def train_epoch(model: nn.Module, loader: torch.utils.data.DataLoader, device: torch.device, opt: torch.optim.Optimizer) -> float:
    model.train()
    loss_fn = nn.CrossEntropyLoss()
    total_loss = 0.0
    total = 0
    for imgs, labels in loader:
        imgs = imgs.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        opt.zero_grad(set_to_none=True)
        logits = model(imgs)
        loss = loss_fn(logits, labels)
        loss.backward()
        opt.step()
        bs = imgs.size(0)
        total_loss += float(loss.item()) * bs
        total += bs
    return total_loss / max(1, total)


def eval_float_acc(model: nn.Module, loader: torch.utils.data.DataLoader, device: torch.device) -> float:
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for imgs, labels in loader:
            imgs = imgs.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            logits = model(imgs)
            pred = logits.argmax(dim=1)
            correct += int((pred == labels).sum().item())
            total += int(labels.numel())
    return correct / max(1, total)


def collect_hidden_relu_max(model: MiniMLP, loader: torch.utils.data.DataLoader) -> List[float]:
    hidden_count = max(0, len(model.linears) - 1)
    maxima = [0.0 for _ in range(hidden_count)]
    model.eval()
    with torch.no_grad():
        for imgs, _ in loader:
            x = imgs.flatten(1)
            for i, lin in enumerate(model.linears):
                x = lin(x)
                if i != len(model.linears) - 1:
                    x = torch.relu(x)
                    m = float(x.abs().max().item())
                    if m > maxima[i]:
                        maxima[i] = m
    return maxima


def linear_requant(acc: np.ndarray, bias: np.ndarray, scale_in: float, scale_w: float, scale_out: float, relu: bool) -> np.ndarray:
    m = (scale_in * scale_w) / max(scale_out, 1e-12)
    q = np.rint((acc + bias) * m).astype(np.int32)
    q = np.clip(q, -128, 127)
    if relu:
        q = np.maximum(q, 0)
    return q.astype(np.int8)


def export_model(model: MiniMLP, calib_loader: torch.utils.data.DataLoader, resize: int, hidden_dims: List[int]) -> ExportModel:
    input_scale = 1.0 / 127.0
    hidden_relu_max = collect_hidden_relu_max(model, calib_loader)
    layers: List[LinearLayerExport] = []

    prev_scale = input_scale
    last_idx = len(model.linears) - 1
    for i, lin in enumerate(model.linears):
        w_f = lin.weight.detach().cpu()
        b_f = lin.bias.detach().cpu()
        w_scale = symmetric_scale(w_f)
        w_q = quantize_i8_tensor(w_f, w_scale)
        if i != last_idx:
            scale_out = max(hidden_relu_max[i] / 127.0, 1e-6)
        else:
            scale_out = 1.0
        b_q = torch.round(b_f / (prev_scale * w_scale)).to(torch.int32)
        layers.append(
            LinearLayerExport(
                w=w_q.tolist(),
                b=b_q.tolist(),
                scale_in=prev_scale,
                scale_w=w_scale,
                scale_out=scale_out,
                zp_out=0,
            )
        )
        prev_scale = scale_out

    return ExportModel(
        input_scale=input_scale,
        input_zp=0,
        layers=layers,
        description="MNIST int8 MLP export for UART tiled 16x16 systolic inference",
        resize=resize,
        hidden_dims=hidden_dims,
    )


def eval_quant_acc(model_export: ExportModel, loader: torch.utils.data.DataLoader) -> float:
    ws = [np.asarray(l.w, dtype=np.int32) for l in model_export.layers]
    bs = [np.asarray(l.b, dtype=np.int32) for l in model_export.layers]
    correct = 0
    total = 0
    last = len(model_export.layers) - 1

    for imgs, labels in loader:
        x = imgs.flatten(1).cpu().numpy()
        act = np.rint(x / model_export.input_scale).astype(np.int32)
        act = np.clip(act, -128, 127).astype(np.int8)

        logits = None
        for i, layer in enumerate(model_export.layers):
            acc = act.astype(np.int32) @ ws[i].T
            if i != last:
                act = linear_requant(acc, bs[i], layer.scale_in, layer.scale_w, layer.scale_out, relu=True)
            else:
                logits = (acc + bs[i]).astype(np.float64) * (layer.scale_in * layer.scale_w)

        if logits is None:
            raise RuntimeError("logits not produced")
        pred = np.argmax(logits, axis=1)
        y = labels.numpy()
        correct += int((pred == y).sum())
        total += int(y.shape[0])

    return correct / max(1, total)


def save_json(export: ExportModel, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(asdict(export), indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Train/export MNIST int8 MLP for current hardware path")
    ap.add_argument("--data-root", type=Path, default=Path("/home/sra-admin/riscv-gpu/data"))
    ap.add_argument("--out", type=Path, default=Path("/home/sra-admin/riscv-gpu/fpga/mnist_int8_4layer.json"))
    ap.add_argument("--resize", type=int, default=16, help="MNIST resize side (input dim = resize^2)")
    ap.add_argument(
        "--hidden-dims",
        type=str,
        default=HIDDEN_DIM_PRESETS["default"],
        help="comma-separated hidden dims (ignored when --mlp-preset is set)",
    )
    ap.add_argument(
        "--mlp-preset",
        choices=sorted(HIDDEN_DIM_PRESETS.keys()),
        help="named hidden-layer preset; overrides --hidden-dims",
    )
    ap.add_argument(
        "--epochs",
        type=int,
        default=None,
        help=(
            "training epochs; defaults to 24 for 16-layer presets "
            "and 8 otherwise"
        ),
    )
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--num-workers", type=int, default=0)
    args = ap.parse_args()

    hidden_spec = HIDDEN_DIM_PRESETS[args.mlp_preset] if args.mlp_preset else args.hidden_dims
    hidden_dims = parse_hidden_dims(hidden_spec)
    if args.epochs is not None and args.epochs <= 0:
        raise ValueError("--epochs must be > 0")
    if args.epochs is None:
        epochs = DEFAULT_EPOCHS_16L if (args.mlp_preset and args.mlp_preset.startswith("16layer")) else DEFAULT_EPOCHS
    else:
        epochs = args.epochs
    dims = [args.resize * args.resize] + hidden_dims + [10]
    validate_fw_dims(dims)

    set_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device={device}")
    print(f"data_root={args.data_root}")
    print(f"dims={dims} epochs={epochs} batch={args.batch_size}")

    train_loader, test_loader = load_data(args.data_root, args.resize, args.batch_size, args.num_workers)
    model = MiniMLP(dims).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)

    best = 0.0
    for epoch in range(1, epochs + 1):
        loss = train_epoch(model, train_loader, device, opt)
        acc = eval_float_acc(model, test_loader, device)
        if acc > best:
            best = acc
        print(f"epoch={epoch:02d} loss={loss:.4f} test_acc={acc:.4f} best={best:.4f}")

    model_cpu = model.to(torch.device("cpu"))
    export = export_model(model_cpu, test_loader, args.resize, hidden_dims)
    q_acc = eval_quant_acc(export, test_loader)
    print(f"quantized_test_acc={q_acc:.4f}")

    save_json(export, args.out)
    print(f"saved={args.out}")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

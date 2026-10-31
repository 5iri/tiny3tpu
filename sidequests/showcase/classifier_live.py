#!/usr/bin/env python3
"""Show trained classifier results from the physical board; no host inference."""
import argparse
import base64
import hashlib
import io
import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from protocol import transact
from build_support import load_expected_modes
from stream import LatestResults
from uart_transport import open_transport, LatencyWindow

ROOT = Path(__file__).resolve().parents[2]
PAGE = b'''<!doctype html><html><meta name="viewport" content="width=device-width"><title>KC705 trained MNIST classifier</title><body style="margin:0;background:#0f1621;color:white;font:18px sans-serif"><img id="frame" style="width:100%;max-width:760px"><p id="status"></p><script>
const frameEl=document.getElementById('frame'),statusEl=document.getElementById('status');let sequence=-1;
async function update(){try{const s=await(await fetch('/state')).json();if(s.png&&s.sequence!==sequence){frameEl.src='data:image/png;base64,'+s.png;sequence=s.sequence}statusEl.textContent=s.png?(Date.now()/1000-s.timestamp<3?`Live board / ${(s.transport||'uart').toUpperCase()} / ${s.acquisition_fps.toFixed(1)} verified requests/s / roundtrip p50 ${s.latency.roundtrip_ms.p50.toFixed(2)} ms, p95 ${s.latency.roundtrip_ms.p95.toFixed(2)} ms / ${s.display_updates_fps.toFixed(1)} display updates/s`:'Last captured frame / board stream stale'):'Waiting for first verified result'}catch(e){statusEl.textContent='Stream unavailable'}setTimeout(update,16)}update()
</script></body></html>'''


def render(rec, data, samples, training, large, small):
    index = rec['sample']; pred = rec['board_prediction']; label = rec['true_label']
    calls = rec['backend_calls']
    im = Image.new('RGB', (760, 720), (15, 22, 33)); d = ImageDraw.Draw(im)
    d.text((26, 20), f"TINY3TPU / PHYSICAL KC705 / {rec['clock_hz']/1e6:g} MHz", font=small, fill='#52d8c9')
    d.text((26, 57), 'Trained MNIST digit classifier / int8', font=large, fill='white')
    digit = Image.fromarray(samples['images'][index]).resize((280, 280), Image.Resampling.NEAREST).convert('RGB')
    im.paste(digit, (26, 132))
    d.text((26, 441), f'Board prediction: {pred}', font=large, fill='#b2f073' if pred == label else '#ff9b7a')
    d.text((26, 484), f'Test label: {label} / sample {index}', font=small, fill='white')
    low = float(data[:10].min()); high = float(data[:10].max())
    for i, value in enumerate(data[:10]):
        y = 128 + i * 37
        d.text((348, y), str(i), font=small, fill='white')
        width = int((float(value) - low) / max(high - low, 1e-9) * 290)
        d.rectangle((379, y + 3, 379 + width, y + 27), fill='#52d8c9' if i == pred else '#31586d')
    d.text((348, 520), 'Relative logit bars / not probabilities', font=small, fill='white')
    backend = f'{calls} TPU matrix product' + ('s' if calls != 1 else '') if calls else 'CPU matrix product'
    d.text((26, 566), f"Board compute: {rec['compute_ms']:.2f} ms / {backend}", font=small, fill='#b2f073')
    d.text((26, 613), f"Held-out int8 accuracy: {training['int8_test_accuracy']*100:.2f}% / 10,000 images", font=small, fill='white')
    d.text((26, 651), 'First 20 test images / no cherry-picking / no host model execution', font=small, fill='white')
    d.text((26, 683), f"Request {rec['sequence']} / checksum + all 10 logits verified", font=small, fill='#52d8c9')
    return im


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', default='/dev/cu.usbserial-0001')
    p.add_argument('--http-port', type=int, default=8766)
    p.add_argument('--frames', type=int, default=0, help='Verified requests to acquire; zero runs continuously')
    p.add_argument('--board', type=Path, default=ROOT/'build-classifier/board', help='Build directory for the programmed image')
    p.add_argument('--expected-backend-calls', type=int, help='Explicit count for an older image without a build manifest')
    p.add_argument('--presentation-delay', type=float, default=0, help='Optional display pacing in seconds; acquisition remains unpaced')
    p.add_argument('--capture-gif', type=Path, help='Explicit destination for the first 20 verified samples and a JSON capture record')
    a = p.parse_args()
    if a.frames < 0 or a.presentation_delay < 0: p.error('Frame limit and presentation delay must be nonnegative')
    if a.capture_gif and 0 < a.frames < 20: p.error('--capture-gif needs at least 20 frames')
    out = ROOT/'build-classifier'
    manifest_path = a.board/'build-manifest.json'
    if manifest_path.exists():
        _, manifest = load_expected_modes(a.board, {i:0 for i in range(20)})
        if manifest.get('io_transport','uart') != 'uart': p.error('Selected build manifest does not match the requested UART transport')
        out = Path(manifest.get('artifact_dir', out))
        contracts = {int(x['mode']): x for x in manifest['modes']}; clock_hz = manifest['clock_hz']
        if set(contracts) != set(range(20)): p.error('Classifier build manifest must describe all 20 samples')
    else:
        calls = a.expected_backend_calls
        if calls is None:
            report_path = out/'compile-report.json'
            if not report_path.exists(): p.error('Select --board with build-manifest.json or provide --expected-backend-calls for the programmed image')
            report = json.loads(report_path.read_text())
            # The historical classifier has one straight-line matrix product.
            # New image builds carry a manifest bound to their firmware hash.
            if report.get('regions') or report.get('gemm_policy') is not None: p.error('Use the new image build manifest or explicitly set --expected-backend-calls for an older image')
            calls = sum(x['device'] == 'tpu' for x in report['placement'])
        if calls < 0: p.error('--expected-backend-calls must be nonnegative')
        contracts = {i: dict(expected_backend_calls=calls, words=11) for i in range(20)}; clock_hz = 100000000
    samples = np.load(out/'samples.npz'); expected = np.load(a.board/'classifier-expected.npy' if manifest_path.exists() else out/'expected.npy')
    training = json.loads((out/'training-report.json').read_text())
    state = {}; lock = threading.Lock(); capture = []
    font = '/System/Library/Fonts/Supplemental/Arial.ttf'
    if not Path(font).exists(): font = 'DejaVuSans.ttf'
    try: large = ImageFont.truetype(font, 28); small = ImageFont.truetype(font, 19)
    except OSError: large = ImageFont.load_default(); small = ImageFont.load_default()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/': b = PAGE; mime = 'text/html'
            elif self.path.startswith('/state'):
                with lock: b = json.dumps(state).encode()
                mime = 'application/json'
            else: self.send_error(404); return
            self.send_response(200); self.send_header('Content-Type', mime); self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', a.http_port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    def acquire(stream):
        intervals = deque(maxlen=16); previous = None; latencies = LatencyWindow()
        with open_transport(a.port, stop=stream.stopped) as uart:
            uart.reset_input_buffer(); seq = 0
            while not stream.stopped.is_set() and (not a.frames or seq < a.frames):
                index = seq % 20; rec, data = transact(uart, seq, index, stop=stream.stopped)
                contract = contracts[index]
                if rec['status'] or rec['words'] != contract['words'] or rec['words'] != 11 or rec['backend_calls'] != contract['expected_backend_calls']:
                    raise RuntimeError(f'Classifier response does not match selected image: {rec}')
                np.testing.assert_array_equal(data[:10].view(np.uint32), expected[index].view(np.uint32))
                if data[10] != np.argmax(expected[index]): raise RuntimeError('Incorrect classifier prediction')
                now = time.perf_counter()
                if previous is not None: intervals.append(now - previous)
                previous = now
                rec.update(sample=index, true_label=int(samples['labels'][index]), board_prediction=int(data[10]), all_logits_bit_exact=True, timestamp=time.time(), acquisition_fps=len(intervals)/sum(intervals) if intervals else 0, clock_hz=clock_hz, compute_ms=rec['cycles']/(clock_hz/1000))
                latencies.observe(rec['roundtrip_ms'],rec['compute_ms']); rec['latency']=latencies.summary()
                rec['outside_compute_ms']=max(0.,rec['roundtrip_ms']-rec['compute_ms'])
                if a.capture_gif and seq < 20: capture.append((dict(rec), data))
                stream.publish(0, (rec, data)); seq += 1
    captured = False; displayed = 0; previous = None; intervals = deque(maxlen=16)
    try:
        with LatestResults(acquire, [0]) as stream:
            for pending in stream:
                rec, data = pending[0]; start = time.perf_counter()
                im = render(rec, data, samples, training, large, small)
                buf = io.BytesIO(); im.save(buf, format='PNG'); displayed += 1
                now = time.perf_counter()
                if previous is not None: intervals.append(now - previous)
                previous = now
                with lock:
                    state.update(**rec, png=base64.b64encode(buf.getvalue()).decode(), host_render_ms=(now-start)*1000, display_updates_fps=len(intervals)/sum(intervals) if intervals else 0, displayed_frames=displayed, skipped_display_frames=rec['sequence']+1-displayed)
                if a.capture_gif and not captured and len(capture) == 20:
                    frames = [render(r, d, samples, training, large, small) for r, d in capture]
                    a.capture_gif.parent.mkdir(parents=True, exist_ok=True)
                    frames[0].save(a.capture_gif, save_all=True, append_images=frames[1:], duration=800, loop=0)
                    report = dict(passed=True, source='Physical KC705 trained classifier', training=training, physical_samples=[r for r, _ in capture], playback_frame_ms=800, playback_note='Presentation paced at 0.8 seconds per image; acquisition has no presentation delay.')
                    bitstream = a.board/'soc.bit'
                    if bitstream.exists(): report['selected_bitstream_sha256'] = hashlib.sha256(bitstream.read_bytes()).hexdigest()
                    a.capture_gif.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
                    captured = True
                if a.presentation_delay: stream.stopped.wait(a.presentation_delay)
    except KeyboardInterrupt: pass
    finally: server.shutdown(); server.server_close()


if __name__ == '__main__': main()

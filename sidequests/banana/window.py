#!/usr/bin/env python3
"""Native live-render window; displays only frames verified by live.py."""
import argparse
import base64
import io
import json
import queue
import threading
import time
import tkinter as tk
from urllib.request import urlopen
from PIL import Image, ImageTk

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/state")
    parser.add_argument("--title", default="KC705 — Live Banana Render / FPS")
    parser.add_argument("--heading", default="KC705 / LIVE BANANA")
    parser.add_argument("--scope", default="TPU camera transforms on physical KC705 · JAX rasterization on host · No DDR")
    args = parser.parse_args()
    root = tk.Tk()
    root.title(args.title)
    root.geometry("1100x740+80+70")
    root.configure(bg="#11160e")
    root.lift()
    root.attributes("-topmost", True)
    root.after(3000, lambda: root.attributes("-topmost", False))
    tk.Label(root, text=args.heading, fg="#eaf3d6", bg="#11160e",
             font=("Helvetica", 24), anchor="w").pack(fill="x", padx=30, pady=(24, 18))
    body = tk.Frame(root, bg="#11160e")
    body.pack(fill="both", expand=True, padx=30)
    placeholder = ImageTk.PhotoImage(Image.new("RGB", (512, 512), "black"))
    image_label = tk.Label(body, bg="black", image=placeholder)
    image_label.image = placeholder
    image_label.pack(side="left", anchor="n")
    panel = tk.Frame(body, bg="#11160e")
    panel.pack(side="left", fill="both", expand=True, padx=28)
    fps = tk.StringVar(value="— FPS")
    tk.Label(panel, textvariable=fps, fg="#dafa7b", bg="#11160e",
             font=("Helvetica", 53), anchor="w").pack(fill="x", pady=(20, 8))
    tk.Label(panel, text="Measured completed frames\nRolling 16-frame window", fg="#aebf98",
             bg="#11160e", font=("Helvetica", 16), justify="left", anchor="w").pack(fill="x")
    details = tk.StringVar(value="Waiting for the programmed board…")
    tk.Label(panel, textvariable=details, fg="#eaf3d6", bg="#11160e", font=("Helvetica", 17),
             justify="left", anchor="nw").pack(fill="x", pady=35)
    status = tk.StringVar(value="Building/programming image. No live frames received yet.")
    tk.Label(root, textvariable=status, fg="#c0cbad", bg="#11160e", font=("Helvetica", 15),
             anchor="w", wraplength=1030).pack(fill="x", padx=30, pady=12)
    tk.Label(root, text=args.scope,
             fg="#879776", bg="#11160e", font=("Helvetica", 13), anchor="w").pack(fill="x", padx=30, pady=(0, 20))
    messages = queue.Queue(maxsize=2)
    stopped = threading.Event()

    def worker():
        while not stopped.is_set():
            try:
                with urlopen(args.url, timeout=1) as response:
                    item = json.load(response)
            except Exception:
                item = None
            try:
                messages.put_nowait(item)
            except queue.Full:
                pass
            stopped.wait(.02)

    threading.Thread(target=worker, daemon=True).start()
    previous = -1
    def update():
        nonlocal previous
        item = None
        received = False
        while not messages.empty():
            item = messages.get_nowait()
            received = True
        if received and item is None:
            fps.set("— FPS")
            status.set("Waiting for the live renderer / board connection…")
        if item is not None:
            active = item.get("connected") and item.get("age_seconds", 10) < 5
            fps.set(f"{item['fps']:.2f} FPS" if active else "— FPS")
            status.set(item.get("message", "Waiting for board") +
                       (" · Last frame retained" if item.get("age_seconds", 0) >= 5 else ""))
            if item.get("png") and item["sequence"] != previous:
                previous = item["sequence"]
                image = Image.open(io.BytesIO(base64.b64decode(item["png"]))).resize((512, 512), Image.Resampling.NEAREST)
                photo = ImageTk.PhotoImage(image)
                image_label.configure(image=photo, width=512, height=512)
                image_label.image = photo
                scene_details = (f"Simulated time         {item['sim_time']:.1f} s\n\n"
                                 f"Energy drift             {item['energy_drift_percent']:.4f}%"
                                 if 'sim_time' in item else f"Camera angle           {item['azimuth']:.0f}°")
                details.set(f"FPGA + CPU driver    {item['fpga_compute_ms']:.2f} ms\n\n"
                            f"UART + host wait     {item['uart_and_host_wait_ms']:.2f} ms\n\n"
                            f"Host render + PNG    {item['host_render_ms']:.2f} ms\n\n"
                            f"Verified frame          {item['sequence']}\n\n" + scene_details)
        root.after(16, update)
    def close():
        stopped.set()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    root.after(16, update)
    root.mainloop()

if __name__ == "__main__":
    main()

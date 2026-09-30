# Tweet images

- `demo-viewer.jpg`: actual browser screenshot of the live cloth stream, with the same frame/metrics as the native viewer. Not a photograph of the FPGA.
- `architecture.png`: exported from Excalidraw; edit `architecture.excalidraw` to revise it.
- `performance-table.jpg`: browser screenshot of `performance.html`, using recorded first-step RTL measurements.
- `bottleneck-table.jpg`: browser screenshot of `bottleneck.html`, using recorded first-step RTL cycle attribution.

Run `python3 media/cloth-thread/v2/serve.py` and open http://127.0.0.1:8771/ to view the gallery. The live viewer requires the existing cloth renderer on port 8765. Image and table sources are included. Display FPS is not real-time simulation speed. Each physics step advances 1/7680 s.

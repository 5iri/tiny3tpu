"""Serve the image tables and a read-only mirror of the native cloth viewer."""
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import urlopen
from pathlib import Path
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(Path(__file__).parent),**kw)
 def do_GET(self):
  if self.path=='/state':
   with urlopen('http://127.0.0.1:8765/state',timeout=2) as r:b=r.read()
   self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
  else:super().do_GET()
ThreadingHTTPServer(('127.0.0.1',8771),Handler).serve_forever()

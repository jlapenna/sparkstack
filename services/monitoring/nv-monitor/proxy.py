import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

class ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            req = urllib.request.Request("http://127.0.0.1:9102" + self.path)
            with urllib.request.urlopen(req) as response:
                body = response.read().decode('utf-8', errors='replace')
                lines = body.split('\n')
                new_lines = []
                for line in lines:
                    if 'nv_disk_' in line:
                        continue
                    if line.startswith('mplicit_layer'):
                        continue
                    if 'gsp_ga' in line:
                        continue
                    new_lines.append(line)
                new_body = '\n'.join(new_lines).encode('utf-8')
                
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; version=0.0.4')
                self.end_headers()
                self.wfile.write(new_body)
        except Exception as e:
            self.send_response(500)
            self.end_headers()

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 9101), ProxyHandler)
    server.serve_forever()

"""
本地代理服务器：解决浏览器 CORS 限制
- 静态文件：http://localhost:8766/
- LLM 普通：POST http://localhost:8766/llm
- LLM 流式：POST http://localhost:8766/llm/stream  (SSE)
"""
import http.client
import json
import urllib.request
import urllib.error
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import cast
from typing_extensions import override

ONEAPI_URL   = 'https://oneapi-comate.baidu-int.com/v1/chat/completions'
ONEAPI_TOKEN = 'sk-vrZ3CIi7X0vjUDAICb3d1e6f3f3a4aD981AfC5D6F4E39e1e'
PORT         = 8766


class Handler(SimpleHTTPRequestHandler):
    @override
    def log_message(self, format: str, *args: object) -> None:
        print(f'[proxy] {format % args}')

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path in ('/llm', '/llm/stream'):
            is_stream = (self.path == '/llm/stream')
            length = int(self.headers.get('Content-Length', 0))
            body   = self.rfile.read(length)

            # 流式请求：注入 stream:true
            if is_stream:
                try:
                    payload = cast(dict[str, object], json.loads(body))
                    payload['stream'] = True
                    body = json.dumps(payload).encode()
                except Exception:
                    pass

            req = urllib.request.Request(
                ONEAPI_URL,
                data=body,
                headers={
                    'Content-Type':  'application/json',
                    'Authorization': f'Bearer {ONEAPI_TOKEN}',
                },
                method='POST'
            )
            try:
                r: http.client.HTTPResponse = cast(http.client.HTTPResponse, urllib.request.urlopen(req, timeout=120))
                if is_stream:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('X-Accel-Buffering', 'no')
                    self._cors()
                    self.end_headers()
                    # 逐块转发 SSE
                    while True:
                        chunk: bytes = r.read(256)
                        if not chunk:
                            break
                        _ = self.wfile.write(chunk)
                        self.wfile.flush()
                else:
                    resp_body: bytes = r.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self._cors()
                    self.end_headers()
                    _ = self.wfile.write(resp_body)
            except urllib.error.HTTPError as e:
                err = e.read()
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self._cors()
                self.end_headers()
                _ = self.wfile.write(err)
            except Exception as e:
                self.send_response(502)
                self._cors()
                self.end_headers()
                _ = self.wfile.write(json.dumps({'error': str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f'启动代理服务器：http://localhost:{PORT}/')
    print(f'LLM 普通端点：  http://localhost:{PORT}/llm')
    print(f'LLM 流式端点：  http://localhost:{PORT}/llm/stream')
    print('打开浏览器访问上方地址即可，按 Ctrl+C 停止\n')
    HTTPServer(('', PORT), Handler).serve_forever()

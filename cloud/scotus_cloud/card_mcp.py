"""Stateless, authenticated loopback MCP transport for existing host card tools."""
import base64
from contextlib import contextmanager
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import jsonschema


def mcp_content(value):
    if not isinstance(value, dict) or set(value) != {'contentItems'}:
        return [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}]
    result = []
    for item in value['contentItems']:
        if item['type'] == 'inputText':
            result.append({'type': 'text', 'text': item['text']})
        elif item['type'] == 'inputImage':
            prefix, data = item['imageUrl'].split(',', 1)
            if prefix not in ('data:image/jpeg;base64', 'data:image/png;base64'):
                raise ValueError('Only inline card preview images are supported')
            if len(base64.b64decode(data, validate=True)) > 524288:
                raise ValueError('Preview image exceeds the transport limit')
            result.append({'type': 'image', 'mimeType': prefix[5:-7], 'data': data})
        else:
            raise ValueError('Unknown card tool result')
    return result


@contextmanager
def card_server(definitions, handler):
    """Both transports call the same role handler; no separate tool implementation."""
    token = secrets.token_urlsafe(32)
    catalog = {tool['name']: tool for tool in definitions}

    class HTTP(BaseHTTPRequestHandler):
        def log_message(self, *_): pass  # Headers include a private bearer token.

        def send(self, status, value=None):
            body = json.dumps(value).encode() if value is not None else b''
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self): self.send(405)
        def do_DELETE(self): self.send(405)

        def do_POST(self):
            if self.path != '/mcp' or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                self.send(403); return
            origin = self.headers.get('Origin')
            if origin and origin != 'http://127.0.0.1:' + str(self.server.server_port):
                self.send(403); return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2097152: raise ValueError('Invalid MCP request size')
                message = json.loads(self.rfile.read(length))
                if not isinstance(message, dict): raise ValueError('Invalid MCP request')
            except (ValueError, TypeError):
                self.send(400); return
            if 'id' not in message:
                self.send(202); return
            method = message.get('method'); params = message.get('params') or {}
            reply = {'jsonrpc': '2.0', 'id': message['id']}
            if method == 'initialize':
                reply['result'] = {'protocolVersion': params.get('protocolVersion', '2025-03-26'),
                                   'capabilities': {'tools': {}}, 'serverInfo': {'name': 'scotus-cards', 'version': '1'}}
            elif method == 'ping': reply['result'] = {}
            elif method == 'tools/list': reply['result'] = {'tools': list(catalog.values())}
            elif method == 'tools/call':
                try:
                    tool = catalog[params['name']]
                    arguments = params.get('arguments', {})
                    jsonschema.validate(arguments, tool['inputSchema'])
                    reply['result'] = {'content': mcp_content(handler(params['name'], arguments)), 'isError': False}
                except (KeyError, jsonschema.ValidationError):
                    reply['result'] = {'content': [{'type': 'text', 'text': 'Unknown tool or invalid arguments'}], 'isError': True}
                except Exception as error:
                    message = str(error)[:600] if isinstance(error, ValueError) else 'Card tool unavailable; preserve the draft and report the problem.'
                    reply['result'] = {'content': [{'type': 'text', 'text': message}], 'isError': True}
            else: reply['error'] = {'code': -32601, 'message': 'Method not found'}
            self.send(200, reply)

    server = ThreadingHTTPServer(('127.0.0.1', 0), HTTP)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield {'mcpServers': {'cards': {'type': 'http', 'url': 'http://127.0.0.1:' + str(server.server_port) + '/mcp',
                                         'headers': {'Authorization': 'Bearer ' + token}}}}
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


"""Cancelable loopback OAuth callback; no browser secrets are inspected."""
import http.server
import threading
import time
import urllib.parse
import webbrowser


class LoginCancelled(RuntimeError):
    pass


class CallbackServer:
    def __init__(self, port=0, path='/', cancel=None, timeout=120):
        self.cancel = cancel if cancel is not None else threading.Event()
        self.timeout, self.params, self.path = timeout, {}, path
        self.state = None
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path != owner.path:
                    self.send_error(404)
                    return
                params = urllib.parse.parse_qs(parsed.query)
                if not owner.state or params.get('state') != [owner.state]:
                    self.send_error(400, 'Invalid OAuth state')
                    return
                owner.params = params
                owner.response_url = owner.redirect_uri + '?' + parsed.query
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write('Anmeldung empfangen. Du kannst diesen Tab schließen und zur Anwendung zurückkehren.'.encode('utf-8'))
            def log_message(self, *_):
                pass
        self.server = http.server.HTTPServer(('127.0.0.1', port), Handler)
        self.server.timeout = 0.2
        self.redirect_uri = f'http://127.0.0.1:{self.server.server_port}{path}'
        self.response_url = None

    def wait(self, url, state, open_browser=True):
        self.state = state
        print('Anmeldung im Browser:\n' + url)
        if open_browser:
            webbrowser.open(url)
        deadline = time.monotonic() + self.timeout
        while not self.params and time.monotonic() < deadline:
            if self.cancel.is_set():
                raise LoginCancelled('Anmeldung abgebrochen. Du kannst sie erneut starten.')
            self.server.handle_request()
        if self.cancel.is_set():
            raise LoginCancelled('Anmeldung abgebrochen.')
        if not self.params:
            raise RuntimeError('Keine Anmeldung empfangen. Browserseite geschlossen oder blockiert? Erneut anmelden oder Einrichtungshilfe öffnen.')
        if self.params.get('error'):
            raise RuntimeError('Anmeldung vom Anbieter abgelehnt: ' + self.params['error'][0] + '. Einrichtungshilfe und Testnutzer prüfen.')
        if not self.params.get('code'):
            raise RuntimeError('Die Anmeldung hat keinen OAuth-Code geliefert.')
        return self.params

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.server.server_close()

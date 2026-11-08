import json
import queue
import socket
import threading
import unittest

from gui_client import SocketClient


class SocketClientTests(unittest.TestCase):
    def test_connect_sends_login_and_receives_response(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        received = queue.Queue()
        server_errors = queue.Queue()

        def serve():
            try:
                connection, _ = server.accept()
                with connection:
                    line = connection.makefile("rb").readline()
                    received.put(json.loads(line))
                    connection.sendall(b'{"status":"011","data":"ok"}\n')
            except Exception as exc:
                server_errors.put(exc)
            finally:
                server.close()

        threading.Thread(target=serve, daemon=True).start()
        events = queue.Queue()
        client = SocketClient(events)
        client.connect("127.0.0.1", port, "alice")

        try:
            login = received.get(timeout=2)
        except queue.Empty:
            errors = list(server_errors.queue)
            client_events = list(events.queue)
            self.fail(f"No login received; server errors={errors!r}, client events={client_events!r}")
        self.assertEqual(
            login,
            {"action": "login", "data": {"username": "alice"}},
        )
        self.assertEqual(
            events.get(timeout=2),
            ("response", {"status": "011", "data": "ok"}),
        )
        client.close(notify=False)


if __name__ == "__main__":
    unittest.main()

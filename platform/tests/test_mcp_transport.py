"""Database-free transport checks: python -m unittest discover -s tests -p test_mcp_transport.py."""
import os
import unittest
from unittest.mock import patch

from mcp.server.mcpserver import MCPServer
from starlette.testclient import TestClient

from app.mcp.server import transport_security_settings


class MCPTransportTests(unittest.TestCase):
    def initialize(self, host, *, origin=None, settings=None):
        server = MCPServer("transport-test")
        app = server.streamable_http_app(
            transport_security=settings or transport_security_settings(),
            json_response=True,
        )
        headers = {"Host": host, "Accept": "application/json, text/event-stream"}
        if origin:
            headers["Origin"] = origin
        with TestClient(app) as client:
            return client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "transport-test", "version": "1"}},
            })

    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("MCP_PUBLIC_HOSTS", None)
        os.environ.pop("MCP_PUBLIC_HOST", None)
        self.addCleanup(self.env.stop)

    def test_public_host_and_same_origin_initialize(self):
        response = self.initialize("platform.aitinkerers.space", origin="https://platform.aitinkerers.space")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["serverInfo"]["name"], "transport-test")

    def test_loopback_with_port_remains_available(self):
        self.assertEqual(self.initialize("127.0.0.1:8790").status_code, 200)

    def test_mounted_platform_app_uses_public_host_configuration(self):
        from app.core.config import settings
        from app.main import app

        with TestClient(app) as client:
            response = client.post("/mcp-server/mcp", headers={
                "Host": "platform.aitinkerers.space", "X-API-Key": settings.api_key,
                "Accept": "application/json, text/event-stream",
            }, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "transport-test", "version": "1"}},
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn("safety-platform", response.text)

    def test_unrecognized_host_is_rejected(self):
        self.assertEqual(self.initialize("platform.aitinkerers.space.attacker.example").status_code, 421)

    def test_unrecognized_origin_is_rejected(self):
        self.assertEqual(self.initialize("platform.aitinkerers.space", origin="https://attacker.example").status_code, 403)

    def test_configured_public_hosts_replace_default(self):
        os.environ["MCP_PUBLIC_HOSTS"] = "telemetry.example:8443, copilot.example"
        settings = transport_security_settings()
        self.assertEqual(self.initialize("telemetry.example:8443", settings=settings).status_code, 200)
        self.assertEqual(self.initialize("copilot.example:443", settings=settings).status_code, 200)
        self.assertEqual(self.initialize("platform.aitinkerers.space", settings=settings).status_code, 421)

    def test_wildcard_or_url_configuration_is_rejected(self):
        for invalid in ("*", "*.example", "https://example.com", "example.com/path", "example.com:0"):
            with self.subTest(invalid=invalid), patch.dict(os.environ, {"MCP_PUBLIC_HOSTS": invalid}):
                with self.assertRaises(ValueError):
                    transport_security_settings()


if __name__ == "__main__":
    unittest.main()

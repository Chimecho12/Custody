"""OpenAI 호환 프록시: 전송 형식만 바꾸고 집행은 바꾸지 않는다는 약속을 검사한다.

- 공개된 응답만 200 으로 나가고, 검증 결과는 꾸미지 않고 itx 필드에 그대로 적는다.
- 스트리밍은 버퍼링해 흘리지 않고 거부한다 (검증기는 있으나 경로에 연결되지 않았다 — limits 9).
- usage 는 지어내지 않는다. 공유 비밀이 켜져 있으면 없는 요청은 401 이다.
"""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from itx.crypto import HAS_CRYPTOGRAPHY


@unittest.skipUnless(HAS_CRYPTOGRAPHY, "network runtime requires cryptography")
class ProxyGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from itx.runtime.proxy import Gateway, build_server
        cls.temp = tempfile.TemporaryDirectory(prefix="itx-proxy-")
        cls.gateway = Gateway(Path(cls.temp.name) / "data", lab=True, api_key="local-secret")
        cls.server = build_server(cls.gateway, "127.0.0.1", 0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.gateway.close()
        cls.temp.cleanup()

    def call(self, path, body=None, auth="local-secret", headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method="POST" if data else "GET",
                                         headers={"Content-Type": "application/json", **(headers or {}),
                                                  **({"Authorization": "Bearer " + auth} if auth else {})})
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_health_reports_streaming_unsupported(self):
        status, body = self.call("/health")
        self.assertEqual(status, 200, body)
        self.assertFalse(body["streaming_supported"])
        self.assertEqual(body["itx"]["source"], "network_lab")

    def test_completion_releases_only_the_verified_response(self):
        status, body = self.call("/v1/chat/completions", {"model": "gpt-anything",
                                 "messages": [{"role": "user", "content": "프록시 경유 정상 요청"}]})
        self.assertEqual(status, 200, body)
        self.assertIn("프록시 경유 정상 요청", body["choices"][0]["message"]["content"])
        self.assertNotIn("usage", body)  # 세지 않은 토큰 수를 지어내지 않는다
        self.assertTrue(body["itx"]["verified"])
        self.assertEqual(body["itx"]["action"], "accept")
        self.assertEqual(body["itx"]["checks"]["response_binding"], "pass")
        self.assertTrue(body["itx"]["model_substituted"])  # 클라이언트의 model 은 경로 선택에 쓰이지 않는다
        self.assertEqual(body["itx"]["requested_model"], "gpt-anything")
        self.assertNotEqual(body["model"], "gpt-anything")

    def test_observe_mode_is_not_reported_as_verified(self):
        status, body = self.call("/v1/chat/completions", {"messages": [{"role": "user", "content": "관찰 모드"}]},
                                 headers={"X-Itx-Mode": "observe"})
        self.assertEqual(status, 200, body)
        self.assertFalse(body["itx"]["verified"])
        self.assertEqual(body["itx"]["action"], "accept_unverified")

    def test_streaming_is_refused_not_buffered(self):
        status, body = self.call("/v1/chat/completions", {"stream": True,
                                 "messages": [{"role": "user", "content": "스트리밍"}]})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "streaming_unsupported")

    def test_missing_api_key_is_rejected_before_the_agent(self):
        status, body = self.call("/v1/chat/completions", {"messages": [{"role": "user", "content": "x"}]}, auth=None)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "invalid_api_key")

    def test_malformed_requests_are_400(self):
        status, body = self.call("/v1/chat/completions", {"messages": []})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_messages")
        status, _ = self.call("/v1/other", {"messages": [{"role": "user", "content": "x"}]})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()

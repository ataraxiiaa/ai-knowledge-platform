"""Deterministic OpenAI-compatible provider for disposable research verification."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os

if os.environ.get("PHASE7_TEST_MODE") != "1":
    raise SystemExit("Only run in the disposable research test project")

QUOTES = (
    "KV cache compression reduces memory used by attention state.",
    "Weight quantization reduces memory used by model parameters.",
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        size = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(size))
        payload = json.loads(request["messages"][1]["content"])
        if "passages" in payload:
            passage = payload["passages"][0]
            content = {"claims": [{"text": "The paper describes a memory-saving approach.",
                "evidence": [{"source_id": passage["source_id"], "quote": passage["text"]}]}]}
        elif "evidence" not in payload:
            content = {"questions": ["How does KV cache compression reduce memory?",
                                     "How does weight quantization reduce memory?",
                                     "How do cache compression and quantization compare?"]}
        else:
            sections = []
            for index, quote in enumerate(QUOTES, 1):
                source = next(item for item in payload["evidence"] if quote in item["content"])
                if "invalid evidence test" in payload["request"] and index == 1:
                    quote = "fabricated evidence"
                sections.append({"question_index": index, "claims": [{
                    "text": QUOTES[index - 1],
                    "evidence": [{"source_id": source["source_id"], "quote": quote}],
                }]})
            sections.append({"question_index": 3, "claims": [{
                "text": "Cache compression reduces attention-state memory, while quantization reduces parameter memory.",
                "evidence": [{"source_id": next(item["source_id"] for item in payload["evidence"]
                               if QUOTES[0] in item["content"]), "quote": QUOTES[0]},
                             {"source_id": next(item["source_id"] for item in payload["evidence"]
                               if QUOTES[1] in item["content"]), "quote": QUOTES[1]}],
            }]})
            content = {"sections": sections}
        body = json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(content)}}], "usage": {
            "prompt_tokens": 12, "completion_tokens": 8}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("0.0.0.0", 8089), Handler).serve_forever()

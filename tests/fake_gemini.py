"""A tiny local stand-in for the Gemini REST API so the real google-genai SDK
code path (request building, headers, schema, error mapping) is tested offline."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GOOD_TURN = {
    "partner_line": "Thanks for coming. How would you describe your strengths?",
    "note": "",
    "tip": "Give one strength and one proof.",
    "options": [
        {"text": "I analyse data carefully; for example, I cut a report's errors by half.", "rating": 3,
         "feedback": "Specific strength with evidence."},
        {"text": "I am good with data and I work hard.", "rating": 2, "feedback": "Fine but generic."},
        {"text": "I am having many strengths.", "rating": 1, "feedback": "'Am having' should be 'have'."},
        {"text": "Nothing special.", "rating": 0, "feedback": "Undersells you."},
    ],
}


class FakeGemini:
    def __init__(self):
        self.ok_models = {"gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"}
        self.status_for = {}          # model -> http status to return (overrides ok_models)
        self.listed = []              # model ids returned by GET /models
        self.turn_modes = []          # queue: "good" | "garbage" | "bad_ratings" | "empty" (default good)
        self.debrief_text = ("You picked the best reply most of the time and your tone was strong. "
                             "Grammar needs a little more care. Next, replay the scenario and focus on articles.")
        self.requests = []
        self.global_status = None     # e.g. 400/401/500 for every call
        self._server = None

    # ---- lifecycle
    def start(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                fake.requests.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
                models = [{"name": f"models/{m}", "supportedGenerationMethods": ["generateContent"]} for m in fake.listed]
                self._send(200, {"models": models})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                m = re.search(r"/models/([^:/]+):generateContent", self.path)
                model = m.group(1) if m else ""
                fake.requests.append({"method": "POST", "model": model, "body": body, "headers": dict(self.headers)})
                status = fake.global_status or fake.status_for.get(model)
                if status is None and model not in fake.ok_models:
                    status = 404
                if status:
                    msgs = {400: "API key not valid. Please pass a valid API key.", 401: "Unauthorized",
                            403: "Permission denied for this model", 404: f"models/{model} is not found",
                            429: "Quota exceeded", 500: "Internal error"}
                    self._send(status, {"error": {"code": status, "message": msgs.get(status, "err"),
                                                  "status": "ERR"}})
                    return
                system = (body.get("systemInstruction") or {}).get("parts", [{}])[0].get("text", "")
                if system.startswith("You write ONE turn"):
                    mode = fake.turn_modes.pop(0) if fake.turn_modes else "good"
                    text = {
                        "good": json.dumps(GOOD_TURN),
                        "garbage": "Sure! Here is your turn: {not json",
                        "bad_ratings": json.dumps(dict(GOOD_TURN, options=[dict(o, rating=3) for o in GOOD_TURN["options"]])),
                        "empty": "",
                    }[mode]
                elif system.startswith("You are a supportive"):
                    text = fake.debrief_text
                else:
                    text = "OK"
                parts = [{"text": text}] if text else []
                self._send(200, {"candidates": [{"content": {"role": "model", "parts": parts},
                                                 "finishReason": "STOP", "index": 0}],
                                 "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2}})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    @property
    def url(self):
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def posts(self):
        return [r for r in self.requests if r["method"] == "POST"]

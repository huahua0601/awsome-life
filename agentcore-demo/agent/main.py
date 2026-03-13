"""Strands Agent on AgentCore Runtime with Claude Opus 4.6.

Implements the AgentCore contract directly with uvicorn + a minimal HTTP handler,
without depending on bedrock-agentcore SDK for faster cold start.

Endpoints:
  GET  /ping         -> {"status": "healthy"}
  POST /invocations  -> {"result": "..."}
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from strands import Agent
        from strands.models import BedrockModel

        model = BedrockModel(model_id="global.anthropic.claude-opus-4-6-v1")
        _agent = Agent(
            model=model,
            system_prompt="你是一个由 Claude Opus 4.6 驱动的智能助手。请用中文回复用户。",
        )
    return _agent


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ping":
            self._respond(200, {"status": "healthy"})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/invocations":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            prompt = body.get("prompt", "Hello")
            try:
                agent = _get_agent()
                result = agent(prompt)

                usage = getattr(result.metrics, "accumulated_usage", {}) or {}
                input_tokens = usage.get("inputTokens", 0)
                output_tokens = usage.get("outputTokens", 0)
                total_tokens = usage.get("totalTokens", input_tokens + output_tokens)

                # Claude Opus 4.6: $5 / 1M input, $25 / 1M output
                input_cost = input_tokens * 5.0 / 1_000_000
                output_cost = output_tokens * 25.0 / 1_000_000
                total_cost = input_cost + output_cost

                self._respond(200, {
                    "result": result.message,
                    "usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": total_tokens,
                    },
                    "cost": {
                        "model": "claude-opus-4-6-v1",
                        "input_cost_usd": round(input_cost, 6),
                        "output_cost_usd": round(output_cost, 6),
                        "total_cost_usd": round(total_cost, 6),
                        "pricing": "$5/M input, $25/M output",
                    },
                })
            except Exception as e:
                self._respond(500, {"error": str(e)})
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, code, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    print("Agent server listening on :8080")
    server.serve_forever()

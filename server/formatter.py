"""Response Formatter: the JSON contract returned by POST /chat.

{
  "session_id":   "uuid",
  "message_id":   123,
  "answer":       "assistant text (Markdown-light)",
  "routes":       ["tool", "rag"],          # which paths the router chose, in execution order
  "route_reason": "why",
  "router":       "llm" | "rules",          # which router made the decision
  "sources":      [{"n", "title", "heading", "source_type", "source_url", "score"}],
  "tool_calls":   [{"tool", "input", "assessment", "indicators", "error"}]
}
"""


def sources_payload(sources: list[dict]) -> list[dict]:
    return [{
        "n": i,
        "title": s["title"],
        "heading": s["heading"],
        "source_type": s["source_type"],
        "source_url": s["source_url"],
        "score": s["score"],
    } for i, s in enumerate(sources, 1)]


def tool_calls_payload(results: list[dict]) -> list[dict]:
    payload = []
    for r in results:
        out = r.get("output") or {}
        payload.append({
            "tool": r["tool"],
            "input": next(iter(r["input"].values()), "") if isinstance(r["input"], dict) else "",
            "selected_by": r.get("selected_by"),
            "assessment": out.get("assessment"),
            "indicators": [{"severity": i["severity"], "detail": i["detail"]}
                           for i in out.get("indicators", [])],
            "error": r.get("error"),
        })
    return payload


def format_response(session_id, message_id, answer, decision, sources, tool_results) -> dict:
    return {
        "session_id": str(session_id),
        "message_id": message_id,
        "answer": answer,
        "routes": decision["routes"],
        "route_reason": decision["reason"],
        "router": decision["router"],
        "sources": sources_payload(sources),
        "tool_calls": tool_calls_payload(tool_results),
    }

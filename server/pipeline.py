"""The AI pipeline, run for every /chat request:

  Agent Router -> [Tools] -> [RAG] -> LLM (LCEL) -> Response Formatter

The router may choose several paths; they always run in the order tool -> rag, so retrieval can
use what the tools found. Every step degrades instead of crashing: a failed tool is reported to
the model as an error, a failed retrieval continues without documents, and only a failure of
both LLMs returns an error response.
"""
import logging
import time

from werkzeug.exceptions import ServiceUnavailable

from server import config, db, formatter, llm, rag, router, tool_runner

log = logging.getLogger("phishcheck.pipeline")


class _Timer:
    def __init__(self):
        self.ms: dict[str, int] = {}
        self._last = time.perf_counter()

    def lap(self, step: str) -> None:
        now = time.perf_counter()
        self.ms[step] = int((now - self._last) * 1000)
        self._last = now


def run(session_id, message: str) -> dict:
    timer = _Timer()
    db.ensure_session(session_id)
    history = db.get_history(session_id, limit=config.HISTORY_TURNS * 2)
    db.save_message(session_id, "user", message)

    # 1. Agent Router
    decision = router.route(message, history)
    timer.lap("router")
    log.info("Routes %s (%s): %s", decision["routes"], decision["router"], decision["reason"])

    # 2. Tools
    tool_results, tool_log_ids = [], []
    if "tool" in decision["routes"]:
        tool_results, tool_log_ids = tool_runner.select_and_run(session_id, message, history)
        timer.lap("tools")

    # 3. RAG
    sources = []
    if "rag" in decision["routes"]:
        query = decision["search_query"] or message
        findings = tool_runner.findings_for_search(tool_results)
        if findings:
            query = f"{query} {findings}"
        try:
            sources = rag.retrieve_balanced(query)
        except Exception:
            log.exception("Retrieval failed; answering without documents")
        timer.lap("rag")

    # 4. LLM
    try:
        answer = llm.answer(message, history, sources, tool_results, decision["routes"])
    except llm.LLMUnavailable as exc:
        raise ServiceUnavailable(str(exc)) from exc
    timer.lap("llm")

    # 5. Persist and format
    message_id = db.save_message(
        session_id, "assistant", answer, routes=decision["routes"],
        route_reason=decision["reason"], sources=formatter.sources_payload(sources))
    db.link_tool_calls(tool_log_ids, message_id)
    log.info("Timings (ms): %s", timer.ms)
    response = formatter.format_response(session_id, message_id, answer, decision, sources,
                                         tool_results)
    response["timings_ms"] = timer.ms
    return response

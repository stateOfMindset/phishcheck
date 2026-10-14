"""The AI pipeline: Router -> (Tools | RAG | Direct) -> LLM -> Response Formatter.

Placeholder until the router, tools, RAG and LLM modules are in place.
"""
from werkzeug.exceptions import NotImplemented as HTTPNotImplemented


def run(session_id, message: str) -> dict:
    raise HTTPNotImplemented("The chat pipeline is not implemented yet.")

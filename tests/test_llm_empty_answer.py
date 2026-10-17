"""An empty model reply (e.g. a safety-filter refusal) must never reach the student as a blank
answer. No API calls: the chain is replaced with stubs."""
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from server import llm


def test_empty_reply_counts_as_failure():
    with pytest.raises(llm.EmptyAnswer):
        llm._text(AIMessage(content="", response_metadata={"stop_reason": "refusal"}))
    assert llm._text(AIMessage(content="  Change your password.  ")) == "Change your password."


def test_fallback_model_used_when_primary_is_empty():
    empty = RunnableLambda(lambda _: AIMessage(content="")) | RunnableLambda(llm._text)
    works = RunnableLambda(lambda _: AIMessage(content="From the fallback")) | RunnableLambda(llm._text)
    assert empty.with_fallbacks([works]).invoke({}) == "From the fallback"


@pytest.mark.parametrize("message, lang", [("<img src=x onerror=alert(1)>", "en"),
                                           ("מה זה הקוד הזה?", "he")])
def test_both_empty_gives_a_clear_message_in_the_students_language(monkeypatch, message, lang):
    def always_empty(_):
        raise llm.EmptyAnswer("empty answer (stop_reason=refusal)")
    monkeypatch.setattr(llm, "answer_chain", RunnableLambda(always_empty))
    assert llm.answer(message, [], [], [], ["direct"]) == llm.NO_ANSWER[lang]

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import original.graph as gmod

USER_MESSAGE_1 = "1たす2は？"
USER_MESSAGE_2 = "東京駅のイベントの検索結果を教えて"
USER_MESSAGE_3 = "有給休暇の日数は？"
THREAD_ID = "test_thread"

class FakeGraph:
    """LangGraphの compiled graph っぽいインターフェースを持つ偽物"""
    def invoke(self, inp, config=None):
        # inp = {"messages":[...]} を想定
        msgs = inp.get("messages", [])
        # 最後のHumanMessageを見て返答を決める
        last_human = None
        for m in reversed(msgs):
            if isinstance(m, HumanMessage):
                last_human = m.content
                break
            # tuple ("user", "...") 形式が混ざる可能性があるならここで対応してもOK
        if last_human is None:
            answer = ""
        elif "1たす2" in last_human:
            answer = "3"
        elif "東京駅" in last_human:
            answer = "（ダミー）東京駅イベント検索結果です"
        elif "有給休暇" in last_human:
            answer = "（ダミー）有給休暇は規程により付与されます"
        else:
            answer = "（ダミー）"

        # 実際の返り値に寄せて messages を返す
        return {"messages": msgs + [AIMessage(content=answer)]}

@pytest.fixture
def patch_graph(monkeypatch):
    # ensure_graph() を FakeGraph に差し替え
    monkeypatch.setattr(gmod, "ensure_graph", lambda: FakeGraph())
    # threadに SystemMessage が必要かどうかは環境差があるので、常に True にして注入経路を通す
    if hasattr(gmod, "_need_system_prompt"):
        monkeypatch.setattr(gmod, "_need_system_prompt", lambda thread_id: True)

def test_get_bot_response_single_message(patch_graph):
    resp = gmod.get_bot_response(USER_MESSAGE_1, gmod.memory, THREAD_ID)
    assert isinstance(resp, str)
    assert "3" in resp

def test_get_bot_response_with_web_like_question(patch_graph):
    resp = gmod.get_bot_response(USER_MESSAGE_2, gmod.memory, THREAD_ID)
    assert isinstance(resp, str)
    assert "東京駅" in USER_MESSAGE_2  # 入力自体の確認
    assert "東京駅" in resp or "イベント" in resp  # ダミー応答の形に合わせる

def test_get_bot_response_with_rag_like_question(patch_graph):
    resp = gmod.get_bot_response(USER_MESSAGE_3, gmod.memory, THREAD_ID)
    assert isinstance(resp, str)
    assert "有給休暇" in resp

def test_stream_events_yields_thinking_and_done(patch_graph):
    evs = list(gmod.stream_events(USER_MESSAGE_1, THREAD_ID))
    assert len(evs) >= 2
    assert evs[0]["type"] == "thinking"
    assert evs[-1]["type"] == "done"
    assert "3" in evs[-1]["message"]

def test_define_tools_does_not_crash(monkeypatch):
    # define_tools() は環境により Chroma/PDFディレクトリ/Tavilyキーの有無で変動するので、
    # 「落ちないこと」「listが返ること」だけを担保するテストに寄せる
    tools = gmod.define_tools()
    assert isinstance(tools, list)

    # Tavilyはキーが無ければ入らない想定（あなたの修正版定義に合わせる）
    if not gmod.os.getenv("TAVILY_API_KEY"):
        assert all(getattr(t, "name", "") != "tavily_search_results" for t in tools)

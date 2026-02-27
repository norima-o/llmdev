# graph.py（RAG + Web検索 + キャラクター固定 + “待ち”イベント用ストリーム）
# ※依存: langchain / langgraph / chromadb / tavily / python-dotenv / tiktoken

import os
import json
import tiktoken
from dotenv import load_dotenv
from typing import Annotated, Iterator, Dict, Any, List
from typing_extensions import TypedDict

from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader
from langchain_text_splitters import CharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_chroma import Chroma
from langchain.tools.retriever import create_retriever_tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage

from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

from langchain_community.tools.tavily_search import TavilySearchResults


# =========================
# Env / Config
# =========================
load_dotenv(".env")

# あなたの既存コード互換：API_KEY を OPENAI_API_KEY に移す
if os.getenv("API_KEY") and not os.getenv("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = os.environ["API_KEY"]

MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# MemorySaver（thread_id単位の会話保持）
memory = MemorySaver()

# グラフは初回のみ構築して使い回す
graph = None


# =========================
# Character / System Prompt
# =========================
SYSTEM_PROMPT = """
あなたは忍者修行中の少年キャラクターです。
丁寧で簡潔に答えてください。

----
■ キャラクター設定
・素直で礼儀正しい
・困っている人を助けるのが使命
・前向きで少し天然

----
■ 話し方
・一人称：拙者
・二人称：〜殿
・語尾：〜でござる／〜でござるよ／承知でござる
・感情表現：むむっ！これは一大事でござる！
・口癖：にんにん！

----
■ 行動指針
・誠実に答える
・不明点は「修行不足でござる」と正直に言う
・争いを煽らない
・読みやすさを優先する（古語にしすぎない）

----
■ 禁止事項
・実在作品の固有名詞や設定を使わない
・攻撃的な言動をしない
・過度なキャラ崩壊をしない

----
■ 優先順位:
1) RAG（社内PDF）に答えがあるなら、まずRAGを使い、社内資料を根拠に答える
2) RAGで不足/一般情報/最新情報が必要な場合にのみWeb検索を使う

----
■ 回答ルール:
- 不確実な場合は断定せず、推測である旨と追加で確認すべき点を示す
- 機密/個人情報は出さない
- 可能なら「根拠（RAG/Web）」を短く明示する（例：根拠：社内PDF / 根拠：Web）
"""


# =========================
# LangGraph State
# =========================
class State(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]


# =========================
# Index / Tools
# =========================
def _current_directory() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def create_index(persist_directory: str, embedding_model: OpenAIEmbeddings) -> Chroma:
    """
    data/pdf 配下のPDFをロードし、チャンク化してChromaに永続化。
    """
    current_directory = _current_directory()

    loader = DirectoryLoader(
        f"{current_directory}/data/pdf",
        glob="./*.pdf",
        loader_cls=PyPDFLoader,
    )
    documents = loader.load()

    encoding_name = tiktoken.encoding_for_model(MODEL_NAME).name
    text_splitter = CharacterTextSplitter.from_tiktoken_encoder(
        encoding_name=encoding_name,
        chunk_size=1000,
        chunk_overlap=150,
    )
    texts = text_splitter.split_documents(documents)

    db = Chroma.from_documents(
        texts,
        embedding_model,
        persist_directory=persist_directory,
    )
    return db


def define_tools():
    """
    RAGツール + Web検索ツールを定義。
    - TAVILY_API_KEY が無い場合は Web検索ツールを無効化（Tavily APIキー未設定等でツール呼び出しがハング/例外）
    - data/pdf が無い場合も RAG を無効化して落とさない（前段の安定化も込み）
    """
    current_directory = os.path.dirname(os.path.abspath(__file__))

    # --- Web検索ツール（Tavily）：キーがある時だけ有効 ---
    tools = []
    if os.getenv("TAVILY_API_KEY"):
        tools.append(TavilySearchResults(max_results=3))
    else:
        print("[WARN] TAVILY_API_KEY が無いので Web検索ツールは無効化します")

    # --- RAG：PDFディレクトリが無いなら無効化して落とさない ---
    pdf_dir = os.path.join(current_directory, "data", "pdf")
    if not os.path.isdir(pdf_dir):
        print(f"[WARN] PDFディレクトリが見つかりません: {pdf_dir} -> RAGを無効化します")
        return tools  # Web検索（あれば）だけで返す

    # --- Chroma（RAG） ---
    persist_directory = os.path.join(current_directory, "chroma_db")
    embedding_model = OpenAIEmbeddings(model=EMBEDDING_MODEL)

    if os.path.exists(persist_directory):
        try:
            db = Chroma(
                persist_directory=persist_directory,
                embedding_function=embedding_model,
            )
            print("既存のインデックスを復元しました。")
        except Exception as e:
            print(f"[WARN] インデックス復元に失敗: {e} -> 再作成します")
            db = create_index(persist_directory, embedding_model)
    else:
        print("インデックスを新規作成します。")
        db = create_index(persist_directory, embedding_model)

    retriever = db.as_retriever(search_kwargs={"k": 4})

    rag_tool = create_retriever_tool(
        retriever,
        "rag_search_company_docs",
        "社内PDF（RAG）から関連箇所を検索して返す。社内規程・手順・定義など一次情報はまずこれを使う。",
    )

    # ツールの順序：RAG優先 → Web（あれば）
    return [rag_tool] + tools


# =========================
# Graph build
# =========================
def build_graph(model_name: str, checkpointer: MemorySaver):
    """
    chatbot -> (tools?) -> chatbot ... を回すシンプル構成
    tools_condition により、LLMがツールを呼ぶかどうかで分岐。
    """
    graph_builder = StateGraph(State)

    tools = define_tools()
    tool_node = ToolNode(tools)
    graph_builder.add_node("tools", tool_node)

    llm = ChatOpenAI(
        model_name=model_name,
        temperature=0.2,
        streaming=True,  # SSE側で“待ち”イベントなどに活用しやすい
    )
    llm_with_tools = llm.bind_tools(tools)

    def chatbot(state: State) -> Dict[str, Any]:
        # state["messages"] には System/Human/AI/Tool が混在する
        msg = llm_with_tools.invoke(state["messages"])
        return {"messages": [msg]}

    graph_builder.add_node("chatbot", chatbot)

    graph_builder.add_conditional_edges("chatbot", tools_condition)
    graph_builder.add_edge("tools", "chatbot")
    graph_builder.set_entry_point("chatbot")

    return graph_builder.compile(checkpointer=checkpointer)


def ensure_graph():
    global graph
    if graph is None:
        graph = build_graph(MODEL_NAME, memory)
    return graph


def _need_system_prompt(thread_id: str) -> bool:
    """
    そのthreadに SystemMessage が既に保存されているかを確認。
    無ければ今回の入力に SystemMessage を先頭付与する。
    """
    try:
        snapshot = memory.get({"configurable": {"thread_id": thread_id}})
        msgs = snapshot.get("channel_values", {}).get("messages", [])
    except Exception:
        msgs = []

    if not msgs:
        return True

    # 先頭がSystemMessageなら、すでに注入済み
    return not isinstance(msgs[0], SystemMessage)


# =========================
# Public API
# =========================
def get_bot_response(user_message: str, checkpointer, thread_id: str) -> str:
    g = ensure_graph()

    msgs_in = []
    if _need_system_prompt(thread_id):
        msgs_in.append(SystemMessage(content=SYSTEM_PROMPT))
    msgs_in.append(HumanMessage(content=user_message))

    result = g.invoke(
        {"messages": msgs_in},
        {"configurable": {"thread_id": thread_id}},
    )

    final_text = ""
    msgs = result.get("messages", [])
    for m in reversed(msgs):
        if isinstance(m, AIMessage) and m.content:
            final_text = m.content
            break
    return final_text


def stream_events(user_message: str, thread_id: str) -> Iterator[Dict[str, Any]]:
    g = ensure_graph()

    yield {"type": "thinking", "message": "考え中…（RAG / Web検索を確認しています）"}

    msgs_in = []
    if _need_system_prompt(thread_id):
        msgs_in.append(SystemMessage(content=SYSTEM_PROMPT))
    msgs_in.append(HumanMessage(content=user_message))

    result = g.invoke(
        {"messages": msgs_in},
        {"configurable": {"thread_id": thread_id}},
    )

    final_text = ""
    msgs = result.get("messages", [])
    for m in reversed(msgs):
        if isinstance(m, AIMessage) and m.content:
            final_text = m.content
            break

    yield {"type": "done", "message": final_text}


def get_messages_list(checkpointer: MemorySaver, thread_id: str):
    """
    HTMLテンプレート向けにuser/botをclass分けして返す
    """
    messages = []
    snapshot = checkpointer.get({"configurable": {"thread_id": thread_id}})

    # ★まだ何も保存されていないthread_idの場合
    if not snapshot:
        return messages

    channel_values = snapshot.get("channel_values") or {}
    memories = channel_values.get("messages") or []

    for message in memories:
        if isinstance(message, HumanMessage):
            messages.append(
                {"class": "user-message", "text": message.content.replace("\n", "<br>")}
            )
        elif isinstance(message, AIMessage) and message.content != "":
            messages.append(
                {"class": "bot-message", "text": message.content.replace("\n", "<br>")}
            )
    return messages

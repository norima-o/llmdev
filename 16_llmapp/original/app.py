"""
app.py

Flaskアプリケーション本体。

役割:
- HTTPエンドポイントの提供
- セッション管理（thread_id単位）
- SSE (Server-Sent Events) によるストリーミング応答
- graph.py との接続

設計方針:
- 会話状態は LangGraph + MemorySaver 側に持たせる
- Flask側は「thread_idの払い出し」と「イベントの中継」に専念する
- メモリを全消ししない（マルチユーザー安全設計）
"""

# VS Codeのデバッグ実行で import エラーを出さない対策
# 実行ファイルが original/app.py の場合にプロジェクトルートを通す
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import json
from flask import (
    Flask, render_template, request, make_response, session,
    Response, stream_with_context
)

from original.graph import stream_events, get_messages_list, memory

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "your_secret_key")


def _ensure_thread_id() -> str:
    """
    セッションにthread_idが存在することを保証する。

    設計意図:
    - thread_id単位でLangGraphのMemorySaverが会話履歴を管理する
    - FlaskセッションとLangGraphのスレッドを1対1対応させる
    """
    if "thread_id" not in session:
        session["thread_id"] = str(uuid.uuid4())
    return session["thread_id"]


@app.route("/", methods=["GET"])
def index():
    """
    初期画面表示。

    注意:
    - ここで memory.storage.clear() をしない。
      理由:
        MemorySaverは全ユーザー共有インスタンスのため、
        クリアすると他ユーザーの会話も消える可能性がある。
    """
    _ensure_thread_id()
    return make_response(render_template("index.html", messages=[]))


@app.route("/history", methods=["GET"])
def history():
    """
    現在のthread_idに紐づく履歴を表示。

    graph.py 側が MemorySaver から履歴を取得する。
    """
    thread_id = _ensure_thread_id()
    messages = get_messages_list(memory, thread_id)
    return make_response(render_template("index.html", messages=messages))


@app.route("/stream", methods=["POST"])
def stream():
    """
    チャット送信口（SSE対応）。

    設計:
    - 通常のJSONレスポンスではなく text/event-stream を返す
    - フロントは main.js で逐次イベントを受信
    - thinking → done の2段階イベントを返す

    なぜSSEか？
    - ユーザーに「考え中」を明示するため
    - 将来的にトークン逐次表示へ拡張可能
    """
    thread_id = _ensure_thread_id()
    user_message = request.form.get("user_message", "").strip()

    def event_stream():
        # まず接続が生きてることをクライアントに通知（ここが無いとブラウザ側が待ち続けることがある）
        yield f"data: {json.dumps({'type':'ping','message':'connected'}, ensure_ascii=False)}\n\n"

        try:
            for ev in stream_events(user_message, thread_id):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            # 例外でも必ずクライアントに返す
            yield f"data: {json.dumps({'type':'error','message': str(e)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/clear", methods=["POST"])
def clear():
    """
    会話クリア。

    実装戦略:
    - メモリを直接消さない
    - thread_idを新規発行することで「新しい会話」として扱う

    理由:
    - MemorySaverはグローバルなので安全に部分削除しにくい
    - thread_id変更が最も安全
    """
    session["thread_id"] = str(uuid.uuid4())
    return make_response(render_template("index.html", messages=[]))


if __name__ == "__main__":
    # 本番では debug=False にする
    app.run(debug=True)

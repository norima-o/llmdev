# app.py（修正版：SSEで“待ち”を明示 / 履歴表示 / クリアはthread切替）
# そのまま original/app.py に置き換える想定です。
# ※ templates/index.html 側は /stream を叩くJS実装が必要（前回例の main.js など）

# VS Codeのデバッグ実行で import エラーを出さない対策
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
    """セッションにthread_idが無ければ作って返す"""
    if "thread_id" not in session:
        session["thread_id"] = str(uuid.uuid4())
    return session["thread_id"]


@app.route("/", methods=["GET"])
def index():
    """
    初期画面。
    ※ここで memory.storage.clear() しない（全ユーザー/全スレッド影響の可能性があるため）
    """
    _ensure_thread_id()
    return make_response(render_template("index.html", messages=[]))


@app.route("/history", methods=["GET"])
def history():
    """
    現在thread_idの履歴を表示
    """
    thread_id = _ensure_thread_id()
    messages = get_messages_list(memory, thread_id)
    return make_response(render_template("index.html", messages=messages))


@app.route("/stream", methods=["POST"])
def stream():
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
    会話クリア：
    - MemorySaverは全消しが危険なので、基本は「thread_idを新規発行」して新規会話扱いにする。
    - これでユーザー体感としては“クリア”になる。
    """
    session["thread_id"] = str(uuid.uuid4())
    return make_response(render_template("index.html", messages=[]))


if __name__ == "__main__":
    # debug=True は開発時のみ
    app.run(debug=True)

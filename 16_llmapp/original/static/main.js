// static/main.js（元の「スクロール最下部」「Ctrl+Enter送信」を維持しつつ、/stream(SSE)対応）
// 前提：
// - form id="chat-form"
// - 入力欄 id="user-input"（textarea）
// - 送信ボタン id="send-btn"（無ければ自動で無効化はスキップ）
// - チャット表示領域 id="chat-box"
// - app.py に /stream がある（text/event-stream を返す）
//
// ※テンプレ側で form の action を "/" のままにしていても、ここで submit を止めて fetch に置き換える。

window.onload = function () {
  // チャットボックスを取得
  const chatBox = document.getElementById('chat-box');

  // フォーム/入力欄
  const form = document.getElementById('chat-form');
  const textarea = document.getElementById('user-input');

  // 任意：送信ボタン（存在しない場合もあるのでガード）
  const sendBtn = document.getElementById('send-btn');

  // 初期表示：スクロール最下部
  if (chatBox) chatBox.scrollTop = chatBox.scrollHeight;

  // HTML挿入（簡易）※XSS気になる場合はtextContentで組み立ててください
  function appendMessage(cssClass, html) {
    if (!chatBox) return;
    const div = document.createElement('div');
    div.className = cssClass;
    div.innerHTML = html;
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
    return div;
  }

  // 改行を<br>へ
  function nl2br(s) {
    return (s || '').replace(/\n/g, '<br>');
  }

  // SSEレスポンスを読み取って event を処理
  async function sendMessageViaSSE(text) {
    // ユーザーメッセージを表示
    appendMessage('user-message', nl2br(text));

    // 待ち表示（Thinking）
    const thinkingDiv = appendMessage('bot-message', '<span>考え中…</span>');

    // 送信中は入力無効
    textarea.disabled = true;
    if (sendBtn) sendBtn.disabled = true;

    const body = new URLSearchParams();
    body.append('user_message', text);

    const res = await fetch('/stream', {
      method: 'POST',
      body: body,
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded'
      }
    });

    if (!res.ok || !res.body) {
      if (thinkingDiv) thinkingDiv.innerHTML = 'エラー：サーバ応答に失敗しました。';
      textarea.disabled = false;
      if (sendBtn) sendBtn.disabled = false;
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // SSEは \n\n 区切り
        const parts = buffer.split('\n\n');
        buffer = parts.pop();

        for (const part of parts) {
          // "data: {...}" 行を探す
          const dataLine = part.split('\n').find((l) => l.startsWith('data: '));
          if (!dataLine) continue;

          let ev;
          try {
            ev = JSON.parse(dataLine.replace('data: ', ''));
          } catch (e) {
            continue;
          }

          if (ev.type === 'ping') {
            // 接続確認用。表示は不要なら何もしない
          }

          if (ev.type === 'error') {
            if (thinkingDiv) thinkingDiv.innerHTML = 'エラー：' + (ev.message || '');
            textarea.disabled = false;
            if (sendBtn) sendBtn.disabled = false;
          }
          // thinking → 表示更新
          if (ev.type === 'thinking') {
            if (thinkingDiv) thinkingDiv.innerHTML = nl2br(ev.message);
          }

          // done → 最終回答を表示
          if (ev.type === 'done') {
            if (thinkingDiv) {
              thinkingDiv.innerHTML = nl2br(ev.message);
            } else {
              appendMessage('bot-message', nl2br(ev.message));
            }
            textarea.disabled = false;
            if (sendBtn) sendBtn.disabled = false;
          }
        }
      }
    } catch (err) {
      if (thinkingDiv) thinkingDiv.innerHTML = 'エラー：ストリーム処理中に問題が発生しました。';
      textarea.disabled = false;
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  // 既存のCtrl+Enter送信（SSE版に置き換え）
  textarea.addEventListener('keydown', function (event) {
    if (event.ctrlKey && event.key === 'Enter') {
      event.preventDefault();
      // form.submit() はやめて、SSE送信
      const text = textarea.value.trim();
      if (!text) return;
      textarea.value = '';
      sendMessageViaSSE(text);
    }
  });

  // 通常の送信ボタン/Enter送信（フォームsubmit）もSSEに置き換え
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    const text = textarea.value.trim();
    if (!text) return;
    textarea.value = '';
    sendMessageViaSSE(text);
  });
};
/**
 * Kin Spark Widget — Embeddable chat widget.
 *
 * Usage:
 *   <script src="https://cdn.trykin.ai/spark/widget.js"
 *     data-spark-key="sk_..."
 *     data-accent="#4F46E5"
 *     data-position="bottom-right"
 *     data-title="Chat with Kin">
 *   </script>
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Config from script tag data attributes
  // ---------------------------------------------------------------------------
  const scriptTag = document.currentScript;
  const config = {
    apiKey: scriptTag?.getAttribute("data-spark-key") || "",
    accent: scriptTag?.getAttribute("data-accent") || "#4F46E5",
    position: scriptTag?.getAttribute("data-position") || "bottom-right",
    title: scriptTag?.getAttribute("data-title") || "Chat with us",
    apiBase: scriptTag?.getAttribute("data-api-base") || "",
  };

  // Auto-detect API base from script src if not explicitly set
  if (!config.apiBase && scriptTag?.src) {
    try {
      const url = new URL(scriptTag.src);
      config.apiBase = url.origin + "/spark";
    } catch (_) {
      config.apiBase = "/spark";
    }
  }

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let sessionToken = null;
  let conversationId = null;
  let isOpen = false;
  let isStreaming = false;

  // Session persistence (30-min expiry)
  const SESSION_KEY = "spark_session";
  const SESSION_EXPIRY_MS = 30 * 60 * 1000;

  function loadSession() {
    try {
      const raw = localStorage.getItem(SESSION_KEY);
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (Date.now() - data.ts > SESSION_EXPIRY_MS) {
        localStorage.removeItem(SESSION_KEY);
        return null;
      }
      return data;
    } catch (_) {
      return null;
    }
  }

  function saveSession(token, convId) {
    try {
      localStorage.setItem(
        SESSION_KEY,
        JSON.stringify({ token: token, convId: convId, ts: Date.now() })
      );
    } catch (_) {}
  }

  // Restore session
  const saved = loadSession();
  if (saved) {
    sessionToken = saved.token;
    conversationId = saved.convId;
  }

  // ---------------------------------------------------------------------------
  // Styles
  // ---------------------------------------------------------------------------
  const styles = document.createElement("style");
  styles.textContent = `
    .spark-widget-container {
      position: fixed;
      ${config.position === "bottom-left" ? "left: 20px;" : "right: 20px;"}
      bottom: 20px;
      z-index: 999999;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }
    .spark-toggle {
      width: 56px;
      height: 56px;
      border-radius: 28px;
      background: ${config.accent};
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
      transition: transform 0.2s, box-shadow 0.2s;
    }
    .spark-toggle:hover {
      transform: scale(1.05);
      box-shadow: 0 6px 16px rgba(0,0,0,0.2);
    }
    .spark-toggle svg {
      width: 24px;
      height: 24px;
      fill: white;
    }
    .spark-chat {
      display: none;
      width: 380px;
      max-width: calc(100vw - 40px);
      height: 520px;
      max-height: calc(100vh - 100px);
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 8px 30px rgba(0,0,0,0.12);
      flex-direction: column;
      overflow: hidden;
      margin-bottom: 12px;
    }
    .spark-chat.open {
      display: flex;
    }
    .spark-header {
      background: ${config.accent};
      color: white;
      padding: 16px;
      font-weight: 600;
      font-size: 15px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .spark-close {
      background: none;
      border: none;
      color: white;
      cursor: pointer;
      font-size: 20px;
      padding: 0 4px;
      opacity: 0.8;
    }
    .spark-close:hover { opacity: 1; }
    .spark-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .spark-msg {
      max-width: 85%;
      padding: 10px 14px;
      border-radius: 12px;
      word-wrap: break-word;
    }
    .spark-msg-user {
      align-self: flex-end;
      background: ${config.accent};
      color: white;
      border-bottom-right-radius: 4px;
    }
    .spark-msg-assistant {
      align-self: flex-start;
      background: #f0f0f0;
      color: #1a1a1a;
      border-bottom-left-radius: 4px;
    }
    .spark-msg-assistant a {
      color: ${config.accent};
      text-decoration: underline;
    }
    .spark-typing {
      align-self: flex-start;
      padding: 10px 14px;
      background: #f0f0f0;
      border-radius: 12px;
      border-bottom-left-radius: 4px;
      display: none;
    }
    .spark-typing.visible { display: block; }
    .spark-typing-dots span {
      display: inline-block;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #999;
      margin: 0 2px;
      animation: spark-bounce 1.4s infinite;
    }
    .spark-typing-dots span:nth-child(2) { animation-delay: 0.2s; }
    .spark-typing-dots span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes spark-bounce {
      0%, 80%, 100% { transform: translateY(0); }
      40% { transform: translateY(-6px); }
    }
    .spark-input-area {
      padding: 12px 16px;
      border-top: 1px solid #e5e5e5;
      display: flex;
      gap: 8px;
    }
    .spark-input {
      flex: 1;
      border: 1px solid #ddd;
      border-radius: 8px;
      padding: 8px 12px;
      font-size: 14px;
      outline: none;
      font-family: inherit;
      resize: none;
    }
    .spark-input:focus {
      border-color: ${config.accent};
    }
    .spark-send {
      background: ${config.accent};
      color: white;
      border: none;
      border-radius: 8px;
      padding: 8px 16px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      white-space: nowrap;
    }
    .spark-send:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .spark-lead-form {
      padding: 16px;
      border-top: 1px solid #e5e5e5;
      display: none;
    }
    .spark-lead-form.visible { display: block; }
    .spark-lead-form input {
      width: 100%;
      border: 1px solid #ddd;
      border-radius: 8px;
      padding: 8px 12px;
      font-size: 14px;
      margin-bottom: 8px;
      font-family: inherit;
      box-sizing: border-box;
    }
    .spark-lead-form input:focus {
      border-color: ${config.accent};
      outline: none;
    }
    .spark-lead-submit {
      background: ${config.accent};
      color: white;
      border: none;
      border-radius: 8px;
      padding: 10px;
      width: 100%;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
    }
    .spark-lead-skip {
      background: none;
      border: none;
      color: #999;
      cursor: pointer;
      font-size: 13px;
      padding: 8px 0 0;
      width: 100%;
      text-align: center;
    }
    @media (max-width: 480px) {
      .spark-chat {
        width: calc(100vw - 20px);
        height: calc(100vh - 80px);
        border-radius: 12px 12px 0 0;
      }
      .spark-widget-container {
        ${config.position === "bottom-left" ? "left: 10px;" : "right: 10px;"}
        bottom: 10px;
      }
    }
  `;
  document.head.appendChild(styles);

  // ---------------------------------------------------------------------------
  // DOM
  // ---------------------------------------------------------------------------
  const container = document.createElement("div");
  container.className = "spark-widget-container";
  container.innerHTML = `
    <div class="spark-chat">
      <div class="spark-header">
        <span>${escapeHtml(config.title)}</span>
        <button class="spark-close" aria-label="Close">&times;</button>
      </div>
      <div class="spark-messages"></div>
      <div class="spark-typing">
        <div class="spark-typing-dots"><span></span><span></span><span></span></div>
      </div>
      <div class="spark-input-area">
        <input class="spark-input" placeholder="Type a message..." maxlength="4000" />
        <button class="spark-send" disabled>Send</button>
      </div>
      <div class="spark-lead-form">
        <div style="font-weight:600;margin-bottom:8px;">Want to continue the conversation?</div>
        <input class="spark-lead-email" type="email" placeholder="Your email" />
        <input class="spark-lead-name" type="text" placeholder="Your name (optional)" />
        <button class="spark-lead-submit">Send</button>
        <button class="spark-lead-skip">No thanks</button>
      </div>
    </div>
    <button class="spark-toggle" aria-label="Open chat">
      <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/></svg>
    </button>
  `;
  document.body.appendChild(container);

  const chatEl = container.querySelector(".spark-chat");
  const messagesEl = container.querySelector(".spark-messages");
  const typingEl = container.querySelector(".spark-typing");
  const inputEl = container.querySelector(".spark-input");
  const sendBtn = container.querySelector(".spark-send");
  const toggleBtn = container.querySelector(".spark-toggle");
  const closeBtn = container.querySelector(".spark-close");
  const leadForm = container.querySelector(".spark-lead-form");
  const leadEmail = container.querySelector(".spark-lead-email");
  const leadName = container.querySelector(".spark-lead-name");
  const leadSubmit = container.querySelector(".spark-lead-submit");
  const leadSkip = container.querySelector(".spark-lead-skip");

  // ---------------------------------------------------------------------------
  // Event handlers
  // ---------------------------------------------------------------------------
  toggleBtn.addEventListener("click", () => {
    isOpen = !isOpen;
    chatEl.classList.toggle("open", isOpen);
    if (isOpen) inputEl.focus();
  });

  closeBtn.addEventListener("click", () => {
    isOpen = false;
    chatEl.classList.remove("open");
  });

  inputEl.addEventListener("input", () => {
    sendBtn.disabled = !inputEl.value.trim() || isStreaming;
  });

  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !sendBtn.disabled) {
      e.preventDefault();
      sendMessage();
    }
  });

  sendBtn.addEventListener("click", sendMessage);

  leadSubmit.addEventListener("click", submitLead);

  leadSkip.addEventListener("click", () => {
    leadForm.classList.remove("visible");
    emitEvent("lead_declined");
  });

  // Fire widget_loaded event
  emitEvent("widget_loaded");

  // ---------------------------------------------------------------------------
  // Chat logic
  // ---------------------------------------------------------------------------
  function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || isStreaming) return;

    addMessage("user", text);
    inputEl.value = "";
    sendBtn.disabled = true;
    isStreaming = true;
    typingEl.classList.add("visible");

    const body = { message: text };
    if (sessionToken) body.session_token = sessionToken;

    fetch(config.apiBase + "/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Spark-Key": config.apiKey,
      },
      body: JSON.stringify(body),
    })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        return readSSE(res.body.getReader());
      })
      .catch((err) => {
        typingEl.classList.remove("visible");
        isStreaming = false;
        sendBtn.disabled = false;
        addMessage("assistant", "Sorry, something went wrong. Please try again.");
        console.error("[Spark]", err);
      });
  }

  async function readSSE(reader) {
    const decoder = new TextDecoder();
    let buffer = "";
    let assistantText = "";
    let assistantEl = null;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let eventType = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith("data: ") && eventType) {
            const data = JSON.parse(line.slice(6));
            handleSSEEvent(eventType, data);
            eventType = "";
          }
        }
      }
    } catch (err) {
      console.error("[Spark] SSE read error:", err);
    }

    typingEl.classList.remove("visible");
    isStreaming = false;
    sendBtn.disabled = !inputEl.value.trim();

    function handleSSEEvent(type, data) {
      switch (type) {
        case "session":
          sessionToken = data.session_token;
          conversationId = data.conversation_id;
          saveSession(sessionToken, conversationId);
          break;
        case "token":
          typingEl.classList.remove("visible");
          if (!assistantEl) {
            assistantEl = addMessage("assistant", "");
          }
          assistantText += data.text;
          assistantEl.innerHTML = renderMarkdown(assistantText);
          scrollToBottom();
          break;
        case "wind_down":
          // Show lead form after a short delay
          setTimeout(() => {
            leadForm.classList.add("visible");
          }, 500);
          break;
        case "done":
          break;
        case "error":
          if (!assistantEl) {
            addMessage("assistant", data.message || "Something went wrong.");
          }
          break;
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Lead capture
  // ---------------------------------------------------------------------------
  function submitLead() {
    const email = leadEmail.value.trim();
    if (!email) return;

    fetch(config.apiBase + "/lead", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Spark-Key": config.apiKey,
      },
      body: JSON.stringify({
        conversation_id: conversationId,
        email: email,
        name: leadName.value.trim() || null,
      }),
    })
      .then(() => {
        leadForm.innerHTML =
          '<div style="text-align:center;padding:8px;color:#666;">Thanks! We\'ll be in touch.</div>';
      })
      .catch(() => {
        leadForm.innerHTML =
          '<div style="text-align:center;padding:8px;color:#c00;">Something went wrong. Please try again.</div>';
      });
  }

  // ---------------------------------------------------------------------------
  // Analytics
  // ---------------------------------------------------------------------------
  function emitEvent(eventType, metadata) {
    fetch(config.apiBase + "/event", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Spark-Key": config.apiKey,
      },
      body: JSON.stringify({
        event_type: eventType,
        conversation_id: conversationId,
        metadata: metadata || {},
      }),
    }).catch(() => {});
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------
  function addMessage(role, text) {
    const el = document.createElement("div");
    el.className = `spark-msg spark-msg-${role}`;
    el.innerHTML = role === "user" ? escapeHtml(text) : renderMarkdown(text);
    messagesEl.appendChild(el);
    scrollToBottom();
    return el;
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function renderMarkdown(text) {
    // Light markdown: bold, italic, links, lists, line breaks
    let html = escapeHtml(text);
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    // Italic
    html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
    // Links
    html = html.replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>'
    );
    // Unordered lists
    html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
    html = html.replace(/(<li>.*<\/li>\n?)+/g, "<ul>$&</ul>");
    // Line breaks
    html = html.replace(/\n/g, "<br>");
    return html;
  }
})();

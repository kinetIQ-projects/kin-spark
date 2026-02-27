/**
 * Kin Spark Widget — Embeddable chat widget.
 *
 * === Method 1: Plain HTML (script tag with data attributes) ===
 *
 * Floating mode (default):
 *   <script src="https://api.trykin.ai/static/spark/widget.js"
 *     data-spark-key="sk_..."
 *     data-accent="#4F46E5"
 *     data-position="bottom-right"
 *     data-title="Chat with Kin">
 *   </script>
 *
 * Inline mode (embedded in page):
 *   <div id="spark-demo" style="height:500px"></div>
 *   <script src="https://api.trykin.ai/static/spark/widget.js"
 *     data-spark-key="sk_..."
 *     data-mode="inline"
 *     data-target="#spark-demo"
 *     data-accent="#4F46E5"
 *     data-title="Chat with Kin">
 *   </script>
 *
 * === Method 2: JavaScript API (for React/Next.js/SPAs) ===
 *
 * Load the script first (any method), then call:
 *
 *   window.SparkWidget.mount({
 *     apiKey: "sk_...",
 *     apiBase: "https://api.trykin.ai/spark",
 *     mode: "inline",
 *     target: "#spark-demo",
 *     accent: "#4F46E5",
 *     title: "Chat with Kin",
 *   });
 *
 * To remove a mounted widget:
 *   window.SparkWidget.unmount("#spark-demo");
 */
(function () {
  "use strict";

  // Prevent double-initialization from multiple script tags
  if (window.SparkWidget) return;

  // ---------------------------------------------------------------------------
  // Widget factory — creates one widget instance
  // ---------------------------------------------------------------------------
  function createWidget(config) {
    const isInline = config.mode === "inline";

    // State
    let sessionToken = null;
    let conversationId = null;
    let isOpen = isInline;
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

    const saved = loadSession();
    if (saved) {
      sessionToken = saved.token;
      conversationId = saved.convId;
    }

    // -------------------------------------------------------------------------
    // Styles — scoped with unique class prefix per mode
    // -------------------------------------------------------------------------
    const styleId = isInline ? "spark-styles-inline" : "spark-styles-floating";
    if (!document.getElementById(styleId)) {
      const styles = document.createElement("style");
      styles.id = styleId;
      styles.textContent = `
        .spark-widget-container.spark-${isInline ? "inline" : "floating"} {
          ${isInline ? "" : `
          position: fixed;
          ${config.position === "bottom-left" ? "left: 20px;" : "right: 20px;"}
          bottom: 20px;
          z-index: 999999;
          `}
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          font-size: 14px;
          line-height: 1.5;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-toggle {
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
        .spark-${isInline ? "inline" : "floating"} .spark-toggle:hover {
          transform: scale(1.05);
          box-shadow: 0 6px 16px rgba(0,0,0,0.2);
        }
        .spark-${isInline ? "inline" : "floating"} .spark-toggle svg {
          width: 24px;
          height: 24px;
          fill: white;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-chat {
          ${isInline ? `
          display: flex;
          width: 100%;
          height: 100%;
          ` : `
          display: none;
          width: 380px;
          max-width: calc(100vw - 40px);
          height: 520px;
          max-height: calc(100vh - 100px);
          margin-bottom: 12px;
          `}
          background: ${isInline ? "transparent" : "#fff"};
          border-radius: 12px;
          ${isInline ? "" : "box-shadow: 0 8px 30px rgba(0,0,0,0.12);"}
          flex-direction: column;
          overflow: hidden;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-chat.open {
          display: flex;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-header {
          background: ${config.accent};
          color: white;
          padding: 16px;
          font-weight: 600;
          font-size: 15px;
          ${isInline ? "display: none;" : `
          display: flex;
          align-items: center;
          justify-content: space-between;
          `}
        }
        .spark-${isInline ? "inline" : "floating"} .spark-close {
          background: none;
          border: none;
          color: white;
          cursor: pointer;
          font-size: 20px;
          padding: 0 4px;
          opacity: 0.8;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-close:hover { opacity: 1; }
        .spark-${isInline ? "inline" : "floating"} .spark-messages {
          flex: 1;
          overflow-y: auto;
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-msg {
          max-width: 85%;
          padding: 10px 14px;
          border-radius: 12px;
          word-wrap: break-word;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-msg-user {
          align-self: flex-end;
          background: ${config.accent};
          color: white;
          border-bottom-right-radius: 4px;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-msg-assistant {
          align-self: flex-start;
          background: ${isInline ? "rgba(255,255,255,0.1)" : "#f0f0f0"};
          color: ${isInline ? "#e5e5e5" : "#1a1a1a"};
          border-bottom-left-radius: 4px;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-msg-assistant a {
          color: ${config.accent};
          text-decoration: underline;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-typing {
          align-self: flex-start;
          padding: 10px 14px;
          background: ${isInline ? "rgba(255,255,255,0.1)" : "#f0f0f0"};
          border-radius: 12px;
          border-bottom-left-radius: 4px;
          display: none;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-typing.visible { display: block; }
        .spark-${isInline ? "inline" : "floating"} .spark-typing-dots span {
          display: inline-block;
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: ${isInline ? "#888" : "#999"};
          margin: 0 2px;
          animation: spark-bounce 1.4s infinite;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-typing-dots span:nth-child(2) { animation-delay: 0.2s; }
        .spark-${isInline ? "inline" : "floating"} .spark-typing-dots span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes spark-bounce {
          0%, 80%, 100% { transform: translateY(0); }
          40% { transform: translateY(-6px); }
        }
        .spark-${isInline ? "inline" : "floating"} .spark-input-area {
          padding: 12px 16px;
          border-top: 1px solid ${isInline ? "rgba(255,255,255,0.1)" : "#e5e5e5"};
          display: flex;
          gap: 8px;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-input {
          flex: 1;
          border: 1px solid ${isInline ? "rgba(255,255,255,0.2)" : "#ddd"};
          border-radius: 8px;
          padding: 8px 12px;
          font-size: 14px;
          outline: none;
          font-family: inherit;
          resize: none;
          ${isInline ? `
          background: rgba(255,255,255,0.05);
          color: #e5e5e5;
          ` : ""}
        }
        .spark-${isInline ? "inline" : "floating"} .spark-input:focus {
          border-color: ${config.accent};
        }
        ${isInline ? `
        .spark-inline .spark-input::placeholder {
          color: rgba(255,255,255,0.4);
        }
        ` : ""}
        .spark-${isInline ? "inline" : "floating"} .spark-send {
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
        .spark-${isInline ? "inline" : "floating"} .spark-send:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-lead-form {
          padding: 16px;
          border-top: 1px solid ${isInline ? "rgba(255,255,255,0.1)" : "#e5e5e5"};
          display: none;
          ${isInline ? "color: #e5e5e5;" : ""}
        }
        .spark-${isInline ? "inline" : "floating"} .spark-lead-form.visible { display: block; }
        .spark-${isInline ? "inline" : "floating"} .spark-lead-form input {
          width: 100%;
          border: 1px solid ${isInline ? "rgba(255,255,255,0.2)" : "#ddd"};
          border-radius: 8px;
          padding: 8px 12px;
          font-size: 14px;
          margin-bottom: 8px;
          font-family: inherit;
          box-sizing: border-box;
          ${isInline ? `
          background: rgba(255,255,255,0.05);
          color: #e5e5e5;
          ` : ""}
        }
        .spark-${isInline ? "inline" : "floating"} .spark-lead-form input:focus {
          border-color: ${config.accent};
          outline: none;
        }
        .spark-${isInline ? "inline" : "floating"} .spark-lead-submit {
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
        .spark-${isInline ? "inline" : "floating"} .spark-lead-skip {
          background: none;
          border: none;
          color: #999;
          cursor: pointer;
          font-size: 13px;
          padding: 8px 0 0;
          width: 100%;
          text-align: center;
        }
        ${isInline ? "" : `
        @media (max-width: 480px) {
          .spark-floating .spark-chat {
            width: calc(100vw - 20px);
            height: calc(100vh - 80px);
            border-radius: 12px 12px 0 0;
          }
          .spark-floating {
            ${config.position === "bottom-left" ? "left: 10px;" : "right: 10px;"}
            bottom: 10px;
          }
        }
        `}
      `;
      document.head.appendChild(styles);
    }

    // -------------------------------------------------------------------------
    // DOM
    // -------------------------------------------------------------------------
    const container = document.createElement("div");
    container.className = `spark-widget-container spark-${isInline ? "inline" : "floating"}`;
    container.innerHTML = `
      <div class="spark-chat${isInline ? " open" : ""}">
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
          <input class="spark-lead-company" type="text" placeholder="Company (optional)" />
          <button class="spark-lead-submit">Send</button>
          <button class="spark-lead-skip">No thanks</button>
        </div>
      </div>
      ${isInline ? "" : `
      <button class="spark-toggle" aria-label="Open chat">
        <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/></svg>
      </button>
      `}
    `;

    // Mount into target or body
    if (isInline && config.target) {
      const targetEl = document.querySelector(config.target);
      if (targetEl) {
        targetEl.appendChild(container);
      } else {
        console.error("[Spark] Target element not found:", config.target);
        return null;
      }
    } else {
      document.body.appendChild(container);
    }

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
    const leadCompany = container.querySelector(".spark-lead-company");
    const leadSubmit = container.querySelector(".spark-lead-submit");
    const leadSkip = container.querySelector(".spark-lead-skip");

    // -------------------------------------------------------------------------
    // Event handlers
    // -------------------------------------------------------------------------
    if (toggleBtn) {
      toggleBtn.addEventListener("click", function () {
        isOpen = !isOpen;
        chatEl.classList.toggle("open", isOpen);
        if (isOpen) inputEl.focus();
      });
    }

    if (closeBtn && !isInline) {
      closeBtn.addEventListener("click", function () {
        isOpen = false;
        chatEl.classList.remove("open");
      });
    }

    inputEl.addEventListener("input", function () {
      sendBtn.disabled = !inputEl.value.trim() || isStreaming;
    });

    inputEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !sendBtn.disabled) {
        e.preventDefault();
        sendMessage();
      }
    });

    sendBtn.addEventListener("click", sendMessage);
    leadSubmit.addEventListener("click", submitLead);

    leadSkip.addEventListener("click", function () {
      leadForm.classList.remove("visible");
      emitEvent("lead_declined");
    });

    emitEvent("widget_loaded");

    // -------------------------------------------------------------------------
    // Chat logic
    // -------------------------------------------------------------------------
    function sendMessage() {
      var text = inputEl.value.trim();
      if (!text || isStreaming) return;

      addMessage("user", text);
      inputEl.value = "";
      sendBtn.disabled = true;
      isStreaming = true;
      typingEl.classList.add("visible");

      var body = { message: text };
      if (sessionToken) body.session_token = sessionToken;

      fetch(config.apiBase + "/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Spark-Key": config.apiKey,
        },
        body: JSON.stringify(body),
      })
        .then(function (res) {
          if (!res.ok) throw new Error("HTTP " + res.status);
          return readSSE(res.body.getReader());
        })
        .catch(function (err) {
          typingEl.classList.remove("visible");
          isStreaming = false;
          sendBtn.disabled = false;
          addMessage("assistant", "Sorry, something went wrong. Please try again.");
          console.error("[Spark]", err);
        });
    }

    function readSSE(reader) {
      var decoder = new TextDecoder();
      var buffer = "";
      var assistantText = "";
      var assistantEl = null;

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
            setTimeout(function () {
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

      function pump() {
        return reader.read().then(function (result) {
          if (result.done) {
            typingEl.classList.remove("visible");
            isStreaming = false;
            sendBtn.disabled = !inputEl.value.trim();
            return;
          }

          buffer += decoder.decode(result.value, { stream: true });
          var lines = buffer.split("\n");
          buffer = lines.pop() || "";

          var eventType = "";
          for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            if (line.indexOf("event: ") === 0) {
              eventType = line.slice(7).trim();
            } else if (line.indexOf("data: ") === 0 && eventType) {
              try {
                var data = JSON.parse(line.slice(6));
                handleSSEEvent(eventType, data);
              } catch (_) {}
              eventType = "";
            }
          }

          return pump();
        });
      }

      return pump().catch(function (err) {
        console.error("[Spark] SSE read error:", err);
        typingEl.classList.remove("visible");
        isStreaming = false;
        sendBtn.disabled = !inputEl.value.trim();
      });
    }

    // -------------------------------------------------------------------------
    // Lead capture
    // -------------------------------------------------------------------------
    function submitLead() {
      var email = leadEmail.value.trim();
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
          company_name: leadCompany.value.trim() || null,
        }),
      })
        .then(function () {
          leadForm.innerHTML =
            '<div style="text-align:center;padding:8px;color:#666;">Thanks! We\'ll be in touch.</div>';
        })
        .catch(function () {
          leadForm.innerHTML =
            '<div style="text-align:center;padding:8px;color:#c00;">Something went wrong. Please try again.</div>';
        });
    }

    // -------------------------------------------------------------------------
    // Analytics
    // -------------------------------------------------------------------------
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
      }).catch(function () {});
    }

    // -------------------------------------------------------------------------
    // Rendering
    // -------------------------------------------------------------------------
    function addMessage(role, text) {
      var el = document.createElement("div");
      el.className = "spark-msg spark-msg-" + role;
      el.innerHTML = role === "user" ? escapeHtml(text) : renderMarkdown(text);
      messagesEl.appendChild(el);
      scrollToBottom();
      return el;
    }

    function scrollToBottom() {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // Return handle for cleanup
    return {
      destroy: function () {
        container.remove();
      },
    };
  }

  // ---------------------------------------------------------------------------
  // Shared utilities
  // ---------------------------------------------------------------------------
  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function renderMarkdown(text) {
    var html = escapeHtml(text);
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
    html = html.replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>'
    );
    html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
    html = html.replace(/(<li>.*<\/li>\n?)+/g, "<ul>$&</ul>");
    html = html.replace(/\n/g, "<br>");
    return html;
  }

  // ---------------------------------------------------------------------------
  // Public API — window.SparkWidget
  // ---------------------------------------------------------------------------
  var instances = {};

  window.SparkWidget = {
    /**
     * Mount a widget instance.
     * @param {Object} opts - Configuration object
     * @param {string} opts.apiKey - Spark API key
     * @param {string} opts.apiBase - API base URL (e.g. "https://api.trykin.ai/spark")
     * @param {string} [opts.mode="floating"] - "floating" or "inline"
     * @param {string} [opts.target] - CSS selector for inline target element
     * @param {string} [opts.accent="#4F46E5"] - Accent color
     * @param {string} [opts.position="bottom-right"] - "bottom-right" or "bottom-left"
     * @param {string} [opts.title="Chat with us"] - Widget title
     */
    mount: function (opts) {
      var cfg = {
        apiKey: opts.apiKey || "",
        apiBase: opts.apiBase || "",
        mode: opts.mode || "floating",
        target: opts.target || "",
        accent: opts.accent || "#4F46E5",
        position: opts.position || "bottom-right",
        title: opts.title || "Chat with us",
      };

      var key = cfg.target || "__floating__";

      // Don't double-mount
      if (instances[key]) return;

      var instance = createWidget(cfg);
      if (instance) {
        instances[key] = instance;
      }
    },

    /**
     * Unmount a widget instance.
     * @param {string} [target] - CSS selector of the target, or omit for floating
     */
    unmount: function (target) {
      var key = target || "__floating__";
      if (instances[key]) {
        instances[key].destroy();
        delete instances[key];
      }
    },
  };

  // ---------------------------------------------------------------------------
  // Auto-init from script tag data attributes (plain HTML usage)
  // ---------------------------------------------------------------------------
  var scriptTag = document.currentScript;
  if (scriptTag && scriptTag.getAttribute("data-spark-key")) {
    var apiBase = scriptTag.getAttribute("data-api-base") || "";
    if (!apiBase && scriptTag.src) {
      try {
        var url = new URL(scriptTag.src);
        apiBase = url.origin + "/spark";
      } catch (_) {
        apiBase = "/spark";
      }
    }

    window.SparkWidget.mount({
      apiKey: scriptTag.getAttribute("data-spark-key"),
      apiBase: apiBase,
      mode: scriptTag.getAttribute("data-mode") || "floating",
      target: scriptTag.getAttribute("data-target") || "",
      accent: scriptTag.getAttribute("data-accent") || "#4F46E5",
      position: scriptTag.getAttribute("data-position") || "bottom-right",
      title: scriptTag.getAttribute("data-title") || "Chat with us",
    });
  }
})();

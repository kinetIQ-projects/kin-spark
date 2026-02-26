"use client"

/**
 * SparkChat — Self-contained React component for Kin Spark.
 *
 * Drop this into any Next.js / React project. No external scripts needed.
 * Talks directly to the Spark API via fetch + SSE streaming.
 *
 * Usage:
 *   <SparkChat
 *     apiKey="sk_spark_..."
 *     apiBase="https://api.trykin.ai/spark"
 *     accent="#4F46E5"
 *   />
 */

import { useState, useRef, useEffect, useCallback } from "react"

interface SparkChatProps {
  apiKey: string
  apiBase: string
  accent?: string
  placeholder?: string
}

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
}

export default function SparkChat({
  apiKey,
  apiBase,
  accent = "#4F46E5",
  placeholder = "Type a message...",
}: SparkChatProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [isStreaming, setIsStreaming] = useState(false)
  const [showLeadForm, setShowLeadForm] = useState(false)
  const [leadSubmitted, setLeadSubmitted] = useState(false)

  const sessionTokenRef = useRef<string | null>(null)
  const conversationIdRef = useRef<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const streamTextRef = useRef("")

  // Restore session from localStorage
  useEffect(() => {
    try {
      const raw = localStorage.getItem("spark_session")
      if (!raw) return
      const data = JSON.parse(raw)
      if (Date.now() - data.ts > 30 * 60 * 1000) {
        localStorage.removeItem("spark_session")
        return
      }
      sessionTokenRef.current = data.token
      conversationIdRef.current = data.convId
    } catch (_) {}
  }, [])

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  const saveSession = (token: string, convId: string) => {
    sessionTokenRef.current = token
    conversationIdRef.current = convId
    try {
      localStorage.setItem(
        "spark_session",
        JSON.stringify({ token, convId, ts: Date.now() })
      )
    } catch (_) {}
  }

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || isStreaming) return

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: text,
    }

    setMessages((prev) => [...prev, userMsg])
    setInput("")
    setIsStreaming(true)
    streamTextRef.current = ""

    const assistantId = (Date.now() + 1).toString()
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", content: "" },
    ])

    try {
      const body: Record<string, string> = { message: text }
      if (sessionTokenRef.current) {
        body.session_token = sessionTokenRef.current
      }

      const res = await fetch(apiBase + "/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Spark-Key": apiKey,
        },
        body: JSON.stringify(body),
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      if (!res.body) throw new Error("No response body")

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      let eventType = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim()
          } else if (line.startsWith("data: ") && eventType) {
            try {
              const data = JSON.parse(line.slice(6))

              if (eventType === "session") {
                saveSession(data.session_token, data.conversation_id)
              } else if (eventType === "token") {
                streamTextRef.current += data.text
                const currentText = streamTextRef.current
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId
                      ? { ...m, content: currentText }
                      : m
                  )
                )
              } else if (eventType === "wind_down") {
                setTimeout(() => setShowLeadForm(true), 500)
              } else if (eventType === "error") {
                const errText = data.message || "Something went wrong."
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId ? { ...m, content: errText } : m
                  )
                )
              }
            } catch (_) {}
            eventType = ""
          }
        }
      }
    } catch (err) {
      console.error("[SparkChat]", err)
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: "Sorry, something went wrong. Please try again." }
            : m
        )
      )
    }

    setIsStreaming(false)
  }

  const submitLead = async (email: string, name: string) => {
    try {
      await fetch(apiBase + "/lead", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Spark-Key": apiKey,
        },
        body: JSON.stringify({
          conversation_id: conversationIdRef.current,
          email,
          name: name || null,
        }),
      })
      setLeadSubmitted(true)
    } catch (_) {
      setLeadSubmitted(true)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey && !isStreaming && input.trim()) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        width: "100%",
        height: "100%",
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        fontSize: 14,
        lineHeight: 1.5,
      }}
    >
      {/* Messages */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: 16,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        {messages.map((msg) => (
          <div
            key={msg.id}
            style={{
              alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "85%",
              padding: "10px 14px",
              borderRadius: 12,
              ...(msg.role === "user"
                ? {
                    background: accent,
                    color: "white",
                    borderBottomRightRadius: 4,
                  }
                : {
                    background: "rgba(255,255,255,0.1)",
                    color: "#e5e5e5",
                    borderBottomLeftRadius: 4,
                  }),
              wordWrap: "break-word",
            }}
            dangerouslySetInnerHTML={
              msg.role === "assistant"
                ? { __html: renderMarkdown(msg.content) }
                : undefined
            }
          >
            {msg.role === "user" ? msg.content : undefined}
          </div>
        ))}

        {isStreaming && messages[messages.length - 1]?.content === "" && (
          <div
            style={{
              alignSelf: "flex-start",
              padding: "10px 14px",
              background: "rgba(255,255,255,0.1)",
              borderRadius: 12,
              borderBottomLeftRadius: 4,
            }}
          >
            <TypingDots />
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Lead form */}
      {showLeadForm && !leadSubmitted && (
        <LeadForm accent={accent} onSubmit={submitLead} onSkip={() => setShowLeadForm(false)} />
      )}
      {leadSubmitted && (
        <div style={{ textAlign: "center", padding: 12, color: "#888" }}>
          Thanks! We'll be in touch.
        </div>
      )}

      {/* Input */}
      <div
        style={{
          padding: "12px 16px",
          borderTop: "1px solid rgba(255,255,255,0.1)",
          display: "flex",
          gap: 8,
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          maxLength={4000}
          disabled={isStreaming}
          style={{
            flex: 1,
            border: "1px solid rgba(255,255,255,0.2)",
            borderRadius: 8,
            padding: "8px 12px",
            fontSize: 14,
            outline: "none",
            fontFamily: "inherit",
            background: "rgba(255,255,255,0.05)",
            color: "#e5e5e5",
          }}
        />
        <button
          onClick={sendMessage}
          disabled={!input.trim() || isStreaming}
          style={{
            background: accent,
            color: "white",
            border: "none",
            borderRadius: 8,
            padding: "8px 16px",
            cursor: !input.trim() || isStreaming ? "not-allowed" : "pointer",
            fontSize: 14,
            fontWeight: 500,
            opacity: !input.trim() || isStreaming ? 0.5 : 1,
          }}
        >
          Send
        </button>
      </div>
    </div>
  )
}

function TypingDots() {
  return (
    <span style={{ display: "inline-flex", gap: 4 }}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "#888",
            animation: "spark-bounce 1.4s infinite",
            animationDelay: `${i * 0.2}s`,
          }}
        />
      ))}
      <style>{`
        @keyframes spark-bounce {
          0%, 80%, 100% { transform: translateY(0); }
          40% { transform: translateY(-6px); }
        }
      `}</style>
    </span>
  )
}

function LeadForm({
  accent,
  onSubmit,
  onSkip,
}: {
  accent: string
  onSubmit: (email: string, name: string) => void
  onSkip: () => void
}) {
  const [email, setEmail] = useState("")
  const [name, setName] = useState("")

  return (
    <div
      style={{
        padding: 16,
        borderTop: "1px solid rgba(255,255,255,0.1)",
        color: "#e5e5e5",
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 8 }}>
        Want to continue the conversation?
      </div>
      <input
        type="email"
        placeholder="Your email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        style={{
          width: "100%",
          border: "1px solid rgba(255,255,255,0.2)",
          borderRadius: 8,
          padding: "8px 12px",
          fontSize: 14,
          marginBottom: 8,
          boxSizing: "border-box",
          background: "rgba(255,255,255,0.05)",
          color: "#e5e5e5",
          outline: "none",
        }}
      />
      <input
        type="text"
        placeholder="Your name (optional)"
        value={name}
        onChange={(e) => setName(e.target.value)}
        style={{
          width: "100%",
          border: "1px solid rgba(255,255,255,0.2)",
          borderRadius: 8,
          padding: "8px 12px",
          fontSize: 14,
          marginBottom: 8,
          boxSizing: "border-box",
          background: "rgba(255,255,255,0.05)",
          color: "#e5e5e5",
          outline: "none",
        }}
      />
      <button
        onClick={() => email.trim() && onSubmit(email.trim(), name.trim())}
        style={{
          background: accent,
          color: "white",
          border: "none",
          borderRadius: 8,
          padding: 10,
          width: "100%",
          cursor: "pointer",
          fontSize: 14,
          fontWeight: 500,
        }}
      >
        Send
      </button>
      <button
        onClick={onSkip}
        style={{
          background: "none",
          border: "none",
          color: "#999",
          cursor: "pointer",
          fontSize: 13,
          padding: "8px 0 0",
          width: "100%",
          textAlign: "center",
        }}
      >
        No thanks
      </button>
    </div>
  )
}

function renderMarkdown(text: string): string {
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>")
  html = html.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline">$1</a>'
  )
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>")
  html = html.replace(/(<li>.*<\/li>)+/g, "<ul>$&</ul>")
  html = html.replace(/\n/g, "<br>")
  return html
}

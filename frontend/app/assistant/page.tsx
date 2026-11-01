"use client";

import { useEffect, useState, FormEvent } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import type {
  AssistantAskResponse,
  AssistantEvaluation,
  AssistantSourcesResponse,
} from "@/lib/types";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  response?: AssistantAskResponse;
}

const MODE_LABELS: Record<AssistantAskResponse["mode"], string> = {
  generated: "AI answer from cited evidence",
  retrieve_only: "Retrieved evidence only (model offline)",
  abstained: "No confident evidence — no answer invented",
};

export default function AssistantPage() {
  const { ready } = useRequireAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [askError, setAskError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sources, setSources] = useState<AssistantSourcesResponse | null>(null);
  const [evaluation, setEvaluation] = useState<AssistantEvaluation | null>(null);
  const [evalBusy, setEvalBusy] = useState(false);

  useEffect(() => {
    if (!ready) return;
    apiFetch<AssistantSourcesResponse>("/assistant/sources")
      .then(setSources)
      .catch(() => setSources(null));
  }, [ready]);

  async function handleAsk(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    setAskError(null);
    setMessages((prev) => [...prev, { role: "user", text }]);
    setQuestion("");
    try {
      const data = await apiFetch<AssistantAskResponse>("/assistant/ask", {
        method: "POST",
        body: JSON.stringify({ question: text }),
      });
      setMessages((prev) => [...prev, { role: "assistant", text: data.answer ?? "", response: data }]);
    } catch (err) {
      setAskError(
        err instanceof ApiError ? err.message : "The assistant request failed",
      );
    } finally {
      setBusy(false);
    }
  }

  async function runSelfCheck() {
    setEvalBusy(true);
    setAskError(null);
    try {
      const data = await apiFetch<AssistantEvaluation>("/assistant/evaluation");
      setEvaluation(data);
    } catch (err) {
      setAskError(err instanceof ApiError ? err.message : "Self-check failed");
    } finally {
      setEvalBusy(false);
    }
  }

  if (!ready) return null;

  return (
    <main className="container">
      <header>
        <h1>Sustainability Assistant</h1>
        <p>
          Ask questions about platform methods, regulation/news items, and
          records your organization can access. Answers cite their sources;
          when evidence is insufficient the assistant says so instead of
          inventing an answer. Informational only — not legal advice.
        </p>
      </header>

      {sources && (
        <section className="card">
          <h2>What this assistant may cite</h2>
          <ul className="muted">
            {sources.allowed_sources.map((source) => (
              <li key={source}>{source}</li>
            ))}
          </ul>
          <details>
            <summary>Knowledge volume &amp; caveats</summary>
            <p className="muted small-note">
              Platform knowledge chunks:{" "}
              {Object.entries(sources.platform_chunk_counts)
                .map(([kind, count]) => `${kind.replace("_", " ")}: ${count}`)
                .join(", ") || "none yet"}
            </p>
            <ul>
              {sources.caveats.map((caveat) => (
                <li key={caveat} className="muted small-note">
                  {caveat}
                </li>
              ))}
            </ul>
          </details>
        </section>
      )}

      <div>
        {messages.length === 0 && !busy && (
          <div className="card empty">
            <p>
              No conversation yet. Try: “How are avoided emissions estimated?”
              or “What do the pathway criteria weights mean?”
            </p>
          </div>
        )}
        {messages.map((message, index) =>
          message.role === "user" ? (
            <div key={index} className="card">
              <p>
                <strong>You:</strong> {message.text}
              </p>
            </div>
          ) : message.response ? (
            <div key={index} className="card match-card">
              <div className="match-header">
                <div>
                  <span className="badge">
                    {MODE_LABELS[message.response.mode]}
                  </span>
                  <span className="muted small-note">
                    {" "}
                    · {message.response.runtime_ms} ms
                  </span>
                </div>
              </div>
              <p>{message.text}</p>
              {message.response.citations.length > 0 ? (
                <>
                  <h3>Citations</h3>
                  <ol>
                    {message.response.citations.map((citation) => (
                      <li key={citation.evidence_key}>
                        {citation.url ? (
                          <a href={citation.url} target="_blank" rel="noopener noreferrer">
                            {citation.title}
                          </a>
                        ) : (
                          <span>{citation.title}</span>
                        )}{" "}
                        <span className="muted small-note">
                          · {citation.source_label ?? citation.kind}
                        </span>
                        {citation.untrusted && (
                          <span className="chip">untrusted external text</span>
                        )}
                        <div className="muted small-note">
                          {citation.excerpt}
                        </div>
                      </li>
                    ))}
                  </ol>
                </>
              ) : (
                <p className="muted small-note">No citations — see mode above.</p>
              )}
            </div>
          ) : null
        )}
        {askError && <div className="alert error">{askError}</div>}
      </div>

      <form className="form-actions" onSubmit={handleAsk}>
        <label className="field" style={{ flex: 1 }}>
          Question
          <input
            type="text"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about methods, records, or regulation items..."
            maxLength={1000}
            required
          />
        </label>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Thinking..." : "Ask"}
        </button>
      </form>

      <section className="card">
        <h2>Retrieval self-check</h2>
        <p className="muted small-note">
          {evaluation?.limitations ??
            "Runs a small, version-controlled, SYNTHETIC evaluation set: it checks retrieval hits and genuine abstention. No real-world accuracy is claimed."}
        </p>
        <button
          type="button"
          className="btn"
          onClick={runSelfCheck}
          disabled={evalBusy}
        >
          {evalBusy ? "Running..." : "Run self-check"}
        </button>
        {evaluation && (
          <p className="small-note">
            {evaluation.evaluation_version}: {evaluation.passed}/
            {evaluation.case_count} cases passed.{" "}
            {evaluation.passed === evaluation.case_count
              ? "All retrieval/abstention expectations hold."
              : "Some expectations failed — see backend logs."}
          </p>
        )}
      </section>
    </main>
  );
}

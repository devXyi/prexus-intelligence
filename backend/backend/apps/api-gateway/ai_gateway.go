// backend/apps/api-gateway/ai_gateway.go
// Prexus Intelligence — single AI gateway (audit fix: one place for LLM calls).
//
//   • Model allowlist is configurable (ALLOWED_MODELS) and the selected model is
//     actually used (v1 hardcoded "claude-haiku-4-5" and ignored the selector).
//   • Provider keys live only in headers (v1 put the Gemini key in the URL, which
//     leaked into error strings/logs).
//   • Base URLs are overridable (ANTHROPIC_BASE_URL / OPENAI_BASE_URL /
//     GEMINI_BASE_URL) — this is also the air-gap hook: point OPENAI_BASE_URL at a
//     local vLLM/Ollama OpenAI-compatible server and no traffic leaves the enclave.
//   • Legacy provider-native routes used by meteorium.html (/claude with
//     Anthropic-shaped bodies, /openai, /gemini) are served here.
//   • Per-user daily quota (AI_DAILY_QUOTA) caps the LLM-budget abuse path.

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

const (
	defaultModel      = "claude-haiku-4-5-20251001"
	maxAIPayloadBytes = 48 << 10
	maxAITokens       = 1500
	defaultAITokens   = 1000
)

var errProviderNotConfigured = errors.New("AI provider not configured")

// sharedAIClient is reused across calls; the caller's context owns the deadline.
var sharedAIClient = &http.Client{}

// ── Model allowlist ───────────────────────────────────────────────────────────

func allowedModelSet() map[string]struct{} {
	list := []string{
		"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5-20251001",
		"claude-opus-4-7", "claude-sonnet-4-6", // legacy IDs kept for old clients
	}
	if raw := strings.TrimSpace(os.Getenv("ALLOWED_MODELS")); raw != "" {
		list = nil
		for _, m := range strings.Split(raw, ",") {
			if m = strings.TrimSpace(m); m != "" {
				list = append(list, m)
			}
		}
	}
	set := make(map[string]struct{}, len(list))
	for _, m := range list {
		set[m] = struct{}{}
	}
	return set
}

func getAllowedModelList() []string {
	set := allowedModelSet()
	list := make([]string, 0, len(set))
	for m := range set {
		list = append(list, m)
	}
	sort.Strings(list)
	return list
}

// pickClaudeModel honours the client's choice only if allowlisted; otherwise the default.
func pickClaudeModel(v any) string {
	set := allowedModelSet()
	if s, _ := v.(string); s != "" {
		if _, ok := set[strings.TrimSpace(s)]; ok {
			return strings.TrimSpace(s)
		}
	}
	if _, ok := set[defaultModel]; ok {
		return defaultModel
	}
	if l := getAllowedModelList(); len(l) > 0 {
		return l[0]
	}
	return defaultModel
}

// ── Provider plumbing ─────────────────────────────────────────────────────────

func envOr(k, d string) string {
	if v := strings.TrimSpace(os.Getenv(k)); v != "" {
		return v
	}
	return d
}

func baseURL(env, def string) string { return strings.TrimRight(envOr(env, def), "/") }

func clampTokens(v any) int {
	if f, ok := v.(float64); ok && f > 0 {
		if f > maxAITokens {
			return maxAITokens
		}
		return int(f)
	}
	if i, ok := v.(int); ok && i > 0 {
		if i > maxAITokens {
			return maxAITokens
		}
		return i
	}
	return defaultAITokens
}

func postJSON(ctx context.Context, url string, headers map[string]string, payload any) (int, []byte, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return 0, nil, fmt.Errorf("marshal request: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return 0, nil, fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := sharedAIClient.Do(req)
	if err != nil {
		// url.Error embeds the URL; keys are never in URLs, so this is safe to surface.
		return 0, nil, fmt.Errorf("http error: %w", err)
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(io.LimitReader(resp.Body, 2<<20))
	if err != nil {
		return 0, nil, fmt.Errorf("read response: %w", err)
	}
	return resp.StatusCode, b, nil
}

// callProvider forwards an already-whitelisted payload to the provider and
// returns the provider's raw status/body.
func callProvider(ctx context.Context, provider string, payload map[string]any) (int, []byte, error) {
	switch provider {
	case "claude":
		key := os.Getenv("ANTHROPIC_API_KEY")
		if key == "" {
			return 0, nil, errProviderNotConfigured
		}
		payload["model"] = pickClaudeModel(payload["model"])
		payload["max_tokens"] = clampTokens(payload["max_tokens"])
		return postJSON(ctx, baseURL("ANTHROPIC_BASE_URL", "https://api.anthropic.com")+"/v1/messages",
			map[string]string{"x-api-key": key, "anthropic-version": "2023-06-01"}, payload)
	case "openai":
		key := os.Getenv("OPENAI_API_KEY")
		if key == "" && os.Getenv("OPENAI_BASE_URL") == "" {
			return 0, nil, errProviderNotConfigured
		}
		payload["model"] = envOr("OPENAI_MODEL", "gpt-4o")
		payload["max_tokens"] = clampTokens(payload["max_tokens"])
		h := map[string]string{}
		if key != "" {
			h["Authorization"] = "Bearer " + key
		}
		return postJSON(ctx, baseURL("OPENAI_BASE_URL", "https://api.openai.com")+"/v1/chat/completions", h, payload)
	case "gemini":
		key := os.Getenv("GEMINI_API_KEY")
		if key == "" {
			return 0, nil, errProviderNotConfigured
		}
		gc, _ := payload["generationConfig"].(map[string]any)
		if gc == nil {
			gc = map[string]any{}
		}
		gc["maxOutputTokens"] = clampTokens(gc["maxOutputTokens"])
		payload["generationConfig"] = gc
		model := envOr("GEMINI_MODEL", "gemini-2.5-flash")
		return postJSON(ctx, baseURL("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com")+
			"/v1beta/models/"+model+":generateContent", map[string]string{"x-goog-api-key": key}, payload)
	}
	return 0, nil, fmt.Errorf("unknown provider %q", provider)
}

var providerKeys = map[string][]string{
	"claude": {"model", "max_tokens", "system", "messages", "temperature"},
	"openai": {"model", "max_tokens", "messages", "temperature"},
	"gemini": {"systemInstruction", "contents", "generationConfig"},
}

// serveProviderBytes: whitelist keys, cap size/tokens, inject server-side keys,
// return the provider's raw JSON (the contract meteorium.html parses).
func serveProviderBytes(c *gin.Context, provider string, raw []byte) {
	var in map[string]any
	if err := json.Unmarshal(raw, &in); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid JSON body"})
		return
	}
	payload := map[string]any{}
	for _, k := range providerKeys[provider] {
		if v, ok := in[k]; ok {
			payload[k] = v
		}
	}
	need := "messages"
	if provider == "gemini" {
		need = "contents"
	}
	if arr, ok := payload[need].([]any); !ok || len(arr) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": need + " is required"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()
	status, body, err := callProvider(ctx, provider, payload)
	uid, _ := c.Get("user_id")
	if err != nil {
		if errors.Is(err, errProviderNotConfigured) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "AI provider not configured"})
			return
		}
		log.Printf("[ai] provider=%s user=%v error: %v", provider, uid, err)
		c.JSON(http.StatusBadGateway, gin.H{"error": "AI provider unreachable"})
		return
	}
	if status >= 400 {
		log.Printf("[ai] provider=%s user=%v upstream status=%d body=%s", provider, uid, status, truncate(body, 200))
		c.JSON(http.StatusBadGateway, gin.H{"error": fmt.Sprintf("AI provider error (HTTP %d)", status)})
		return
	}
	c.Data(http.StatusOK, "application/json", body)
}

func handleLegacyAI(provider string) gin.HandlerFunc {
	return func(c *gin.Context) {
		raw, err := io.ReadAll(io.LimitReader(c.Request.Body, maxAIPayloadBytes+1))
		if err != nil || len(raw) > maxAIPayloadBytes {
			c.JSON(http.StatusRequestEntityTooLarge, gin.H{"error": "payload too large"})
			return
		}
		serveProviderBytes(c, provider, raw)
	}
}

// handleClaude accepts BOTH shapes:
//
//	{message, model}                         → {reply}          (simple)
//	{model, system, messages, max_tokens}    → raw provider JSON (meteorium.html)
func handleClaude(c *gin.Context) {
	raw, err := io.ReadAll(io.LimitReader(c.Request.Body, maxAIPayloadBytes+1))
	if err != nil || len(raw) > maxAIPayloadBytes {
		c.JSON(http.StatusRequestEntityTooLarge, gin.H{"error": "payload too large"})
		return
	}
	var probe struct {
		Message  string          `json:"message"`
		Model    string          `json:"model"`
		Messages json.RawMessage `json:"messages"`
	}
	if err := json.Unmarshal(raw, &probe); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request"})
		return
	}
	if len(probe.Messages) > 0 {
		serveProviderBytes(c, "claude", raw)
		return
	}
	if strings.TrimSpace(probe.Message) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "message is required"})
		return
	}
	model := strings.TrimSpace(probe.Model)
	if model == "" {
		model = defaultModel
	}
	if _, ok := allowedModelSet()[model]; !ok {
		c.JSON(http.StatusBadRequest, gin.H{"error": "unsupported model", "allowed": getAllowedModelList()})
		return
	}
	userID, _ := c.Get("user_id")
	reqID, _ := c.Get("request_id")
	log.Printf("[claude] req=%v user=%v model=%s ip=%s msg_len=%d", reqID, userID, model, c.ClientIP(), len(probe.Message))
	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()
	reply, err := AnalyzeProbability(ctx, probe.Message, model)
	if err != nil {
		log.Printf("[claude] error req=%v user=%v: %v", reqID, userID, err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "AI inference failed"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"reply": reply})
}

// ── Per-user daily quota ──────────────────────────────────────────────────────

type quotaStore struct {
	mu     sync.Mutex
	day    string
	counts map[string]int
	limit  int
}

func newQuotaStore(limit int) *quotaStore { return &quotaStore{counts: map[string]int{}, limit: limit} }

func (q *quotaStore) take(user string) bool {
	q.mu.Lock()
	defer q.mu.Unlock()
	today := time.Now().UTC().Format("2006-01-02")
	if q.day != today {
		q.day, q.counts = today, map[string]int{}
	}
	if q.counts[user] >= q.limit {
		return false
	}
	q.counts[user]++
	return true
}

func aiDailyQuota() int {
	if v, err := strconv.Atoi(os.Getenv("AI_DAILY_QUOTA")); err == nil && v > 0 {
		return v
	}
	return 100
}

func AIQuotaMiddleware(q *quotaStore) gin.HandlerFunc {
	return func(c *gin.Context) {
		if !q.take(c.GetString("user_id")) {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{"error": "daily AI quota exceeded"})
			return
		}
		c.Next()
	}
}

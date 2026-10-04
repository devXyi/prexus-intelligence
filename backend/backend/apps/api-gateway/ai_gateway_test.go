package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

type capture struct {
	path   string
	query  string
	header http.Header
	body   map[string]any
}

func fakeProvider(t *testing.T, status int, reply string) (*httptest.Server, *capture) {
	t.Helper()
	c := &capture{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		c.path, c.query, c.header = r.URL.Path, r.URL.RawQuery, r.Header.Clone()
		_ = json.Unmarshal(b, &c.body)
		w.WriteHeader(status)
		w.Write([]byte(reply))
	}))
	t.Cleanup(srv.Close)
	return srv, c
}

func claudeRouter() *gin.Engine {
	r := gin.New()
	r.POST("/claude", handleClaude)
	r.POST("/openai", handleLegacyAI("openai"))
	r.POST("/gemini", handleLegacyAI("gemini"))
	return r
}

const anthropicOK = `{"content":[{"type":"text","text":"hello"}]}`

func TestClaude_SimpleShape_UsesSelectedModel(t *testing.T) {
	srv, cap := fakeProvider(t, 200, anthropicOK)
	t.Setenv("ANTHROPIC_BASE_URL", srv.URL)
	t.Setenv("ANTHROPIC_API_KEY", "sk-test-123")
	w := doJSON(claudeRouter(), "POST", "/claude", map[string]any{"message": "hi", "model": "claude-sonnet-5-5"}, nil)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"reply":"hello"`) {
		t.Fatalf("code=%d body=%s", w.Code, w.Body.String())
	}
	if cap.body["model"] != "claude-sonnet-5-5" {
		t.Fatalf("selector ignored (v1 bug): sent model=%v", cap.body["model"])
	}
	if cap.header.Get("x-api-key") != "sk-test-123" || cap.path != "/v1/messages" {
		t.Fatalf("auth/path wrong: %v %s", cap.header, cap.path)
	}
}

func TestClaude_UnsupportedModelRejected(t *testing.T) {
	t.Setenv("ANTHROPIC_API_KEY", "k")
	w := doJSON(claudeRouter(), "POST", "/claude", map[string]any{"message": "hi", "model": "totally-fake"}, nil)
	if w.Code != 400 || !strings.Contains(w.Body.String(), "allowed") {
		t.Fatalf("code=%d %s", w.Code, w.Body.String())
	}
}

func TestClaude_RawShape_WhitelistsAndClamps(t *testing.T) {
	srv, cap := fakeProvider(t, 200, anthropicOK)
	t.Setenv("ANTHROPIC_BASE_URL", srv.URL)
	t.Setenv("ANTHROPIC_API_KEY", "k")
	body := map[string]any{
		"model": "gpt-evil", "max_tokens": 999999, "system": "sys",
		"messages": []map[string]string{{"role": "user", "content": "x"}},
		"tools":    []string{"rm -rf"}, "stream": true, "metadata": map[string]string{"a": "b"},
	}
	w := doJSON(claudeRouter(), "POST", "/claude", body, nil)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"text":"hello"`) {
		t.Fatalf("raw passthrough broken: %d %s", w.Code, w.Body.String())
	}
	if cap.body["model"] != defaultModel {
		t.Errorf("non-allowlisted model must fall back to default, got %v", cap.body["model"])
	}
	if cap.body["max_tokens"].(float64) != maxAITokens {
		t.Errorf("max_tokens not clamped: %v", cap.body["max_tokens"])
	}
	for _, k := range []string{"tools", "stream", "metadata"} {
		if _, ok := cap.body[k]; ok {
			t.Errorf("client-controlled key %q reached the provider", k)
		}
	}
}

func TestGemini_KeyInHeaderNotURL(t *testing.T) {
	srv, cap := fakeProvider(t, 200, `{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}`)
	t.Setenv("GEMINI_BASE_URL", srv.URL)
	t.Setenv("GEMINI_API_KEY", "AIza-secret")
	body := map[string]any{"contents": []map[string]any{{"role": "user", "parts": []map[string]string{{"text": "x"}}}}}
	w := doJSON(claudeRouter(), "POST", "/gemini", body, nil)
	if w.Code != 200 {
		t.Fatalf("%d %s", w.Code, w.Body.String())
	}
	if strings.Contains(cap.query, "key=") || strings.Contains(cap.path, "AIza") {
		t.Fatalf("API key leaked into URL: %s?%s", cap.path, cap.query)
	}
	if cap.header.Get("x-goog-api-key") != "AIza-secret" || !strings.HasSuffix(cap.path, ":generateContent") {
		t.Fatalf("header/path wrong: %v %s", cap.header, cap.path)
	}
}

func TestOpenAI_LocalBaseURLNeedsNoKey_AirGapHook(t *testing.T) {
	srv, cap := fakeProvider(t, 200, `{"choices":[{"message":{"content":"local"}}]}`)
	t.Setenv("OPENAI_BASE_URL", srv.URL) // e.g. local vLLM / Ollama
	t.Setenv("OPENAI_API_KEY", "")
	t.Setenv("OPENAI_MODEL", "qwen3-32b")
	body := map[string]any{"messages": []map[string]string{{"role": "user", "content": "x"}}}
	w := doJSON(claudeRouter(), "POST", "/openai", body, nil)
	if w.Code != 200 || cap.body["model"] != "qwen3-32b" || cap.path != "/v1/chat/completions" {
		t.Fatalf("code=%d model=%v path=%s", w.Code, cap.body["model"], cap.path)
	}
}

func TestProvider_MissingKey_503_UpstreamError_502_NoLeak(t *testing.T) {
	t.Setenv("ANTHROPIC_API_KEY", "")
	msgs := map[string]any{"messages": []map[string]string{{"role": "user", "content": "x"}}}
	if w := doJSON(claudeRouter(), "POST", "/claude", msgs, nil); w.Code != 503 {
		t.Fatalf("missing key → %d", w.Code)
	}
	srv, _ := fakeProvider(t, 500, `{"error":{"message":"INTERNAL-SECRET-DETAIL sk-live"}}`)
	t.Setenv("ANTHROPIC_BASE_URL", srv.URL)
	t.Setenv("ANTHROPIC_API_KEY", "k")
	w := doJSON(claudeRouter(), "POST", "/claude", msgs, nil)
	if w.Code != 502 || strings.Contains(w.Body.String(), "INTERNAL-SECRET") {
		t.Fatalf("code=%d body=%s", w.Code, w.Body.String())
	}
}

func TestClaude_OversizedPayload413(t *testing.T) {
	t.Setenv("ANTHROPIC_API_KEY", "k")
	big := map[string]any{"message": strings.Repeat("a", maxAIPayloadBytes+10)}
	if w := doJSON(claudeRouter(), "POST", "/claude", big, nil); w.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("code=%d", w.Code)
	}
}

func TestAllowedModels_EnvOverride(t *testing.T) {
	t.Setenv("ALLOWED_MODELS", "m-a, m-b")
	l := getAllowedModelList()
	if len(l) != 2 || l[0] != "m-a" || l[1] != "m-b" {
		t.Fatalf("%v", l)
	}
	if pickClaudeModel("m-b") != "m-b" || pickClaudeModel("zzz") != "m-a" {
		t.Fatal("pickClaudeModel")
	}
}

func TestQuota(t *testing.T) {
	q := newQuotaStore(2)
	if !q.take("u") || !q.take("u") || q.take("u") {
		t.Fatal("quota should allow exactly 2")
	}
	if !q.take("other") {
		t.Fatal("quota must be per user")
	}
}

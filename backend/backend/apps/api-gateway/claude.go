// backend/apps/api-gateway/claude.go
// Prexus Intelligence — AI Provider Bridge (simple {message} → {reply} path).
// All provider I/O now goes through callProvider (ai_gateway.go).
//
// History: [BUG-1..4] timeout/ctx/marshal fixes (v1) · v2: selected model is
// honoured, Gemini key moved out of the URL, single code path for all providers.

package main

import (
	"context"
	"encoding/json"
	"fmt"
)

// AnalyzeProbability dispatches to the requested provider. ctx is owned by the caller.
func AnalyzeProbability(ctx context.Context, prompt string, model string) (string, error) {
	switch model {
	case "gemini":
		return callGemini(ctx, prompt)
	case "chatgpt":
		return callOpenAI(ctx, prompt)
	default:
		return callClaude(ctx, prompt, model)
	}
}

func callClaude(ctx context.Context, prompt, model string) (string, error) {
	status, b, err := callProvider(ctx, "claude", map[string]any{
		"model":      model,
		"max_tokens": 1024,
		"messages":   []map[string]string{{"role": "user", "content": prompt}},
	})
	if err != nil {
		return "", fmt.Errorf("claude: %w", err)
	}
	if status >= 400 {
		return "", fmt.Errorf("claude: http %d: %s", status, truncate(b, 200))
	}
	var r struct {
		Content []struct {
			Text string `json:"text"`
		} `json:"content"`
		Error *struct {
			Message string `json:"message"`
		} `json:"error,omitempty"`
	}
	if err := json.Unmarshal(b, &r); err != nil {
		return "", fmt.Errorf("claude: unmarshal (status %d): %w | body: %s", status, err, truncate(b, 200))
	}
	if r.Error != nil {
		return "", fmt.Errorf("claude API error: %s", r.Error.Message)
	}
	if len(r.Content) == 0 {
		return "", fmt.Errorf("claude: empty response (status %d): %s", status, truncate(b, 200))
	}
	return r.Content[0].Text, nil
}

func callGemini(ctx context.Context, prompt string) (string, error) {
	status, b, err := callProvider(ctx, "gemini", map[string]any{
		"contents": []map[string]any{{"parts": []map[string]string{{"text": prompt}}}},
	})
	if err != nil {
		return "", fmt.Errorf("gemini: %w", err)
	}
	if status >= 400 {
		return "", fmt.Errorf("gemini: http %d: %s", status, truncate(b, 200))
	}
	var r struct {
		Error *struct {
			Code    int    `json:"code"`
			Message string `json:"message"`
		} `json:"error,omitempty"`
		Candidates []struct {
			Content struct {
				Parts []struct {
					Text string `json:"text"`
				} `json:"parts"`
			} `json:"content"`
		} `json:"candidates"`
	}
	if err := json.Unmarshal(b, &r); err != nil {
		return "", fmt.Errorf("gemini: unmarshal (status %d): %w | body: %s", status, err, truncate(b, 200))
	}
	if r.Error != nil {
		return "", fmt.Errorf("gemini API error %d: %s", r.Error.Code, r.Error.Message)
	}
	if len(r.Candidates) == 0 || len(r.Candidates[0].Content.Parts) == 0 {
		return "", fmt.Errorf("gemini: empty candidates (status %d): %s", status, truncate(b, 200))
	}
	return r.Candidates[0].Content.Parts[0].Text, nil
}

func callOpenAI(ctx context.Context, prompt string) (string, error) {
	status, b, err := callProvider(ctx, "openai", map[string]any{
		"max_tokens": 1024,
		"messages":   []map[string]string{{"role": "user", "content": prompt}},
	})
	if err != nil {
		return "", fmt.Errorf("openai: %w", err)
	}
	if status >= 400 {
		return "", fmt.Errorf("openai: http %d: %s", status, truncate(b, 200))
	}
	var r struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
		Error *struct {
			Message string `json:"message"`
		} `json:"error,omitempty"`
	}
	if err := json.Unmarshal(b, &r); err != nil {
		return "", fmt.Errorf("openai: unmarshal (status %d): %w | body: %s", status, err, truncate(b, 200))
	}
	if r.Error != nil {
		return "", fmt.Errorf("openai API error: %s", r.Error.Message)
	}
	if len(r.Choices) == 0 {
		return "", fmt.Errorf("openai: empty choices (status %d): %s", status, truncate(b, 200))
	}
	return r.Choices[0].Message.Content, nil
}

func truncate(b []byte, n int) string {
	if len(b) <= n {
		return string(b)
	}
	return string(b[:n]) + "…"
}

package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
)

// AnalyzeProbability routes to the correct AI based on model choice
func AnalyzeProbability(prompt string, model string) (string, error) {
	switch model {
	case "gemini":
		return callGemini(prompt)
	case "chatgpt":
		return callOpenAI(prompt)
	default:
		return callClaude(prompt)
	}
}

// ── Claude (Anthropic) ──────────────────────────────
func callClaude(prompt string) (string, error) {
	apiKey := os.Getenv("ANTHROPIC_API_KEY")
	if apiKey == "" {
		return "", fmt.Errorf("ANTHROPIC_API_KEY not set")
	}
	body, _ := json.Marshal(map[string]interface{}{
		"model":      "claude-sonnet-4-20250514",
		"max_tokens": 1024,
		"messages":   []map[string]string{{"role": "user", "content": prompt}},
	})
	req, _ := http.NewRequest("POST", "https://api.anthropic.com/v1/messages", bytes.NewBuffer(body))
	req.Header.Set("x-api-key", apiKey)
	req.Header.Set("anthropic-version", "2023-06-01")
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil { return "", err }
	defer resp.Body.Close()
	var result struct {
		Content []struct{ Text string `json:"text"` } `json:"content"`
		Error   *struct{ Message string `json:"message"` } `json:"error,omitempty"`
	}
	b, _ := io.ReadAll(resp.Body)
	json.Unmarshal(b, &result)
	if result.Error != nil { return "", fmt.Errorf("Claude API error: %s", result.Error.Message) }
	if len(result.Content) > 0 { return result.Content[0].Text, nil }
	return "", fmt.Errorf("empty response from Claude")
}

// ── Gemini (Google) ─────────────────────────────────
func callGemini(prompt string) (string, error) {
	apiKey := os.Getenv("GEMINI_API_KEY")
	if apiKey == "" { return "", fmt.Errorf("GEMINI_API_KEY not set") }
	url := fmt.Sprintf("https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=%s", apiKey)
	body, _ := json.Marshal(map[string]interface{}{
		"contents": []map[string]interface{}{{"parts": []map[string]string{{"text": prompt}}}},
	})
	req, _ := http.NewRequest("POST", url, bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil { return "", err }
	defer resp.Body.Close()
	var result struct {
		Candidates []struct {
			Content struct {
				Parts []struct{ Text string `json:"text"` } `json:"parts"`
			} `json:"content"`
		} `json:"candidates"`
	}
	b, _ := io.ReadAll(resp.Body)
	json.Unmarshal(b, &result)
	if len(result.Candidates) > 0 && len(result.Candidates[0].Content.Parts) > 0 {
		return result.Candidates[0].Content.Parts[0].Text, nil
	}
	return "", fmt.Errorf("empty response from Gemini")
}

// ── ChatGPT (OpenAI) ─────────────────────────────────
func callOpenAI(prompt string) (string, error) {
	apiKey := os.Getenv("OPENAI_API_KEY")
	if apiKey == "" { return "", fmt.Errorf("OPENAI_API_KEY not set") }
	body, _ := json.Marshal(map[string]interface{}{
		"model":      "gpt-4o",
		"max_tokens": 1024,
		"messages":   []map[string]string{{"role": "user", "content": prompt}},
	})
	req, _ := http.NewRequest("POST", "https://api.openai.com/v1/chat/completions", bytes.NewBuffer(body))
	req.Header.Set("Authorization", "Bearer "+apiKey)
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil { return "", err }
	defer resp.Body.Close()
	var result struct {
		Choices []struct {
			Message struct{ Content string `json:"content"` } `json:"message"`
		} `json:"choices"`
		Error *struct{ Message string `json:"message"` } `json:"error,omitempty"`
	}
	b, _ := io.ReadAll(resp.Body)
	json.Unmarshal(b, &result)
	if result.Error != nil { return "", fmt.Errorf("OpenAI API error: %s", result.Error.Message) }
	if len(result.Choices) > 0 { return result.Choices[0].Message.Content, nil }
	return "", fmt.Errorf("empty response from OpenAI")
}


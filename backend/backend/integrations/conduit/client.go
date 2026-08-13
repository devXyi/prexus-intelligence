package conduit

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

type Client struct {
	cfg        Config
	httpClient *http.Client
	token      string
	tokenExp   time.Time
	sessionID  string
	mu         sync.Mutex
	seq        uint64
}

func NewClient(cfg Config) *Client {
	return &Client{cfg: cfg, httpClient: &http.Client{Timeout: 30 * time.Second}}
}

type tokenResponse struct {
	AccessToken string `json:"access_token"`
	TokenType   string `json:"token_type"`
	ExpiresIn   int    `json:"expires_in"`
}

func (c *Client) accessToken(ctx context.Context) (string, error) {
	c.mu.Lock()
	if c.token != "" && time.Now().Before(c.tokenExp.Add(-30*time.Second)) {
		t := c.token
		c.mu.Unlock()
		return t, nil
	}
	c.mu.Unlock()

	payload, err := json.Marshal(map[string]string{
		"client_id": c.cfg.ClientID, "client_secret": c.cfg.ClientSecret,
		"audience": c.cfg.Audience, "grant_type": "client_credentials",
	})
	if err != nil {
		return "", fmt.Errorf("encode conduit token request: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.cfg.TokenURL, bytes.NewReader(payload))
	if err != nil {
		return "", fmt.Errorf("create conduit token request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("request conduit token: %w", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("conduit token endpoint returned %s: %s", resp.Status, strings.TrimSpace(string(body)))
	}
	var tr tokenResponse
	if err := json.Unmarshal(body, &tr); err != nil {
		return "", fmt.Errorf("decode conduit token response: %w", err)
	}
	if tr.AccessToken == "" {
		return "", fmt.Errorf("conduit token endpoint returned no access_token")
	}
	expires := time.Duration(tr.ExpiresIn) * time.Second
	if expires <= 0 {
		expires = 5 * time.Minute
	}
	c.mu.Lock()
	c.token, c.tokenExp = tr.AccessToken, time.Now().Add(expires)
	t := c.token
	c.mu.Unlock()
	return t, nil
}

type rpcRequest struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      uint64      `json:"id,omitempty"`
	Method  string      `json:"method"`
	Params  interface{} `json:"params,omitempty"`
}

type rpcResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      uint64          `json:"id"`
	Result  json.RawMessage `json:"result,omitempty"`
	Error   *rpcError       `json:"error,omitempty"`
}

type rpcError struct {
	Code int `json:"code"`
	Message string `json:"message"`
	Data any `json:"data,omitempty"`
}

func (c *Client) nextID() uint64 { return atomic.AddUint64(&c.seq, 1) }

func (c *Client) request(ctx context.Context, method string, params interface{}, notification bool) (json.RawMessage, error) {
	token, err := c.accessToken(ctx)
	if err != nil {
		return nil, err
	}
	rpc := rpcRequest{JSONRPC: "2.0", Method: method, Params: params}
	if !notification {
		rpc.ID = c.nextID()
	}
	body, err := json.Marshal(rpc)
	if err != nil {
		return nil, fmt.Errorf("encode MCP request: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.cfg.MCPURL, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("create MCP request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")
	c.mu.Lock()
	if c.sessionID != "" {
		req.Header.Set("Mcp-Session-Id", c.sessionID)
	}
	c.mu.Unlock()

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("MCP request failed: %w", err)
	}
	defer resp.Body.Close()
	if sid := resp.Header.Get("Mcp-Session-Id"); sid != "" {
		c.mu.Lock()
		c.sessionID = sid
		c.mu.Unlock()
	}
	responseBody, _ := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("MCP endpoint returned %s: %s", resp.Status, strings.TrimSpace(string(responseBody)))
	}
	if notification {
		return nil, nil
	}
	result, err := decodeRPC(responseBody, resp.Header.Get("Content-Type"))
	if err != nil {
		return nil, err
	}
	if result.Error != nil {
		return nil, fmt.Errorf("MCP error %d: %s", result.Error.Code, result.Error.Message)
	}
	return result.Result, nil
}

func (c *Client) call(ctx context.Context, method string, params interface{}) (json.RawMessage, error) {
	return c.request(ctx, method, params, false)
}

func (c *Client) notify(ctx context.Context, method string, params interface{}) error {
	_, err := c.request(ctx, method, params, true)
	return err
}

func decodeRPC(body []byte, contentType string) (rpcResponse, error) {
	var direct rpcResponse
	if json.Unmarshal(body, &direct) == nil && (direct.Result != nil || direct.Error != nil) {
		return direct, nil
	}
	for _, line := range strings.Split(string(body), "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		payload := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		var msg rpcResponse
		if json.Unmarshal([]byte(payload), &msg) == nil && (msg.Result != nil || msg.Error != nil) {
			return msg, nil
		}
	}
	return rpcResponse{}, fmt.Errorf("unable to decode MCP JSON-RPC response (content-type %q)", contentType)
}

func (c *Client) Initialize(ctx context.Context) (json.RawMessage, error) {
	return c.call(ctx, "initialize", map[string]interface{}{
		"protocolVersion": "2025-03-26",
		"capabilities": map[string]interface{}{},
		"clientInfo": map[string]string{"name": "prexus-intelligence", "version": "2.1.0"},
	})
}

func (c *Client) Initialized(ctx context.Context) error {
	return c.notify(ctx, "notifications/initialized", nil)
}

func (c *Client) ListTools(ctx context.Context) (json.RawMessage, error) {
	return c.call(ctx, "tools/list", map[string]interface{}{})
}

func (c *Client) CallTool(ctx context.Context, name string, arguments map[string]interface{}) (json.RawMessage, error) {
	return c.call(ctx, "tools/call", map[string]interface{}{"name": name, "arguments": arguments})
}

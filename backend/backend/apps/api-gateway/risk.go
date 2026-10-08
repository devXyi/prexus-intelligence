// backend/apps/api-gateway/risk.go
// Prexus Intelligence — Risk proxy handlers
// Forwards authenticated risk requests to the Python data engine.
//
// v2 (audit fixes):
//   • Cache key = sha256(user_id ‖ path ‖ full body). v1 keyed on
//     asset_id:scenario:horizon only, so another user could receive your
//     cached result (and edits to an asset were ignored for 5 minutes).
//   • Requests carry the caller's context (client disconnect cancels retries)
//     and back-off sleeps are context-aware.
//   • Internal error details/URLs are no longer echoed to clients.
//   • No implicit default engine URL in production (v1 defaulted to the
//     gateway's own public URL).

package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

const (
	ProxyTimeoutSeconds = 35
	CacheRiskTTLSeconds = 300
	EngineMaxRetries    = 4
	maxRiskCacheEntries = 1000
	maxEngineResponse   = 8 << 20
)

var (
	engineClientPost = &http.Client{Timeout: ProxyTimeoutSeconds * time.Second}
	engineClientGet  = &http.Client{Timeout: 15 * time.Second}
)

var riskCache = struct {
	mu    sync.RWMutex
	store map[string]cachedRisk
}{store: make(map[string]cachedRisk)}

type cachedRisk struct {
	data      []byte
	expiresAt time.Time
}

func getDataEngineURL() string {
	u := strings.TrimRight(strings.TrimSpace(os.Getenv("DATA_ENGINE_URL")), "/")
	if u == "" && os.Getenv("ENV") != "production" {
		u = "http://localhost:8000"
	}
	if u != "" && !strings.Contains(u, "://") {
		u = "http://" + u // Render's private-network `hostport` has no scheme
	}
	return u
}

func retryDelay(attempt int, resp *http.Response) time.Duration {
	if resp != nil {
		if ra := resp.Header.Get("Retry-After"); ra != "" {
			if d, err := time.ParseDuration(ra + "s"); err == nil && d > 0 && d <= 10*time.Second {
				return d
			}
		}
	}
	return retryBase << uint(attempt-1)
}

// retryBase is the first back-off step (a var so tests can shrink it).
var retryBase = time.Second

func shouldRetryEngineStatus(status int) bool {
	return status == http.StatusTooManyRequests || status == http.StatusBadGateway ||
		status == http.StatusServiceUnavailable || status == http.StatusGatewayTimeout
}

func sleepCtx(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}

// callEngine performs the request with bounded retries/back-off.
func callEngine(ctx context.Context, client *http.Client, method, path string, body []byte) (int, []byte, error) {
	url := getDataEngineURL() + path
	secret := os.Getenv("ENGINE_SECRET")
	var lastErr error
	for attempt := 1; attempt <= EngineMaxRetries; attempt++ {
		var rdr io.Reader
		if body != nil {
			rdr = bytes.NewReader(body)
		}
		req, err := http.NewRequestWithContext(ctx, method, url, rdr)
		if err != nil {
			return 0, nil, err
		}
		if body != nil {
			req.Header.Set("Content-Type", "application/json")
		}
		if secret != "" {
			req.Header.Set("Authorization", "Bearer "+secret)
		}
		start := time.Now()
		resp, err := client.Do(req)
		if err != nil {
			lastErr = err
			log.Printf("[proxy] %s %s attempt=%d engine error after %v: %v", method, path, attempt, time.Since(start), err)
			if attempt < EngineMaxRetries && sleepCtx(ctx, retryDelay(attempt, nil)) {
				continue
			}
			break
		}
		b, rerr := io.ReadAll(io.LimitReader(resp.Body, maxEngineResponse))
		_ = resp.Body.Close()
		if rerr != nil {
			lastErr = rerr
			if attempt < EngineMaxRetries && sleepCtx(ctx, retryDelay(attempt, nil)) {
				continue
			}
			break
		}
		if shouldRetryEngineStatus(resp.StatusCode) && attempt < EngineMaxRetries {
			log.Printf("[proxy] %s %s attempt=%d upstream=%d; retrying", method, path, attempt, resp.StatusCode)
			if sleepCtx(ctx, retryDelay(attempt, resp)) {
				continue
			}
			lastErr = ctx.Err()
			break
		}
		return resp.StatusCode, b, nil
	}
	if lastErr == nil {
		lastErr = context.Canceled
	}
	return 0, nil, lastErr
}

func proxyToDataEngine(path string) gin.HandlerFunc {
	return func(c *gin.Context) {
		body, err := io.ReadAll(c.Request.Body)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Failed to read request"})
			return
		}
		key := ""
		if path == "/risk/asset" {
			key = riskCacheKey(c.GetString("user_id"), path, body)
			if cached, ok := getRiskCache(key); ok {
				c.Data(http.StatusOK, "application/json", cached)
				return
			}
		}
		status, respBody, err := callEngine(c.Request.Context(), engineClientPost, http.MethodPost, path, body)
		if err != nil {
			log.Printf("[proxy] %s failed: %v", path, err)
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "Data engine unavailable", "path": path})
			return
		}
		log.Printf("[proxy] %s → %d", path, status)
		if key != "" && status == http.StatusOK {
			setRiskCache(key, respBody)
		}
		c.Data(status, "application/json", respBody)
	}
}

func proxyToDataEngineGET(path string) gin.HandlerFunc {
	return func(c *gin.Context) {
		status, body, err := callEngine(c.Request.Context(), engineClientGet, http.MethodGet, path, nil)
		if err != nil {
			log.Printf("[proxy] GET %s failed: %v", path, err)
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "Data engine unavailable", "path": path})
			return
		}
		log.Printf("[proxy] GET %s → %d", path, status)
		c.Data(status, "application/json", body)
	}
}

// riskCacheKey isolates entries per user AND per full request body.
func riskCacheKey(userID, path string, body []byte) string {
	h := sha256.New()
	h.Write([]byte(userID))
	h.Write([]byte{0})
	h.Write([]byte(path))
	h.Write([]byte{0})
	h.Write(body)
	return hex.EncodeToString(h.Sum(nil))
}

func getRiskCache(key string) ([]byte, bool) {
	riskCache.mu.RLock()
	defer riskCache.mu.RUnlock()
	if c, ok := riskCache.store[key]; ok && time.Now().Before(c.expiresAt) {
		return c.data, true
	}
	return nil, false
}

func setRiskCache(key string, respBody []byte) {
	riskCache.mu.Lock()
	defer riskCache.mu.Unlock()
	riskCache.store[key] = cachedRisk{data: respBody, expiresAt: time.Now().Add(CacheRiskTTLSeconds * time.Second)}
	if len(riskCache.store) > maxRiskCacheEntries {
		now := time.Now()
		for k, e := range riskCache.store {
			if now.After(e.expiresAt) {
				delete(riskCache.store, k)
			}
		}
		if len(riskCache.store) > maxRiskCacheEntries { // still full of live entries: reset
			riskCache.store = make(map[string]cachedRisk)
		}
	}
}

// backend/apps/api-gateway/risk.go
// Prexus Intelligence — Risk proxy handlers
// Forwards authenticated risk requests to the Python data engine.
// Handles caching, timeout, retries, and graceful degradation.

package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

const (
	ProxyTimeoutSeconds = 35
	CacheRiskTTLSeconds = 300
	EngineMaxRetries    = 4
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
	url := os.Getenv("DATA_ENGINE_URL")
	if url == "" {
		url = "https://prexus-intelligence.onrender.com"
	}
	return url
}

func retryDelay(attempt int, resp *http.Response) time.Duration {
	if resp != nil {
		if retryAfter := resp.Header.Get("Retry-After"); retryAfter != "" {
			if d, err := time.ParseDuration(retryAfter + "s"); err == nil && d > 0 && d <= 10*time.Second {
				return d
			}
		}
	}
	return time.Duration(1<<(attempt-1)) * time.Second
}

func shouldRetryEngineStatus(status int) bool {
	return status == http.StatusTooManyRequests ||
		status == http.StatusBadGateway ||
		status == http.StatusServiceUnavailable ||
		status == http.StatusGatewayTimeout
}

func proxyToDataEngine(path string) gin.HandlerFunc {
	return func(c *gin.Context) {
		engineURL := getDataEngineURL() + path

		body, err := io.ReadAll(c.Request.Body)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Failed to read request"})
			return
		}

		if path == "/risk/asset" {
			if cached, ok := getRiskCache(body); ok {
				c.Data(http.StatusOK, "application/json", cached)
				return
			}
		}

		client := &http.Client{Timeout: ProxyTimeoutSeconds * time.Second}
		var resp *http.Response
		var lastErr error

		for attempt := 1; attempt <= EngineMaxRetries; attempt++ {
			req, reqErr := http.NewRequest(http.MethodPost, engineURL, bytes.NewReader(body))
			if reqErr != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": "Proxy request failed"})
				return
			}
			req.Header.Set("Content-Type", "application/json")
			if secret := os.Getenv("ENGINE_SECRET"); secret != "" {
				req.Header.Set("Authorization", "Bearer "+secret)
			}

			start := time.Now()
			resp, lastErr = client.Do(req)
			elapsed := time.Since(start)

			if lastErr != nil {
				log.Printf("[proxy] %s attempt=%d engine error after %v: %v", path, attempt, elapsed, lastErr)
				if attempt < EngineMaxRetries {
					time.Sleep(retryDelay(attempt, nil))
					continue
				}
				break
			}

			if !shouldRetryEngineStatus(resp.StatusCode) || attempt == EngineMaxRetries {
				break
			}

			log.Printf("[proxy] %s attempt=%d upstream=%d; retrying", path, attempt, resp.StatusCode)
			resp.Body.Close()
			time.Sleep(retryDelay(attempt, resp))
		}

		if lastErr != nil || resp == nil {
			c.JSON(http.StatusServiceUnavailable, gin.H{
				"error": "Data engine unavailable",
				"detail": lastErr.Error(),
				"path": path,
			})
			return
		}
		defer resp.Body.Close()

		respBody, _ := io.ReadAll(resp.Body)
		log.Printf("[proxy] %s → %d", path, resp.StatusCode)

		if path == "/risk/asset" && resp.StatusCode == http.StatusOK {
			setRiskCache(body, respBody)
		}

		c.Data(resp.StatusCode, "application/json", respBody)
	}
}

func proxyToDataEngineGET(path string) gin.HandlerFunc {
	return func(c *gin.Context) {
		engineURL := getDataEngineURL() + path
		client := &http.Client{Timeout: 15 * time.Second}
		var resp *http.Response
		var lastErr error

		for attempt := 1; attempt <= EngineMaxRetries; attempt++ {
			req, reqErr := http.NewRequest(http.MethodGet, engineURL, nil)
			if reqErr != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": "Proxy request failed"})
				return
			}
			if secret := os.Getenv("ENGINE_SECRET"); secret != "" {
				req.Header.Set("Authorization", "Bearer "+secret)
			}

			start := time.Now()
			resp, lastErr = client.Do(req)
			elapsed := time.Since(start)

			if lastErr != nil {
				log.Printf("[proxy] GET %s attempt=%d engine error after %v: %v", path, attempt, elapsed, lastErr)
				if attempt < EngineMaxRetries {
					time.Sleep(retryDelay(attempt, nil))
					continue
				}
				break
			}

			if !shouldRetryEngineStatus(resp.StatusCode) || attempt == EngineMaxRetries {
				break
			}

			log.Printf("[proxy] GET %s attempt=%d upstream=%d; retrying", path, attempt, resp.StatusCode)
			resp.Body.Close()
			time.Sleep(retryDelay(attempt, resp))
		}

		if lastErr != nil || resp == nil {
			c.JSON(http.StatusServiceUnavailable, gin.H{
				"error": "Data engine unavailable",
				"path": path,
			})
			return
		}
		defer resp.Body.Close()

		body, _ := io.ReadAll(resp.Body)
		log.Printf("[proxy] GET %s → %d", path, resp.StatusCode)
		c.Data(resp.StatusCode, "application/json", body)
	}
}

type cacheKey struct {
	AssetID  string `json:"asset_id"`
	Scenario string `json:"scenario"`
	Horizon  int    `json:"horizon_days"`
}

func getRiskCache(reqBody []byte) ([]byte, bool) {
	var k cacheKey
	if err := json.Unmarshal(reqBody, &k); err != nil || k.AssetID == "" {
		return nil, false
	}
	key := fmt.Sprintf("%s:%s:%d", k.AssetID, k.Scenario, k.Horizon)

	riskCache.mu.RLock()
	defer riskCache.mu.RUnlock()

	if c, ok := riskCache.store[key]; ok && time.Now().Before(c.expiresAt) {
		return c.data, true
	}
	return nil, false
}

func setRiskCache(reqBody, respBody []byte) {
	var k cacheKey
	if err := json.Unmarshal(reqBody, &k); err != nil || k.AssetID == "" {
		return
	}
	key := fmt.Sprintf("%s:%s:%d", k.AssetID, k.Scenario, k.Horizon)

	riskCache.mu.Lock()
	defer riskCache.mu.Unlock()

	riskCache.store[key] = cachedRisk{
		data: respBody,
		expiresAt: time.Now().Add(CacheRiskTTLSeconds * time.Second),
	}

	if len(riskCache.store) > 1000 {
		now := time.Now()
		for entryKey, entry := range riskCache.store {
			if now.After(entry.expiresAt) {
				delete(riskCache.store, entryKey)
			}
		}
	}
}

package main

import (
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func withUser(r *gin.Engine) {
	r.Use(func(c *gin.Context) { c.Set("user_id", c.GetHeader("X-Test-User")); c.Next() })
}

func resetRiskCache() {
	riskCache.mu.Lock()
	riskCache.store = map[string]cachedRisk{}
	riskCache.mu.Unlock()
}

func TestRiskCacheKey_IsolatesUsersAndBodies(t *testing.T) {
	a := riskCacheKey("userA", "/risk/asset", []byte(`{"asset_id":"X","scenario":"base"}`))
	b := riskCacheKey("userB", "/risk/asset", []byte(`{"asset_id":"X","scenario":"base"}`))
	c := riskCacheKey("userA", "/risk/asset", []byte(`{"asset_id":"X","scenario":"base","lat":9}`))
	if a == b {
		t.Fatal("different users share a cache key (cross-tenant leak)")
	}
	if a == c {
		t.Fatal("body change ignored by cache key (stale results after edits)")
	}
	if a != riskCacheKey("userA", "/risk/asset", []byte(`{"asset_id":"X","scenario":"base"}`)) {
		t.Fatal("key not deterministic")
	}
}

func TestProxy_CacheNotSharedAcrossUsers_ButHitsForSameUser(t *testing.T) {
	resetRiskCache()
	var hits int32
	eng := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"ok":true}`))
	}))
	defer eng.Close()
	t.Setenv("DATA_ENGINE_URL", eng.URL)
	r := gin.New()
	withUser(r)
	r.POST("/risk/asset", proxyToDataEngine("/risk/asset"))
	body := map[string]any{"asset_id": "AST-1", "scenario": "base", "horizon_days": 30}
	post := func(user string) int {
		return doJSON(r, "POST", "/risk/asset", body, map[string]string{"X-Test-User": user}).Code
	}
	if post("A") != 200 || post("B") != 200 {
		t.Fatal("proxy failed")
	}
	if atomic.LoadInt32(&hits) != 2 {
		t.Fatalf("user B must not be served user A's cache: hits=%d", hits)
	}
	post("A")
	if atomic.LoadInt32(&hits) != 2 {
		t.Fatalf("same-user repeat should be cached: hits=%d", hits)
	}
}

func TestProxy_ForwardsSecretAndRetriesTransient(t *testing.T) {
	resetRiskCache()
	old := retryBase
	retryBase = time.Millisecond
	defer func() { retryBase = old }()
	var n int32
	var sawAuth atomic.Value
	eng := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sawAuth.Store(r.Header.Get("Authorization"))
		if atomic.AddInt32(&n, 1) == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		w.Write([]byte(`{"ok":1}`))
	}))
	defer eng.Close()
	t.Setenv("DATA_ENGINE_URL", eng.URL)
	t.Setenv("ENGINE_SECRET", "s3cr3t")
	r := gin.New()
	withUser(r)
	r.POST("/risk/portfolio", proxyToDataEngine("/risk/portfolio"))
	w := doJSON(r, "POST", "/risk/portfolio", map[string]any{"x": 1}, map[string]string{"X-Test-User": "u"})
	if w.Code != 200 || atomic.LoadInt32(&n) != 2 {
		t.Fatalf("code=%d attempts=%d", w.Code, n)
	}
	if sawAuth.Load() != "Bearer s3cr3t" {
		t.Fatalf("engine secret not forwarded: %v", sawAuth.Load())
	}
}

func TestProxy_EngineDownHidesInternalDetail(t *testing.T) {
	old := retryBase
	retryBase = time.Millisecond
	defer func() { retryBase = old }()
	t.Setenv("DATA_ENGINE_URL", "http://127.0.0.1:1") // closed port
	r := gin.New()
	withUser(r)
	r.POST("/risk/portfolio", proxyToDataEngine("/risk/portfolio"))
	w := doJSON(r, "POST", "/risk/portfolio", map[string]any{"x": 1}, map[string]string{"X-Test-User": "u"})
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("code=%d", w.Code)
	}
	if body := w.Body.String(); contains(body, "127.0.0.1") || contains(body, "connect") || contains(body, "refused") {
		t.Fatalf("internal detail leaked: %s", body)
	}
}

func TestProxy_ClientCancelStopsRetries(t *testing.T) {
	old := retryBase
	retryBase = 200 * time.Millisecond
	defer func() { retryBase = old }()
	eng := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(503) }))
	defer eng.Close()
	t.Setenv("DATA_ENGINE_URL", eng.URL)
	r := gin.New()
	withUser(r)
	r.POST("/risk/portfolio", proxyToDataEngine("/risk/portfolio"))
	req := httptest.NewRequest("POST", "/risk/portfolio", nil)
	ctx, cancel := contextWithTimeout(50 * time.Millisecond)
	defer cancel()
	req = req.WithContext(ctx)
	start := time.Now()
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if time.Since(start) > 700*time.Millisecond {
		t.Fatalf("retries continued after client went away: %v", time.Since(start))
	}
}

func TestDataEngineURL_NoImplicitPublicDefaultInProduction(t *testing.T) {
	t.Setenv("DATA_ENGINE_URL", "")
	t.Setenv("ENV", "production")
	if u := getDataEngineURL(); u != "" {
		t.Fatalf("production must not default the engine URL, got %q", u)
	}
	t.Setenv("ENV", "development")
	if getDataEngineURL() == "" {
		t.Fatal("dev default expected")
	}
}

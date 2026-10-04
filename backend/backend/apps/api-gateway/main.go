// backend/apps/api-gateway/main.go
// Prexus Intelligence — API Gateway (RBAC integrated) v2.2
//
// v2.2 (audit fixes): /apply wired; /alerts, /openai, /gemini served; startup
// config validation (fail-closed in production); DB init retry; /ready probe;
// buildRouter() extracted so routing is testable; per-route strict limiter and
// per-user AI quota.

package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"github.com/joho/godotenv"
	"golang.org/x/time/rate"
)

const VERSION = "2.2.0"

// ── Per-IP rate limiting ──────────────────────────────────────────────────────

type ipLimiter struct {
	limiter  *rate.Limiter
	lastSeen time.Time
}

var (
	limiters   = make(map[string]*ipLimiter)
	limitersMu sync.Mutex
)

// getLimiter: global default — 5 req/s sustained, burst 10, per client IP.
func getLimiter(ip string) *rate.Limiter {
	limitersMu.Lock()
	defer limitersMu.Unlock()
	if il, ok := limiters[ip]; ok {
		il.lastSeen = time.Now()
		return il.limiter
	}
	l := rate.NewLimiter(5, 10)
	limiters[ip] = &ipLimiter{limiter: l, lastSeen: time.Now()}
	return l
}

func cleanupLimiters(ctx context.Context) {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			limitersMu.Lock()
			for ip, il := range limiters {
				if time.Since(il.lastSeen) > 10*time.Minute {
					delete(limiters, ip)
				}
			}
			limitersMu.Unlock()
		}
	}
}

func RateLimitMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		if !getLimiter(c.ClientIP()).Allow() {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{"error": "rate limit exceeded — slow down"})
			return
		}
		c.Next()
	}
}

// limiterSet is an independent, stricter limiter for public write endpoints.
type limiterSet struct {
	mu sync.Mutex
	m  map[string]*ipLimiter
	r  rate.Limit
	b  int
}

func newLimiterSet(r rate.Limit, b int) *limiterSet {
	return &limiterSet{m: map[string]*ipLimiter{}, r: r, b: b}
}

func (s *limiterSet) allow(ip string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now()
	if len(s.m) > 5000 {
		for k, v := range s.m {
			if now.Sub(v.lastSeen) > 30*time.Minute {
				delete(s.m, k)
			}
		}
	}
	il, ok := s.m[ip]
	if !ok {
		il = &ipLimiter{limiter: rate.NewLimiter(s.r, s.b)}
		s.m[ip] = il
	}
	il.lastSeen = now
	return il.limiter.Allow()
}

func (s *limiterSet) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		if !s.allow(c.ClientIP()) {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{"error": "too many requests — please try again later"})
			return
		}
		c.Next()
	}
}

const maxBodyBytes = 1 << 20

func BodySizeMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, maxBodyBytes)
		c.Next()
	}
}

// ── Config validation (fail closed in production) ─────────────────────────────

// isPlaceholderSecret catches the values shipped in .env.example.
func isPlaceholderSecret(v string) bool {
	l := strings.ToLower(v)
	return strings.Contains(l, "change-this") || strings.Contains(l, "change-in-production") || strings.Contains(l, "changeme")
}

func validateConfig(env string) (fatal, warn []string) {
	prod := env == "production"
	if prod {
		for _, k := range []string{"JWT_SECRET", "ENGINE_SECRET"} {
			if isPlaceholderSecret(os.Getenv(k)) {
				fatal = append(fatal, k+" is still the placeholder from .env.example")
			}
		}
	}
	if s := os.Getenv("JWT_SECRET"); s == "" {
		fatal = append(fatal, "JWT_SECRET is not set")
	} else if len(s) < 32 {
		if prod {
			fatal = append(fatal, "JWT_SECRET must be at least 32 characters")
		} else {
			warn = append(warn, "JWT_SECRET is shorter than 32 characters")
		}
	}
	if prod {
		if os.Getenv("DATABASE_URL") == "" && os.Getenv("DB_HOST") == "" {
			fatal = append(fatal, "DATABASE_URL (or DB_HOST) is not set")
		}
		if os.Getenv("ENGINE_SECRET") == "" {
			fatal = append(fatal, "ENGINE_SECRET is not set — the data engine would be reachable without authentication")
		}
		if os.Getenv("DATA_ENGINE_URL") == "" {
			fatal = append(fatal, "DATA_ENGINE_URL is not set")
		}
		if os.Getenv("ALLOWED_ORIGINS") == "" {
			fatal = append(fatal, "ALLOWED_ORIGINS is not set")
		}
		if os.Getenv("TRUSTED_PROXIES") == "" {
			warn = append(warn, "TRUSTED_PROXIES is unset behind a proxy — every client will share one rate-limit bucket")
		}
	}
	if !smtpConfigured() {
		warn = append(warn, "SMTP_* / NOTIFY_EMAILS not fully set — applications are stored but not emailed")
	}
	return
}

// ── Router ────────────────────────────────────────────────────────────────────

var applyLimiter = newLimiterSet(rate.Every(2*time.Minute), 3)

func buildRouter() *gin.Engine {
	allowedOrigins := getAllowedOrigins()
	r := gin.New()
	r.Use(gin.Recovery(), RequestID(), BodySizeMiddleware(), requestLogger())

	if tp := os.Getenv("TRUSTED_PROXIES"); tp != "" {
		if err := r.SetTrustedProxies(strings.Split(tp, ",")); err != nil {
			log.Fatalf("Invalid TRUSTED_PROXIES: %v", err)
		}
		log.Printf("✓ Trusted proxies: %s", tp)
	} else {
		_ = r.SetTrustedProxies(nil)
		log.Printf("✓ Trusted proxies: none (direct connections only)")
	}

	r.Use(cors.New(cors.Config{
		AllowOrigins:     allowedOrigins,
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Content-Type", "Authorization"},
		ExposeHeaders:    []string{"Content-Length", "X-Request-ID"},
		AllowCredentials: false,
		MaxAge:           12 * time.Hour,
	}))

	r.GET("/", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"service": "prexus-api-gateway", "status": "ok", "version": VERSION,
			"health": "/health", "ready": "/ready"})
	})
	r.GET("/health", RateLimitMiddleware(), handleHealth) // liveness
	r.GET("/ready", RateLimitMiddleware(), handleReady)   // readiness (DB)
	r.POST("/register", RateLimitMiddleware(), handleRegister)
	r.POST("/login", RateLimitMiddleware(), handleLogin)
	r.POST("/apply", applyLimiter.Middleware(), handleApply)

	quota := AIQuotaMiddleware(newQuotaStore(aiDailyQuota()))

	auth := r.Group("/", AuthMiddleware())
	{
		auth.GET("/assets", RequirePermission("assets:read"), handleGetAssets)
		auth.POST("/assets", RequirePermission("assets:create"), handleCreateAsset)
		auth.PUT("/assets/:id", RequirePermission("assets:update"), handleUpdateAsset)
		auth.DELETE("/assets/:id", RequirePermission("assets:delete"), handleDeleteAsset)
		auth.GET("/alerts", RequirePermission("assets:read"), handleAlerts)

		auth.POST("/risk/asset", RequirePermission("risk:run"), proxyToDataEngine("/risk/asset"))
		auth.POST("/risk/portfolio", RequirePermission("risk:run"), proxyToDataEngine("/risk/portfolio"))
		auth.POST("/risk/stress-test", RequirePermission("risk:run"), proxyToDataEngine("/risk/stress-test"))
		auth.POST("/risk/simulate", RequirePermission("risk:run"), proxyToDataEngine("/risk/simulate"))
		auth.GET("/risk/health", RequirePermission("risk:run"), proxyToDataEngineGET("/risk/health"))
		auth.GET("/sources", RequirePermission("risk:run"), proxyToDataEngineGET("/sources"))
		auth.GET("/lake/stats", RequirePermission("risk:run"), proxyToDataEngineGET("/lake/stats"))
		auth.GET("/lake/files", RequirePermission("risk:run"), proxyToDataEngineGET("/lake/files"))

		auth.POST("/chat", RateLimitMiddleware(), RequirePermission("risk:run"), quota, proxyToDataEngine("/chat"))
		auth.POST("/analyze", RateLimitMiddleware(), RequirePermission("risk:run"), quota, proxyToDataEngine("/analyze"))
		auth.POST("/claude", RateLimitMiddleware(), RequirePermission("risk:run"), quota, handleClaude)
		auth.POST("/openai", RateLimitMiddleware(), RequirePermission("risk:run"), quota, handleLegacyAI("openai"))
		auth.POST("/gemini", RateLimitMiddleware(), RequirePermission("risk:run"), quota, handleLegacyAI("gemini"))

		auth.GET("/conduit/tools", RequirePermission("conduit:read"), handleConduitTools)
		auth.GET("/me", handleGetMe)
		auth.PUT("/me", handleUpdateMe)
	}
	return r
}

func main() {
	_ = godotenv.Load()
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	env := os.Getenv("ENV")
	if env == "production" {
		gin.SetMode(gin.ReleaseMode)
	}

	fatal, warn := validateConfig(env)
	for _, w := range warn {
		log.Printf("⚠️  config: %s", w)
	}
	if len(fatal) > 0 {
		for _, f := range fatal {
			log.Printf("✗ config: %s", f)
		}
		log.Fatal("refusing to start: invalid configuration")
	}

	dataEngineURL := getDataEngineURL()
	if dataEngineURL == "" {
		log.Fatal("DATA_ENGINE_URL is not set — cannot start")
	}
	if err := InitDBWithRetry(8, 2*time.Second); err != nil {
		log.Fatalf("Database init failed: %v", err)
	}
	defer CloseDB()
	log.Printf("✓ Data engine: %s", dataEngineURL)
	initConduit()
	if prexusConduit != nil {
		log.Printf("✓ Conduit MCP integration configured")
	} else {
		log.Printf("• Conduit MCP integration not configured (optional)")
	}
	log.Printf("✓ CORS origins: %v", getAllowedOrigins())

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()
	go cleanupLimiters(ctx)

	r := buildRouter()
	log.Printf("🚀 Prexus API Gateway v%s running on :%s (env=%s)", VERSION, port, env)
	srv := &http.Server{
		Addr: ":" + port, Handler: r,
		ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 30 * time.Second,
		WriteTimeout: 90 * time.Second, IdleTimeout: 120 * time.Second,
	}
	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Server error: %v", err)
		}
	}()
	<-ctx.Done()
	log.Println("Shutting down gracefully…")
	shutCtx, shutCancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer shutCancel()
	if err := srv.Shutdown(shutCtx); err != nil {
		log.Printf("Graceful shutdown error: %v", err)
	}
	log.Println("Server stopped.")
}

func handleHealth(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "prexus-api-gateway", "version": VERSION,
		"timestamp": time.Now().UTC().Format(time.RFC3339)})
}

func handleReady(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	if err := DBReady(ctx); err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"status": "not_ready", "db": "down"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "ready", "db": "ok"})
}

func requestLogger() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		userID, exists := c.Get("user_id")
		if !exists {
			userID = "anonymous"
		}
		reqID, _ := c.Get("request_id")
		log.Printf("[%d] %s %s req=%v user=%v ip=%s latency=%v", c.Writer.Status(), c.Request.Method,
			c.Request.URL.Path, reqID, userID, c.ClientIP(), time.Since(start))
	}
}

func getAllowedOrigins() []string {
	raw := os.Getenv("ALLOWED_ORIGINS")
	if raw == "" {
		log.Println("⚠️  ALLOWED_ORIGINS not set — defaulting to localhost (dev only)")
		return []string{"http://localhost:3000", "http://localhost:5173"}
	}
	origins := []string{}
	for _, o := range strings.Split(raw, ",") {
		if o = strings.TrimSpace(o); o != "" {
			origins = append(origins, o)
		}
	}
	return origins
}

func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		id := fmt.Sprintf("%d", time.Now().UnixNano())
		c.Set("request_id", id)
		c.Writer.Header().Set("X-Request-ID", id)
		c.Next()
	}
}

func init() {
	if os.Getenv("ENV") == "production" {
		return
	}
	fmt.Printf(`
╔══════════════════════════════════════════╗
║   PREXUS INTELLIGENCE — API GATEWAY     ║
║   Version %-30s ║
╚══════════════════════════════════════════╝
`, VERSION)
}

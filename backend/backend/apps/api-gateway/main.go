// backend/apps/api-gateway/main.go
// Prexus Intelligence — API Gateway
// Go service: JWT auth, user management, asset CRUD, AI proxy routing.
// Proxies risk computation requests to the Python data engine.

package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"github.com/joho/godotenv"
)

const VERSION = "2.0.0"

func main() {
	// Load .env if present (local dev)
	_ = godotenv.Load()

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	env := os.Getenv("ENV")
	if env == "production" {
		gin.SetMode(gin.ReleaseMode)
	}

	// ── Database ───────────────────────────────────────────────────────────
	if err := InitDB(); err != nil {
		log.Fatalf("Database init failed: %v", err)
	}
	defer CloseDB()

	log.Printf("✓ Database connected")
	log.Printf("✓ Rust engine proxy: %s", getDataEngineURL())

	// ── Router ─────────────────────────────────────────────────────────────
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(requestLogger())

	// CORS — allow Meteorium frontend
	r.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"*"},
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Content-Type", "Authorization"},
		ExposeHeaders:    []string{"Content-Length"},
		AllowCredentials: true,
		MaxAge:           12 * time.Hour,
	}))

	// ── Public routes ───────────────────────────────────────────────────────
	r.GET("/health",    handleHealth)
	r.POST("/register", handleRegister)
	r.POST("/login",    handleLogin)

	// ── Protected routes ────────────────────────────────────────────────────
	auth := r.Group("/", AuthMiddleware())
	{
		// Assets
		auth.GET("/assets",          handleGetAssets)
		auth.POST("/assets",         handleCreateAsset)
		auth.PUT("/assets/:id",      handleUpdateAsset)
		auth.DELETE("/assets/:id",   handleDeleteAsset)

		// Risk — proxied to Python data engine
		auth.POST("/risk/asset",       proxyToDataEngine("/risk/asset"))
		auth.POST("/risk/portfolio",   proxyToDataEngine("/risk/portfolio"))
		auth.POST("/risk/stress-test", proxyToDataEngine("/risk/stress-test"))
		auth.GET("/risk/health",       proxyToDataEngineGET("/risk/health"))

		// AI — proxied to data engine (which holds API keys server-side)
		auth.POST("/analyze", proxyToDataEngine("/analyze"))
		auth.POST("/chat",    proxyToDataEngine("/chat"))

		// User
		auth.GET("/me",     handleGetMe)
		auth.PUT("/me",     handleUpdateMe)
	}

	log.Printf("🚀 Prexus API Gateway v%s listening on :%s (env=%s)", VERSION, port, env)
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("Server error: %v", err)
	}
}

// ── Health ─────────────────────────────────────────────────────────────────

func handleHealth(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":    "ok",
		"service":   "prexus-api-gateway",
		"version":   VERSION,
		"timestamp": time.Now().UTC().Format(time.RFC3339),
	})
}

// ── Request logger ─────────────────────────────────────────────────────────

func requestLogger() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		latency := time.Since(start)
		log.Printf("[%d] %s %s %v",
			c.Writer.Status(), c.Request.Method, c.Request.URL.Path, latency)
	}
}


// Print startup banner
func init() {
	fmt.Printf(`
╔══════════════════════════════════════════╗
║   PREXUS INTELLIGENCE — API GATEWAY     ║
║   Version %-30s ║
╚══════════════════════════════════════════╝
`, VERSION)
}


package main

import (
	"context"
	"net/http"
	"os"
	"time"

	conduit "github.com/devXyi/prexus-intelligence/backend/integrations/conduit"
	"github.com/gin-gonic/gin"
)

var prexusConduit *conduit.Client

func initConduit() {
	if os.Getenv("CONDUIT_CLIENT_ID") == "" || os.Getenv("CONDUIT_CLIENT_SECRET") == "" {
		return
	}
	cfg, err := conduit.LoadConfig()
	if err != nil {
		return
	}
	prexusConduit = conduit.NewClient(cfg)
}

// handleConduitTools is intentionally read-only. It proves the external
// Conduit integration without moving any Prexus risk traffic onto it yet.
func handleConduitTools(c *gin.Context) {
	if prexusConduit == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "Conduit integration is not configured"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 20*time.Second)
	defer cancel()

	if _, err := prexusConduit.Initialize(ctx); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "Conduit initialization failed"})
		return
	}
	if err := prexusConduit.Initialized(ctx); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "Conduit session initialization failed"})
		return
	}
	tools, err := prexusConduit.ListTools(ctx)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "Conduit tools/list failed"})
		return
	}

	c.Data(http.StatusOK, "application/json", tools)
}

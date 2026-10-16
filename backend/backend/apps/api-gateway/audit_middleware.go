package main

import (
	"log"
	"os"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/devXyi/prexus-intelligence/backend/auditledger"
)

// gatewayAuditLedger is initialized once at startup and closed during graceful shutdown.
// The ledger serializes appends and fails closed after any persistence/integrity error.
var gatewayAuditLedger *auditledger.Ledger

// AuditMiddleware records an intent before the protected handler runs and records
// the outcome afterward. It deliberately excludes bodies, query strings, credentials,
// and provider payloads from audit metadata.
func AuditMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		ledger := gatewayAuditLedger
		if ledger == nil {
			if os.Getenv("ENV") == "production" {
				c.AbortWithStatusJSON(503, gin.H{"error": "audit ledger unavailable"})
				return
			}
			c.Next()
			return
		}

		actor := c.GetString("user_id")
		if actor == "" {
			actor = "unknown"
		}
		resource := c.Request.URL.Path
		method := c.Request.Method
		requestID := c.GetString("request_id")
		started := time.Now()
		_, err := ledger.Append(actor, "http.request.started", resource, map[string]any{
			"method": method, "request_id": requestID,
		})
		if err != nil {
			log.Printf("audit ledger refused request: action=start resource=%s error=%v", resource, err)
			c.AbortWithStatusJSON(503, gin.H{"error": "audit ledger unavailable; request not executed"})
			return
		}

		c.Next()

		_, err = ledger.Append(actor, "http.request.completed", resource, map[string]any{
			"method": method, "request_id": requestID,
			"status": c.Writer.Status(), "duration_ms": time.Since(started).Milliseconds(),
		})
		if err != nil {
			// The start event remains durable. The ledger poisons itself after a failed
			// append, so subsequent requests are blocked before their handlers execute.
			log.Printf("audit ledger failed to persist request outcome: action=complete resource=%s status=%d error=%v",
				resource, c.Writer.Status(), err)
		}
	}
}

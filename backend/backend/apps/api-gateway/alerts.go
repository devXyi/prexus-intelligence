// backend/apps/api-gateway/alerts.go
// GET /alerts — the Meteorium UI calls this on load; v1 had no such route so the
// alerts panel was always empty. Alerts are DERIVED from the caller's stored
// asset scores (no invented data): severity thresholds on composite risk.

package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

const (
	alertElevated = 0.60
	alertHigh     = 0.70
	alertCritical = 0.80
)

func severityFor(cr float64) string {
	switch {
	case cr >= alertCritical:
		return "CRITICAL"
	case cr >= alertHigh:
		return "HIGH"
	case cr >= alertElevated:
		return "ELEVATED"
	}
	return ""
}

func handleAlerts(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(c.Request.Context(), dbTimeout)
	defer cancel()
	rows, err := DB.QueryContext(ctx,
		`SELECT id,name,pr,tr,cr,updated_at FROM assets WHERE user_id=$1 AND cr >= $2 ORDER BY cr DESC LIMIT 100`,
		userID, alertElevated)
	if err != nil {
		log.Printf("DB error (alerts): %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Database error"})
		return
	}
	defer rows.Close()
	out := make([]gin.H, 0)
	for rows.Next() {
		var id, name string
		var pr, tr, cr float64
		var ts time.Time
		if err := rows.Scan(&id, &name, &pr, &tr, &cr, &ts); err != nil {
			log.Printf("alerts scan: %v", err)
			continue
		}
		typ := "PHYSICAL"
		if tr > pr {
			typ = "TRANSITION"
		}
		out = append(out, gin.H{
			"id": "ALR-" + id, "asset_id": id, "asset_name": name,
			"severity": severityFor(cr), "risk_type": typ, "risk_score": cr,
			"message":   fmt.Sprintf("Composite risk %.2f (physical %.2f, transition %.2f) on %s", cr, pr, tr, strings.TrimSpace(name)),
			"source":    "derived:asset-scores",
			"timestamp": ts.UTC().Format(time.RFC3339),
		})
	}
	if err := rows.Err(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Database error"})
		return
	}
	c.JSON(http.StatusOK, out)
}

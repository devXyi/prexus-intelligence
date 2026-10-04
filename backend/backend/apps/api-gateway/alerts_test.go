package main

import (
	"encoding/json"
	"testing"
	"time"

	"database/sql/driver"
	"github.com/gin-gonic/gin"
	"strings"
)

func TestSeverityFor(t *testing.T) {
	cases := map[float64]string{0.10: "", 0.59: "", 0.60: "ELEVATED", 0.70: "HIGH", 0.79: "HIGH", 0.80: "CRITICAL", 1.0: "CRITICAL"}
	for cr, want := range cases {
		if got := severityFor(cr); got != want {
			t.Errorf("severityFor(%.2f)=%q want %q", cr, got, want)
		}
	}
}

func TestAlerts_DerivedFromCallersAssetsOnly(t *testing.T) {
	f := newFakeDB(t)
	f.QueryCols = []string{"id", "name", "pr", "tr", "cr", "updated_at"}
	f.QueryRows = [][]driver.Value{
		{"AST-1", "Port A", 0.9, 0.2, 0.85, time.Now()},
		{"AST-2", "Grid B", 0.3, 0.7, 0.65, time.Now()},
	}
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("user_id", "u1"); c.Next() })
	r.GET("/alerts", handleAlerts)
	w := doJSON(r, "GET", "/alerts", nil, nil)
	if w.Code != 200 {
		t.Fatalf("%d %s", w.Code, w.Body.String())
	}
	var out []map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &out)
	if len(out) != 2 || out[0]["severity"] != "CRITICAL" || out[1]["risk_type"] != "TRANSITION" {
		t.Fatalf("unexpected alerts: %v", out)
	}
	if len(f.Queries) != 1 || !strings.Contains(f.Queries[0].query, "FROM assets WHERE user_id=$1 AND cr >= $2") {
		t.Fatalf("query must be scoped to the caller: %+v", f.Queries)
	}
	if f.Queries[0].args[0] != "u1" || f.Queries[0].args[1] != alertElevated {
		t.Fatalf("args: %v", f.Queries[0].args)
	}
}

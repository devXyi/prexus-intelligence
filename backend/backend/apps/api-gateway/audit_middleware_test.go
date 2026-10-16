package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/x509"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/devXyi/prexus-intelligence/backend/auditledger"
)

func TestAuditMiddlewareRecordsRequestWithoutQuerySecrets(t *testing.T) {
	oldLedger, oldEnv := gatewayAuditLedger, os.Getenv("ENV")
	t.Cleanup(func() {
		if gatewayAuditLedger != nil && gatewayAuditLedger != oldLedger { _ = gatewayAuditLedger.Close() }
		gatewayAuditLedger = oldLedger
		_ = os.Setenv("ENV", oldEnv)
	})
	_ = os.Setenv("ENV", "test")

	_, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil { t.Fatal(err) }
	der, err := x509.MarshalPKCS8PrivateKey(privateKey)
	if err != nil { t.Fatal(err) }
	dir := t.TempDir()
	keyPath := filepath.Join(dir, "ledger-key.pem")
	if err := os.WriteFile(keyPath, pem.EncodeToMemory(&pem.Block{Type:"PRIVATE KEY",Bytes:der}), 0600); err != nil { t.Fatal(err) }
	ledger, err := auditledger.Open(filepath.Join(dir,"ledger"), keyPath)
	if err != nil { t.Fatal(err) }
	gatewayAuditLedger = ledger

	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(RequestID(), func(c *gin.Context) { c.Set("user_id","operator-test"); c.Next() }, AuditMiddleware())
	r.GET("/risk/asset", func(c *gin.Context) { c.Status(http.StatusNoContent) })
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/risk/asset?token=do-not-log", nil)
	r.ServeHTTP(rec, req)
	if rec.Code != http.StatusNoContent { t.Fatalf("status = %d, want %d", rec.Code, http.StatusNoContent) }

	result := ledger.Verify()
	if !result.Valid || result.HeadSequence != 2 { t.Fatalf("audit chain invalid: %+v", result) }
	raw, err := os.ReadFile(filepath.Join(dir,"ledger","ledger.ndjson"))
	if err != nil { t.Fatal(err) }
	text := string(raw)
	if strings.Contains(text,"do-not-log") || strings.Contains(text,"token") { t.Fatal("query secrets must not be written to audit metadata") }
	if !strings.Contains(text,"http.request.started") || !strings.Contains(text,"http.request.completed") { t.Fatal("expected both start and completion events") }
}

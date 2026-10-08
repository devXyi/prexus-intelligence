package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"
)

func init() { gin.SetMode(gin.TestMode) }

// newTestRouter builds the real router with permissive per-IP limiters.
func newTestRouter(t *testing.T) *gin.Engine {
	t.Helper()
	t.Setenv("ALLOWED_ORIGINS", "http://localhost:3000")
	t.Setenv("JWT_SECRET", strings.Repeat("k", 40))
	applyLimiter = newLimiterSet(rate.Every(time.Millisecond), 1000)
	limitersMu.Lock()
	limiters = map[string]*ipLimiter{}
	limitersMu.Unlock()
	return buildRouter()
}

func doJSON(r http.Handler, method, path string, body any, hdr map[string]string) *httptest.ResponseRecorder {
	var rdr *bytes.Reader
	if body == nil {
		rdr = bytes.NewReader(nil)
	} else if b, ok := body.([]byte); ok {
		rdr = bytes.NewReader(b)
	} else {
		b, _ := json.Marshal(body)
		rdr = bytes.NewReader(b)
	}
	req := httptest.NewRequest(method, path, rdr)
	req.Header.Set("Content-Type", "application/json")
	for k, v := range hdr {
		req.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

// repoRoot walks up from this file (symlink-resolved) to the directory that
// contains both frontend/ and backend/.
func repoRoot(t *testing.T) string {
	t.Helper()
	_, file, _, _ := runtime.Caller(0)
	dir, err := filepath.EvalSymlinks(filepath.Dir(file))
	if err != nil {
		t.Skipf("cannot resolve source dir: %v", err)
	}
	for i := 0; i < 8; i++ {
		if st, e := os.Stat(filepath.Join(dir, "frontend")); e == nil && st.IsDir() {
			if st2, e2 := os.Stat(filepath.Join(dir, "backend")); e2 == nil && st2.IsDir() {
				return dir
			}
		}
		dir = filepath.Dir(dir)
	}
	t.Skip("repo root with frontend/ not found (backend vendored separately?)")
	return ""
}

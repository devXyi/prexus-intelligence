package main

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

func TestValidateConfig_ProductionFailsClosed(t *testing.T) {
	for _, k := range []string{"JWT_SECRET", "DATABASE_URL", "DB_HOST", "ENGINE_SECRET", "DATA_ENGINE_URL", "ALLOWED_ORIGINS", "TRUSTED_PROXIES"} {
		t.Setenv(k, "")
	}
	fatal, _ := validateConfig("production")
	joined := strings.Join(fatal, "|")
	for _, want := range []string{"JWT_SECRET", "ENGINE_SECRET", "DATABASE_URL", "DATA_ENGINE_URL", "ALLOWED_ORIGINS"} {
		if !strings.Contains(joined, want) {
			t.Errorf("production must reject missing %s", want)
		}
	}
	t.Setenv("JWT_SECRET", strings.Repeat("s", 40))
	t.Setenv("DATABASE_URL", "postgres://x")
	t.Setenv("ENGINE_SECRET", "e")
	t.Setenv("DATA_ENGINE_URL", "http://engine.internal")
	t.Setenv("ALLOWED_ORIGINS", "https://prexus.in")
	if fatal, _ := validateConfig("production"); len(fatal) != 0 {
		t.Errorf("complete config rejected: %v", fatal)
	}
	t.Setenv("JWT_SECRET", "short")
	if fatal, _ := validateConfig("production"); len(fatal) == 0 {
		t.Error("short JWT secret accepted in production")
	}
	if fatal, _ := validateConfig("development"); len(fatal) != 0 {
		t.Errorf("dev should only warn about short secret: %v", fatal)
	}
}

func TestReadyProbe(t *testing.T) {
	r := newTestRouter(t)
	DB = nil
	if w := doJSON(r, "GET", "/ready", nil, nil); w.Code != 503 {
		t.Fatalf("no DB → want 503 got %d", w.Code)
	}
	newFakeDB(t)
	if w := doJSON(r, "GET", "/ready", nil, nil); w.Code != 200 {
		t.Fatalf("db ok → want 200 got %d", w.Code)
	}
	if w := doJSON(r, "GET", "/health", nil, nil); w.Code != 200 {
		t.Fatalf("liveness must not depend on DB: %d", w.Code)
	}
}

func TestProtectedRoutesRequireAuth(t *testing.T) {
	r := newTestRouter(t)
	for _, p := range [][2]string{{"GET", "/alerts"}, {"GET", "/assets"}, {"POST", "/claude"}, {"POST", "/openai"}, {"POST", "/gemini"}, {"POST", "/chat"}, {"POST", "/analyze"}, {"POST", "/risk/asset"}} {
		if w := doJSON(r, p[0], p[1], map[string]any{}, nil); w.Code != 401 {
			t.Errorf("%s %s without token → %d (want 401)", p[0], p[1], w.Code)
		}
	}
}

// ── Frontend ↔ gateway contract ──────────────────────────────────────────────
// Regression guard for the P0 found in the audit: pricing.html POSTed /apply,
// the handler existed, but no route was registered (every application 404'd).

var feEndpointRes = []*regexp.Regexp{
	regexp.MustCompile("(?:API_BASE|API|getBase\\(\\))\\s*\\+\\s*['\"`](/[A-Za-z][A-Za-z0-9_\\-/]*)"),
	regexp.MustCompile("(?:request|apiGet|apiPost|apiPut|apiDelete)\\(\\s*['\"`](/[A-Za-z][A-Za-z0-9_\\-/]*)"),
	regexp.MustCompile("endpoint:\\s*['\"](/[A-Za-z][A-Za-z0-9_\\-/]*)['\"]"),
}

func TestFrontendEndpointsAreAllRouted(t *testing.T) {
	root := repoRoot(t)
	registered := map[string]bool{}
	for _, rt := range newTestRouter(t).Routes() {
		registered[strings.TrimRight(rt.Path, "/")] = true
		registered[strings.TrimSuffix(strings.TrimSuffix(rt.Path, "/:id"), "/")] = true
	}
	used := map[string][]string{}
	_ = filepath.Walk(filepath.Join(root, "frontend"), func(p string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() || !(strings.HasSuffix(p, ".html") || strings.HasSuffix(p, ".js")) {
			return nil
		}
		b, _ := os.ReadFile(p)
		for _, re := range feEndpointRes {
			for _, m := range re.FindAllStringSubmatch(string(b), -1) {
				ep := strings.TrimRight(m[1], "/")
				used[ep] = append(used[ep], filepath.Base(p))
			}
		}
		return nil
	})
	if len(used) < 4 {
		t.Fatalf("contract scan found only %d endpoints — regexes rotted?", len(used))
	}
	var missing []string
	for ep, files := range used {
		if !registered[ep] {
			missing = append(missing, ep+" ("+strings.Join(files, ",")+")")
		}
	}
	sort.Strings(missing)
	if len(missing) > 0 {
		t.Fatalf("frontend calls endpoints with no gateway route: %v", missing)
	}
}

func TestValidateConfig_RejectsExamplePlaceholders(t *testing.T) {
	t.Setenv("JWT_SECRET", "change-this-to-a-long-random-string-in-production")
	t.Setenv("ENGINE_SECRET", "dev-engine-secret-change-in-production")
	t.Setenv("DATABASE_URL", "postgres://x")
	t.Setenv("DATA_ENGINE_URL", "engine:10000")
	t.Setenv("ALLOWED_ORIGINS", "https://prexus.in")
	fatal, _ := validateConfig("production")
	joined := strings.Join(fatal, "|")
	if !strings.Contains(joined, "JWT_SECRET is still the placeholder") || !strings.Contains(joined, "ENGINE_SECRET is still the placeholder") {
		t.Fatalf("placeholders accepted in production: %v", fatal)
	}
}

func TestEngineURL_AddsSchemeToRenderHostport(t *testing.T) {
	t.Setenv("DATA_ENGINE_URL", "meteorium-engine:10000")
	if got := getDataEngineURL(); got != "http://meteorium-engine:10000" {
		t.Fatalf("got %q", got)
	}
	t.Setenv("DATA_ENGINE_URL", "https://engine.internal/")
	if got := getDataEngineURL(); got != "https://engine.internal" {
		t.Fatalf("got %q", got)
	}
}

package main

import (
	"database/sql/driver"
	"encoding/json"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func adminRouter(role string) *gin.Engine {
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("role", role); c.Set("user_id", "u-1"); c.Next() })
	r.GET("/admin/applications", RequirePermission("applications:read"), handleListApplications)
	r.GET("/admin/applications/:ref", RequirePermission("applications:read"), handleGetApplication)
	return r
}

func appRow(ref string) []driver.Value {
	return []driver.Value{ref, "meteorium", "Institutional", "cloud", "Asha Rao", "Director", "asha@example.org", "DST CoE", "India", "Government", "Flood pilot — ünïcode ✓", true, "", time.Now()}
}

func TestAdmin_OnlyAdminsCanReadApplications(t *testing.T) {
	f := newFakeDB(t)
	f.QueryCols = []string{"ref", "module", "plan", "deployment", "name", "title", "email", "org", "country", "org_type", "use_case", "notified", "notify_error", "created_at"}
	f.QueryRows = [][]driver.Value{appRow("PRX-MET-0A1B2C3D")}
	for role, want := range map[string]int{"admin": 200, "user": 403, "viewer": 403, "nonsense": 403} {
		w := doJSON(adminRouter(role), "GET", "/admin/applications", nil, nil)
		if w.Code != want { t.Errorf("role %q: want %d got %d", role, want, w.Code) }
	}
	var out struct { Applications []map[string]any `json:"applications"` }
	w := doJSON(adminRouter("admin"), "GET", "/admin/applications", nil, nil)
	_ = json.Unmarshal(w.Body.Bytes(), &out)
	if len(out.Applications) != 1 || out.Applications[0]["ref"] != "PRX-MET-0A1B2C3D" || out.Applications[0]["use_case"] != "Flood pilot — ünïcode ✓" || out.Applications[0]["email"] != "asha@example.org" {
		t.Fatalf("applicant details must be readable by admins: %v", out.Applications)
	}
}

func TestAdmin_PaginationIsClamped(t *testing.T) {
	f := newFakeDB(t)
	f.QueryCols = []string{"ref", "module", "plan", "deployment", "name", "title", "email", "org", "country", "org_type", "use_case", "notified", "notify_error", "created_at"}
	for q, want := range map[string][2]int64{"": {50, 0}, "?limit=99999&offset=-5": {200, 0}, "?limit=abc&offset=xyz": {50, 0}, "?limit=0": {1, 0}, "?limit=10&offset=30": {10, 30}} {
		f.Queries = nil
		w := doJSON(adminRouter("admin"), "GET", "/admin/applications"+q, nil, nil)
		if w.Code != 200 { t.Fatalf("%q: %d", q, w.Code) }
		if len(f.Queries) != 1 || f.Queries[0].args[0] != want[0] || f.Queries[0].args[1] != want[1] {
			t.Errorf("%q: LIMIT/OFFSET args %v, want %v", q, f.Queries, want)
		}
	}
}

func TestAdmin_GetApplication_ValidatesRefBeforeTouchingTheDatabase(t *testing.T) {
	f := newFakeDB(t)
	for _, bad := range []string{"PRX-XXX-ZZZZZZZZ", "prx-met-0a1b2c3d", "PRX-MET-0A1B2C3", "PRX-MET-0A1B2C3D%27%20OR%201=1", "..%2Fetc%2Fpasswd", "PRX-ME-0A1B2C3D"} {
		if w := doJSON(adminRouter("admin"), "GET", "/admin/applications/"+bad, nil, nil); w.Code != 400 && w.Code != 404 {
			t.Errorf("%q → %d, want 400/404", bad, w.Code)
		}
	}
	if len(f.Queries) != 0 { t.Fatalf("invalid references reached SQL: %v", f.Queries) }
	if w := doJSON(adminRouter("admin"), "GET", "/admin/applications/PRX-MET-0A1B2C3D", nil, nil); w.Code != 404 {
		t.Errorf("well-formed but unknown ref → %d", w.Code)
	}
	if w := doJSON(adminRouter("user"), "GET", "/admin/applications/PRX-MET-0A1B2C3D", nil, nil); w.Code != 403 {
		t.Errorf("non-admin → %d", w.Code)
	}
}

func TestAdmin_RoutesRegisteredOnTheRealRouter_AndRequireAuth(t *testing.T) {
	r := newTestRouter(t)
	have := map[string]bool{}
	for _, rt := range r.Routes() { have[rt.Method+" "+rt.Path] = true }
	for _, want := range []string{"GET /admin/applications", "GET /admin/applications/:ref"} {
		if !have[want] { t.Errorf("route %s not registered", want) }
	}
	for _, p := range []string{"/admin/applications", "/admin/applications/PRX-MET-0A1B2C3D"} {
		if w := doJSON(r, "GET", p, nil, nil); w.Code != 401 { t.Errorf("%s without a token → %d, want 401", p, w.Code) }
	}
	for _, role := range []string{"user", "viewer"} {
		for _, perm := range rolePermissions[role] {
			if perm == "applications:read" { t.Errorf("role %s must not hold applications:read", role) }
		}
	}
}

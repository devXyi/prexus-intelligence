package main

// Real-PostgreSQL integration tests. They run only when PREXUS_TEST_DATABASE_URL is set.

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"regexp"
	"strings"
	"testing"
	"time"
)

func pgSetup(t *testing.T) {
	t.Helper()
	url := os.Getenv("PREXUS_TEST_DATABASE_URL")
	if url == "" { t.Skip("set PREXUS_TEST_DATABASE_URL to run Postgres integration tests") }
	t.Setenv("DATABASE_URL", url)
	CloseDB()
	if err := InitDB(); err != nil { t.Fatalf("InitDB (real migration) failed: %v", err) }
	t.Cleanup(func() {
		_, _ = DB.Exec(`TRUNCATE applications, assets, users CASCADE`)
		CloseDB()
	})
	if _, err := DB.Exec(`TRUNCATE applications, assets, users CASCADE`); err != nil { t.Fatal(err) }
}

func TestPG_MigrationIsIdempotent(t *testing.T) {
	pgSetup(t)
	for i:=0;i<2;i++ { CloseDB(); if err:=InitDB();err!=nil{t.Fatalf("migration run %d: %v",i+2,err)} }
	var n int
	if err:=DB.QueryRow(`SELECT COUNT(*) FROM information_schema.columns WHERE table_name='applications'`).Scan(&n);err!=nil||n!=15{t.Fatalf("applications table shape: cols=%d err=%v",n,err)}
}

func TestPG_Apply_PersistsEveryField_AndRecordsEmailOutcome(t *testing.T) {
	pgSetup(t)
	r:=newTestRouter(t)
	t.Setenv("SMTP_HOST","smtp.test");t.Setenv("SMTP_USER","u@prexus.in");t.Setenv("SMTP_PASS","x");t.Setenv("NOTIFY_EMAILS","ops@prexus.in")
	var sendErr error
	orig:=sendMail;sendMail=func(ApplyRequest,string)error{return sendErr};defer func(){sendMail=orig}()
	body:=validApply();body["use_case"]="line1\nline2 — ünïcode ✓"
	w:=doJSON(r,"POST","/apply",body,nil);if w.Code!=http.StatusOK{t.Fatalf("%d %s",w.Code,w.Body.String())}
	var out map[string]string;_ = json.Unmarshal(w.Body.Bytes(),&out)
	var module,org,useCase,ip string;var notified bool;deadline:=time.Now().Add(3*time.Second)
	for { err:=DB.QueryRow(`SELECT module,org,use_case,ip,notified FROM applications WHERE ref=$1`,out["ref"]).Scan(&module,&org,&useCase,&ip,&notified);if err!=nil{t.Fatalf("row missing: %v",err)};if notified||time.Now().After(deadline){break};time.Sleep(20*time.Millisecond) }
	if module!="meteorium"||org!="DST CoE"||!strings.Contains(useCase,"ünïcode ✓")||ip==""||!notified{t.Fatalf("stored row wrong: module=%q org=%q use_case=%q ip=%q notified=%v",module,org,useCase,ip,notified)}
	sendErr=errors.New("dial tcp: i/o timeout")
	w=doJSON(r,"POST","/apply",validApply(),nil);_ = json.Unmarshal(w.Body.Bytes(),&out)
	var nerr string;for i:=0;i<150;i++{_ = DB.QueryRow(`SELECT COALESCE(notify_error,'') FROM applications WHERE ref=$1`,out["ref"]).Scan(&nerr);if nerr!=""{break};time.Sleep(20*time.Millisecond)}
	if !strings.Contains(nerr,"i/o timeout"){t.Fatalf("email failure not recorded: %q",nerr)}
	var total int;_ = DB.QueryRow(`SELECT COUNT(*) FROM applications`).Scan(&total);if total!=2{t.Fatalf("both applications must be stored, got %d",total)}
}

func TestPG_Apply_SQLInjectionAttemptIsStoredAsData(t *testing.T) {
	pgSetup(t);t.Setenv("SMTP_HOST","");r:=newTestRouter(t);b:=validApply();b["name"]="x'); DROP TABLE users; --"
	if w:=doJSON(r,"POST","/apply",b,nil);w.Code!=200{t.Fatalf("%d %s",w.Code,w.Body.String())}
	var n int;if err:=DB.QueryRow(`SELECT COUNT(*) FROM users`).Scan(&n);err!=nil{t.Fatalf("users table damaged: %v",err)}
	var name string;_ = DB.QueryRow(`SELECT name FROM applications LIMIT 1`).Scan(&name);if !strings.HasPrefix(name,"x'); DROP TABLE"){t.Fatalf("payload altered: %q",name)}
}

func TestPG_AuthAndAlerts_TenantIsolation(t *testing.T) {
	pgSetup(t);r:=newTestRouter(t)
	token:=func(email string)string{if w:=doJSON(r,"POST","/register",map[string]any{"email":email,"password":"correct-horse-1","full_name":"T"},nil);w.Code>=300{t.Fatalf("register %s: %d %s",email,w.Code,w.Body.String())};w:=doJSON(r,"POST","/login",map[string]any{"email":email,"password":"correct-horse-1"},nil);var a AuthResponse;_ = json.Unmarshal(w.Body.Bytes(),&a);if a.Token==""{t.Fatalf("login %s: %d %s",email,w.Code,w.Body.String())};return a.Token}
	ta,tb:=token("a@example.org"),token("b@example.org");var uidA string;if err:=DB.QueryRow(`SELECT id FROM users WHERE email='a@example.org'`).Scan(&uidA);err!=nil{t.Fatal(err)}
	for _,q:=range []struct{id string;cr,pr,tr float64;name string}{{"AST-1",0.85,0.9,0.2,"Port A"},{"AST-2",0.65,0.3,0.7,"Grid B"},{"AST-3",0.2,0.1,0.1,"Quiet C"}}{if _,err:=DB.Exec(`INSERT INTO assets (id,user_id,name,pr,tr,cr) VALUES ($1,$2,$3,$4,$5,$6)`,q.id,uidA,q.name,q.pr,q.tr,q.cr);err!=nil{t.Fatal(err)}}
	get:=func(tok string)(int,[]map[string]any){w:=doJSON(r,"GET","/alerts",nil,map[string]string{"Authorization":"Bearer "+tok});var out []map[string]any;_ = json.Unmarshal(w.Body.Bytes(),&out);return w.Code,out}
	code,a:=get(ta);if code!=200||len(a)!=2||a[0]["severity"]!="CRITICAL"||a[1]["risk_type"]!="TRANSITION"||a[0]["asset_id"]!="AST-1"{t.Fatalf("A's alerts wrong: %d %v",code,a)}
	if code,b:=get(tb);code!=200||len(b)!=0{t.Fatalf("tenant leak: B sees %v",b)}
	if w:=doJSON(r,"GET","/assets",nil,map[string]string{"Authorization":"Bearer "+tb});strings.Contains(w.Body.String(),"AST-1"){t.Fatal("B can list A's assets")}
	if w:=doJSON(r,"GET","/alerts",nil,nil);w.Code!=401{t.Fatalf("unauthenticated alerts: %d",w.Code)}
	if w:=doJSON(r,"GET","/ready",nil,nil);w.Code!=200{t.Fatalf("/ready with a live database: %d",w.Code)}
}

func TestPG_InitDBWithRetry_RecoversWhenDatabaseComesUp(t *testing.T) {
	url:=os.Getenv("PREXUS_TEST_DATABASE_URL");if url==""{t.Skip("PREXUS_TEST_DATABASE_URL not set")}
	bad:=regexp.MustCompile(`@[^/]+/`).ReplaceAllString(url,"@127.0.0.1:1/")
	t.Setenv("DATABASE_URL",bad);CloseDB();start:=time.Now();err:=InitDBWithRetry(2,10*time.Millisecond)
	if err==nil||time.Since(start)>5*time.Second{t.Fatalf("retry must fail fast on a dead database: err=%v elapsed=%v",err,time.Since(start))}
	t.Setenv("DATABASE_URL",url);if err:=InitDBWithRetry(3,10*time.Millisecond);err!=nil{t.Fatal(fmt.Errorf("recovery: %w",err))};CloseDB()
}

func TestPG_Admin_ReadsStoredApplications_AndRBAC(t *testing.T) {
	pgSetup(t);t.Setenv("SMTP_HOST","");r:=newTestRouter(t)
	for _,e:=range []string{"boss@example.org","peon@example.org"}{if w:=doJSON(r,"POST","/register",map[string]any{"email":e,"password":"correct-horse-1","full_name":"T"},nil);w.Code>=300{t.Fatalf("register %s: %d %s",e,w.Code,w.Body.String())}}
	if _,err:=DB.Exec(`UPDATE users SET role='admin' WHERE email='boss@example.org'`);err!=nil{t.Fatal(err)}
	login:=func(e string)string{w:=doJSON(r,"POST","/login",map[string]any{"email":e,"password":"correct-horse-1"},nil);var a AuthResponse;_ = json.Unmarshal(w.Body.Bytes(),&a);if a.Token==""{t.Fatalf("login %s: %d %s",e,w.Code,w.Body.String())};return a.Token}
	boss,peon:=login("boss@example.org"),login("peon@example.org");body:=validApply();body["use_case"]="line1\nline2 — ünïcode ✓"
	w:=doJSON(r,"POST","/apply",body,nil);var applied map[string]string;_ = json.Unmarshal(w.Body.Bytes(),&applied);if w.Code!=200||applied["ref"]==""{t.Fatalf("apply: %d %s",w.Code,w.Body.String())}
	auth:=func(tok string)map[string]string{return map[string]string{"Authorization":"Bearer "+tok}}
	w=doJSON(r,"GET","/admin/applications",nil,auth(boss));var list struct{Applications []map[string]any `json:"applications"`};_ = json.Unmarshal(w.Body.Bytes(),&list)
	if w.Code!=200||len(list.Applications)!=1||list.Applications[0]["ref"]!=applied["ref"]||list.Applications[0]["use_case"]!="line1\nline2 — ünïcode ✓"||list.Applications[0]["email"]!="asha@example.org"{t.Fatalf("admin list wrong: %d %s",w.Code,w.Body.String())}
	if w=doJSON(r,"GET","/admin/applications/"+applied["ref"],nil,auth(boss));w.Code!=200||!strings.Contains(w.Body.String(),"DST CoE"){t.Fatalf("admin get: %d %s",w.Code,w.Body.String())}
	if w=doJSON(r,"GET","/admin/applications/PRX-MET-00000000",nil,auth(boss));w.Code!=404{t.Fatalf("unknown ref: %d",w.Code)}
	if w=doJSON(r,"GET","/admin/applications/PRX-MET-0000'--",nil,auth(boss));w.Code!=400&&w.Code!=404{t.Fatalf("malformed ref: %d",w.Code)}
	if w=doJSON(r,"GET","/admin/applications",nil,auth(peon));w.Code!=403{t.Fatalf("non-admin must not read applications: %d %s",w.Code,w.Body.String())}
	if w=doJSON(r,"GET","/admin/applications",nil,nil);w.Code!=401{t.Fatalf("anonymous: %d",w.Code)}
}

func TestPG_Migration_EnablesRowLevelSecurity_AndRevokesAPIRoles(t *testing.T) {
	pgSetup(t);var n int
	if err:=DB.QueryRow(`SELECT COUNT(*) FROM pg_class WHERE relname IN ('users','assets','applications') AND relkind='r' AND relrowsecurity`).Scan(&n);err!=nil||n!=3{t.Fatalf("RLS must be enabled on all three tables: n=%d err=%v",n,err)}
	_,_ = DB.Exec(`DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF; IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF; END $$`)
	if _,err:=DB.Exec(`GRANT ALL ON TABLE users,assets,applications TO anon,authenticated`);err!=nil{t.Skipf("cannot create/grant API roles in this database: %v",err)}
	CloseDB();if err:=InitDB();err!=nil{t.Fatal(err)}
	if err:=DB.QueryRow(`SELECT COUNT(*) FROM information_schema.role_table_grants WHERE table_schema='public' AND table_name IN ('users','assets','applications') AND grantee IN ('anon','authenticated')`).Scan(&n);err!=nil||n!=0{t.Fatalf("API roles must hold no privileges: n=%d err=%v",n,err)}
}

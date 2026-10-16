package auditledger

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/x509"
	"encoding/pem"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func writeTestKey(t *testing.T) string {
	t.Helper()
	_, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil { t.Fatal(err) }
	der, err := x509.MarshalPKCS8PrivateKey(privateKey)
	if err != nil { t.Fatal(err) }
	path := filepath.Join(t.TempDir(), "ledger-key.pem")
	if err := os.WriteFile(path, pem.EncodeToMemory(&pem.Block{Type:"PRIVATE KEY",Bytes:der}), 0600); err != nil { t.Fatal(err) }
	return path
}

func TestCanonicalRejectsFloatsAndNonASCIIKeys(t *testing.T) {
	if _, err := Canonical(map[string]any{"risk": 0.25}); err == nil { t.Fatal("expected float to be rejected") }
	if _, err := Canonical(map[string]any{"réponse": "x"}); err == nil { t.Fatal("expected non-ASCII key to be rejected") }
	got, err := Canonical(map[string]any{"z": "é", "a": 2})
	if err != nil { t.Fatal(err) }
	if string(got) != "{\"a\":2,\"z\":\"é\"}" { t.Fatalf("unexpected canonical JSON: %s", got) }
}

func TestAppendReopenAndVerify(t *testing.T) {
	dir, key := filepath.Join(t.TempDir(),"ledger"), writeTestKey(t)
	l, err := Open(dir,key); if err != nil { t.Fatal(err) }
	if _, err := l.Append("operator-1","risk.evaluate","asset:AST-1",map[string]any{"method":"POST","status":200}); err != nil { t.Fatal(err) }
	if _, err := l.Append("operator-1","risk.complete","asset:AST-1",map[string]any{"duration_ms":12}); err != nil { t.Fatal(err) }
	if result:=l.Verify(); !result.Valid || result.HeadSequence!=2 { t.Fatalf("unexpected verification: %+v",result) }
	if err:=l.Close(); err!=nil { t.Fatal(err) }
	l, err = Open(dir,key); if err != nil { t.Fatal(err) }
	defer l.Close()
	if result:=l.Verify(); !result.Valid || result.HeadSequence!=2 { t.Fatalf("verification after reopen failed: %+v",result) }
}

func TestConcurrentAppendsAreSerialized(t *testing.T) {
	dir,key:=filepath.Join(t.TempDir(),"ledger"),writeTestKey(t)
	l,err:=Open(dir,key);if err!=nil{t.Fatal(err)}
	defer l.Close()
	const n=40
	var wg sync.WaitGroup
	errs:=make(chan error,n)
	for i:=0;i<n;i++{wg.Add(1);go func(i int){defer wg.Done();_,e:=l.Append("operator","test.concurrent","resource",map[string]any{"index":i});if e!=nil{errs<-e}}(i)}
	wg.Wait();close(errs)
	for e:=range errs{t.Error(e)}
	if result:=l.Verify();!result.Valid||result.HeadSequence!=n{t.Fatalf("invalid concurrent ledger: %+v",result)}
}

func TestTamperedEventFailsClosed(t *testing.T) {
	dir,key:=filepath.Join(t.TempDir(),"ledger"),writeTestKey(t)
	l,err:=Open(dir,key);if err!=nil{t.Fatal(err)}
	if _,err:=l.Append("operator","test.write","resource",map[string]any{"status":200});err!=nil{t.Fatal(err)}
	if err:=l.Close();err!=nil{t.Fatal(err)}
	path:=filepath.Join(dir,"ledger.ndjson")
	raw,err:=os.ReadFile(path);if err!=nil{t.Fatal(err)}
	raw=[]byte(strings.Replace(string(raw),"\"status\":200","\"status\":500",1))
	if err:=os.WriteFile(path,raw,0600);err!=nil{t.Fatal(err)}
	if _,err:=Open(dir,key);err==nil{t.Fatal("expected tampered ledger to fail opening")}
}

func TestMissingSigningKeyFails(t *testing.T) {
	if _,err:=Open(filepath.Join(t.TempDir(),"ledger"),filepath.Join(t.TempDir(),"missing.pem"));err==nil{t.Fatal("expected missing signing key to fail")}
func TestTornTailRecoveryIsRecorded(t *testing.T) {
	dir, key := filepath.Join(t.TempDir(), "ledger"), writeTestKey(t)
	l, err := Open(dir, key)
	if err != nil { t.Fatal(err) }
	if _, err := l.Append("operator", "test.write", "resource", map[string]any{"status": 200}); err != nil { t.Fatal(err) }
	if err := l.Close(); err != nil { t.Fatal(err) }
	f, err := os.OpenFile(filepath.Join(dir, "ledger.ndjson"), os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil { t.Fatal(err) }
	if _, err := f.Write([]byte("{\\"torn\\":")); err != nil { t.Fatal(err) }
	if err := f.Close(); err != nil { t.Fatal(err) }
	l, err = Open(dir, key)
	if err != nil { t.Fatal(err) }
	defer l.Close()
	result := l.Verify()
	if !result.Valid || result.HeadSequence != 2 { t.Fatalf("recovery not recorded: %+v", result) }
	raw, err := os.ReadFile(filepath.Join(dir, "ledger.ndjson"))
	if err != nil { t.Fatal(err) }
	if !strings.Contains(string(raw), "ledger.recovered") { t.Fatal("expected ledger.recovered event") }
}

func TestInsecureSigningKeyPermissionsFail(t *testing.T) {
	key := writeTestKey(t)
	if err := os.Chmod(key, 0644); err != nil { t.Fatal(err) }
	if _, err := Open(filepath.Join(t.TempDir(), "ledger"), key); err == nil {
		t.Fatal("expected broad signing-key permissions to fail")
	}
}

}

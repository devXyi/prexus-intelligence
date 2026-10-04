package main

import (
	"bufio"
	"encoding/json"
	"mime"
	"mime/quotedprintable"
	"net"
	"net/http"
	"net/mail"
	"regexp"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"golang.org/x/time/rate"
)

func validApply() map[string]any {
	return map[string]any{
		"module": "meteorium", "plan": "Institutional", "deployment": "cloud",
		"name": "Asha Rao", "title": "Director", "email": "asha@example.org",
		"org": "DST CoE", "country": "India", "org_type": "Government", "use_case": "Flood risk pilot",
	}
}

func TestApply_RouteRegistered_PersistsAndReturnsRef(t *testing.T) {
	f := newFakeDB(t)
	t.Setenv("SMTP_HOST", "")
	r := newTestRouter(t)
	w := doJSON(r, "POST", "/apply", validApply(), nil)
	if w.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s (404 here means the route is not wired)", w.Code, w.Body.String())
	}
	var out map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &out)
	if !regexp.MustCompile(`^PRX-MET-[0-9A-F]{8}$`).MatchString(out["ref"]) {
		t.Fatalf("bad ref %q", out["ref"])
	}
	ins := f.execMatching("INSERT INTO applications")
	if len(ins) != 1 || len(ins[0].args) != 12 || ins[0].args[0] != out["ref"] {
		t.Fatalf("application not persisted with its ref: %+v", ins)
	}
}

func TestApply_NoDBNoEmail_Returns503_NotSilentSuccess(t *testing.T) {
	DB = nil
	t.Setenv("SMTP_HOST", "")
	r := newTestRouter(t)
	if w := doJSON(r, "POST", "/apply", validApply(), nil); w.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503 (lead would be lost), got %d", w.Code)
	}
}

func TestApply_Validation(t *testing.T) {
	r := newTestRouter(t)
	bad := func(mut func(m map[string]any)) int {
		m := validApply()
		mut(m)
		return doJSON(r, "POST", "/apply", m, nil).Code
	}
	cases := map[string]func(map[string]any){
		"bad email":    func(m map[string]any) { m["email"] = "not-an-email" },
		"missing name": func(m map[string]any) { delete(m, "name") },
		"long name":    func(m map[string]any) { m["name"] = strings.Repeat("a", 500) },
		"long usecase": func(m map[string]any) { m["use_case"] = strings.Repeat("a", 5000) },
	}
	for name, mut := range cases {
		if c := bad(mut); c != http.StatusBadRequest {
			t.Errorf("%s: want 400 got %d", name, c)
		}
	}
	if w := doJSON(r, "POST", "/apply", []byte("{not json"), nil); w.Code != http.StatusBadRequest {
		t.Errorf("malformed json: want 400 got %d", w.Code)
	}
}

func TestApply_HeaderInjectionNeutralised(t *testing.T) {
	req := ApplyRequest{
		Module: "meteorium\r\nBcc: evil@x.com", Plan: "Pro\nX-Injected: 1", Deployment: "cloud",
		Name: "A\r\nCc: evil2@x.com", Title: "t", Email: "a@b.co", Org: "o", Country: "IN", OrgType: "g",
		UseCase: "line1\r\n.\r\nQUIT\r\nBcc: evil3@x.com",
	}
	req.normalize()
	msg := buildMIMEMessage("from@prexus.in", []string{"to@prexus.in"}, applicationSubject(), applicationBody())
	m, err := mail.ReadMessage(strings.NewReader(msg))
	if err != nil {
		t.Fatalf("message must parse: %v", err)
	}
	for _, h := range []string{"Bcc", "Cc", "X-Injected"} {
		if v := m.Header.Get(h); v != "" {
			t.Errorf("injected header %s=%q", h, v)
		}
	}
	if got := m.Header.Get("To"); got != "to@prexus.in" {
		t.Errorf("To header altered: %q", got)
	}
	subj, _ := (&mime.WordDecoder{}).DecodeHeader(m.Header.Get("Subject"))
	if strings.ContainsAny(subj, "\r\n") {
		t.Errorf("subject has newline: %q", subj)
	}
	// Direct call with dirty inputs must also be safe.
	raw := buildMIMEMessage("f@x.io", []string{"t@x.io\r\nBcc: e@x.io"}, "hi\r\nBcc: evil@x.com", "body")
	m2, err := mail.ReadMessage(strings.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	if m2.Header.Get("Bcc") != "" {
		t.Errorf("Bcc injected via direct call")
	}
	// Body survives QP round trip.
	body := make([]byte, 4096)
	n, _ := quotedprintable.NewReader(m.Body).Read(body)
	if !strings.Contains(string(body[:n]), "Flood") && !strings.Contains(string(body[:n]), "line1") {
		t.Errorf("body lost: %q", string(body[:n]))
	}
}

func TestApply_RecipientsFromEnvOnly(t *testing.T) {
	t.Setenv("NOTIFY_EMAILS", "")
	if got := notifyRecipients(); len(got) != 0 {
		t.Fatalf("no hardcoded fallback allowed, got %v", got)
	}
	t.Setenv("NOTIFY_EMAILS", "a@b.co, not valid, c@d.org")
	if got := notifyRecipients(); len(got) != 2 || got[0] != "a@b.co" || got[1] != "c@d.org" {
		t.Fatalf("got %v", got)
	}
}

func TestApply_RefsUniqueAndSanitised(t *testing.T) {
	seen := map[string]bool{}
	for i := 0; i < 2000; i++ {
		ref := newApplicationRef("raksha")
		if seen[ref] {
			t.Fatalf("collision %s", ref)
		}
		seen[ref] = true
	}
	if got := newApplicationRef("  ../x\r\n"); !regexp.MustCompile(`^PRX-X-[0-9A-F]{8}$`).MatchString(got) {
		t.Errorf("unsanitised prefix: %s", got)
	}
	if got := newApplicationRef("!!!"); !strings.HasPrefix(got, "PRX-GEN-") {
		t.Errorf("empty prefix fallback: %s", got)
	}
}

// ── fake SMTP server ──────────────────────────────────────────────────────────

func startFakeSMTP(t *testing.T, offerStartTLS, silent bool) (host, port string, sawAuth *atomic.Bool) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	sawAuth = &atomic.Bool{}
	done := make(chan struct{})
	t.Cleanup(func() { close(done); ln.Close() })
	go func() {
		conn, err := ln.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		if silent {
			<-done
			return
		}
		conn.Write([]byte("220 fake ESMTP\r\n"))
		rd := bufio.NewReader(conn)
		for {
			line, err := rd.ReadString('\n')
			if err != nil {
				return
			}
			u := strings.ToUpper(strings.TrimSpace(line))
			switch {
			case strings.HasPrefix(u, "EHLO"), strings.HasPrefix(u, "HELO"):
				if offerStartTLS {
					conn.Write([]byte("250-fake\r\n250-STARTTLS\r\n250 8BITMIME\r\n"))
				} else {
					conn.Write([]byte("250-fake\r\n250 8BITMIME\r\n"))
				}
			case strings.HasPrefix(u, "AUTH"):
				sawAuth.Store(true)
				conn.Write([]byte("235 ok\r\n"))
			case strings.HasPrefix(u, "QUIT"):
				conn.Write([]byte("221 bye\r\n"))
				return
			default:
				conn.Write([]byte("250 ok\r\n"))
			}
		}
	}()
	h, p, _ := net.SplitHostPort(ln.Addr().String())
	return h, p, sawAuth
}

func smtpEnv(t *testing.T, host, port string) {
	t.Setenv("SMTP_HOST", host)
	t.Setenv("SMTP_PORT", port)
	t.Setenv("SMTP_USER", "u@prexus.in")
	t.Setenv("SMTP_PASS", "secret-pass")
	t.Setenv("NOTIFY_EMAILS", "ops@prexus.in")
}

func TestApply_RefusesCredentialsInClear(t *testing.T) {
	host, port, sawAuth := startFakeSMTP(t, false, false)
	smtpEnv(t, host, port)
	err := sendApplicationEmail(ApplyRequest{Module: "m", Plan: "p", Name: "n", Email: "a@b.co", Org: "o", Country: "c", OrgType: "t"}, "PRX-T")
	if err == nil || !strings.Contains(err.Error(), "STARTTLS") {
		t.Fatalf("expected STARTTLS refusal, got %v", err)
	}
	if sawAuth.Load() {
		t.Fatal("credentials were sent without TLS")
	}
}

func TestApply_SMTPTimeoutsBounded(t *testing.T) {
	host, port, _ := startFakeSMTP(t, true, true) // accepts, never speaks
	smtpEnv(t, host, port)
	old := smtpTotalTimeout
	smtpTotalTimeout = 300 * time.Millisecond
	defer func() { smtpTotalTimeout = old }()
	start := time.Now()
	err := sendApplicationEmail(ApplyRequest{Module: "m", Plan: "p", Name: "n", Email: "a@b.co", Org: "o", Country: "c", OrgType: "t"}, "PRX-T")
	if err == nil {
		t.Fatal("expected error from silent server")
	}
	if d := time.Since(start); d > 3*time.Second {
		t.Fatalf("hung for %v — no effective timeout", d)
	}
}

func TestApply_StrictRateLimit(t *testing.T) {
	f := newFakeDB(t)
	t.Setenv("SMTP_HOST", "")
	newTestRouter(t)
	applyLimiter = newLimiterSet(rate.Every(time.Hour), 2)
	r := buildRouter()
	codes := []int{}
	for i := 0; i < 3; i++ {
		codes = append(codes, doJSON(r, "POST", "/apply", validApply(), nil).Code)
	}
	if codes[0] != 200 || codes[1] != 200 || codes[2] != http.StatusTooManyRequests {
		t.Fatalf("codes=%v", codes)
	}
	if n := len(f.execMatching("INSERT INTO applications")); n != 2 {
		t.Fatalf("rate-limited request must not be stored; inserts=%d", n)
	}
}

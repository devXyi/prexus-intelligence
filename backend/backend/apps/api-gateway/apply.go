// backend/apps/api-gateway/apply.go
// Prexus Intelligence — Access Application Handler (v2)
//
// v2 (audit fixes):
//   • The route is now registered in main.go. v1 was never wired, so every
//     pricing-page submission (all modules, incl. Raksha) returned 404.
//   • Applications are persisted to Postgres BEFORE any email is attempted:
//     an SMTP outage can no longer lose a lead.
//   • Header-injection safe: CR/LF/control chars are stripped from every value
//     that reaches a mail header; the subject is RFC 2047 encoded.
//   • SMTP dial + session have hard timeouts (no hung goroutines).
//   • No hardcoded personal recipients. NOTIFY_EMAILS is the only source.
//   • STARTTLS (587) and implicit TLS (465) supported; refuses to send
//     credentials in clear.
//
// Env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, NOTIFY_EMAILS (comma list)

package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/tls"
	"encoding/hex"
	"fmt"
	"log"
	"mime"
	"mime/quotedprintable"
	"net"
	"net/http"
	"net/mail"
	"net/smtp"
	"os"
	"regexp"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// Vars (not consts) so tests can shrink them.
var (
	smtpDialTimeout  = 10 * time.Second
	smtpTotalTimeout = 30 * time.Second
)

// sendMail is a package var so tests can stub the network.
var sendMail = sendApplicationEmail

// notifyRecipients returns validated recipients from NOTIFY_EMAILS only.
func notifyRecipients() []string {
	var list []string
	for _, e := range strings.Split(os.Getenv("NOTIFY_EMAILS"), ",") {
		e = strings.TrimSpace(e)
		if e == "" {
			continue
		}
		addr, err := mail.ParseAddress(e)
		if err != nil {
			log.Printf("[apply] ignoring invalid NOTIFY_EMAILS entry")
			continue
		}
		list = append(list, addr.Address)
	}
	return list
}

func smtpConfigured() bool {
	return os.Getenv("SMTP_HOST") != "" && os.Getenv("SMTP_USER") != "" &&
		os.Getenv("SMTP_PASS") != "" && len(notifyRecipients()) > 0
}

// ── Request model ─────────────────────────────────────────────────────────────

type ApplyRequest struct {
	Module     string `json:"module"     binding:"required,max=32"`
	Plan       string `json:"plan"       binding:"required,max=64"`
	Deployment string `json:"deployment" binding:"max=64"`

	Name    string `json:"name"     binding:"required,max=120"`
	Title   string `json:"title"    binding:"max=120"`
	Email   string `json:"email"    binding:"required,email,max=254"`
	Org     string `json:"org"      binding:"required,max=200"`
	Country string `json:"country"  binding:"required,max=80"`
	OrgType string `json:"org_type" binding:"required,max=80"`
	UseCase string `json:"use_case" binding:"max=4000"`
}

// cleanLine collapses any value into a single header-safe line.
func cleanLine(s string, max int) string {
	var b strings.Builder
	for _, r := range s {
		if r < 0x20 || r == 0x7f || r == 0x85 || r == 0x2028 || r == 0x2029 {
			b.WriteRune(' ')
			continue
		}
		b.WriteRune(r)
	}
	out := strings.Join(strings.Fields(b.String()), " ")
	if rs := []rune(out); max > 0 && len(rs) > max {
		out = string(rs[:max])
	}
	return out
}

// cleanBlock keeps newlines (for the free-text use case) but drops other control chars.
func cleanBlock(s string, max int) string {
	s = strings.ReplaceAll(strings.ReplaceAll(s, "\r\n", "\n"), "\r", "\n")
	var b strings.Builder
	for _, r := range s {
		if r == '\n' || r == '\t' || (r >= 0x20 && r != 0x7f) {
			b.WriteRune(r)
		}
	}
	out := strings.TrimSpace(b.String())
	if rs := []rune(out); max > 0 && len(rs) > max {
		out = string(rs[:max])
	}
	return out
}

func (r *ApplyRequest) normalize() {
	r.Module = cleanLine(r.Module, 32)
	r.Plan = cleanLine(r.Plan, 64)
	r.Deployment = cleanLine(r.Deployment, 64)
	r.Name = cleanLine(r.Name, 120)
	r.Title = cleanLine(r.Title, 120)
	r.Email = cleanLine(r.Email, 254)
	r.Org = cleanLine(r.Org, 200)
	r.Country = cleanLine(r.Country, 80)
	r.OrgType = cleanLine(r.OrgType, 80)
	r.UseCase = cleanBlock(r.UseCase, 4000)
}

var refModuleRe = regexp.MustCompile(`[^A-Z0-9]`)

func newApplicationRef(module string) string {
	prefix := refModuleRe.ReplaceAllString(strings.ToUpper(module), "")
	if len(prefix) > 3 {
		prefix = prefix[:3]
	}
	if prefix == "" {
		prefix = "GEN"
	}
	b := make([]byte, 4)
	if _, err := rand.Read(b); err != nil {
		return fmt.Sprintf("PRX-%s-%08X", prefix, uint32(time.Now().UnixNano()))
	}
	return fmt.Sprintf("PRX-%s-%s", prefix, strings.ToUpper(hex.EncodeToString(b)))
}

// ── Handler ──────────────────────────────────────────────────────────────────

func handleApply(c *gin.Context) {
	var req ApplyRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid application — please complete all required fields with valid values"})
		return
	}
	req.normalize()
	ref := newApplicationRef(req.Module)

	persisted := true
	ctx, cancel := context.WithTimeout(c.Request.Context(), dbTimeout)
	defer cancel()
	if err := saveApplication(ctx, ref, req, c.ClientIP()); err != nil {
		persisted = false
		log.Printf("[apply] persist failed ref=%s: %v", ref, err)
	}

	emailOK := smtpConfigured()
	if !persisted && !emailOK {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "applications are temporarily unavailable — please retry shortly"})
		return
	}
	if emailOK {
		go notifyApplication(req, ref, persisted)
	} else {
		log.Printf("[apply] stored ref=%s (email not configured: set SMTP_* and NOTIFY_EMAILS)", ref)
	}
	c.JSON(http.StatusOK, gin.H{"status": "submitted", "ref": ref})
}

func saveApplication(ctx context.Context, ref string, r ApplyRequest, ip string) error {
	if DB == nil {
		return fmt.Errorf("database not initialised")
	}
	_, err := DB.ExecContext(ctx,
		`INSERT INTO applications (ref,module,plan,deployment,name,title,email,org,country,org_type,use_case,ip)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`,
		ref, r.Module, r.Plan, r.Deployment, r.Name, r.Title, r.Email, r.Org, r.Country, r.OrgType, r.UseCase, ip)
	return err
}

func notifyApplication(req ApplyRequest, ref string, persisted bool) {
	err := sendMail(req, ref)
	if err != nil {
		log.Printf("[apply] email send error ref=%s: %v", ref, err)
	} else {
		log.Printf("[apply] notification sent ref=%s module=%s plan=%s", ref, req.Module, req.Plan)
	}
	if !persisted || DB == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), dbTimeout)
	defer cancel()
	msg := ""
	if err != nil {
		msg = cleanLine(err.Error(), 300)
	}
	if _, e := DB.ExecContext(ctx, `UPDATE applications SET notified=$2, notify_error=$3 WHERE ref=$1`, ref, err == nil, msg); e != nil {
		log.Printf("[apply] could not record notify status ref=%s: %v", ref, e)
	}
}

// ── Email composition ─────────────────────────────────────────────────────────

func applicationSubject() string {
	return "New PREXUS Access Application"
}

func applicationBody() string {
	return fmt.Sprintf(`PREXUS INTELLIGENCE PLATFORM
New access application received at %s UTC.

Review the application in the administrative system. Applicant-provided
content is intentionally excluded from email notifications and remains in
the application database.
`, time.Now().UTC().Format("2006-01-02 15:04:05"))
}

func sendApplicationEmail(req ApplyRequest, ref string) error {
	host, port := os.Getenv("SMTP_HOST"), os.Getenv("SMTP_PORT")
	user, pass := os.Getenv("SMTP_USER"), os.Getenv("SMTP_PASS")
	if host == "" || user == "" || pass == "" {
		return fmt.Errorf("SMTP env vars not configured (SMTP_HOST, SMTP_USER, SMTP_PASS)")
	}
	if port == "" {
		port = "587"
	}
	recipients := notifyRecipients()
	if len(recipients) == 0 {
		return fmt.Errorf("NOTIFY_EMAILS not configured")
	}

	msg := buildMIMEMessage(user, recipients, applicationSubject(), applicationBody())

	addr := net.JoinHostPort(host, port)
	dialer := &net.Dialer{Timeout: smtpDialTimeout}
	tlsConf := &tls.Config{ServerName: host, MinVersion: tls.VersionTLS12}

	var conn net.Conn
	var err error
	if port == "465" {
		conn, err = tls.DialWithDialer(dialer, "tcp", addr, tlsConf)
	} else {
		conn, err = dialer.Dial("tcp", addr)
	}
	if err != nil {
		return fmt.Errorf("dial: %w", err)
	}
	_ = conn.SetDeadline(time.Now().Add(smtpTotalTimeout))

	client, err := smtp.NewClient(conn, host)
	if err != nil {
		_ = conn.Close()
		return fmt.Errorf("smtp client: %w", err)
	}
	defer client.Close()

	if port != "465" {
		if ok, _ := client.Extension("STARTTLS"); !ok {
			return fmt.Errorf("server does not offer STARTTLS; refusing to send credentials in clear")
		}
		if err = client.StartTLS(tlsConf); err != nil {
			return fmt.Errorf("starttls: %w", err)
		}
	}
	if err = client.Auth(smtp.PlainAuth("", user, pass, host)); err != nil {
		return fmt.Errorf("auth: %w", err)
	}
	if err = client.Mail(user); err != nil {
		return fmt.Errorf("mail from: %w", err)
	}
	for _, r := range recipients {
		if err = client.Rcpt(r); err != nil {
			return fmt.Errorf("rcpt: %w", err)
		}
	}
	w, err := client.Data()
	if err != nil {
		return fmt.Errorf("data: %w", err)
	}
	if _, err = fmt.Fprint(w, msg); err != nil {
		return fmt.Errorf("write: %w", err)
	}
	if err = w.Close(); err != nil {
		return err
	}
	return client.Quit()
}

// buildMIMEMessage composes an injection-safe message. subject/body are cleaned
// by the caller; every header value is additionally forced onto one line here.
func buildMIMEMessage(from string, to []string, subject, body string) string {
	var hdr strings.Builder
	hdr.WriteString("From: Prexus Applications <" + cleanLine(from, 254) + ">\r\n")
	safeTo := make([]string, 0, len(to))
	for _, t := range to {
		safeTo = append(safeTo, cleanLine(t, 254))
	}
	hdr.WriteString("To: " + strings.Join(safeTo, ", ") + "\r\n")
	hdr.WriteString("Subject: " + mime.QEncoding.Encode("UTF-8", cleanLine(subject, 200)) + "\r\n")
	hdr.WriteString("Date: " + time.Now().UTC().Format(time.RFC1123Z) + "\r\n")
	hdr.WriteString("MIME-Version: 1.0\r\n")
	hdr.WriteString("Content-Type: text/plain; charset=UTF-8\r\n")
	hdr.WriteString("Content-Transfer-Encoding: quoted-printable\r\n\r\n")

	var qp bytes.Buffer
	w := quotedprintable.NewWriter(&qp)
	_, _ = w.Write([]byte(body))
	_ = w.Close()
	return hdr.String() + qp.String()
}

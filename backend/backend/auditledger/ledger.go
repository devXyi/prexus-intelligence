// Package auditledger implements the Prexus v2 append-only audit ledger.
// Its canonical event and signed-head formats follow docs/LEDGER_SPEC.md.
package auditledger

import (
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const genesis = "GENESIS"
const maxSafeInteger int64 = 1<<53 - 1

type Ledger struct {
	mu       sync.Mutex
	dir      string
	file     *os.File
	private  ed25519.PrivateKey
	public   ed25519.PublicKey
	publicPEM string
	keyID    string
	seq      int64
	headHash string
	closed   bool
	broken   error
}

type VerifyResult struct {
	Valid        bool   `json:"valid"`
	CheckedEvents int   `json:"checked_events"`
	HeadHash     string `json:"head_hash,omitempty"`
	HeadSequence int64  `json:"head_sequence,omitempty"`
	Reason       string `json:"reason,omitempty"`
}

func Open(dir, privateKeyPath string) (*Ledger, error) {
	if strings.TrimSpace(dir) == "" || strings.TrimSpace(privateKeyPath) == "" {
		return nil, errors.New("audit ledger directory and private key path are required")
	}
	keyInfo, err := os.Stat(privateKeyPath)
	if err != nil {
		return nil, fmt.Errorf("stat audit signing key: %w", err)
	}
	if keyInfo.Mode().Perm()&0077 != 0 {
		return nil, errors.New("audit signing key permissions are too broad; require owner-only access (0600)")
	}
	keyBytes, err := os.ReadFile(privateKeyPath)
	if err != nil {
		return nil, fmt.Errorf("read audit signing key: %w", err)
	}
	block, _ := pem.Decode(keyBytes)
	if block == nil {
		return nil, errors.New("audit signing key is not PEM encoded")
	}
	parsed, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return nil, fmt.Errorf("parse audit signing key: %w", err)
	}
	privateKey, ok := parsed.(ed25519.PrivateKey)
	if !ok {
		return nil, errors.New("audit signing key must be Ed25519 PKCS#8")
	}
	publicKey := privateKey.Public().(ed25519.PublicKey)
	pubDER, err := x509.MarshalPKIXPublicKey(publicKey)
	if err != nil {
		return nil, fmt.Errorf("encode audit public key: %w", err)
	}
	keyHash := sha256.Sum256(pubDER)
	pubPEM := pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: pubDER})

	if err := os.MkdirAll(filepath.Join(dir, "anchors"), 0700); err != nil {
		return nil, fmt.Errorf("create audit ledger directory: %w", err)
	}
	if err := os.Chmod(dir, 0700); err != nil {
		return nil, fmt.Errorf("secure audit ledger directory: %w", err)
	}
	l := &Ledger{dir: dir, private: privateKey, public: publicKey, publicPEM: string(pubPEM),
		keyID: hex.EncodeToString(keyHash[:])[:16], seq: 0, headHash: genesis}
	path := filepath.Join(dir, "ledger.ndjson")
	raw, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("read audit ledger: %w", err)
	}
	discardedBytes := 0
	if len(raw) > 0 && raw[len(raw)-1] != '\n' {
		cut := bytes.LastIndexByte(raw, '\n') + 1
		discardedBytes = len(raw) - cut
		f, openErr := os.OpenFile(path, os.O_WRONLY|os.O_CREATE, 0600)
		if openErr != nil {
			return nil, fmt.Errorf("open ledger for torn-tail recovery: %w", openErr)
		}
		if truncErr := f.Truncate(int64(cut)); truncErr != nil {
			_ = f.Close()
			return nil, fmt.Errorf("truncate torn ledger tail: %w", truncErr)
		}
		if syncErr := f.Sync(); syncErr != nil {
			_ = f.Close()
			return nil, fmt.Errorf("sync recovered ledger: %w", syncErr)
		}
		_ = f.Close()
		raw = raw[:cut]
	}
	events, err := decodeEvents(raw)
	if err != nil {
		return nil, fmt.Errorf("decode audit ledger: %w", err)
	}
	check := VerifyEvents(events)
	if !check.Valid {
		return nil, fmt.Errorf("audit ledger integrity failure: %s", check.Reason)
	}
	if len(events) > 0 {
		seq, ok := integer(events[len(events)-1]["seq"])
		if !ok {
			return nil, errors.New("audit ledger has an invalid final sequence")
		}
		hash, ok := events[len(events)-1]["hash"].(string)
		if !ok {
			return nil, errors.New("audit ledger has an invalid final hash")
		}
		l.seq, l.headHash = seq, hash
	}
	if err := l.verifyAnchor(len(events), events); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_RDWR, 0600)
	if err != nil {
		return nil, fmt.Errorf("open audit ledger for append: %w", err)
	}
	if err := f.Chmod(0600); err != nil {
		_ = f.Close()
		return nil, fmt.Errorf("secure audit ledger file: %w", err)
	}
	l.file = f
	if err := l.writeAnchor(); err != nil {
		_ = f.Close()
		return nil, fmt.Errorf("write initial signed audit head: %w", err)
	}
	if discardedBytes > 0 {
		if _, err := l.Append("system", "ledger.recovered", "ledger", map[string]any{"discarded_bytes": discardedBytes}); err != nil {
			_ = f.Close()
			return nil, fmt.Errorf("record torn-tail recovery: %w", err)
		}
	}
	return l, nil
}

func decodeEvents(raw []byte) ([]map[string]any, error) {
	if len(raw) == 0 { return nil, nil }
	lines := bytes.Split(raw, []byte("\n"))
	events := make([]map[string]any, 0, len(lines))
	for i, line := range lines {
		if len(line) == 0 { continue }
		dec := json.NewDecoder(bytes.NewReader(line))
		dec.UseNumber()
		var ev map[string]any
		if err := dec.Decode(&ev); err != nil { return nil, fmt.Errorf("line %d: %w", i+1, err) }
		events = append(events, ev)
	}
	return events, nil
}

func VerifyEvents(events []map[string]any) VerifyResult {
	prev := genesis
	for i, ev := range events {
		seq, ok := integer(ev["seq"])
		if ev["v"] != json.Number("2") && ev["v"] != int64(2) && ev["v"] != int(2) {
			return VerifyResult{Valid:false, CheckedEvents:len(events), Reason:"unsupported event version"}
		}
		if !ok || seq != int64(i+1) {
			return VerifyResult{Valid:false, CheckedEvents:len(events), Reason:"sequence gap or reorder"}
		}
		if ev["previous_hash"] != prev {
			return VerifyResult{Valid:false, CheckedEvents:len(events), Reason:"previous_hash mismatch (event removed or reordered)"}
		}
		got, ok := ev["hash"].(string)
		if !ok { return VerifyResult{Valid:false, CheckedEvents:len(events), Reason:"event hash missing"} }
		unsigned := make(map[string]any, len(ev)-1)
		for k, v := range ev { if k != "hash" { unsigned[k] = v } }
		canon, err := Canonical(unsigned)
		if err != nil { return VerifyResult{Valid:false, CheckedEvents:len(events), Reason:"event cannot be canonicalised: "+err.Error()} }
		sum := sha256.Sum256(canon)
		want := hex.EncodeToString(sum[:])
		if got != want { return VerifyResult{Valid:false, CheckedEvents:len(events), Reason:"event content does not match its hash (modified)"} }
		prev = got
	}
	return VerifyResult{Valid:true, CheckedEvents:len(events), HeadHash:prev, HeadSequence:int64(len(events))}
}

func integer(v any) (int64, bool) {
	switch n := v.(type) {
	case int: return int64(n), true
	case int64: return n, true
	case json.Number:
		i, err := strconv.ParseInt(string(n), 10, 64); return i, err == nil
	default: return 0, false
	}
}

// Canonical emits the cross-language canonical JSON specified in docs/LEDGER_SPEC.md.
// Floating-point values and non-ASCII object keys are rejected by design.
func Canonical(v any) ([]byte, error) {
	var out bytes.Buffer
	var walk func(any) error
	walk = func(value any) error {
		switch x := value.(type) {
		case nil: out.WriteString("null")
		case bool: if x { out.WriteString("true") } else { out.WriteString("false") }
		case string:
			b, err := canonicalString(x); if err != nil { return err }; out.Write(b)
		case int: if int64(x) > maxSafeInteger || int64(x) < -maxSafeInteger { return errors.New("integer outside the safe range") }; out.WriteString(strconv.Itoa(x))
		case int64: if x > maxSafeInteger || x < -maxSafeInteger { return errors.New("integer outside the safe range") }; out.WriteString(strconv.FormatInt(x,10))
		case json.Number:
			i, err := strconv.ParseInt(string(x),10,64); if err != nil || i > maxSafeInteger || i < -maxSafeInteger { return errors.New("canonical JSON requires safe integers only") }; out.WriteString(strconv.FormatInt(i,10))
		case []any:
			out.WriteByte('['); for i, item := range x { if i>0 { out.WriteByte(',') }; if err:=walk(item); err!=nil{return err} }; out.WriteByte(']')
		case map[string]any:
			keys:=make([]string,0,len(x)); for k:=range x { for _, r:=range k { if r<0x20 || r>0x7e { return errors.New("canonical JSON keys must be ASCII strings") } }; keys=append(keys,k) }; sort.Strings(keys)
			out.WriteByte('{'); for i,k:=range keys { if i>0 {out.WriteByte(',')}; kb,err:=canonicalString(k); if err!=nil{return err}; out.Write(kb); out.WriteByte(':'); if err:=walk(x[k]);err!=nil{return err} }; out.WriteByte('}')
		default: return fmt.Errorf("cannot canonicalise %T", value)
		}
		return nil
	}
	if err:=walk(v);err!=nil{return nil,err}
	return out.Bytes(),nil
}

func canonicalString(s string) ([]byte,error) {
	var b bytes.Buffer
	enc:=json.NewEncoder(&b); enc.SetEscapeHTML(false)
	if err:=enc.Encode(s);err!=nil{return nil,err}
	raw:=bytes.TrimSuffix(b.Bytes(),[]byte("\n"))
	raw=bytes.ReplaceAll(raw,[]byte(`\u2028`),[]byte("\u2028"))
	raw=bytes.ReplaceAll(raw,[]byte(`\u2029`),[]byte("\u2029"))
	return append([]byte(nil),raw...),nil
}

func (l *Ledger) verifyAnchor(eventCount int, events []map[string]any) error {
	path:=filepath.Join(l.dir,"anchors","head.json")
	raw,err:=os.ReadFile(path)
	if errors.Is(err,os.ErrNotExist) {
		if eventCount>0 { return errors.New("audit ledger has events but signed anchor is missing") }
		return nil
	}
	if err!=nil{return fmt.Errorf("read signed audit anchor: %w",err)}
	var h map[string]any
	dec:=json.NewDecoder(bytes.NewReader(raw)); dec.UseNumber()
	if err:=dec.Decode(&h);err!=nil{return fmt.Errorf("decode signed audit anchor: %w",err)}
	seq,ok:=integer(h["sequence"]); if !ok || seq<0{return errors.New("signed audit anchor has invalid sequence")}
	headHash,ok:=h["head_hash"].(string); if !ok{return errors.New("signed audit anchor has invalid head hash")}
	signedAt,_:=h["signed_at"].(string); keyID,_:=h["key_id"].(string)
	if h["alg"]!="Ed25519" || keyID!=l.keyID{return errors.New("signed audit anchor uses an untrusted algorithm or key")}
	message,err:=Canonical(map[string]any{"sequence":seq,"head_hash":headHash,"signed_at":signedAt,"key_id":keyID})
	if err!=nil{return err}
	sigText,_:=h["signature"].(string); sig,err:=base64.StdEncoding.DecodeString(sigText)
	if err!=nil || !ed25519.Verify(l.public,message,sig){return errors.New("signed audit anchor signature is invalid")}
	if seq>int64(eventCount){return fmt.Errorf("ledger has %d events but signed anchor attests %d (truncated or replaced)",eventCount,seq)}
	if seq>0 && events[seq-1]["hash"]!=headHash{return errors.New("ledger diverges from signed anchor (history rewritten)")}
	return nil
}

func (l *Ledger) Append(actor, action, resource string, metadata map[string]any) (map[string]any,error) {
	l.mu.Lock(); defer l.mu.Unlock()
	if l.closed{return nil,errors.New("audit ledger is closed")}
	if l.broken!=nil{return nil,fmt.Errorf("audit ledger unavailable after write failure: %w",l.broken)}
	if actor=="" || action=="" || resource=="" {return nil,errors.New("audit actor, action, and resource are required")}
	if metadata==nil{metadata=map[string]any{}}
	now:=time.Now().UTC().Format("2006-01-02T15:04:05.000Z")
	id,err:=uuid4();if err!=nil{return nil,err}
	ev:=map[string]any{"v":int(2),"seq":l.seq+1,"id":id,"at":now,"actor":actor,"action":action,"resource":resource,"metadata":metadata,"previous_hash":l.headHash}
	canon,err:=Canonical(ev);if err!=nil{return nil,fmt.Errorf("canonicalise audit event: %w",err)}
	sum:=sha256.Sum256(canon);ev["hash"]=hex.EncodeToString(sum[:])
	line,err:=Canonical(ev);if err!=nil{return nil,err};line=append(line,'\n')
	if _,err=l.file.Write(line);err!=nil{l.broken=err;return nil,fmt.Errorf("append audit event: %w",err)}
	if err=l.file.Sync();err!=nil{l.broken=err;return nil,fmt.Errorf("sync audit event: %w",err)}
	l.seq++;l.headHash=ev["hash"].(string)
	if err=l.writeAnchor();err!=nil{l.broken=err;return nil,fmt.Errorf("persist signed audit head: %w",err)}
	return ev,nil
}

func (l *Ledger) writeAnchor() error {
	h:=map[string]any{"sequence":l.seq,"head_hash":l.headHash,"signed_at":time.Now().UTC().Format("2006-01-02T15:04:05.000Z"),"key_id":l.keyID}
	message,err:=Canonical(h);if err!=nil{return err}
	h["alg"]="Ed25519";h["signature"]=base64.StdEncoding.EncodeToString(ed25519.Sign(l.private,message));h["public_key"]=l.publicPEM
	raw,err:=json.MarshalIndent(h,"","  ");if err!=nil{return err};raw=append(raw,'\n')
	path:=filepath.Join(l.dir,"anchors","head.json")
	tmp,err:=os.CreateTemp(filepath.Dir(path),".head-*.tmp");if err!=nil{return err}
	tmpName:=tmp.Name();defer os.Remove(tmpName)
	if err=tmp.Chmod(0600);err==nil{_,err=tmp.Write(raw)}
	if err==nil{err=tmp.Sync()}
	closeErr:=tmp.Close();if err==nil{err=closeErr};if err!=nil{return err}
	if err=os.Rename(tmpName,path);err!=nil{return err}
	d,err:=os.Open(filepath.Dir(path));if err!=nil{return err};defer d.Close()
	return d.Sync()
}

func (l *Ledger) Verify() VerifyResult {
	l.mu.Lock();defer l.mu.Unlock()
	if l.closed{return VerifyResult{Valid:false,Reason:"audit ledger is closed"}}
	if l.broken!=nil{return VerifyResult{Valid:false,Reason:l.broken.Error()}}
	if _,err:=l.file.Seek(0,io.SeekStart);err!=nil{return VerifyResult{Valid:false,Reason:err.Error()}}
	raw,err:=io.ReadAll(l.file);if err!=nil{return VerifyResult{Valid:false,Reason:err.Error()}}
	if _,err:=l.file.Seek(0,io.SeekEnd);err!=nil{return VerifyResult{Valid:false,Reason:err.Error()}}
	events,err:=decodeEvents(raw);if err!=nil{return VerifyResult{Valid:false,Reason:err.Error()}}
	result:=VerifyEvents(events)
	if result.Valid && (result.HeadHash!=l.headHash || result.HeadSequence!=l.seq){return VerifyResult{Valid:false,CheckedEvents:len(events),Reason:"on-disk ledger diverges from running process"}}
	return result
}

func (l *Ledger) Close() error {
	l.mu.Lock();defer l.mu.Unlock()
	if l.closed{return nil};l.closed=true
	if l.file!=nil{return l.file.Close()};return nil
}

func uuid4() (string,error) {
	var b [16]byte
	if _,err:=rand.Read(b[:]);err!=nil{return "",err}
	b[6]=(b[6]&0x0f)|0x40;b[8]=(b[8]&0x3f)|0x80
	s:=hex.EncodeToString(b[:])
	return s[:8]+"-"+s[8:12]+"-"+s[12:16]+"-"+s[16:20]+"-"+s[20:],nil
}

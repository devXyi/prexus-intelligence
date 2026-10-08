package main

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"fmt"
	"io"
	"strings"
	"sync"
	"testing"
)

// A tiny in-memory database/sql driver for handler tests. It exists so the test-suite needs NO
// third-party module beyond what go.mod already pins (no sqlmock → `go test` works from the
// committed go.mod/go.sum).

type fakeCall struct {
	query string
	args  []driver.Value
}

type fakeDB struct {
	mu        sync.Mutex
	Execs     []fakeCall
	Queries   []fakeCall
	PingErr   error
	ExecErr   error
	QueryCols []string
	QueryRows [][]driver.Value
}

var (
	fakeMu  sync.Mutex
	fakeReg = map[string]*fakeDB{}
	fakeN   int
)

type fakeDriver struct{}

func (fakeDriver) Open(name string) (driver.Conn, error) {
	fakeMu.Lock()
	defer fakeMu.Unlock()
	f, ok := fakeReg[name]
	if !ok {
		return nil, fmt.Errorf("unknown fake db %q", name)
	}
	return &fakeConn{f}, nil
}

func init() { sql.Register("prexusfake", fakeDriver{}) }

// newFakeDB installs a fake as the package-level DB and restores nil on cleanup.
func newFakeDB(t *testing.T) *fakeDB {
	t.Helper()
	fakeMu.Lock()
	fakeN++
	name := fmt.Sprintf("db%d", fakeN)
	f := &fakeDB{}
	fakeReg[name] = f
	fakeMu.Unlock()
	db, err := sql.Open("prexusfake", name)
	if err != nil {
		t.Fatal(err)
	}
	DB = db
	t.Cleanup(func() { DB = nil; db.Close() })
	return f
}

type fakeConn struct{ f *fakeDB }

func (c *fakeConn) Prepare(string) (driver.Stmt, error) {
	return nil, fmt.Errorf("prepare not supported")
}
func (c *fakeConn) Close() error               { return nil }
func (c *fakeConn) Begin() (driver.Tx, error)  { return nil, fmt.Errorf("tx not supported") }
func (c *fakeConn) Ping(context.Context) error { return c.f.PingErr }

func plain(args []driver.NamedValue) []driver.Value {
	out := make([]driver.Value, len(args))
	for i, a := range args {
		out[i] = a.Value
	}
	return out
}

func (c *fakeConn) ExecContext(_ context.Context, q string, args []driver.NamedValue) (driver.Result, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	c.f.Execs = append(c.f.Execs, fakeCall{q, plain(args)})
	if c.f.ExecErr != nil {
		return nil, c.f.ExecErr
	}
	return driver.RowsAffected(1), nil
}

func (c *fakeConn) QueryContext(_ context.Context, q string, args []driver.NamedValue) (driver.Rows, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	c.f.Queries = append(c.f.Queries, fakeCall{q, plain(args)})
	return &fakeRows{cols: c.f.QueryCols, rows: c.f.QueryRows}, nil
}

type fakeRows struct {
	cols []string
	rows [][]driver.Value
	i    int
}

func (r *fakeRows) Columns() []string { return r.cols }
func (r *fakeRows) Close() error      { return nil }
func (r *fakeRows) Next(dest []driver.Value) error {
	if r.i >= len(r.rows) {
		return io.EOF
	}
	copy(dest, r.rows[r.i])
	r.i++
	return nil
}

func (f *fakeDB) execMatching(substr string) []fakeCall {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []fakeCall
	for _, c := range f.Execs {
		if strings.Contains(c.query, substr) {
			out = append(out, c)
		}
	}
	return out
}

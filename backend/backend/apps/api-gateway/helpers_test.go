package main

import (
	"context"
	"strings"
	"time"
)

func contains(s, sub string) bool { return strings.Contains(s, sub) }

func contextWithTimeout(d time.Duration) (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), d)
}

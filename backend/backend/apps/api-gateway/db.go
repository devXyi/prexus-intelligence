// backend/apps/api-gateway/db.go
// Prexus Intelligence — Hardened DB Layer (v3.0)
// Production-safe: timeouts, SSL, logging, no leaks, no collisions.

package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/gin-gonic/gin"
	_ "github.com/lib/pq"
)

var DB *sql.DB
const dbTimeout = 5 * time.Second

type Asset struct {
	ID string `json:"id"`
	UserID string `json:"user_id,omitempty"`
	Name string `json:"name"`
	Type string `json:"type"`
	Country string `json:"country"`
	CC string `json:"cc"`
	Lat float64 `json:"lat"`
	Lon float64 `json:"lon"`
	ValueMM float64 `json:"value_mm"`
	PR float64 `json:"pr"`
	TR float64 `json:"tr"`
	CR float64 `json:"cr"`
	Alerts int `json:"alerts"`
	UpdatedAt time.Time `json:"updated_at"`
}

type AssetRequest struct {
	Name string `json:"name" binding:"required"`
	Type string `json:"type"`
	Country string `json:"country"`
	CC string `json:"cc"`
	Lat float64 `json:"lat"`
	Lon float64 `json:"lon"`
	ValueMM float64 `json:"value_mm"`
	PR float64 `json:"pr"`
	TR float64 `json:"tr"`
	CR float64 `json:"cr"`
	Alerts int `json:"alerts"`
}

func InitDB() error {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		dsn = fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s sslmode=require",
			getEnv("DB_HOST", "localhost"), getEnv("DB_PORT", "5432"), getEnv("DB_USER", "postgres"),
			getEnv("DB_PASS", "postgres"), getEnv("DB_NAME", "prexus"))
	}
	db, err := sql.Open("postgres", dsn)
	if err != nil { return fmt.Errorf("sql.Open: %w", err) }
	db.SetMaxOpenConns(25)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(5 * time.Minute)
	ctx, cancel := context.WithTimeout(context.Background(), dbTimeout)
	defer cancel()
	if err := db.PingContext(ctx); err != nil { return fmt.Errorf("db.Ping: %w", err) }
	DB = db
	log.Println("✓ Database connected")
	return migrate()
}

func CloseDB() { if DB != nil { _ = DB.Close() } }

func migrate() error {
	ctx, cancel := context.WithTimeout(context.Background(), dbTimeout)
	defer cancel()
	_, err := DB.ExecContext(ctx, `
	CREATE TABLE IF NOT EXISTS users (
		id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
		email TEXT NOT NULL UNIQUE,
		password_hash TEXT NOT NULL,
		full_name TEXT,
		org_name TEXT,
		role TEXT NOT NULL DEFAULT 'user',
		created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
		updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
	);
	CREATE TABLE IF NOT EXISTS assets (
		id TEXT PRIMARY KEY,
		user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
		name TEXT NOT NULL,
		type TEXT NOT NULL DEFAULT 'Infrastructure',
		country TEXT,
		cc TEXT,
		lat DOUBLE PRECISION NOT NULL DEFAULT 0,
		lon DOUBLE PRECISION NOT NULL DEFAULT 0,
		value_mm DOUBLE PRECISION NOT NULL DEFAULT 0,
		pr DOUBLE PRECISION NOT NULL DEFAULT 0.5,
		tr DOUBLE PRECISION NOT NULL DEFAULT 0.5,
		cr DOUBLE PRECISION NOT NULL DEFAULT 0.5,
		alerts INTEGER NOT NULL DEFAULT 0,
		updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
	);
	CREATE INDEX IF NOT EXISTS idx_assets_user_id ON assets(user_id);
	`)
	if err != nil { return fmt.Errorf("migration: %w", err) }
	log.Println("✓ Database schema ready")
	return nil
}

func handleGetAssets(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(c.Request.Context(), dbTimeout)
	defer cancel()
	rows, err := DB.QueryContext(ctx, `SELECT id,name,type,COALESCE(country,''),COALESCE(cc,''),lat,lon,value_mm,pr,tr,cr,alerts,updated_at FROM assets WHERE user_id=$1 ORDER BY cr DESC`, userID)
	if err != nil { log.Printf("DB error (get assets): %v", err); c.JSON(500, gin.H{"error": "Database error"}); return }
	defer rows.Close()
	var assets []Asset
	for rows.Next() {
		var a Asset
		a.UserID = userID
		if err := rows.Scan(&a.ID,&a.Name,&a.Type,&a.Country,&a.CC,&a.Lat,&a.Lon,&a.ValueMM,&a.PR,&a.TR,&a.CR,&a.Alerts,&a.UpdatedAt); err != nil { log.Printf("Scan error: %v", err); continue }
		assets = append(assets, a)
	}
	if err := rows.Err(); err != nil { log.Printf("Row iteration error: %v", err); c.JSON(500, gin.H{"error": "Database error"}); return }
	c.JSON(200, assets)
}

func handleCreateAsset(c *gin.Context) {
	userID := c.GetString("user_id")
	var req AssetRequest
	if err := c.ShouldBindJSON(&req); err != nil { c.JSON(400, gin.H{"error": err.Error()}); return }
	ctx, cancel := context.WithTimeout(c.Request.Context(), dbTimeout)
	defer cancel()
	assetID := generateAssetID(req.CC, req.Type, userID)
	var a Asset
	err := DB.QueryRowContext(ctx, `INSERT INTO assets (id,user_id,name,type,country,cc,lat,lon,value_mm,pr,tr,cr,alerts,updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) RETURNING id,name,type,COALESCE(country,''),COALESCE(cc,''),lat,lon,value_mm,pr,tr,cr,alerts,updated_at`,
		assetID,userID,req.Name,req.Type,req.Country,req.CC,req.Lat,req.Lon,req.ValueMM,clamp01(req.PR),clamp01(req.TR),clamp01(req.CR),req.Alerts,time.Now().UTC()).Scan(&a.ID,&a.Name,&a.Type,&a.Country,&a.CC,&a.Lat,&a.Lon,&a.ValueMM,&a.PR,&a.TR,&a.CR,&a.Alerts,&a.UpdatedAt)
	if err != nil { log.Printf("Create asset error: %v", err); c.JSON(500, gin.H{"error": "Failed to create asset"}); return }
	a.UserID = userID
	c.JSON(201, a)
}

func generateAssetID(cc, assetType, userID string) string {
	prefix := "AST"
	if len(cc) >= 2 { prefix = cc }
	if len(cc) > 3 { prefix = cc[:3] }
	abbrev := assetType
	if len(abbrev) > 3 { abbrev = abbrev[:3] }
	if abbrev == "" { abbrev = "AST" }
	return fmt.Sprintf("%s-%s-%d", prefix, abbrev, time.Now().UnixNano())
}

func clamp01(v float64) float64 { if v < 0 { return 0 }; if v > 1 { return 1 }; return v }
func getEnv(key, fallback string) string { if v := os.Getenv(key); v != "" { return v }; return fallback }

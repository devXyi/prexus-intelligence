// backend/apps/api-gateway/admin.go
// Read access to stored access applications. These routes are restricted by
// applications:read and are intended for authorised administrators.

package main

import (
	"context"
	"database/sql"
	"errors"
	"log"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
)

type applicationDTO struct {
	Ref string `json:"ref"`
	Module string `json:"module"`
	Plan string `json:"plan"`
	Deployment string `json:"deployment"`
	Name string `json:"name"`
	Title string `json:"title"`
	Email string `json:"email"`
	Org string `json:"org"`
	Country string `json:"country"`
	OrgType string `json:"org_type"`
	UseCase string `json:"use_case"`
	Notified bool `json:"notified"`
	NotifyError string `json:"notify_error"`
	CreatedAt time.Time `json:"created_at"`
}

const applicationCols = `ref,module,plan,COALESCE(deployment,''),name,COALESCE(title,''),email,org,country,org_type,COALESCE(use_case,''),notified,COALESCE(notify_error,''),created_at`

type rowScanner interface{ Scan(dest ...any) error }

func scanApplication(sc rowScanner) (applicationDTO, error) {
	var a applicationDTO
	err := sc.Scan(&a.Ref, &a.Module, &a.Plan, &a.Deployment, &a.Name, &a.Title, &a.Email, &a.Org, &a.Country, &a.OrgType, &a.UseCase, &a.Notified, &a.NotifyError, &a.CreatedAt)
	return a, err
}

func clampQueryInt(raw string, def, min, max int) int {
	n, err := strconv.Atoi(raw)
	if err != nil { return def }
	if n < min { return min }
	if n > max { return max }
	return n
}

func handleListApplications(c *gin.Context) {
	if DB == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error":"database unavailable"})
		return
	}
	limit := clampQueryInt(c.Query("limit"), 50, 1, 200)
	offset := clampQueryInt(c.Query("offset"), 0, 0, 1_000_000)
	ctx, cancel := context.WithTimeout(c.Request.Context(), dbTimeout)
	defer cancel()
	rows, err := DB.QueryContext(ctx, `SELECT `+applicationCols+` FROM applications ORDER BY created_at DESC, ref LIMIT $1 OFFSET $2`, limit, offset)
	if err != nil {
		log.Printf("[admin] list applications: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error":"Database error"})
		return
	}
	defer rows.Close()
	out := make([]applicationDTO, 0, limit)
	for rows.Next() {
		a, err := scanApplication(rows)
		if err != nil {
			log.Printf("[admin] scan application: %v", err)
			c.JSON(http.StatusInternalServerError, gin.H{"error":"Database error"})
			return
		}
		out = append(out, a)
	}
	if err := rows.Err(); err != nil {
		log.Printf("[admin] row iteration applications: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error":"Database error"})
		return
	}
	log.Printf("[admin] user=%s listed applications limit=%d offset=%d returned=%d", c.GetString("user_id"), limit, offset, len(out))
	c.JSON(http.StatusOK, gin.H{"applications": out, "limit": limit, "offset": offset})
}

func handleGetApplication(c *gin.Context) {
	ref := c.Param("ref")
	if !appRefRe.MatchString(ref) {
		c.JSON(http.StatusBadRequest, gin.H{"error":"invalid application reference"})
		return
	}
	if DB == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error":"database unavailable"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), dbTimeout)
	defer cancel()
	a, err := scanApplication(DB.QueryRowContext(ctx, `SELECT `+applicationCols+` FROM applications WHERE ref=$1`, ref))
	if errors.Is(err, sql.ErrNoRows) {
		c.JSON(http.StatusNotFound, gin.H{"error":"application not found"})
		return
	}
	if err != nil {
		log.Printf("[admin] get application %s: %v", ref, err)
		c.JSON(http.StatusInternalServerError, gin.H{"error":"Database error"})
		return
	}
	log.Printf("[admin] user=%s read application %s", c.GetString("user_id"), ref)
	c.JSON(http.StatusOK, a)
}

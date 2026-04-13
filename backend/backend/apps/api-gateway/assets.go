// backend/apps/api-gateway/assets.go
// Prexus Intelligence — Asset Handlers (Update + Delete)
// handleGetAssets and handleCreateAsset live in db.go.

package main

import (
	"context"
	"log"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

func handleUpdateAsset(c *gin.Context) {
	userID := c.GetInt64("user_id")
	assetID := c.Param("id")

	var req AssetRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), dbTimeout)
	defer cancel()

	var a Asset
	err := DB.QueryRowContext(ctx, `
		UPDATE assets SET
			name=$1, type=$2, country=$3, cc=$4,
			lat=$5, lon=$6, value_mm=$7,
			pr=$8, tr=$9, cr=$10,
			alerts=$11, updated_at=$12
		WHERE id=$13 AND user_id=$14
		RETURNING id,name,type,COALESCE(country,''),COALESCE(cc,''),
		          lat,lon,value_mm,pr,tr,cr,alerts,updated_at
	`,
		req.Name, req.Type, req.Country, req.CC,
		req.Lat, req.Lon, req.ValueMM,
		clamp01(req.PR), clamp01(req.TR), clamp01(req.CR),
		req.Alerts, time.Now().UTC(),
		assetID, userID,
	).Scan(
		&a.ID, &a.Name, &a.Type, &a.Country, &a.CC,
		&a.Lat, &a.Lon, &a.ValueMM, &a.PR, &a.TR,
		&a.CR, &a.Alerts, &a.UpdatedAt,
	)

	if err != nil {
		log.Printf("Update asset error (id=%s user=%d): %v", assetID, userID, err)
		c.JSON(http.StatusNotFound, gin.H{"error": "Asset not found or not yours"})
		return
	}

	a.UserID = userID
	c.JSON(http.StatusOK, a)
}

func handleDeleteAsset(c *gin.Context) {
	userID := c.GetInt64("user_id")
	assetID := c.Param("id")

	ctx, cancel := context.WithTimeout(c.Request.Context(), dbTimeout)
	defer cancel()

	result, err := DB.ExecContext(ctx,
		`DELETE FROM assets WHERE id=$1 AND user_id=$2`,
		assetID, userID,
	)
	if err != nil {
		log.Printf("Delete asset error (id=%s user=%d): %v", assetID, userID, err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Delete failed"})
		return
	}

	rows, _ := result.RowsAffected()
	if rows == 0 {
		c.JSON(http.StatusNotFound, gin.H{"error": "Asset not found or not yours"})
		return
	}

	c.Status(http.StatusNoContent)
}


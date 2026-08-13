package main

// Control plane primitives for Meteorium delivery.
//
// This is intentionally separate from the Meteorium data plane. It records
// commercial state (orders/entitlements), deployment intent, and provisioning
// jobs. It does not expose Meteorium publicly or execute infrastructure yet.
// The next phase can attach Terraform/Conduit workers to provisioning_jobs.

import (
    "context"
    "database/sql"
    "fmt"
    "net/http"
    "strings"
    "time"

    "github.com/gin-gonic/gin"
)

const controlPlaneTimeout = 5 * time.Second

func InitControlPlaneSchema() error {
    ctx, cancel := context.WithTimeout(context.Background(), controlPlaneTimeout)
    defer cancel()

    _, err := DB.ExecContext(ctx, `
CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    primary_domain TEXT,
    country_code TEXT,
    verification_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (verification_status IN ('pending','verified','rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS customer_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    product TEXT NOT NULL DEFAULT 'meteorium',
    plan TEXT NOT NULL,
    deployment_tier TEXT NOT NULL DEFAULT 'cloud'
        CHECK (deployment_tier IN ('cloud','dedicated','sovereign')),
    status TEXT NOT NULL DEFAULT 'requested'
        CHECK (status IN ('requested','reviewing','approved','rejected','cancelled')),
    requested_by_email TEXT NOT NULL,
    requirements JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS entitlements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    product TEXT NOT NULL DEFAULT 'meteorium',
    plan TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','active','suspended','expired','revoked')),
    starts_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    limits JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS deployments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    entitlement_id UUID REFERENCES entitlements(id),
    product TEXT NOT NULL DEFAULT 'meteorium',
    tier TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'requested'
        CHECK (status IN ('requested','provisioning','active','suspended','retired','failed')),
    endpoint TEXT,
    region TEXT,
    isolation_class TEXT,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS provisioning_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deployment_id UUID NOT NULL REFERENCES deployments(id),
    requested_by UUID REFERENCES users(id),
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    idempotency_key TEXT NOT NULL UNIQUE,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    actor_user_id UUID REFERENCES users(id),
    organization_id UUID REFERENCES organizations(id),
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    request_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_org ON customer_orders(organization_id);
CREATE INDEX IF NOT EXISTS idx_entitlements_org ON entitlements(organization_id);
CREATE INDEX IF NOT EXISTS idx_deployments_org ON deployments(organization_id);
CREATE INDEX IF NOT EXISTS idx_provisioning_deployment ON provisioning_jobs(deployment_id);
CREATE INDEX IF NOT EXISTS idx_audit_org_created ON audit_events(organization_id, created_at DESC);
`)
    if err != nil {
        return fmt.Errorf("control-plane migration: %w", err)
    }
    return nil
}

type ControlOrderRequest struct {
    LegalName       string         `json:"legal_name" binding:"required"`
    DisplayName     string         `json:"display_name" binding:"required"`
    PrimaryDomain   string         `json:"primary_domain"`
    CountryCode     string         `json:"country_code"`
    Plan            string         `json:"plan" binding:"required"`
    DeploymentTier  string         `json:"deployment_tier"`
    Requirements    map[string]any `json:"requirements"`
}

func requireControlAdmin(c *gin.Context) bool {
    if c.GetString("role") != "admin" {
        c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "control-plane admin permission required"})
        return false
    }
    return true
}

func auditControlEvent(c *gin.Context, orgID, action, resourceType, resourceID string, metadata map[string]any) {
    if DB == nil {
        return
    }
    _, _ = DB.ExecContext(c.Request.Context(),
        `INSERT INTO audit_events (actor_user_id, organization_id, action, resource_type, resource_id, request_id, metadata)
         VALUES (NULLIF($1,'')::uuid, NULLIF($2,'')::uuid, $3, $4, $5, $6, $7::jsonb)`,
        c.GetString("user_id"), orgID, action, resourceType, resourceID,
        c.GetString("request_id"), jsonString(metadata),
    )
}

func jsonString(v map[string]any) string {
    if v == nil {
        return "{}"
    }
    b, err := json.Marshal(v)
    if err != nil {
        return "{}"
    }
    return string(b)
}

func handleControlCreateOrder(c *gin.Context) {
    if !requireControlAdmin(c) { return }

    var req ControlOrderRequest
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
        return
    }
    tier := strings.ToLower(strings.TrimSpace(req.DeploymentTier))
    if tier == "" { tier = "cloud" }
    if tier != "cloud" && tier != "dedicated" && tier != "sovereign" {
        c.JSON(http.StatusBadRequest, gin.H{"error": "deployment_tier must be cloud, dedicated, or sovereign"})
        return
    }

    ctx, cancel := context.WithTimeout(c.Request.Context(), controlPlaneTimeout)
    defer cancel()

    var orgID, orderID string
    err := DB.QueryRowContext(ctx, `
        INSERT INTO organizations (legal_name, display_name, primary_domain, country_code)
        VALUES ($1,$2,NULLIF($3,''),NULLIF($4,''))
        RETURNING id`,
        strings.TrimSpace(req.LegalName), strings.TrimSpace(req.DisplayName),
        strings.TrimSpace(req.PrimaryDomain), strings.ToUpper(strings.TrimSpace(req.CountryCode)),
    ).Scan(&orgID)
    if err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "organization creation failed"})
        return
    }

    err = DB.QueryRowContext(ctx, `
        INSERT INTO customer_orders (organization_id, plan, deployment_tier, status, requested_by_email, requirements)
        VALUES ($1,$2,$3,'requested',$4,$5::jsonb)
        RETURNING id`,
        orgID, strings.TrimSpace(req.Plan), tier, c.GetString("email"), jsonString(req.Requirements),
    ).Scan(&orderID)
    if err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "order creation failed"})
        return
    }

    auditControlEvent(c, orgID, "order.created", "customer_order", orderID, map[string]any{"tier": tier, "plan": req.Plan})
    c.JSON(http.StatusCreated, gin.H{"organization_id": orgID, "order_id": orderID, "status": "requested"})
}

func handleControlApproveOrder(c *gin.Context) {
    if !requireControlAdmin(c) { return }
    orderID := c.Param("id")

    ctx, cancel := context.WithTimeout(c.Request.Context(), controlPlaneTimeout)
    defer cancel()

    var orgID, plan, tier string
    err := DB.QueryRowContext(ctx, `
        UPDATE customer_orders
        SET status='approved', updated_at=NOW()
        WHERE id=$1 AND status IN ('requested','reviewing')
        RETURNING organization_id, plan, deployment_tier`, orderID).Scan(&orgID, &plan, &tier)
    if err != nil {
        if err == sql.ErrNoRows {
            c.JSON(http.StatusConflict, gin.H{"error": "order not found or not approvable"})
            return
        }
        c.JSON(http.StatusInternalServerError, gin.H{"error": "order approval failed"})
        return
    }

    var entitlementID string
    err = DB.QueryRowContext(ctx, `
        INSERT INTO entitlements (organization_id, plan, status, starts_at)
        VALUES ($1,$2,'active',NOW()) RETURNING id`, orgID, plan).Scan(&entitlementID)
    if err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "entitlement creation failed"})
        return
    }

    var deploymentID string
    err = DB.QueryRowContext(ctx, `
        INSERT INTO deployments (organization_id, entitlement_id, tier, status, isolation_class)
        VALUES ($1,$2,$3,'requested',$3) RETURNING id`, orgID, entitlementID, tier).Scan(&deploymentID)
    if err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "deployment record creation failed"})
        return
    }

    auditControlEvent(c, orgID, "order.approved", "customer_order", orderID, map[string]any{"entitlement_id": entitlementID, "deployment_id": deploymentID})
    c.JSON(http.StatusOK, gin.H{"order_id": orderID, "organization_id": orgID, "entitlement_id": entitlementID, "deployment_id": deploymentID, "status": "approved"})
}

func handleControlProvision(c *gin.Context) {
    if !requireControlAdmin(c) { return }
    deploymentID := c.Param("id")
    idem := strings.TrimSpace(c.GetHeader("Idempotency-Key"))
    if idem == "" {
        c.JSON(http.StatusBadRequest, gin.H{"error": "Idempotency-Key header required"})
        return
    }

    ctx, cancel := context.WithTimeout(c.Request.Context(), controlPlaneTimeout)
    defer cancel()

    var jobID, status string
    err := DB.QueryRowContext(ctx, `
        INSERT INTO provisioning_jobs (deployment_id, requested_by, kind, idempotency_key)
        VALUES ($1,NULLIF($2,'')::uuid,'meteorium.deployment.provision',$3)
        ON CONFLICT (idempotency_key) DO UPDATE SET idempotency_key=EXCLUDED.idempotency_key
        RETURNING id, status`, deploymentID, c.GetString("user_id"), idem).Scan(&jobID, &status)
    if err != nil {
        c.JSON(http.StatusConflict, gin.H{"error": "provisioning job could not be created"})
        return
    }

    _, _ = DB.ExecContext(ctx, `UPDATE deployments SET status='provisioning', updated_at=NOW() WHERE id=$1 AND status IN ('requested','failed')`, deploymentID)
    auditControlEvent(c, "", "deployment.provision.requested", "deployment", deploymentID, map[string]any{"job_id": jobID})

    c.JSON(http.StatusAccepted, gin.H{
        "deployment_id": deploymentID,
        "job_id": jobID,
        "status": status,
        "next": "provisioning worker",
    })
}

func handleControlJob(c *gin.Context) {
    if !requireControlAdmin(c) { return }
    id := c.Param("id")
    var deploymentID, kind, status, lastError string
    var attempts int
    err := DB.QueryRowContext(c.Request.Context(), `
        SELECT deployment_id, kind, status, attempts, COALESCE(last_error,'')
        FROM provisioning_jobs WHERE id=$1`, id).Scan(&deploymentID, &kind, &status, &attempts, &lastError)
    if err != nil {
        c.JSON(http.StatusNotFound, gin.H{"error": "provisioning job not found"})
        return
    }
    c.JSON(http.StatusOK, gin.H{"id": id, "deployment_id": deploymentID, "kind": kind, "status": status, "attempts": attempts, "last_error": lastError})
}

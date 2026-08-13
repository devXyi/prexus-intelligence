// backend/apps/api-gateway/rbac.go
// Prexus Intelligence — RBAC System (v1.1)

package main

import "github.com/gin-gonic/gin"

var rolePermissions = map[string][]string{
    "admin": {
        "assets:read", "assets:create", "assets:update", "assets:delete",
        "risk:run", "user:read", "conduit:read", "control:admin",
    },
    "user": {
        "assets:read", "assets:create", "assets:update", "risk:run", "conduit:read",
    },
    "viewer": {"assets:read"},
}

func RequirePermission(permission string) gin.HandlerFunc {
    return func(c *gin.Context) {
        role := c.GetString("role")
        perms, ok := rolePermissions[role]
        if !ok { c.AbortWithStatusJSON(403, gin.H{"error":"Invalid role"}); return }
        for _, p := range perms {
            if p == permission { c.Next(); return }
        }
        c.AbortWithStatusJSON(403, gin.H{"error":"Permission denied"})
    }
}

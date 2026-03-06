package auth

import (
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

var jwtSecret = []byte(getEnvOrDefault("JWT_SECRET", "CHANGE_ME_USE_A_REAL_SECRET"))

const TokenTTL = 15 * time.Minute

// SovereignClaims represents custom claims carried inside the JWT.
type SovereignClaims struct {
	OrgID          string `json:"org_id"`
	OrgName        string `json:"org_name"`
	UserID         string `json:"user_id"`
	Role           string `json:"role"`
	ClearanceLevel int    `json:"clearance_level"`
	jwt.RegisteredClaims
}

// IssueToken creates a signed JWT token.
func IssueToken(orgID, orgName, userID, role string, clearance int) (string, error) {

	now := time.Now().UTC()

	claims := SovereignClaims{
		OrgID:          orgID,
		OrgName:        orgName,
		UserID:         userID,
		Role:           role,
		ClearanceLevel: clearance,
		RegisteredClaims: jwt.RegisteredClaims{
			Issuer:    "prexus-api",
			Subject:   userID,
			IssuedAt:  jwt.NewNumericDate(now),
			NotBefore: jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(TokenTTL)),
		},
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)

	signedToken, err := token.SignedString(jwtSecret)
	if err != nil {
		return "", fmt.Errorf("token signing failed: %w", err)
	}

	return signedToken, nil
}

// ValidateToken verifies and parses the JWT token.
func ValidateToken(tokenString string) (*SovereignClaims, error) {

	token, err := jwt.ParseWithClaims(tokenString, &SovereignClaims{},
		func(token *jwt.Token) (interface{}, error) {

			if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
				return nil, fmt.Errorf("unexpected signing method")
			}

			return jwtSecret, nil
		},
	)

	if err != nil {
		return nil, err
	}

	claims, ok := token.Claims.(*SovereignClaims)
	if !ok || !token.Valid {
		return nil, errors.New("invalid token")
	}

	return claims, nil
}

func getEnvOrDefault(key, fallback string) string {
	val := os.Getenv(key)
	if val == "" {
		return fallback
	}
	return val
}

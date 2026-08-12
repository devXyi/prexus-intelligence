package conduit

import (
	"fmt"
	"os"
	"strings"
)

// Config contains only the client-side configuration needed to consume the
// independent Conduit MCP service. Conduit remains an external service; this
// package is the Prexus integration boundary.
type Config struct {
	MCPURL      string
	TokenURL    string
	Audience    string
	ClientID    string
	ClientSecret string
	Scope       string
}

func LoadConfig() (Config, error) {
	cfg := Config{
		MCPURL:       strings.TrimRight(os.Getenv("CONDUIT_MCP_URL"), "/"),
		TokenURL:     strings.TrimRight(os.Getenv("CONDUIT_TOKEN_URL"), "/"),
		Audience:     strings.TrimSpace(os.Getenv("CONDUIT_AUDIENCE")),
		ClientID:     strings.TrimSpace(os.Getenv("CONDUIT_CLIENT_ID")),
		ClientSecret: os.Getenv("CONDUIT_CLIENT_SECRET"),
		Scope:        strings.TrimSpace(os.Getenv("CONDUIT_SCOPE")),
	}

	if cfg.MCPURL == "" {
		cfg.MCPURL = "https://conduit-mcp-nfmm.onrender.com/mcp"
	}
	if cfg.TokenURL == "" {
		cfg.TokenURL = "https://dev-jf6pbb4exdzatprm.eu.auth0.com/oauth/token"
	}
	if cfg.Audience == "" {
		cfg.Audience = "https://conduit-mcp.onrender.com/mcp"
	}
	if cfg.Scope == "" {
		cfg.Scope = "conduit:read"
	}

	if cfg.ClientID == "" || cfg.ClientSecret == "" {
		return Config{}, fmt.Errorf("CONDUIT_CLIENT_ID and CONDUIT_CLIENT_SECRET are required")
	}
	return cfg, nil
}

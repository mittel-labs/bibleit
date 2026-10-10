package bibleit

import (
	"context"
	"fmt"
)

// TokenMetadata describes a currently active personal credential, never its value.
// Timestamp fields are Unix seconds. Optional fields remain nil when absent.
type TokenMetadata struct {
	ID, Source      string
	IssuedAt        int64
	IssuedBy, Label *string
	// Empty scopes inherit the actor's permissions. Nil means the field was absent;
	// it must not be interpreted as unrestricted authority.
	Scopes                []string
	LastUsedAt, ExpiresAt *int64
	Retiring              *bool
	Fields                map[string]string
}

type TokenList struct {
	Actor  string
	Tokens []TokenMetadata
	Raw    Response
}

// ListTokens lists active personal token metadata. The server filters expired,
// revoked and expired rotation-grace credentials; it does not return a history.
func (c *Client) ListTokens(ctx context.Context) (TokenList, error) {
	result, err := c.Execute(ctx, AccountTokensCommand())
	if err != nil {
		return TokenList{}, err
	}
	fields, err := counted(result, "count", "token")
	if err != nil {
		return TokenList{}, err
	}
	value := TokenList{Raw: result, Tokens: []TokenMetadata{}}
	value.Actor, err = required(fields, "actor")
	if err != nil {
		return TokenList{}, err
	}
	seen := map[string]bool{}
	for _, record := range result.Records[1:] {
		fields := record.Fields
		token := TokenMetadata{Fields: fields, IssuedBy: optionalString(fields, "issued_by"), Label: optionalString(fields, "label")}
		token.ID, err = required(fields, "id")
		if err != nil {
			return TokenList{}, err
		}
		if seen[token.ID] {
			return TokenList{}, fmt.Errorf("duplicate token id")
		}
		seen[token.ID] = true
		token.Source, err = required(fields, "source")
		if err != nil {
			return TokenList{}, err
		}
		token.IssuedAt, err = number(fields, "issued_at")
		if err != nil {
			return TokenList{}, err
		}
		if scopes, ok := fields["scopes"]; ok {
			token.Scopes = commaList(scopes)
		}
		token.LastUsedAt, err = optionalNumber(fields, "last_used_at")
		if err != nil {
			return TokenList{}, err
		}
		token.ExpiresAt, err = optionalNumber(fields, "expires_at")
		if err != nil {
			return TokenList{}, err
		}
		token.Retiring, err = optionalBoolean(fields, "retiring")
		if err != nil {
			return TokenList{}, err
		}
		value.Tokens = append(value.Tokens, token)
	}
	return value, nil
}

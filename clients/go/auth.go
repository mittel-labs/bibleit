package bibleit

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
)

// AuthConfig supplies an endpoint and optional transport, without a bearer token.
type AuthConfig struct {
	Endpoint   string
	HTTPClient *http.Client
}

// AuthClient exchanges an approved browser code. It does not run a browser,
// validate callback state, persist credentials, or retry a consumed code.
type AuthClient struct {
	endpoint string
	http     *http.Client
}

func NewAuthClient(config AuthConfig) (*AuthClient, error) {
	endpoint, h, err := newHTTPTransport(config.Endpoint, config.HTTPClient)
	if err != nil {
		return nil, err
	}
	return &AuthClient{endpoint: endpoint, http: h}, nil
}

type CodeExchange struct {
	Code, Verifier, DeviceName string
}

// AuthorizationResult contains a secret AccessToken; Fields also contains the
// original JSON response, including that secret. Callers own secure storage.
type AuthorizationResult struct {
	Actor, IdentityName, DisplayName, AuthProvider, TokenID, AccessToken string
	Fields                                                               map[string]json.RawMessage
}

// ExchangeCode redeems an approved one-use code with its PKCE verifier.
// Even a rejected verifier can consume the code on the current server.
func (c *AuthClient) ExchangeCode(ctx context.Context, exchange CodeExchange) (AuthorizationResult, error) {
	if exchange.Code == "" || exchange.Verifier == "" {
		return AuthorizationResult{}, errors.New("authorization code and PKCE verifier are required")
	}
	form := url.Values{"code": {exchange.Code}, "code_verifier": {exchange.Verifier}}
	if exchange.DeviceName != "" {
		form.Set("device_name", exchange.DeviceName)
	}
	body := form.Encode()
	if len(body) > MaxRequestBytes {
		return AuthorizationResult{}, &RequestSizeError{Part: "authorization form", Bytes: len(body), Limit: MaxRequestBytes}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint+"/api/cli/token", strings.NewReader(body))
	if err != nil {
		return AuthorizationResult{}, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	res, err := c.http.Do(req)
	if err != nil {
		return AuthorizationResult{}, err
	}
	defer res.Body.Close()
	data, err := readAuthBody(res.Body)
	if err != nil {
		return AuthorizationResult{}, err
	}
	if res.StatusCode != http.StatusOK {
		return AuthorizationResult{}, authHTTPError(res.StatusCode, data)
	}
	var payload struct {
		Actor        string `json:"actor"`
		IdentityName string `json:"identity_name"`
		DisplayName  string `json:"display_name"`
		AuthProvider string `json:"auth_provider"`
		TokenID      string `json:"token_id"`
		AccessToken  string `json:"access_token"`
	}
	if err := json.Unmarshal(data, &payload); err != nil || payload.Actor == "" || payload.AccessToken == "" || strings.ContainsAny(payload.AccessToken, "\r\n") {
		return AuthorizationResult{}, errors.New("invalid authorization response")
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return AuthorizationResult{}, errors.New("invalid authorization response")
	}
	return AuthorizationResult{Actor: payload.Actor, IdentityName: payload.IdentityName, DisplayName: payload.DisplayName, AuthProvider: payload.AuthProvider, TokenID: payload.TokenID, AccessToken: payload.AccessToken, Fields: fields}, nil
}

// RevokeCredential revokes this client's bearer credential via CLI logout.
// Only HTTP 204 is a successful acknowledgement; errors never mutate the client.
func (c *Client) RevokeCredential(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint+"/api/cli/logout", nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	res, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode == http.StatusNoContent {
		return nil
	}
	data, err := readAuthBody(res.Body)
	if err != nil {
		return err
	}
	return authHTTPError(res.StatusCode, data)
}

func readAuthBody(body io.Reader) ([]byte, error) {
	data, err := io.ReadAll(io.LimitReader(body, maxResponseBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) > maxResponseBytes {
		return nil, errors.New("authorization response exceeds 2 MiB")
	}
	return data, nil
}

func authHTTPError(status int, data []byte) error {
	value := &HTTPError{StatusCode: status}
	if json.Unmarshal(data, &value.Fields) == nil {
		value.Code, _ = value.Fields["error"].(string)
	} else if _, err := DecodeResponse(bytes.NewReader(data)); err != nil {
		var serverErr *ServerError
		if !errors.As(err, &serverErr) {
			return value
		}
		value.Code = serverErr.Code
		value.Fields = map[string]any{}
		for key, field := range serverErr.Fields {
			value.Fields[key] = field
		}
	}
	return value
}

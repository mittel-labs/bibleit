package bibleit

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func TestCodeExchangeAndRevocation(t *testing.T) {
	var calls atomic.Int32
	server := authTestServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.Method != "POST" {
			t.Errorf("method %s", r.Method)
		}
		switch r.URL.Path {
		case "/api/cli/token":
			if r.Header.Get("Authorization") != "" || r.Header.Get("Content-Type") != "application/x-www-form-urlencoded" {
				t.Error("incorrect exchange headers")
			}
			if err := r.ParseForm(); err != nil {
				t.Error(err)
			}
			if r.Form.Get("code") != "code+&=" || r.Form.Get("code_verifier") != "verifier" || r.Form.Get("device_name") != "CLI João" {
				t.Error("incorrect form")
			}
			fmt.Fprint(w, `{"actor":"user","identity_name":"@user","auth_provider":"email","token_id":"id","access_token":"bt_secret","future":{"kept":true}}`)
		case "/api/cli/logout":
			if r.Header.Get("Authorization") != "Bearer bt_secret" {
				t.Error("incorrect bearer")
			}
			w.WriteHeader(204)
		default:
			t.Errorf("path %s", r.URL.Path)
		}
	}))
	defer server.Close()
	c, err := NewAuthClient(AuthConfig{Endpoint: server.URL, HTTPClient: server.Client()})
	if err != nil {
		t.Fatal(err)
	}
	result, err := c.ExchangeCode(context.Background(), CodeExchange{Code: "code+&=", Verifier: "verifier", DeviceName: "CLI João"})
	if err != nil || result.Actor != "user" || result.IdentityName != "@user" || result.AuthProvider != "email" || result.TokenID != "id" || result.AccessToken != "bt_secret" || string(result.Fields["future"]) != `{"kept":true}` {
		t.Fatal("invalid exchange result", err)
	}
	authenticated, err := NewClient(Config{Endpoint: server.URL, HTTPClient: server.Client(), Token: result.AccessToken})
	if err != nil {
		t.Fatal(err)
	}
	if err := authenticated.RevokeCredential(context.Background()); err != nil {
		t.Fatal(err)
	}
	if calls.Load() != 2 {
		t.Fatal("unexpected retries")
	}
}

func TestAuthenticationFailures(t *testing.T) {
	for _, test := range []struct {
		status     int
		body, code string
	}{
		{409, `{"error":"quota_exceeded","future":"kept"}`, "quota_exceeded"},
		{403, `{"error":"username_required"}`, "username_required"},
		{400, `{"error":"invalid_code_verifier"}`, "invalid_code_verifier"},
		{429, "ERR rate_limited retry_after_ms=100\n", "rate_limited"},
		{503, "ERR database_unavailable future=kept\n", "database_unavailable"},
		{302, "", ""},
		{500, "invalid JSON", ""},
	} {
		t.Run(fmt.Sprint(test.status, test.code), func(t *testing.T) {
			var calls atomic.Int32
			server := authTestServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				w.Header().Set("Location", "/other")
				w.WriteHeader(test.status)
				fmt.Fprint(w, test.body)
			}))
			defer server.Close()
			c, _ := NewAuthClient(AuthConfig{Endpoint: server.URL, HTTPClient: server.Client()})
			_, err := c.ExchangeCode(context.Background(), CodeExchange{Code: "code", Verifier: "verifier"})
			var httpErr *HTTPError
			if !errors.As(err, &httpErr) || httpErr.StatusCode != test.status || httpErr.Code != test.code {
				t.Fatalf("%v", err)
			}
			authenticated, _ := NewClient(Config{Endpoint: server.URL, HTTPClient: server.Client(), Token: "secret"})
			err = authenticated.RevokeCredential(context.Background())
			if !errors.As(err, &httpErr) || httpErr.StatusCode != test.status || httpErr.Code != test.code {
				t.Fatalf("%v", err)
			}
			if calls.Load() != 2 {
				t.Fatal("redirect or retry occurred")
			}
			if test.code == "rate_limited" && httpErr.Fields["retry_after_ms"] != "100" {
				t.Fatal("lost error metadata")
			}
		})
	}
	for _, body := range []string{`{}`, `null`, `{"actor":"user","access_token":42}`, `{"actor":"user","access_token":"bad\r\ntoken"}`, `{"access_token":"secret"}`, `{"actor":"user","access_token":""}`, `{"actor":"user","access_token":"secret"} trailing`, strings.Repeat("x", maxResponseBytes+1)} {
		server := authTestServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, body) }))
		c, _ := NewAuthClient(AuthConfig{Endpoint: server.URL, HTTPClient: server.Client()})
		if _, err := c.ExchangeCode(context.Background(), CodeExchange{Code: "code", Verifier: "verifier"}); err == nil {
			t.Error("accepted invalid response")
		}
		server.Close()
	}
}

func TestAuthValidationCancellationAndTransportCopy(t *testing.T) {
	for _, endpoint := range []string{"http://remote.example", "https://user:secret@server.example", "https://server.example?query=x", "https://server.example#fragment", "invalid"} {
		if _, err := NewAuthClient(AuthConfig{Endpoint: endpoint}); err == nil {
			t.Error("accepted invalid endpoint")
		}
	}
	var calls atomic.Int32
	server := authTestServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls.Add(1); w.WriteHeader(204) }))
	defer server.Close()
	supplied := server.Client()
	c, err := NewAuthClient(AuthConfig{Endpoint: server.URL, HTTPClient: supplied})
	if err != nil || supplied.CheckRedirect != nil || c.http == supplied {
		t.Fatal("transport not copied", err)
	}
	for _, input := range []CodeExchange{{Code: "code"}, {Verifier: "verifier"}, {Code: strings.Repeat("x", MaxRequestBytes), Verifier: "verifier"}} {
		if _, err := c.ExchangeCode(context.Background(), input); err == nil {
			t.Error("accepted invalid input")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := c.ExchangeCode(ctx, CodeExchange{Code: "code", Verifier: "verifier"}); !errors.Is(err, context.Canceled) {
		t.Fatalf("%v", err)
	}
	authenticated, _ := NewClient(Config{Endpoint: server.URL, HTTPClient: server.Client(), Token: "secret"})
	if err := authenticated.RevokeCredential(ctx); !errors.Is(err, context.Canceled) {
		t.Fatalf("%v", err)
	}
	if calls.Load() != 0 {
		t.Fatal("invalid or canceled operation reached server")
	}
}

// Run handlers through an in-memory transport; live sockets belong to the
// isolated server integration harness.
type authFixtureServer struct {
	URL       string
	transport *http.Client
}

func (s authFixtureServer) Client() *http.Client { return s.transport }
func (s authFixtureServer) Close()               {}
func authTestServer(handler http.Handler) authFixtureServer {
	return authFixtureServer{URL: "https://bibleit.example", transport: &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if err := r.Context().Err(); err != nil {
			return nil, err
		}
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, r)
		response := recorder.Result()
		response.Request = r
		return response, nil
	})}}
}

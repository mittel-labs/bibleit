package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
)

func TestLogoutPreservesCredentialsOnFailure(t *testing.T) {
	for _, status := range []int{204, 401, 500, 503, 302} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			server := authTestServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/api/cli/logout" || r.Header.Get("Authorization") != "Bearer bt_secret" {
					t.Error("incorrect revocation request")
				}
				w.Header().Set("Location", "/redirect")
				w.WriteHeader(status)
				if status != 204 {
					fmt.Fprint(w, "ERR unavailable\n")
				}
			}))
			defer server.Close()
			previousURL, previousClient := defaultWebURL, cliHTTPClient
			defaultWebURL, cliHTTPClient = server.URL, server.Client()
			t.Cleanup(func() { defaultWebURL, cliHTTPClient = previousURL, previousClient })
			t.Setenv("BIBLEIT_CONFIG", filepath.Join(t.TempDir(), "config.json"))
			cfg := config{AccessToken: "bt_secret"}
			if err := saveConfig(cfg); err != nil {
				t.Fatal(err)
			}
			err := logout(&cfg)
			persisted, loadErr := loadConfig()
			if loadErr != nil {
				t.Fatal(loadErr)
			}
			if status == 204 || status == 401 {
				if err != nil || cfg.AccessToken != "" || persisted.AccessToken != "" {
					t.Fatal("logout failed to clear credentials", err)
				}
			} else if err == nil || cfg.AccessToken != "bt_secret" || persisted.AccessToken != "bt_secret" {
				t.Fatal("failed revocation discarded credentials")
			}
		})
	}
}

func TestCLIExchangeUsesClientAndQuotaAdvice(t *testing.T) {
	for _, body := range []string{`{"actor":"user","access_token":"bt_test"}`, `{"actor":"user","identity_name":"@user","access_token":"bt_test"}`, `{"error":"quota_exceeded"}`} {
		server := authTestServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path != "/api/cli/token" {
				t.Error("incorrect path")
			}
			if strings.Contains(body, "quota_exceeded") {
				w.WriteHeader(409)
			}
			fmt.Fprint(w, body)
		}))
		previousClient := cliHTTPClient
		cliHTTPClient = server.Client()
		name, token, err := exchangeBrowserCode(server.URL, "code", "verifier")
		server.Close()
		cliHTTPClient = previousClient
		if strings.Contains(body, "quota_exceeded") {
			if err == nil || !strings.Contains(err.Error(), "CLI credential limit") {
				t.Fatalf("%v", err)
			}
		} else if err != nil || token != "bt_test" || (name != "user" && name != "@user") {
			t.Fatal("invalid CLI exchange", err)
		}
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

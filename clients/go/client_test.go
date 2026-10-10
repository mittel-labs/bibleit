package bibleit

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func reply(status int, body string) *http.Response {
	return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}
}
func testClient(t *testing.T, fn roundTripFunc) *Client {
	t.Helper()
	c, err := NewClient(Config{Endpoint: "https://bibleit.example", Token: "bt_test", HTTPClient: &http.Client{Transport: fn}})
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestHTTPRead(t *testing.T) {
	c := testClient(t, func(r *http.Request) (*http.Response, error) {
		if r.Method != "POST" || r.URL.Path != "/api/cli/command" || r.Header.Get("Authorization") != "Bearer bt_test" || r.Header.Get("Content-Type") != "application/json" {
			t.Fatalf("unexpected request: %v", r)
		}
		var payload map[string]string
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatal(err)
		}
		if payload["command"] != `READ web "Song of Songs" 2 1` {
			t.Fatalf("got %q", payload["command"])
		}
		return reply(200, "OK translation=\"web\" text=\"Verse\"\n"), nil
	})
	result, err := c.Read(context.Background(), Reference{Translation: "web", Book: "Song of Songs", Chapter: 2, Verse: 1})
	if err != nil || result.Records[0].Fields["text"] != "Verse" {
		t.Fatalf("%#v, %v", result, err)
	}
}

func TestHTTPFailures(t *testing.T) {
	for _, tc := range []struct {
		name       string
		status     int
		body, code string
		httpError  bool
	}{
		{"protocol-error", 200, "ERR forbidden\n", "forbidden", false},
		{"unauthorized", 401, "not a protocol reply", "unauthorized", false},
		{"rate-limit", 429, "ERR rate_limited retry_after_ms=250\n", "rate_limited", false},
		{"http-error", 400, `{"error":"invalid_json"}`, "", true},
		{"server-error", 503, "upstream failure", "", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			calls := 0
			c := testClient(t, func(*http.Request) (*http.Response, error) { calls++; return reply(tc.status, tc.body), nil })
			_, err := c.Ping(context.Background())
			if calls != 1 {
				t.Fatalf("retried %d times", calls)
			}
			if tc.httpError {
				var e *HTTPError
				if !errors.As(err, &e) || e.StatusCode != tc.status {
					t.Fatalf("got %v", err)
				}
			} else {
				var e *ServerError
				if !errors.As(err, &e) || e.Code != tc.code {
					t.Fatalf("got %v", err)
				}
			}
		})
	}
}

func TestRedirectIsNotFollowed(t *testing.T) {
	calls := 0
	c := testClient(t, func(*http.Request) (*http.Response, error) {
		calls++
		res := reply(307, "")
		res.Header.Set("Location", "https://another.example/api/cli/command")
		return res, nil
	})
	_, err := c.Ping(context.Background())
	var e *HTTPError
	if !errors.As(err, &e) || e.StatusCode != 307 || calls != 1 {
		t.Fatalf("calls=%d, err=%v", calls, err)
	}
}

func TestCancellation(t *testing.T) {
	c := testClient(t, func(r *http.Request) (*http.Response, error) { <-r.Context().Done(); return nil, r.Context().Err() })
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := c.Ping(ctx)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("got %v", err)
	}
}

func TestHTTPRejectsStreamingAndZeroCommandLocally(t *testing.T) {
	c := testClient(t, func(*http.Request) (*http.Response, error) { t.Fatal("unexpected request"); return nil, nil })
	subscribe, err := LiveCommand("abc", LiveSubscribe)
	if err != nil {
		t.Fatal(err)
	}
	_, err = c.Execute(context.Background(), subscribe)
	var e *ServerError
	if !errors.As(err, &e) || e.Code != "streaming_requires_ssh" {
		t.Fatalf("got %v", err)
	}
	if _, err = c.Execute(context.Background(), Command{}); err == nil {
		t.Fatal("accepted zero command")
	}
}

func TestEndpointValidation(t *testing.T) {
	for _, endpoint := range []string{"http://remote.example", "https://user:pass@example.com", "https://example.com?token=secret", "https://example.com#fragment", "missing"} {
		if _, err := NewClient(Config{Endpoint: endpoint, Token: "bt_test"}); err == nil {
			t.Fatalf("accepted %s", endpoint)
		}
	}
	for _, endpoint := range []string{"https://example.com", "http://127.0.0.1:8080", "http://localhost:8080", "http://[::1]:8080"} {
		if _, err := NewClient(Config{Endpoint: endpoint, Token: "bt_test"}); err != nil {
			t.Fatalf("%s: %v", endpoint, err)
		}
	}
}

func TestRequestSizeLimitsBeforeNetwork(t *testing.T) {
	c := testClient(t, func(*http.Request) (*http.Response, error) {
		t.Fatal("oversized request reached transport")
		return nil, nil
	})
	for _, wire := range []string{strings.Repeat("é", 4097), strings.Repeat("<", 8000)} {
		_, err := c.Execute(context.Background(), Command{wire: wire})
		var e *RequestSizeError
		if !errors.As(err, &e) {
			t.Fatalf("got %v", err)
		}
	}
}

func TestHTTPJSONErrorMetadata(t *testing.T) {
	c := testClient(t, func(*http.Request) (*http.Response, error) {
		return reply(413, `{"error":"request_too_large","limit":8192,"future":"kept"}`), nil
	})
	_, err := c.Ping(context.Background())
	var e *HTTPError
	if !errors.As(err, &e) || e.StatusCode != 413 || e.Code != "request_too_large" || e.Fields["future"] != "kept" {
		t.Fatalf("got %#v", err)
	}
}

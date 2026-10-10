package main

import (
	"encoding/base64"
	"encoding/json"
	bibleit "github.com/mittel-labs/bibleit-cli/clients/go"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func captureCLI(t *testing.T, fn func() int) (int, string, string) {
	t.Helper()
	oldOut, oldErr := os.Stdout, os.Stderr
	outR, outW, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	errR, errW, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	os.Stdout, os.Stderr = outW, errW
	defer func() { os.Stdout, os.Stderr = oldOut, oldErr; outR.Close(); errR.Close(); outW.Close(); errW.Close() }()
	stdoutResult, stderrResult := make(chan []byte, 1), make(chan []byte, 1)
	go func() { data, _ := io.ReadAll(outR); stdoutResult <- data }()
	go func() { data, _ := io.ReadAll(errR); stderrResult <- data }()
	code := fn()
	outW.Close()
	errW.Close()
	return code, string(<-stdoutResult), string(<-stderrResult)
}
func TestLegacyProfileMigrationAndBinding(t *testing.T) {
	for _, test := range []struct{ legacy, transport, endpoint string }{
		{`{"access_token":"bt_legacy"}`, "http", defaultWebURL},
		{`{"identity":"/tmp/key"}`, "ssh", defaultSSHServer},
		{`{}`, "ssh", defaultSSHServer},
	} {
		path := filepath.Join(t.TempDir(), "config.json")
		t.Setenv("BIBLEIT_CONFIG", path)
		if err := os.WriteFile(path, []byte(test.legacy), 0600); err != nil {
			t.Fatal(err)
		}
		c, err := loadConfig()
		if err != nil || c.Name != "default" || c.Transport != test.transport || c.Endpoint != test.endpoint {
			t.Fatalf("migration: %+v %v", c, err)
		}
		if err := saveConfig(c); err != nil {
			t.Fatal(err)
		}
		store, _, err := loadStore()
		if err != nil || store.Version != 1 || store.Profiles["default"].Endpoint != test.endpoint {
			t.Fatal("failed to persist binding", err)
		}
		if c.AccessToken != "" {
			c.Endpoint = "https://other.example"
			if err := saveConfig(c); err == nil {
				t.Fatal("rebound cached credential")
			}
		}
	}
}
func TestNamedProfilesAndAutomationRouting(t *testing.T) {
	t.Setenv("BIBLEIT_CONFIG", filepath.Join(t.TempDir(), "config.json"))
	t.Setenv("BIBLEIT_PROFILE", "")
	t.Setenv("BIBLEIT_TOKEN", "")
	for _, args := range [][]string{{"profile", "add", "one", "--endpoint", "https://one.example"}, {"profile", "add", "two", "--endpoint", "https://two.example"}, {"profile", "add", "ssh", "--endpoint", "server.example:2222", "--transport", "ssh"}} {
		code, _, stderr := captureCLI(t, func() int { return run(args) })
		if code != exitOK {
			t.Fatal(stderr)
		}
	}
	one, _ := loadSelectedConfig("one")
	one.AccessToken = "bt_one"
	if err := saveConfig(one); err != nil {
		t.Fatal(err)
	}
	two, _ := loadSelectedConfig("two")
	two.AccessToken = "bt_two"
	if err := saveConfig(two); err != nil {
		t.Fatal(err)
	}
	old := cliHTTPClient
	defer func() { cliHTTPClient = old }()
	seen := []string{}
	cliHTTPClient = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		seen = append(seen, r.URL.Host+" "+r.Header.Get("Authorization"))
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader("OK pong=true\n"))}, nil
	})}
	for _, args := range [][]string{{"--profile", "two", "ping"}, {"ping"}} {
		code, _, stderr := captureCLI(t, func() int { return run(args) })
		if code != exitOK {
			t.Fatal(stderr)
		}
	}
	t.Setenv("BIBLEIT_PROFILE", "two")
	t.Setenv("BIBLEIT_TOKEN", "bt_environment")
	code, _, stderr := captureCLI(t, func() int { return run([]string{"ping"}) })
	if code != exitOK {
		t.Fatal(stderr)
	}
	if strings.Join(seen, "|") != "two.example Bearer bt_two|one.example Bearer bt_one|two.example Bearer bt_environment" {
		t.Fatalf("unexpected routing %v", seen)
	}
	persisted, _ := loadSelectedConfig("two")
	if persisted.AccessToken != "bt_two" {
		t.Fatal("persisted automation token")
	}
	store, _, _ := loadStore()
	if store.Active != "one" {
		t.Fatal("per-command selection changed active profile")
	}
	code, stdout, _ := captureCLI(t, func() int { return run([]string{"--format", "json", "profile", "list"}) })
	if code != exitOK || strings.Contains(stdout, "bt_") || !strings.Contains(stdout, "credential_cached") {
		t.Fatal("unsafe profile listing")
	}
	code, _, _ = captureCLI(t, func() int { return run([]string{"--profile", "ssh", "ping"}) })
	if code != exitUsage {
		t.Fatal("automation token used for SSH")
	}
	t.Setenv("BIBLEIT_TOKEN", "")
	code, _, _ = captureCLI(t, func() int { return run([]string{"--profile", "two", "--identity", "/tmp/key", "ping"}) })
	if code != exitUsage {
		t.Fatal("HTTP accepted SSH override")
	}
}
func TestProfileValidationAndLifecycle(t *testing.T) {
	t.Setenv("BIBLEIT_CONFIG", filepath.Join(t.TempDir(), "config.json"))
	for _, args := range [][]string{{"profile", "add", "bad", "--endpoint", "http://remote.example"},
		{"profile", "add", "bad", "--endpoint", "https://:443"},
		{"profile", "add", "bad", "--endpoint", "https://server.example:65536"}, {"profile", "add", "bad", "--endpoint", "https://user:password@remote.example"}, {"profile", "add", "bad", "--transport", "ssh", "--endpoint", "host:0"}, {"profile", "add", "bad", "--transport", "ssh", "--endpoint", "host:65536"}, {"profile", "add", "../bad", "--endpoint", "https://server.example"}, {"--profile"}, {"--format", "json", "--format", "raw", "ping"}} {
		code, _, _ := captureCLI(t, func() int { return run(args) })
		if code != exitUsage {
			t.Fatalf("accepted %v: %d", args, code)
		}
	}
	for _, args := range [][]string{{"profile", "add", "a", "--endpoint", "https://a.example"}, {"profile", "add", "b", "--endpoint", "https://b.example"}, {"profile", "use", "b"}, {"profile", "remove", "a"}} {
		code, _, stderr := captureCLI(t, func() int { return run(args) })
		if code != exitOK {
			t.Fatal(stderr)
		}
	}
	code, _, _ := captureCLI(t, func() int { return run([]string{"profile", "remove", "b"}) })
	if code != exitConflict {
		t.Fatal("removed active profile")
	}
	code, _, _ = captureCLI(t, func() int { return run([]string{"profile", "add", "b", "--endpoint", "https://other.example"}) })
	if code != exitConflict {
		t.Fatal("overwrote profile")
	}
	c, _ := loadConfig()
	c.AccessToken = "bt_b"
	if err := saveConfig(c); err != nil {
		t.Fatal(err)
	}
	code, _, _ = captureCLI(t, func() int { return run([]string{"profile", "add", "other", "--endpoint", "https://other.example"}) })
	if code != exitOK {
		t.Fatal("add")
	}
	captureCLI(t, func() int { return run([]string{"profile", "use", "other"}) })
	code, _, _ = captureCLI(t, func() int { return run([]string{"profile", "remove", "b"}) })
	if code != exitConflict {
		t.Fatal("removed cached bearer")
	}
	old := cliHTTPClient
	defer func() { cliHTTPClient = old }()
	cliHTTPClient = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Host != "b.example" {
			t.Error("logout used another endpoint")
		}
		return &http.Response{StatusCode: 204, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(""))}, nil
	})}
	code, _, stderr := captureCLI(t, func() int { return run([]string{"--profile", "b", "auth", "logout"}) })
	if code != exitOK {
		t.Fatal(stderr)
	}
	b, _ := loadSelectedConfig("b")
	if b.Endpoint != "https://b.example" || b.Transport != "http" || b.AccessToken != "" {
		t.Fatal("logout lost binding")
	}
	store, _, _ := loadStore()
	if store.Active != "other" || len(store.Profiles) != 2 {
		t.Fatal("logout changed another profile")
	}
}
func TestVersionedJSONAndErrors(t *testing.T) {
	code, stdout, stderr := captureCLI(t, func() int {
		return printResponse([]string{"OK actor=user count=1", "TOKEN id=001 source=cli issued_at=100 scopes=\"token.get,future.read\" retiring=false label=\"line\\nlabel\" future=007", "END"}, "json")
	})
	var envelope struct {
		Version int  `json:"schema_version"`
		OK      bool `json:"ok"`
		Records []struct {
			Fields map[string]any `json:"fields"`
		} `json:"records"`
	}
	if json.Unmarshal([]byte(stdout), &envelope) != nil || code != exitOK || stderr != "" || envelope.Version != 1 || !envelope.OK {
		t.Fatal("invalid JSON envelope")
	}
	fields := envelope.Records[1].Fields
	if fields["id"] != "001" || fields["issued_at"] != float64(100) || fields["retiring"] != false || fields["future"] != "007" || fields["label"] != "line\nlabel" {
		t.Fatal("incorrect field types")
	}
	if len(fields["scopes"].([]any)) != 2 {
		t.Fatal("lost permission list")
	}
	previous := activeFormat
	activeFormat = "json"
	defer func() { activeFormat = previous }()
	code, stdout, stderr = captureCLI(t, func() int {
		return protocolFailure(&bibleit.ServerError{Code: "rate_limited", Fields: map[string]string{"retry_after_ms": "250", "future": "kept"}})
	})
	var failure map[string]any
	if code != exitRateLimited || stdout != "" || json.Unmarshal([]byte(stderr), &failure) != nil || failure["ok"] != false || failure["schema_version"] != float64(1) {
		t.Fatal("invalid error envelope")
	}
	if failure["error"].(map[string]any)["fields"].(map[string]any)["retry_after_ms"] != "250" {
		t.Fatal("lost retry metadata")
	}
	code, stdout, _ = captureCLI(t, func() int { return printResponse([]string{"OK count=bad"}, "json") })
	if code != exitFailure || stdout != "" {
		t.Fatal("accepted malformed typed field")
	}
}
func TestNDJSONAndControlRendering(t *testing.T) {
	_, stdout, _ := captureCLI(t, func() int {
		for _, line := range []string{"OK id=live subscribed=true", "EVENT verse " + base64.StdEncoding.EncodeToString([]byte(`[{"translation":"web","text":"João\nverse"}]`)), "EVENT closed"} {
			if err := writeSubscriptionLine(line, "ndjson"); err != nil {
				t.Error(err)
			}
		}
		return exitOK
	})
	lines := strings.Split(strings.TrimSpace(stdout), "\n")
	if len(lines) != 3 {
		t.Fatal("not one JSON object per record")
	}
	for i, line := range lines {
		var value map[string]any
		if json.Unmarshal([]byte(line), &value) != nil || value["schema_version"] != float64(1) {
			t.Fatal("invalid stream JSON")
		}
		if i == 2 && value["record"].(map[string]any)["event"] != "closed" {
			t.Fatal("lost event name")
		}
	}
	if humanValue("line\nlabel\t\x1b[31m") != "line\\nlabel\\t\\u001b[31m" {
		t.Fatal("unescaped human controls")
	}
	values, rest, err := parseOptions([]string{"--profile=a", "search", "web", "--", "--format"}, map[string]bool{"--profile": true, "--format": true})
	if err != nil || values["--profile"] != "a" || strings.Join(rest, " ") != "search web --format" {
		t.Fatal("invalid flag terminator")
	}
}

func TestInvalidProfileDocumentsAndLocalHelp(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	t.Setenv("BIBLEIT_CONFIG", path)
	for _, data := range []string{
		`null`, `{"unknown":true}`, `{"profiles":{}}`,
		`{"version":2,"active_profile":"a","profiles":{}}`,
		`{"version":1,"active_profile":"missing","profiles":{"a":{"transport":"http","endpoint":"https://a.example"}}}`,
		`{"version":1,"active_profile":"a","profiles":{"a":{"transport":"http","endpoint":"https://a.example","identity":"/tmp/key"}}}`,
		`{"version":1,"active_profile":"a","profiles":{"a":{"transport":"ssh","endpoint":"a.example:22","access_token":"secret"}}}`,
	} {
		if err := os.WriteFile(path, []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := loadConfig(); err == nil {
			t.Fatal("accepted invalid profile document")
		}
	}
	for _, args := range [][]string{{"--format", "json", "version"}, {"--format", "json", "help", "profile"}} {
		code, stdout, stderr := captureCLI(t, func() int { return run(args) })
		var value map[string]any
		if code != exitOK || stderr != "" || json.Unmarshal([]byte(stdout), &value) != nil || value["schema_version"] != float64(1) {
			t.Fatal("local metadata required config")
		}
	}
}
func TestStreamPayloadAndEmptyErrorFields(t *testing.T) {
	payload := `{"text":"João\nverse","chapter":23,"future":true}`
	record, err := subscriptionRecord("EVENT verse " + base64.StdEncoding.EncodeToString([]byte(payload)))
	if err != nil || string(record.Payload) != payload || record.Event != "verse" || len(record.Fields) != 0 {
		t.Fatal("lost native verse payload")
	}
	for _, line := range []string{"EVENT verse broken", "EVENT verse " + base64.StdEncoding.EncodeToString([]byte("not JSON"))} {
		if _, err := subscriptionRecord(line); err == nil {
			t.Fatal("accepted malformed verse payload")
		}
	}
	previous := activeFormat
	activeFormat = "json"
	defer func() { activeFormat = previous }()
	_, _, stderr := captureCLI(t, func() int { return protocolFailure(&bibleit.HTTPError{StatusCode: 503}) })
	var result map[string]any
	if json.Unmarshal([]byte(stderr), &result) != nil || result["error"].(map[string]any)["fields"] == nil {
		t.Fatal("nullable error fields")
	}
}

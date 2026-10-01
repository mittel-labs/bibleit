package main

import (
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCommandForAllowsOnlyTypedCommands(t *testing.T) {
	command, err := commandFor([]string{"live", "abc123", "start"})
	if err != nil || command != "LIVE abc123 START" {
		t.Fatalf("got %q, %v", command, err)
	}
	if _, err := commandFor([]string{"raw", "LIVE", "DELETE", "ALL"}); err == nil {
		t.Fatal("raw protocol input must not be accepted")
	}
}

func TestCommandForUsesTheCurrentLiveStackCommands(t *testing.T) {
	for input, expected := range map[string]string{
		"live abc pause":                  "LIVE abc PAUSE",
		"live abc resume":                 "LIVE abc RESUME",
		"live abc stack info":             "LIVE abc STACK INFO",
		"live abc stack pop 2":            "LIVE abc STACK POP 2",
		"live abc stack push NVIPT 19 23": "LIVE abc STACK PUSH NVIPT 19 23",
	} {
		command, err := commandFor(strings.Fields(input))
		if err != nil || command != expected {
			t.Fatalf("%s: got %q, %v", input, command, err)
		}
	}
	if _, err := commandFor([]string{"live", "abc", "show"}); err == nil {
		t.Fatal("removed show command must not be dispatched")
	}
}

func TestCommandForSupportsCurrentLiveAndTranslationCommands(t *testing.T) {
	for input, expected := range map[string]string{
		"live create":                         "LIVE CREATE",
		"live create Sunday service":          "LIVE CREATE \"Sunday service\"",
		"live delete all":                     "LIVE DELETE ALL",
		"live abc stats":                      "LIVE abc STATS",
		"live abc secret rotate":              "LIVE abc SECRET ROTATE",
		"live abc secret set audience-secret": "LIVE abc SECRET SET audience-secret",
		"live abc set translations nvipt kjv": "LIVE abc SET TRANSLATIONS nvipt kjv",
		"translation list":                    "ACCOUNT TRANSLATION LIST",
		"translation add nvipt":               "ACCOUNT TRANSLATION ADD nvipt",
		"translation remove nvipt":            "ACCOUNT TRANSLATION REMOVE nvipt",
		"ping":                                "PING",
	} {
		command, err := commandFor(strings.Fields(input))
		if err != nil || command != expected {
			t.Fatalf("%s: got %q, %v", input, command, err)
		}
	}
	for _, input := range []string{"translation list all", "translation info nvipt", "translation catalog nvipt", "translation fetch nvipt", "translation delete nvipt"} {
		if _, err := commandFor(strings.Fields(input)); err == nil {
			t.Fatalf("operator translation command must not be exposed: %s", input)
		}
	}
}

func TestLiveSubscribeUsesTheStreamingPath(t *testing.T) {
	if !isLiveSubscribe([]string{"live", "abc", "subscribe"}) {
		t.Fatal("live subscribe should be detected as a streaming command")
	}
	for _, args := range [][]string{{"live", "abc", "info"}, {"live", "subscribe"}, {"translation", "abc", "subscribe"}} {
		if isLiveSubscribe(args) {
			t.Fatalf("non-subscription command was treated as streaming: %v", args)
		}
	}
}

func TestCommandForRejectsLineBreaks(t *testing.T) {
	if _, err := commandFor([]string{"search", "KJV", "x\nLIVE DELETE ALL"}); err == nil {
		t.Fatal("newline injection must be rejected")
	}
	if _, err := commandFor([]string{"translation", "add", "KJV\nLIVE DELETE ALL"}); err == nil {
		t.Fatal("translation newline injection must be rejected")
	}
}

func TestTakeOptionDoesNotOverwriteItsValue(t *testing.T) {
	value, rest := takeOption([]string{"--identity", "/tmp/dev-key", "auth", "whoami"}, "--identity")
	if value != "/tmp/dev-key" || len(rest) != 2 || rest[0] != "auth" {
		t.Fatalf("got %q and %#v", value, rest)
	}
}

func TestRemovedConnectionFlagsAreRejected(t *testing.T) {
	t.Setenv("BIBLEIT_CONFIG", filepath.Join(t.TempDir(), "config.json"))
	for _, args := range [][]string{
		{"--server", "example.com:22", "ping"},
		{"--web-url", "https://example.com", "ping"},
		{"--user", "someone", "ping"},
		{"--known-hosts", "/tmp/known_hosts", "ping"},
	} {
		if code := run(args); code != exitUsage {
			t.Fatalf("removed flag was accepted: %v", args)
		}
	}
}

func TestVersionDoesNotRequireConfiguration(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(path, []byte("not json"), 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("BIBLEIT_CONFIG", path)
	if code := run([]string{"--version"}); code != exitOK {
		t.Fatalf("version returned %d", code)
	}
}

func TestAuthRequiresTheLoginSubcommand(t *testing.T) {
	t.Setenv("BIBLEIT_CONFIG", filepath.Join(t.TempDir(), "config.json"))
	if code := run([]string{"auth"}); code != exitOK {
		t.Fatalf("auth help returned %d", code)
	}
	if code := run([]string{"auth", "ssh"}); code != exitUsage {
		t.Fatalf("removed auth ssh alias returned %d", code)
	}
	if code := run([]string{"auth", "login", "--ssh"}); code != exitUsage {
		t.Fatalf("unsupported --ssh alias returned %d", code)
	}
}

func TestParseRecordsPreservesQuotedProtocolFields(t *testing.T) {
	records := parseRecords([]string{"OK actor=\"felipe silva\" auth=true", "LIVE id=abc name=\"Sunday Service\" state=started"})
	if len(records) != 2 || records[0].Fields["actor"] != "felipe silva" || records[1].Fields["name"] != "Sunday Service" {
		t.Fatalf("unexpected records: %#v", records)
	}
	if got := orderedHeaders(records[1:]); len(got) != 3 || got[0] != "id" || got[2] != "state" {
		t.Fatalf("unexpected headers: %#v", got)
	}
}

func TestTextOnlyRecordsHaveOneTextColumn(t *testing.T) {
	records := parseRecords([]string{"VERSE text=\"Psalm 23:1\""})
	headers := orderedHeaders(records)
	if len(headers) != 1 || headers[0] != "text" {
		t.Fatalf("unexpected headers: %#v", headers)
	}
}

func TestAuthenticatedIdentityPrefersDisplayIdentity(t *testing.T) {
	actor := authenticatedIdentity([]string{`OK actor="google-123" display_name="Felipe Mamud" identity_name="Felipe Mamud" auth=true`})
	if actor != "Felipe Mamud" {
		t.Fatalf("got %q", actor)
	}
}

func TestAuthenticatedIdentityUsesGithubHandle(t *testing.T) {
	identity := authenticatedIdentity([]string{`OK actor="github-123" display_name="Felipe Mamud" identity_name="@fmamud" auth_provider="github" auth=true`})
	if identity != "@fmamud" {
		t.Fatalf("got %q", identity)
	}
}

func TestValidateSSHIdentityRequiresBothKeyFiles(t *testing.T) {
	directory := t.TempDir()
	identity := filepath.Join(directory, "bibleit")
	if err := os.WriteFile(identity, []byte("private"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := validateSSHIdentity(identity); err == nil {
		t.Fatal("missing public key must be rejected")
	}
	if err := os.WriteFile(identity+".pub", []byte("ssh-ed25519 AAAA test\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if got, err := validateSSHIdentity(identity); err != nil || got != identity {
		t.Fatalf("got %q, %v", got, err)
	}
}

func TestValidateSSHIdentityRequiresExplicitConfiguration(t *testing.T) {
	if _, err := validateSSHIdentity(""); err == nil {
		t.Fatal("an unconfigured identity must be rejected")
	}
}

func TestSSHAuthenticationCanUseOpenSSHIdentitySelection(t *testing.T) {
	previousServer := defaultSSHServer
	defaultSSHServer = "127.0.0.1:1"
	t.Cleanup(func() { defaultSSHServer = previousServer })
	_, err := requestSSH(config{}, "AUTH INFO")
	if err == nil || strings.Contains(err.Error(), "no SSH identity configured") {
		t.Fatalf("expected a connection error after OpenSSH identity selection, got %v", err)
	}
}

func TestWebProfileRunsCommandsWithCachedBearerToken(t *testing.T) {
	previous := cliHTTPClient
	previousWebURL := defaultWebURL
	defaultWebURL = "https://bibleit.example"
	cliHTTPClient = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Path != "/api/cli/command" || r.Header.Get("Authorization") != "Bearer bt_test" {
			return &http.Response{StatusCode: http.StatusUnauthorized, Body: io.NopCloser(strings.NewReader("ERR unauthorized\n")), Header: make(http.Header)}, nil
		}
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader("OK actor=\"browser-user\" auth=true\n")), Header: make(http.Header)}, nil
	})}
	t.Cleanup(func() {
		cliHTTPClient = previous
		defaultWebURL = previousWebURL
	})
	lines, err := request(config{AccessToken: "bt_test"}, "AUTH INFO")
	if err != nil || len(lines) != 1 || !strings.Contains(lines[0], "browser-user") {
		t.Fatalf("got %#v, %v", lines, err)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) { return fn(request) }

func TestConfigPersistsAnActiveProfilePrivately(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".bibleit", "config.json")
	t.Setenv("BIBLEIT_CONFIG", path)
	want := config{AccessToken: "bt_secret"}
	if err := saveConfig(want); err != nil {
		t.Fatal(err)
	}
	got, err := loadConfig()
	if err != nil || got.AccessToken != want.AccessToken || got.Identity != "" {
		t.Fatalf("got %#v, %v", got, err)
	}
	raw, err := os.ReadFile(path)
	if err != nil || string(raw) != "{\"access_token\":\"bt_secret\"}\n" {
		t.Fatalf("unexpected persisted config %q, %v", raw, err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatalf("config mode is %o", info.Mode().Perm())
	}
}

func TestSSHConfigContainsOnlyIdentity(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".bibleit", "config.json")
	t.Setenv("BIBLEIT_CONFIG", path)
	if err := saveConfig(config{Identity: "/tmp/dev-key"}); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(path)
	if err != nil || string(raw) != "{\"identity\":\"/tmp/dev-key\"}\n" {
		t.Fatalf("unexpected persisted SSH config %q, %v", raw, err)
	}
}

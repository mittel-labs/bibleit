package main

import (
	"bytes"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestDestructiveRequestGuard(t *testing.T) {
	t.Setenv("BIBLEIT_CONFIG", filepath.Join(t.TempDir(), "config.json"))
	t.Setenv("BIBLEIT_PROFILE", "")
	t.Setenv("BIBLEIT_TOKEN", "bt_test")
	old := cliHTTPClient
	defer func() { cliHTTPClient = old }()
	requests := 0
	cliHTTPClient = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		requests++
		return &http.Response{StatusCode: 403, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{"error":"forbidden"}`))}, nil
	})}
	commands := [][]string{
		{"live", "delete", "all"}, {"live", "L1", "delete"}, {"live", "L1", "clear"},
		{"live", "L1", "stack", "clear"}, {"live", "L1", "stack", "pop"}, {"live", "L1", "stack", "pop", "2"},
		{"live", "L1", "secret", "rotate"}, {"live", "L1", "secret", "delete"},
	}
	for _, args := range commands {
		t.Run(strings.Join(args, " "), func(t *testing.T) {
			before := requests
			code, out, stderr := captureCLI(t, func() int { return run(append([]string{"--format", "json"}, args...)) })
			if code != exitUsage || out != "" || !strings.Contains(stderr, `"code":"confirmation_required"`) || !strings.Contains(stderr, "--yes") || requests != before {
				t.Fatalf("unguarded: %d %q %q requests=%d", code, out, stderr, requests)
			}
			pipeR, pipeW, err := os.Pipe()
			if err != nil {
				t.Fatal(err)
			}
			oldInput := os.Stdin
			os.Stdin = pipeR
			code, out, stderr = captureCLI(t, func() int { return run(args) })
			os.Stdin = oldInput
			pipeR.Close()
			pipeW.Close()
			if code != exitUsage || out != "" || !strings.Contains(stderr, "--yes") || requests != before {
				t.Fatalf("noninteractive command was not guarded: %d %q %q", code, out, stderr)
			}
			code, _, stderr = captureCLI(t, func() int { return run(append([]string{"--yes"}, args...)) })
			if code != exitForbidden || requests != before+1 {
				t.Fatalf("--yes did not dispatch exactly once: %d %q", code, stderr)
			}
		})
	}
	for _, args := range [][]string{{"live", "L1", "pause"}, {"live", "L1", "secret", "create"}, {"translation", "remove", "KJV"}} {
		before := requests
		code, _, stderr := captureCLI(t, func() int { return run(args) })
		if code != exitForbidden || requests != before+1 {
			t.Fatalf("unexpected prompt %v: %d %s", args, code, stderr)
		}
	}
	before := requests
	code, _, _ := captureCLI(t, func() int { return run([]string{"--yes", "live", "L1", "stack", "pop", "0"}) })
	if code != exitUsage || requests != before {
		t.Fatal("invalid command dispatched")
	}
}

func TestInteractiveConfirmation(t *testing.T) {
	cfg := config{Name: "production", Transport: "http", Endpoint: "https://prod.example", AccessToken: "DO_NOT_PRINT"}
	for _, test := range []struct {
		action, input, format string
		interactive, ok       bool
		code                  string
	}{
		{"Delete Live L1", "yes\n", "table", true, true, ""},
		{"Delete ALL Lives managed by the actor", "delete all\n", "raw", true, true, ""},
		{"Delete ALL Lives managed by the actor", "yes\n", "table", true, false, "cancelled"},
		{"Delete Live L1", "y\n", "table", true, false, "cancelled"},
		{"Delete Live L1", "yes", "table", true, false, "cancelled"},
		{"Delete Live L1", "\n", "table", true, false, "cancelled"},
		{"Delete Live L1", strings.Repeat(" ", 1024) + "yes\n", "table", true, false, "cancelled"},
		{"Delete Live L1", "yes\n", "json", true, false, "confirmation_required"},
		{"Delete Live L1", "yes\n", "table", false, false, "confirmation_required"},
	} {
		var prompt bytes.Buffer
		err := confirmAction(cfg, test.action, test.format, strings.NewReader(test.input), &prompt, test.interactive)
		if (err == nil) != test.ok {
			t.Fatalf("%+v: %v", test, err)
		}
		if err != nil {
			var result *confirmationError
			if !errors.As(err, &result) || result.code != test.code {
				t.Fatalf("wrong error %v", err)
			}
		}
		if test.interactive && test.format != "json" {
			if !strings.Contains(prompt.String(), "production") || !strings.Contains(prompt.String(), "https://prod.example") {
				t.Fatal("missing scope", prompt.String())
			}
		} else if prompt.Len() != 0 {
			t.Fatal("prompted automation")
		}
		if strings.Contains(prompt.String(), cfg.AccessToken) {
			t.Fatal("leaked credential")
		}
	}
	pipeR, pipeW, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer pipeR.Close()
	defer pipeW.Close()
	if terminalInput(pipeR) || terminalInput(pipeW) {
		t.Fatal("pipe treated as terminal")
	}
}

func TestCompletionCandidates(t *testing.T) {
	t.Setenv("BIBLEIT_CONFIG", filepath.Join(t.TempDir(), "config.json"))
	store := profileStore{Version: 1, Active: "prod", Profiles: map[string]profile{"prod": {Transport: "http", Endpoint: "https://prod.example", AccessToken: "TOP_SECRET"}, "preview": {Transport: "http", Endpoint: "https://preview.example"}}}
	if err := saveStore(store); err != nil {
		t.Fatal(err)
	}
	for _, test := range []struct{ words, want []string }{
		{[]string{"li"}, []string{"live"}},
		{[]string{"--profile", "pr"}, []string{"preview", "prod"}},
		{[]string{"--profile=pr"}, []string{"--profile=preview", "--profile=prod"}},
		{[]string{"--profile", "prod", "live", "L1", "st"}, []string{"stack", "start", "stats", "stop"}},
		{[]string{"live", "L1", "stack", "p"}, []string{"pop", "push"}},
		{[]string{"live", "L1", "secret", ""}, []string{"create", "delete", "rotate"}},
		{[]string{"live", "delete", ""}, []string{"all"}},
		{[]string{"profile", "show", "pr"}, []string{"preview", "prod"}},
		{[]string{"profile", "add", "new", "--transport", ""}, []string{"http", "ssh"}},
		{[]string{"--format", "j"}, []string{"json"}},
		{[]string{"completion", ""}, []string{"bash", "fish", "zsh"}},
		{[]string{"read", "KJV", ""}, []string{}},
		{[]string{"live", "L1", "secret", "sensitive", ""}, []string{}},
		{[]string{"--", "search", "KJV", "--"}, []string{}},
	} {
		got := completionCandidates(test.words)
		if !reflect.DeepEqual(got, test.want) {
			t.Fatalf("%v: %v want %v", test.words, got, test.want)
		}
	}
	before, _ := os.ReadFile(configPath())
	old := cliHTTPClient
	defer func() { cliHTTPClient = old }()
	cliHTTPClient = &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		t.Fatal("completion contacted server")
		return nil, errors.New("unexpected request")
	})}
	code, out, stderr := captureCLI(t, func() int { return run([]string{"__complete", "--profile", ""}) })
	if code != exitOK || out != "preview\nprod\n" || stderr != "" {
		t.Fatalf("completion output: %d %q %q", code, out, stderr)
	}
	after, _ := os.ReadFile(configPath())
	if !bytes.Equal(before, after) {
		t.Fatal("completion modified profile")
	}
	if err := os.WriteFile(configPath(), []byte("malformed"), 0600); err != nil {
		t.Fatal(err)
	}
	code, out, stderr = captureCLI(t, func() int { return run([]string{"__complete", "--profile", ""}) })
	if code != exitOK || out != "" || stderr != "" {
		t.Fatal("bad config completion should be quiet")
	}
	for _, shell := range []string{"bash", "zsh", "fish"} {
		code, out, stderr = captureCLI(t, func() int { return run([]string{"completion", shell}) })
		if code != exitOK || out != completionScripts[shell] || stderr != "" {
			t.Fatalf("generator %s failed", shell)
		}
	}
	code, out, stderr = captureCLI(t, func() int { return run([]string{"completion", "bash", "--format", "json"}) })
	if code != exitUsage || out != "" || !strings.Contains(stderr, `"ok":false`) {
		t.Fatal("script generator broke JSON contract")
	}
	code, out, stderr = captureCLI(t, func() int { return run([]string{"completion", "--help", "--format", "json"}) })
	if code != exitOK || !strings.Contains(out, `"type": "help"`) || stderr != "" {
		t.Fatal("completion help failed")
	}
}

func TestBooleanConfirmationOption(t *testing.T) {
	for _, args := range [][]string{{"--yes=false", "ping"}, {"--yes", "--yes", "ping"}} {
		if _, _, err := parseOptions(args, map[string]bool{"--yes": false}); err == nil {
			t.Fatalf("accepted %v", args)
		}
	}
	values, args, err := parseOptions([]string{"--yes", "live", "--", "L1", "delete"}, map[string]bool{"--yes": false})
	if err != nil || values["--yes"] != "true" || !reflect.DeepEqual(args, []string{"live", "L1", "delete"}) {
		t.Fatal(values, args, err)
	}
}

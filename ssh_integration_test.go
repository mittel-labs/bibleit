package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	bibleit "github.com/mittel-labs/bibleit/clients/go"
)

// The harness supplies only temporary keys, a temporary known_hosts file, and
// the loopback listeners belonging to its disposable server snapshot.
func TestServerSSHSubscription(t *testing.T) {
	if os.Getenv("BIBLEIT_CLIENT_TEST_DISPOSABLE") != "1" {
		t.Skip("run python3 scripts/check_server.py --integration")
	}
	previous := defaultSSHServer
	defaultSSHServer = os.Getenv("BIBLEIT_INTEGRATION_SSH")
	defer func() { defaultSSHServer = previous }()
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	client, err := bibleit.NewClient(bibleit.Config{Endpoint: os.Getenv("BIBLEIT_INTEGRATION_ENDPOINT"), Token: os.Getenv("BIBLEIT_INTEGRATION_TOKEN")})
	if err != nil {
		t.Fatal(err)
	}
	create, _ := bibleit.CreateLiveCommand("SSH subscription fixture")
	result, err := client.Execute(ctx, create)
	if err != nil {
		t.Fatal(err)
	}
	id := result.Records[0].Fields["id"]
	deleted := false
	defer func() {
		if !deleted {
			cmd, _ := bibleit.LiveCommand(id, bibleit.LiveDelete)
			_, _ = client.Execute(ctx, cmd)
		}
	}()
	command, _ := bibleit.LiveCommand(id, bibleit.LiveSubscribe)
	cfg := config{Identity: os.Getenv("BIBLEIT_INTEGRATION_IDENTITY")}
	knownHosts := filepath.Join(t.TempDir(), "known_hosts")
	start := func() (*exec.Cmd, io.Reader) {
		t.Helper()
		base, _, err := sshCommand(cfg, command)
		if err != nil {
			t.Fatal(err)
		}
		args := append([]string{"-o", "UserKnownHostsFile=" + knownHosts, "-o", "BatchMode=yes"}, base.Args[1:]...)
		child := exec.CommandContext(ctx, base.Path, args...)
		reader, err := child.StdoutPipe()
		if err != nil {
			t.Fatal(err)
		}
		if err := child.Start(); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = child.Process.Kill(); _ = child.Wait() })
		return child, reader
	}
	execute := func(cmd bibleit.Command) {
		t.Helper()
		if _, err := client.Execute(ctx, cmd); err != nil {
			t.Fatal(err)
		}
	}
	t.Run("endpoint-bound profiles and stable output", func(t *testing.T) {
		t.Setenv("BIBLEIT_CONFIG", filepath.Join(t.TempDir(), "config.json"))
		t.Setenv("BIBLEIT_PROFILE", "")
		t.Setenv("BIBLEIT_TOKEN", "")
		store := profileStore{Version: 1, Active: "http", Profiles: map[string]profile{
			"http": {Transport: "http", Endpoint: os.Getenv("BIBLEIT_INTEGRATION_ENDPOINT"), AccessToken: os.Getenv("BIBLEIT_INTEGRATION_TOKEN")},
			"ssh":  {Transport: "ssh", Endpoint: os.Getenv("BIBLEIT_INTEGRATION_SSH"), Identity: cfg.Identity},
		}}
		if err := saveStore(store); err != nil {
			t.Fatal(err)
		}
		var httpPing any
		for _, args := range [][]string{{"ping"}, {"server", "info"}, {"server", "help", "account"}, {"account", "info"}, {"account", "quotas"}, {"account", "tokens"}, {"translation", "info", "web"}, {"translation", "catalog", "web"}, {"read", "web", "19", "23", "1"}, {"live", id, "info"}, {"live", id, "stats"}} {
			commandArgs := append([]string{"--profile", "http", "--format", "json"}, args...)
			code, stdout, stderr := captureCLI(t, func() int { return run(commandArgs) })
			var result map[string]any
			if code != exitOK || json.Unmarshal([]byte(stdout), &result) != nil || result["schema_version"] != float64(1) {
				t.Fatalf("CLI %v failed: %s", args, stderr)
			}
			if len(args) == 1 {
				httpPing = result
			}
		}
		selected, err := loadSelectedConfig("ssh")
		if err != nil {
			t.Fatal(err)
		}
		base, _, err := sshCommand(selected, bibleit.PingCommand())
		if err != nil {
			t.Fatal(err)
		}
		argv := append([]string{"-o", "UserKnownHostsFile=" + knownHosts, "-o", "BatchMode=yes"}, base.Args[1:]...)
		wire, err := exec.CommandContext(ctx, base.Path, argv...).Output()
		if err != nil {
			t.Fatal(err)
		}
		result, err := bibleit.DecodeCommandResponse(bibleit.PingCommand(), bytes.NewReader(wire))
		if err != nil {
			t.Fatal(err)
		}
		code, stdout, stderr := captureCLI(t, func() int { return printResponse(result.Lines, "json") })
		var sshPing any
		if code != exitOK || json.Unmarshal([]byte(stdout), &sshPing) != nil || !reflect.DeepEqual(httpPing, sshPing) {
			t.Fatalf("HTTP/SSH JSON mismatch: %s", stderr)
		}
	})
	first, reader := start()
	sawVerse, sawPause := false, false
	err = consumeSubscription(reader, func(line string, initial bool) {
		if err := writeSubscriptionLine(line, "ndjson"); err != nil {
			t.Fatal(err)
		}
		if initial {
			stats, err := client.GetLiveStats(ctx, id)
			if err != nil || len(stats.Connections) != 1 || stats.ActorConnections != 1 ||
				stats.Connections[0].Actor != "security-owner" || stats.Connections[0].Access != "actor" ||
				stats.Connections[0].ConnectedAt <= 0 {
				t.Fatalf("subscriber statistics: %+v %v", stats, err)
			}
			push, _ := bibleit.PushLiveCommand(id, bibleit.Reference{Translation: "web", Book: "Psalms", Chapter: 23, Verse: 1})
			execute(push)
		} else if strings.HasPrefix(line, "EVENT verse ") {
			sawVerse = true
			pause, _ := bibleit.LiveCommand(id, bibleit.LivePause)
			execute(pause)
		} else if line == "EVENT paused" {
			sawPause = true
			_ = first.Process.Kill()
		}
	})
	_ = first.Wait()
	if !errors.Is(err, io.ErrUnexpectedEOF) || !sawVerse || !sawPause {
		t.Fatalf("disconnect: verse=%v pause=%v error=%v", sawVerse, sawPause, err)
	}

	_, reader = start()
	acknowledged := false
	err = consumeSubscription(reader, func(line string, initial bool) {
		if err := writeSubscriptionLine(line, "ndjson"); err != nil {
			t.Fatal(err)
		}
		if initial {
			record, err := bibleit.ParseRecord(line)
			if err != nil || record.Fields["paused"] != "true" {
				t.Fatalf("reconnect snapshot: %s %v", line, err)
			}
			acknowledged = true
			remove, _ := bibleit.LiveCommand(id, bibleit.LiveDelete)
			execute(remove)
			deleted = true
		}
	})
	if err != nil || !acknowledged {
		t.Fatalf("closure after reconnect: %v", err)
	}
}

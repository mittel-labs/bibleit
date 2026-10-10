// bibleit is a deliberately small, typed client for bibleit-server protocol v1.
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"strconv"

	bibleit "github.com/mittel-labs/bibleit-cli/clients/go"
	"strings"
	"time"
)

const (
	exitOK = iota
	exitFailure
	exitUsage
	exitUnauthenticated
	exitForbidden
	exitNotFound
	exitConflict
	exitRateLimited
)

type outputRecord struct {
	Type   string
	Fields map[string]string
	order  []string
}

const sshUser = "bibleit-cli"

var (
	cliVersion       = "dev"
	defaultSSHServer = "127.0.0.1:2222"
	defaultWebURL    = "http://127.0.0.1:8080"
	cliHTTPClient    = &http.Client{Timeout: 15 * time.Second}
)

func main() { os.Exit(run(os.Args[1:])) }
func run(args []string) int {
	// Completion arguments are shell words, not options for this invocation.
	if len(args) > 0 && args[0] == "__complete" {
		return completeCommand(args[1:])
	}
	previousFormat := activeFormat
	defer func() { activeFormat = previousFormat }()
	options, args, err := parseOptions(args, map[string]bool{"--format": true, "--identity": true, "--profile": true, "--yes": false})
	format := options["--format"]
	if format == "" {
		format = "table"
	}
	activeFormat = format
	if err != nil {
		return fail(exitUsage, "%v", err)
	}
	if !oneOf(format, "table", "raw", "json", "ndjson") {
		return fail(exitUsage, "unsupported format %q (use table, raw, json, or ndjson)", format)
	}
	if format == "ndjson" && !isLiveSubscribe(args) {
		return fail(exitUsage, "ndjson is for Live subscriptions; use json for finite commands")
	}
	if len(args) == 1 && oneOf(args[0], "version", "--version", "-v") {
		if format == "json" {
			return printLocal("version", map[string]string{"version": cliVersion}, format)
		}
		fmt.Printf("bibleit CLI version %s\n", cliVersion)
		return exitOK
	}
	if len(args) == 0 {
		return help(nil)
	}
	if oneOf(args[0], "help", "--help", "-h") {
		return help(args[1:])
	}
	if oneOf(args[len(args)-1], "--help", "-h") || (args[len(args)-1] == "help" && args[0] != "server") {
		return help([]string{args[0]})
	}
	if len(args) == 1 && oneOf(args[0], "live", "read", "search", "translation", "server", "account", "profile", "completion") {
		return help(args)
	}
	if args[0] == "completion" {
		return completionCommand(args[1:], format)
	}
	if args[0] == "profile" {
		if options["--identity"] != "" {
			return fail(exitUsage, "select an SSH identity with auth login, not profile management")
		}
		return profileCommand(args[1:], format)
	}
	selected := options["--profile"]
	if selected == "" {
		selected = os.Getenv("BIBLEIT_PROFILE")
	}
	cfg, err := loadSelectedConfig(selected)
	if err != nil {
		return fail(exitFailure, "read configuration: %v", err)
	}
	identity := options["--identity"]
	if identity != "" {
		if cfg.Transport != "ssh" && !(cfg.implicit && len(args) >= 3 && args[0] == "auth" && args[1] == "login" && args[2] == "ssh") {
			return fail(exitUsage, "--identity requires an SSH profile")
		}
		cfg.Identity = identity
	}
	if args[0] == "auth" {
		if len(args) > 1 && oneOf(args[1], "info", "whoami") {
			cfg, err = automationCredential(cfg)
			if err != nil {
				return fail(exitUsage, "%v", err)
			}
		}
		return authCommand(cfg, args[1:], format, identity != "")
	}
	cfg, err = automationCredential(cfg)
	if err != nil {
		return fail(exitUsage, "%v", err)
	}
	command, err := commandFor(args)
	if err != nil {
		return fail(exitUsage, "%v", err)
	}
	if action := destructiveAction(args); action != "" && options["--yes"] != "true" {
		if err := confirmAction(cfg, action, format, os.Stdin, os.Stderr, terminalInput(os.Stdin) && terminalInput(os.Stderr)); err != nil {
			var confirmation *confirmationError
			if errors.As(err, &confirmation) && confirmation.code == "confirmation_required" {
				return outputError(exitUsage, err)
			}
			return outputError(exitFailure, err)
		}
	}
	if isLiveSubscribe(args) {
		if cfg.Transport != "ssh" {
			return fail(exitUsage, "Live subscriptions require an SSH profile; select one with --profile")
		}
		if format == "json" {
			return fail(exitUsage, "use --format ndjson for Live subscriptions")
		}
		if err := subscribeSSH(cfg, command, format); err != nil {
			return protocolFailure(err)
		}
		return exitOK
	}
	lines, err := request(cfg, command)
	if err != nil {
		return protocolFailure(err)
	}
	return printResponse(lines, format)
}
func automationCredential(cfg config) (config, error) {
	if token := os.Getenv("BIBLEIT_TOKEN"); token != "" {
		if cfg.Transport != "http" {
			return cfg, errors.New("BIBLEIT_TOKEN requires an HTTP profile")
		}
		if strings.ContainsAny(token, "\r\n\x00") {
			return cfg, errors.New("invalid BIBLEIT_TOKEN")
		}
		cfg.AccessToken = token
	}
	return cfg, nil
}

func isLiveSubscribe(args []string) bool {
	return len(args) == 3 && args[0] == "live" && args[2] == "subscribe"
}
func authCommand(cfg config, args []string, format string, explicitIdentity bool) int {
	if len(args) == 0 {
		return help([]string{"auth"})
	}
	switch args[0] {
	case "help", "--help", "-h":
		return help([]string{"auth"})
	case "login":
		if len(args) == 1 && cfg.Transport != "ssh" {
			actor, err := browserAuthenticate(&cfg)
			if err != nil {
				return protocolFailure(err)
			}
			return printLocal("auth", map[string]string{"identity": actor, "auth": "true", "transport": "http"}, format)
		}
		if len(args) > 2 || (len(args) == 2 && args[1] != "ssh") {
			return usage()
		}
		if cfg.Transport != "ssh" {
			if !cfg.implicit {
				return fail(exitUsage, "SSH login requires an SSH profile; add one with profile add --transport ssh")
			}
			cfg.Transport = "ssh"
			cfg.Endpoint = defaultSSHServer
		}
		if !explicitIdentity {
			// A fresh SSH login without --identity deliberately asks OpenSSH
			// to select from its config and agent, even if an older profile
			// cached an explicit identity path.
			cfg.Identity = ""
		}
		lines, err := requestSSH(cfg, bibleit.IdentityCommand())
		if err != nil {
			return protocolFailure(err)
		}
		identityName := authenticatedIdentity(lines)
		if identityName == "" {
			return fail(exitFailure, "SSH authentication succeeded but the server did not identify the account")
		}
		cfg.AccessToken = ""
		if err := saveConfig(cfg); err != nil {
			return fail(exitFailure, "save configuration: %v", err)
		}
		return printLocal("auth", map[string]string{"identity": identityName, "auth": "true", "transport": "ssh"}, format)
	case "ssh":
		return fail(exitUsage, "`bibleit auth ssh` was renamed; use `bibleit auth login ssh`")
	case "logout":
		if len(args) != 1 {
			return usage()
		}
		if err := logout(&cfg); err != nil {
			return protocolFailure(err)
		}
		return printLocal("auth", map[string]string{"event": "logged_out", "profile": cfg.Name}, format)
	case "whoami", "info":
		if len(args) != 1 {
			return usage()
		}
		lines, err := request(cfg, bibleit.IdentityCommand())
		if err != nil {
			return protocolFailure(err)
		}
		return printResponse(lines, format)
	default:
		return usage()
	}
}
func commandFor(a []string) (bibleit.Command, error) {
	if len(a) == 0 {
		return bibleit.Command{}, errors.New("unsupported command")
	}
	switch a[0] {
	case "ping":
		if len(a) == 1 {
			return bibleit.PingCommand(), nil
		}
	case "server":
		if len(a) == 2 && a[1] == "info" {
			return bibleit.ServerInfoCommand(), nil
		}
		if len(a) == 2 && a[1] == "help" {
			return bibleit.HelpCommand("")
		}
		if len(a) == 3 && a[1] == "help" {
			return bibleit.HelpCommand(a[2])
		}
	case "account":
		if len(a) == 2 && a[1] == "tokens" {
			return bibleit.AccountTokensCommand(), nil
		}
		if len(a) == 2 && a[1] == "info" {
			return bibleit.AccountInfoCommand(), nil
		}
		if len(a) == 2 && a[1] == "quotas" {
			return bibleit.AccountQuotasCommand(), nil
		}
	case "translation":
		if len(a) == 2 && a[1] == "list" {
			return bibleit.TranslationListCommand(), nil
		}
		if len(a) == 3 {
			switch a[1] {
			case "info":
				return bibleit.TranslationInfoCommand(a[2])
			case "catalog":
				return bibleit.TranslationCatalogCommand(a[2])
			case "add":
				return bibleit.AddTranslationCommand(a[2])
			case "remove":
				return bibleit.RemoveTranslationCommand(a[2])
			}
		}
	case "read":
		if len(a) >= 3 && len(a) <= 5 {
			ref, err := cliReference(a[1], a[2:])
			if err != nil {
				return bibleit.Command{}, err
			}
			return bibleit.ReadCommand(ref)
		}
	case "search":
		if len(a) == 3 {
			return bibleit.SearchCommand(a[1], a[2])
		}
	case "live":
		if len(a) == 2 && a[1] == "list" {
			return bibleit.LiveListCommand(), nil
		}
		if len(a) >= 2 && a[1] == "create" {
			return bibleit.CreateLiveCommand(strings.Join(a[2:], " "))
		}
		if len(a) == 3 && a[1] == "delete" && a[2] == "all" {
			return bibleit.DeleteAllLivesCommand(), nil
		}
		if len(a) == 3 && oneOf(a[2], "info", "stats", "start", "stop", "pause", "resume", "delete", "subscribe", "clear") {
			return bibleit.LiveCommand(a[1], bibleit.LiveAction(strings.ToUpper(a[2])))
		}
		if len(a) == 4 && a[2] == "secret" {
			if oneOf(a[3], "create", "rotate", "delete") {
				return bibleit.LiveSecretCommand(a[1], bibleit.SecretAction(strings.ToUpper(a[3])), "")
			}
			return bibleit.LiveSecretCommand(a[1], bibleit.SecretAuthenticate, a[3])
		}
		if len(a) == 5 && a[2] == "secret" && a[3] == "set" {
			return bibleit.Command{}, errors.New("custom Live secret setting is not supported by the server command API; use secret create or secret rotate")
		}
		if len(a) >= 5 && a[2] == "set" && oneOf(a[3], "name", "reference", "translations") {
			values := a[4:]
			if a[3] != "translations" {
				values = []string{strings.Join(values, " ")}
			}
			return bibleit.SetLiveCommand(a[1], bibleit.LiveField(strings.ToUpper(a[3])), values...)
		}
		if len(a) == 4 && a[2] == "stack" && oneOf(a[3], "info", "clear") {
			return bibleit.LiveStackCommand(a[1], bibleit.StackAction(strings.ToUpper(a[3])))
		}
		if len(a) >= 5 && len(a) <= 8 && a[2] == "stack" && a[3] == "push" {
			values := a[4:]
			translation := ""
			// A translation precedes the book when followed by a nonnumeric book,
			// or when four reference components are supplied.
			if len(values) > 1 {
				_, numeric := strconv.Atoi(values[1])
				if numeric != nil || len(values) == 4 {
					translation = values[0]
					values = values[1:]
				}
			}
			ref, err := cliReference(translation, values)
			if err != nil {
				return bibleit.Command{}, err
			}
			return bibleit.PushLiveCommand(a[1], ref)
		}
		if (len(a) == 4 || len(a) == 5) && a[2] == "stack" && a[3] == "pop" {
			count := 0
			if len(a) == 5 {
				var err error
				count, err = strconv.Atoi(a[4])
				if err != nil || count == 0 {
					return bibleit.Command{}, errors.New("invalid pop count")
				}
			}
			return bibleit.PopLiveCommand(a[1], count)
		}
	}
	return bibleit.Command{}, errors.New("unsupported command")
}

func cliReference(translation string, args []string) (bibleit.Reference, error) {
	if len(args) < 1 || len(args) > 3 {
		return bibleit.Reference{}, errors.New("invalid reference")
	}
	ref := bibleit.Reference{Translation: translation, Book: args[0]}
	parts := args[1:]
	if len(parts) == 1 && strings.Contains(parts[0], ":") {
		parts = strings.Split(parts[0], ":")
	}
	if len(parts) > 2 {
		return ref, errors.New("invalid reference")
	}
	for i, part := range parts {
		value, err := strconv.Atoi(part)
		if err != nil || value <= 0 || value > 255 {
			return ref, errors.New("invalid reference")
		}
		if i == 0 {
			ref.Chapter = value
		} else {
			ref.Verse = value
		}
	}
	return ref, nil
}
func oneOf(s string, values ...string) bool {
	for _, v := range values {
		if s == v {
			return true
		}
	}
	return false
}

type authenticationError struct{ message string }

func (e authenticationError) Error() string { return e.message }
func request(cfg config, command bibleit.Command) ([]string, error) {
	if cfg.Transport == "http" || (cfg.Transport == "" && cfg.AccessToken != "") {
		return requestHTTP(cfg, command)
	}
	return requestSSH(cfg, command)
}

func requestSSH(cfg config, command bibleit.Command) ([]string, error) {
	ssh, identity, err := sshCommand(cfg, command)
	if err != nil {
		return nil, err
	}
	var stdout, stderr bytes.Buffer
	ssh.Stdout, ssh.Stderr = &stdout, &stderr
	if err := ssh.Run(); err != nil {
		return nil, sshCommandError(identity, stderr.String(), err)
	}
	result, err := bibleit.DecodeCommandResponse(command, &stdout)
	return result.Lines, err
}

func sshCommand(cfg config, command bibleit.Command) (*exec.Cmd, string, error) {
	identity := ""
	if cfg.Identity != "" {
		var err error
		identity, err = validateSSHIdentity(cfg.Identity)
		if err != nil {
			return nil, "", err
		}
	}
	host, port, err := net.SplitHostPort(profileFor(cfg).Endpoint)
	if err != nil || host == "" || port == "" {
		return nil, "", fmt.Errorf("invalid SSH server address %q", profileFor(cfg).Endpoint)
	}
	targetHost := host
	if strings.Contains(host, ":") {
		targetHost = "[" + host + "]"
	}
	args := []string{"-T", "-p", port}
	if identity != "" {
		args = append(args, "-i", identity, "-o", "IdentitiesOnly=yes")
	}
	args = append(args,
		"-o", "PreferredAuthentications=publickey",
		"-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
		"-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=5")
	args = append(args, "--", sshUser+"@"+targetHost, command.String())
	ssh := exec.Command("ssh", args...)
	ssh.Stdin = os.Stdin
	return ssh, identity, nil
}

func sshCommandError(identity, stderr string, commandErr error) error {
	detail := strings.TrimSpace(stderr)
	if detail == "" {
		detail = commandErr.Error()
	}
	if strings.Contains(strings.ToLower(detail), "permission denied") {
		if identity == "" {
			return authenticationError{message: fmt.Sprintf("SSH public-key authentication was rejected using your OpenSSH configuration and agent. Add the matching public key in the Bibleit dashboard. If OpenSSH did not select the intended key, retry with `bibleit auth login ssh --identity /path/to/private-key`. Server response: %s", detail)}
		}
		return authenticationError{message: fmt.Sprintf("SSH public-key authentication was rejected. Add %s.pub to your account in the Bibleit dashboard before retrying. Server response: %s", identity, detail)}
	}
	return fmt.Errorf("SSH command failed: %s", detail)
}

func subscribeSSH(cfg config, command bibleit.Command, format string) error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()

	ssh, identity, err := sshCommand(cfg, command)
	if err != nil {
		return err
	}
	ssh = exec.CommandContext(ctx, ssh.Path, ssh.Args[1:]...)
	ssh.Stdin = os.Stdin
	stdout, err := ssh.StdoutPipe()
	if err != nil {
		return err
	}
	var stderr bytes.Buffer
	ssh.Stderr = &stderr
	if err := ssh.Start(); err != nil {
		return err
	}

	// Always reap the OpenSSH child, including protocol errors and Ctrl-C.
	defer func() { _ = ssh.Process.Kill(); _ = ssh.Wait() }()
	var streamOutputErr error
	streamErr := consumeSubscription(stdout, func(line string, initial bool) {
		if streamOutputErr != nil {
			return
		}
		if format == "ndjson" || !initial || format == "raw" {
			streamOutputErr = writeSubscriptionLine(line, format)
			if streamOutputErr != nil {
				stop()
			}
		} else {
			printResponse([]string{line}, format)
			fmt.Print("\nWatching Live changes. Press Ctrl-C to stop.\n\n")
		}
	})
	if streamOutputErr != nil {
		return streamOutputErr
	}
	if ctx.Err() != nil {
		return nil
	}
	if errors.Is(streamErr, io.ErrUnexpectedEOF) {
		if err := ssh.Wait(); err != nil {
			return sshCommandError(identity, stderr.String(), err)
		}
	}
	return streamErr
}

func consumeSubscription(reader io.Reader, emit func(string, bool)) error {
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 4096), 2*1024*1024)
	scanner.Split(func(data []byte, atEOF bool) (int, []byte, error) {
		if atEOF && len(data) > 0 && !bytes.Contains(data, []byte{'\n'}) {
			return 0, nil, io.ErrUnexpectedEOF
		}
		return bufio.ScanLines(data, atEOF)
	})
	initial := true
	for scanner.Scan() {
		line := scanner.Text()
		record, err := bibleit.ParseRecord(line)
		if err != nil {
			return fmt.Errorf("read Live subscription: %w", err)
		}
		if record.Type == "err" {
			_, err := bibleit.DecodeResponse(strings.NewReader(line + "\n"))
			return err
		}
		if initial {
			if record.Type != "ok" {
				return errors.New("subscription must start with OK or ERR")
			}
		} else if record.Type != "event" {
			return errors.New("expected a Live subscription EVENT")
		}
		emit(line, initial)
		initial = false
		if line == "EVENT closed" {
			return nil
		}
		if line == "EVENT revoked" {
			return &bibleit.ServerError{Code: "revoked"}
		}
	}
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("read Live subscription: %w", err)
	}
	return io.ErrUnexpectedEOF // Disconnect is not a successful subscription completion.
}

func printSubscriptionLine(line, format string) { printResponse([]string{line}, format) }

func requestHTTP(cfg config, command bibleit.Command) ([]string, error) {
	if cfg.AccessToken == "" {
		return nil, authenticationError{message: "web authentication is not configured; run `bibleit auth login`"}
	}
	client, err := bibleit.NewClient(bibleit.Config{Endpoint: profileFor(cfg).Endpoint, Token: cfg.AccessToken, HTTPClient: cliHTTPClient})
	if err != nil {
		return nil, err
	}
	result, err := client.Execute(context.Background(), command)
	var serverErr *bibleit.ServerError
	if errors.As(err, &serverErr) && serverErr.Code == "unauthorized" {
		return nil, authenticationError{message: "cached web authentication was rejected; run `bibleit auth login` again"}
	}
	return result.Lines, err
}

func browserAuthenticate(cfg *config) (string, error) {
	if _, err := validatedWebURL(profileFor(*cfg).Endpoint); err != nil {
		return "", err
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return "", fmt.Errorf("start local authentication callback: %w", err)
	}
	defer listener.Close()
	verifier, err := randomURLSafe(48)
	if err != nil {
		return "", err
	}
	clientState, err := randomURLSafe(32)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256([]byte(verifier))
	challenge := base64.RawURLEncoding.EncodeToString(digest[:])
	redirectURI := "http://" + listener.Addr().String() + "/callback"
	authorizeURL, err := url.Parse(endpoint(profileFor(*cfg).Endpoint, "/cli/auth"))
	if err != nil {
		return "", err
	}
	query := authorizeURL.Query()
	query.Set("redirect_uri", redirectURI)
	query.Set("state", clientState)
	query.Set("code_challenge", challenge)
	authorizeURL.RawQuery = query.Encode()

	type callback struct{ code, err string }
	result := make(chan callback, 1)
	mux := http.NewServeMux()
	mux.HandleFunc("/callback", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("state") != clientState {
			http.Error(w, "Invalid authentication state.", http.StatusBadRequest)
			select {
			case result <- callback{err: "invalid authentication state"}:
			default:
			}
			return
		}
		code := r.URL.Query().Get("code")
		if code == "" {
			http.Error(w, "Authorization code is missing.", http.StatusBadRequest)
			select {
			case result <- callback{err: "authorization code is missing"}:
			default:
			}
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = io.WriteString(w, `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CLI connected · Bibleit</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#090f1a;color:#f8f3e8;font:16px system-ui,sans-serif}.card{max-width:34rem;margin:2rem;padding:3rem;border:1px solid #344154;border-radius:20px;background:#111a29;box-shadow:0 24px 80px #0008}.mark{color:#f4b942;font-size:2rem}h1{font-size:2.2rem;margin:.8rem 0}p{color:#bac5d5;line-height:1.6}</style></head><body><main class="card"><div class="mark">✦</div><h1>Your CLI is connected now.</h1><p>Authentication completed successfully. Feel free to close this tab and return to your terminal.</p></main></body></html>`)
		select {
		case result <- callback{code: code}:
		default:
		}
	})
	server := &http.Server{Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	go func() { _ = server.Serve(listener) }()

	fmt.Fprintln(os.Stderr, "Opening your browser to authorize Bibleit CLI…")
	if err := openBrowser(authorizeURL.String()); err != nil {
		fmt.Fprintf(os.Stderr, "Could not open a browser automatically. Open this URL:\n%s\n", authorizeURL.String())
	}
	var received callback
	select {
	case received = <-result:
	case <-time.After(30 * time.Minute):
		_ = server.Shutdown(context.Background())
		return "", errors.New("web authentication timed out")
	}
	_ = server.Shutdown(context.Background())
	if received.err != "" {
		return "", errors.New(received.err)
	}
	displayName, token, err := exchangeBrowserCode(profileFor(*cfg).Endpoint, received.code, verifier)
	if err != nil {
		return "", err
	}
	cfg.AccessToken = token
	if err := saveConfig(*cfg); err != nil {
		return "", fmt.Errorf("save configuration: %w", err)
	}
	return displayName, nil
}

func authenticatedIdentity(lines []string) string {
	for _, record := range parseRecords(lines) {
		if identityName := record.Fields["identity_name"]; identityName != "" {
			return identityName
		}
		if displayName := record.Fields["display_name"]; displayName != "" {
			return displayName
		}
		if actor := record.Fields["actor"]; actor != "" {
			return actor
		}
	}
	return ""
}

func exchangeBrowserCode(webURL, code, verifier string) (string, string, error) {
	deviceName, _ := os.Hostname()
	if deviceName == "" {
		deviceName = "Bibleit CLI"
	}
	client, err := bibleit.NewAuthClient(bibleit.AuthConfig{Endpoint: webURL, HTTPClient: cliHTTPClient})
	if err != nil {
		return "", "", err
	}
	payload, err := client.ExchangeCode(context.Background(), bibleit.CodeExchange{Code: code, Verifier: verifier, DeviceName: "Bibleit CLI on " + deviceName})
	if err != nil {
		var httpErr *bibleit.HTTPError
		if errors.As(err, &httpErr) && httpErr.Code == "quota_exceeded" {
			return "", "", errors.New("CLI credential limit reached; revoke an old CLI credential in account settings and try again")
		}
		return "", "", fmt.Errorf("exchange browser authorization: %w", err)
	}
	name := payload.IdentityName
	if name == "" {
		name = payload.DisplayName
	}
	if name == "" {
		name = payload.Actor
	}
	return name, payload.AccessToken, nil
}

func logout(cfg *config) error {
	if cfg.AccessToken != "" {
		client, err := bibleit.NewClient(bibleit.Config{Endpoint: profileFor(*cfg).Endpoint, Token: cfg.AccessToken, HTTPClient: cliHTTPClient})
		if err != nil {
			return err
		}
		if err := client.RevokeCredential(context.Background()); err != nil {
			var httpErr *bibleit.HTTPError
			// An unauthorized credential is already unusable. Other failures
			// leave the local profile intact so the user can retry logout.
			if !errors.As(err, &httpErr) || httpErr.StatusCode != http.StatusUnauthorized {
				return fmt.Errorf("revoke cached web authentication: %w", err)
			}
		}
	}
	next := *cfg
	bound := profileFor(*cfg)
	next.Transport = bound.Transport
	next.Endpoint = bound.Endpoint
	next.AccessToken = ""
	next.Identity = ""
	if err := saveConfig(next); err != nil {
		return err
	}
	*cfg = next
	return nil
}

func validatedWebURL(raw string) (*url.URL, error) {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Host == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, fmt.Errorf("invalid web server URL %q", raw)
	}
	if parsed.Scheme == "http" && !oneOf(parsed.Hostname(), "127.0.0.1", "localhost", "::1") {
		return nil, fmt.Errorf("insecure web server URL %q; remote web authentication requires HTTPS", raw)
	}
	return parsed, nil
}

func endpoint(webURL, path string) string { return strings.TrimRight(webURL, "/") + path }

func randomURLSafe(size int) (string, error) {
	value := make([]byte, size)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(value), nil
}

func openBrowser(target string) error {
	var command *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		command = exec.Command("open", target)
	case "windows":
		command = exec.Command("rundll32", "url.dll,FileProtocolHandler", target)
	default:
		command = exec.Command("xdg-open", target)
	}
	return command.Start()
}

func validateSSHIdentity(identity string) (string, error) {
	if identity == "" {
		return "", authenticationError{message: "no SSH identity configured; pass --identity /path/to/id_ed25519 or set identity in the Bibleit config"}
	}
	identity = expandHome(identity)
	if strings.HasSuffix(identity, ".pub") {
		return "", authenticationError{message: "--identity must point to the private key, not its .pub file"}
	}
	info, err := os.Stat(identity)
	if err != nil {
		return "", authenticationError{message: fmt.Sprintf("read SSH private key: %v", err)}
	}
	if !info.Mode().IsRegular() {
		return "", authenticationError{message: fmt.Sprintf("SSH private key %q is not a regular file", identity)}
	}
	contents, err := os.ReadFile(identity + ".pub")
	if err != nil {
		return "", authenticationError{message: fmt.Sprintf("read SSH public key: %v", err)}
	}
	parts := strings.Fields(string(contents))

	if len(parts) < 2 || !oneOf(parts[0], "ssh-ed25519", "ssh-rsa",
		"ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521") {
		return "", authenticationError{message: "Bibleit supports Ed25519, RSA (2048 bits or larger), and ECDSA P-256/P-384/P-521 public keys"}
	}
	// OpenSSH validates the encoded key rather than trusting its text label.
	fingerprint, err := exec.Command("ssh-keygen", "-l", "-f", identity+".pub").Output()
	if err != nil {
		return "", authenticationError{message: "invalid SSH public key (ssh-keygen could not validate it)"}
	}
	fields := strings.Fields(string(fingerprint))
	if len(fields) < 2 {
		return "", authenticationError{message: "invalid SSH public key fingerprint"}
	}
	bits, err := strconv.Atoi(fields[0])
	if err != nil || (parts[0] == "ssh-rsa" && bits < 2048) {
		return "", authenticationError{message: "Bibleit requires RSA keys of at least 2048 bits"}
	}
	return identity, nil
}

func expandHome(path string) string {
	if path == "~" {
		return homeDirectory()
	}
	if strings.HasPrefix(path, "~/") {
		return filepath.Join(homeDirectory(), strings.TrimPrefix(path, "~/"))
	}
	return path
}
func response(r *bufio.Reader) ([]string, error) {
	result, err := bibleit.DecodeResponse(r)
	return result.Lines, err
}
func parseRecords(lines []string) []outputRecord {
	records := make([]outputRecord, 0, len(lines))
	for _, line := range lines {
		record, err := bibleit.ParseRecord(line)
		if err != nil {
			continue
		}
		records = append(records, outputRecord{Type: record.Type, Fields: record.Fields, order: record.Order})
	}
	return records
}
func printTable(records []outputRecord) {
	if len(records) == 0 {
		return
	}
	rows := records
	if len(records) > 1 && records[0].Type == "ok" {
		rows = records[1:]
	}
	if len(rows) == 1 && rows[0].Type == "ok" {
		if _, event := rows[0].Fields["event"]; event {
			return
		}
		printKeyValue(rows[0])
		return
	}
	headers := orderedHeaders(rows)
	if len(headers) == 0 {
		return
	}
	if len(headers) == 1 && headers[0] == "text" {
		for _, row := range rows {
			fmt.Println(humanValue(row.Fields["text"]))
		}
		return
	}
	widths := make([]int, len(headers))
	for index, header := range headers {
		widths[index] = len(strings.ToUpper(header))
	}
	for _, row := range rows {
		for index, header := range headers {
			widths[index] = max(widths[index], len(humanValue(row.Fields[header])))
		}
	}
	printTableRow(headers, widths, true)
	for _, row := range rows {
		values := make([]string, len(headers))
		for index, header := range headers {
			values[index] = humanValue(row.Fields[header])
		}
		printTableRow(values, widths, false)
	}
}
func orderedHeaders(records []outputRecord) []string {
	var headers []string
	seen := map[string]bool{}
	for _, record := range records {
		for _, key := range record.order {
			if !seen[key] {
				headers, seen[key] = append(headers, key), true
			}
		}
	}
	return headers
}
func printKeyValue(record outputRecord) {
	width := 0
	for _, key := range record.order {
		width = max(width, len(strings.ToUpper(key)))
	}
	for _, key := range record.order {
		fmt.Printf("%-*s  %s\n", width, strings.ToUpper(key), humanValue(record.Fields[key]))
	}
}
func printTableRow(values []string, widths []int, header bool) {
	for index, value := range values {
		if index > 0 {
			fmt.Print("  │ ")
		}
		if header {
			value = strings.ToUpper(value)
		}
		fmt.Printf("%-*s", widths[index], value)
	}
	fmt.Println()
}
func protocolFailure(err error) int {
	code := exitFailure
	var authentication authenticationError
	if errors.As(err, &authentication) {
		code = exitUnauthenticated
	}
	serverCode := ""
	var serverErr *bibleit.ServerError
	if errors.As(err, &serverErr) {
		serverCode = serverErr.Code
	}
	var httpErr *bibleit.HTTPError
	if errors.As(err, &httpErr) {
		serverCode = httpErr.Code
		switch httpErr.StatusCode {
		case 401:
			code = exitUnauthenticated
		case 403:
			code = exitForbidden
		case 404:
			code = exitNotFound
		case 409:
			code = exitConflict
		case 429:
			code = exitRateLimited
		}
	}
	switch serverCode {
	case "unauthorized", "invalid_token", "revoked":
		code = exitUnauthenticated
	case "forbidden":
		code = exitForbidden
	case "not_found", "actor_not_found":
		code = exitNotFound
	case "rate_limited":
		code = exitRateLimited
	case "actor_exists", "quota_exceeded":
		code = exitConflict
	}
	return outputError(code, err)
}
func takeOption(a []string, name string) (string, []string) {
	for i := 0; i < len(a); i++ {
		if a[i] == name && i+1 < len(a) {
			value := a[i+1]
			remaining := append([]string{}, a[:i]...)
			remaining = append(remaining, a[i+2:]...)
			return value, remaining
		}
	}
	return "", a
}
func configPath() string {
	if p := os.Getenv("BIBLEIT_CONFIG"); p != "" {
		return p
	}
	return filepath.Join(homeDirectory(), ".bibleit", "config.json")
}
func homeDirectory() string {
	if home, err := os.UserHomeDir(); err == nil {
		return home
	}
	return "."
}
func usage() int {
	return fail(exitUsage, "usage: bibleit [--profile name] [--identity path] [--format table|raw|json|ndjson] <command>\n\nRun \"bibleit help\" to list commands.")
}
func help(topic []string) int {
	key := strings.Join(topic, " ")
	var lines []string
	switch key {
	case "", "root":
		lines = []string{
			"This is bibleit, the command line interface for bibleit-server.", "",
			"Usage:", "  bibleit [flags]", "  bibleit [command]", "",
			"Reading Scripture", "  read         Read a verse, chapter, or book.", "  search       Search an enabled translation.", "  translation  Manage your account translation library.", "",
			"Live sessions", "  live         Create, inspect, and control Lives you are allowed to manage.", "",
			"Access control", "  auth         Verify SSH access and inspect the current actor.", "  account      Inspect your account and effective quotas.", "  profile      Add, select, and inspect endpoint-bound profiles.", "",
			"Server", "  server       Inspect the connected bibleit-server.", "",
			"Additional Commands:", "  help         Help about any command.", "  version      Print the CLI version.", "  completion   Generate Bash, Zsh, or Fish completion.", "",
			"Flags:", "      --profile name             Select a named endpoint-bound profile", "      --identity path            Select a supported SSH private key", "      --format table|raw|json|ndjson  Output format (default \"table\")", "      --yes                      Confirm destructive commands without a prompt", "  -h, --help                      Help for bibleit.", "  -v, --version                   Print the CLI version.", "",
			"Use \"bibleit [command] --help\" for more information about a command.",
		}
	case "completion":
		lines = []string{"Generate shell completion without contacting the server.", "", "Usage:", "  bibleit completion bash|zsh|fish", "", "Source the generated Bash script, source Zsh after compinit, or save Fish output to ~/.config/fish/completions/bibleit.fish.", "Completes command words, flags and local profile names; Live IDs, translations, references and secrets are not fetched."}
	case "profile":
		lines = []string{"Manage named profiles bound to one server endpoint and transport.", "", "Usage:", "  bibleit profile add <name> --endpoint <https-url> [--transport http]", "  bibleit profile add <name> --endpoint <host:port> --transport ssh", "  bibleit profile list", "  bibleit profile show [name]", "  bibleit profile use <name>", "  bibleit profile remove <name>", "", "Use --profile <name> or BIBLEIT_PROFILE for one command. BIBLEIT_TOKEN supplies an HTTP token without saving it. Profile listings omit tokens."}
	case "auth":
		lines = []string{
			"Authenticate Bibleit CLI through the dashboard or SSH.", "",
			"`bibleit auth login` opens the dedicated CLI sign-in flow in your browser. `bibleit auth login ssh` first uses the SSH agent and identities selected by OpenSSH configuration. Pass --identity only when you need to choose a specific supported SSH key.", "",
			"Usage:", "  bibleit auth login", "  bibleit auth login ssh [--identity <private-key>]", "  bibleit auth info|whoami|logout", "",
			"Commands:", "  login       Authenticate and cache the active profile.", "  info        Show the authenticated actor and permissions.", "  whoami      Alias for auth info.", "  logout      Revoke cached web authentication and clear the active profile.", "",
			"Examples:", "  bibleit auth login", "  bibleit auth login ssh", "  bibleit auth login ssh --identity ~/.ssh/bibleit_local_dev", "  bibleit live list",
		}
	case "live":
		lines = []string{
			"Create, inspect, and control Bibleit Live sessions.", "",
			"Usage:", "  bibleit live [command]", "",
			"Commands:", "  list                              List Lives visible to the authenticated actor.", "  create [name]                     Create an open Live.", "  delete all                        Delete every Live managed by the actor.", "  <id> info|stats                   Show Live details or connection statistics.", "  <id> start|stop                   Change the Live state.", "  <id> pause|resume                 Pause or resume its retained stack.", "  <id> clear                        Clear the stack.", "  <id> secret <value>               Authenticate a Live secret for this connection.", "  <id> secret create|rotate|delete  Manage a Live secret.", "  <id> set name|reference|translations <value...>", "                                    Change Live options.", "  <id> stack info                   Show the current Live stack.", "  <id> stack push [translation] <book> [chapter] [verse]", "                                    Push a reading onto the stack.", "  <id> stack pop [count]            Pop entries from the stack.", "  <id> stack clear                  Clear the stack.", "  <id> subscribe                    Subscribe to a Live.", "  <id> delete                       Delete a Live.", "", "Deletion, stack clear/pop and secret rotation/removal require confirmation.", "Terminal prompts show the profile, endpoint and target; type yes (delete all for bulk deletion).", "Use --yes for automation or JSON output. Cancellation sends no request and exits 1; missing confirmation exits 2.",
		}
	case "read":
		lines = []string{"Read a verse, chapter, or book.", "", "Usage:", "  bibleit read <translation> <book> [chapter] [verse]", "", "Examples:", "  bibleit read KJV John 3 16", "  bibleit read NVIPT Salmos 23"}
	case "search":
		lines = []string{"Search an installed translation.", "", "Usage:", "  bibleit search <translation> <query>", "", "Example:", "  bibleit search KJV \"love one another\""}
	case "translation":
		lines = []string{"Inspect translation metadata and references, and manage your account library.", "", "Usage:", "  bibleit translation list", "  bibleit translation add <translation>", "  bibleit translation remove <translation>", "  bibleit translation info <translation>", "  bibleit translation catalog <translation>", "", "Physical translation installation and deletion are server operator tasks and are not exposed by this CLI."}
	case "account":
		lines = []string{"Inspect your personal account, effective quotas and token metadata.", "", "Usage:", "  bibleit account info", "  bibleit account quotas", "  bibleit account tokens"}
	case "server":
		lines = []string{"Inspect the connected bibleit-server. This reports the remote server and protocol versions, not the CLI version.", "", "Usage:", "  bibleit server info", "  bibleit server help [server|account|auth|translation|live]"}
	default:
		return fail(exitUsage, "unknown help topic %q", key)
	}
	if activeFormat == "json" {
		return printLocal("help", map[string]string{"topic": key, "text": strings.Join(lines, "\n")}, "json")
	}
	fmt.Println(strings.Join(lines, "\n"))
	return exitOK
}
func fail(code int, format string, args ...any) int {
	return outputError(code, fmt.Errorf(format, args...))
}

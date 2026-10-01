// bibleit is a deliberately small, typed client for bibleit-server protocol v1.
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
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

type config struct {
	Identity    string `json:"identity,omitempty"`
	AccessToken string `json:"access_token,omitempty"`
}
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
	if len(args) == 1 && oneOf(args[0], "version", "--version", "-v") {
		fmt.Printf("bibleit CLI version %s\n", cliVersion)
		return exitOK
	}
	format, args := takeOption(args, "--format")
	identity, args := takeOption(args, "--identity")
	explicitIdentity := identity != ""
	cfg, err := loadConfig()
	if err != nil {
		return fail(exitFailure, "read configuration: %v", err)
	}
	if identity != "" {
		cfg.Identity = identity
	}
	if format == "" {
		format = "table"
	}
	if !oneOf(format, "table", "raw", "json") {
		return fail(exitUsage, "unsupported format %q (use table, raw, or json)", format)
	}
	if len(args) == 0 {
		return help(nil)
	}
	if args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		return help(args[1:])
	}
	if args[len(args)-1] == "--help" || args[len(args)-1] == "-h" {
		return help([]string{args[0]})
	}
	if args[len(args)-1] == "help" {
		return help([]string{args[0]})
	}
	if len(args) == 1 && oneOf(args[0], "live", "read", "search", "translation", "server") {
		return help(args)
	}
	if args[0] == "auth" {
		return authCommand(cfg, args[1:], format, explicitIdentity)
	}
	command, err := commandFor(args)
	if err != nil {
		return fail(exitUsage, "%v", err)
	}
	if isLiveSubscribe(args) {
		if err := subscribeSSH(cfg, command, format); err != nil {
			return protocolFailure(err)
		}
		return exitOK
	}
	lines, err := request(cfg, command)
	if err != nil {
		return protocolFailure(err)
	}
	printResponse(lines, format)
	return exitOK
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
		if len(args) == 1 {
			actor, err := browserAuthenticate(&cfg)
			if err != nil {
				return protocolFailure(err)
			}
			fmt.Printf("Successfully logged in as %s.\n", actor)
			return exitOK
		}
		if len(args) != 2 || args[1] != "ssh" {
			return usage()
		}
		if !explicitIdentity {
			// A fresh SSH login without --identity deliberately asks OpenSSH
			// to select from its config and agent, even if an older profile
			// cached an explicit identity path.
			cfg.Identity = ""
		}
		lines, err := requestSSH(cfg, "AUTH INFO")
		if err != nil {
			return protocolFailure(err)
		}
		sshConfig := config{Identity: cfg.Identity}
		if err := saveConfig(sshConfig); err != nil {
			return fail(exitFailure, "save configuration: %v", err)
		}
		identityName := authenticatedIdentity(lines)
		if identityName == "" {
			return fail(exitFailure, "SSH authentication succeeded but the server did not identify the account")
		}
		fmt.Printf("Successfully logged in as %s via SSH.\n", identityName)
		return exitOK
	case "ssh":
		return fail(exitUsage, "`bibleit auth ssh` was renamed; use `bibleit auth login ssh`")
	case "logout":
		if len(args) != 1 {
			return usage()
		}
		if err := logout(&cfg); err != nil {
			return protocolFailure(err)
		}
		fmt.Println("Logged out.")
		return exitOK
	case "whoami", "info":
		lines, err := request(cfg, "AUTH INFO")
		if err != nil {
			return protocolFailure(err)
		}
		printResponse(lines, format)
		return exitOK
	default:
		return usage()
	}
}
func printResponse(lines []string, format string) {
	switch format {
	case "raw":
		fmt.Println(strings.Join(lines, "\n"))
	case "json":
		records := parseRecords(lines)
		jsonRecords := make([]map[string]any, 0, len(records))
		for _, record := range records {
			jsonRecords = append(jsonRecords, map[string]any{"type": record.Type, "fields": record.Fields})
		}
		encoded, _ := json.MarshalIndent(map[string]any{"records": jsonRecords}, "", "  ")
		fmt.Println(string(encoded))
	default:
		printTable(parseRecords(lines))
	}
}
func commandFor(a []string) (string, error) {
	quote := func(v string) (string, error) {
		if v == "" || strings.ContainsAny(v, "\r\n") {
			return "", errors.New("arguments must be non-empty single lines")
		}
		return "\"" + strings.ReplaceAll(strings.ReplaceAll(v, "\\", "\\\\"), "\"", "\\\"") + "\"", nil
	}
	switch a[0] {
	case "ping":
		if len(a) == 1 {
			return "PING", nil
		}
	case "server":
		if len(a) == 2 && a[1] == "info" {
			return "SERVER INFO", nil
		}
	case "translation":
		if len(a) == 2 && a[1] == "list" {
			return "ACCOUNT TRANSLATION LIST", nil
		}
		if len(a) == 3 && oneOf(a[1], "add", "remove") {
			if err := singleLineArguments(a[2:]); err != nil {
				return "", err
			}
			return "ACCOUNT TRANSLATION " + strings.ToUpper(a[1]) + " " + a[2], nil
		}
	case "read":
		if len(a) >= 3 && len(a) <= 5 {
			for _, v := range a[1:] {
				if strings.ContainsAny(v, "\r\n") {
					return "", errors.New("invalid reference")
				}
			}
			return strings.Join(append([]string{"READ"}, a[1:]...), " "), nil
		}
	case "search":
		if len(a) == 3 {
			q, e := quote(a[2])
			return "SEARCH " + a[1] + " " + q, e
		}
	case "live":
		if len(a) == 2 && a[1] == "list" {
			return "LIVE LIST", nil
		}
		if len(a) >= 2 && a[1] == "create" {
			if len(a) == 2 {
				return "LIVE CREATE", nil
			}
			q, e := quote(strings.Join(a[2:], " "))
			return "LIVE CREATE " + q, e
		}
		if len(a) == 3 && a[1] == "delete" && a[2] == "all" {
			return "LIVE DELETE ALL", nil
		}
		if len(a) == 3 && oneOf(a[2], "info", "stats", "start", "stop", "pause", "resume", "delete", "subscribe", "clear") {
			return "LIVE " + a[1] + " " + strings.ToUpper(a[2]), nil
		}
		if len(a) == 4 && a[2] == "secret" && !oneOf(a[3], "rotate", "delete") {
			return "LIVE " + a[1] + " SECRET " + a[3], nil
		}
		if len(a) == 5 && a[2] == "secret" && oneOf(a[3], "set", "rotate", "delete") {
			return "LIVE " + a[1] + " SECRET " + strings.ToUpper(a[3]) + " " + a[4], nil
		}
		if len(a) == 4 && a[2] == "secret" && oneOf(a[3], "rotate", "delete") {
			return "LIVE " + a[1] + " SECRET " + strings.ToUpper(a[3]), nil
		}
		if len(a) >= 5 && a[2] == "set" && oneOf(a[3], "name", "reference", "translations") {
			if err := singleLineArguments(a[4:]); err != nil {
				return "", err
			}
			return "LIVE " + a[1] + " SET " + strings.ToUpper(a[3]) + " " + strings.Join(a[4:], " "), nil
		}
		if len(a) == 4 && a[2] == "stack" && oneOf(a[3], "info", "clear") {
			return "LIVE " + a[1] + " STACK " + strings.ToUpper(a[3]), nil
		}
		if len(a) >= 5 && len(a) <= 8 && a[2] == "stack" && a[3] == "push" {
			if err := singleLineArguments(a[4:]); err != nil {
				return "", err
			}
			return "LIVE " + a[1] + " STACK PUSH " + strings.Join(a[4:], " "), nil
		}
		if len(a) == 4 || len(a) == 5 {
			if a[2] == "stack" && a[3] == "pop" {
				if len(a) == 5 {
					return "LIVE " + a[1] + " STACK POP " + a[4], nil
				}
				return "LIVE " + a[1] + " STACK POP", nil
			}
		}
	}
	return "", errors.New("unsupported command")
}
func oneOf(s string, values ...string) bool {
	for _, v := range values {
		if s == v {
			return true
		}
	}
	return false
}
func singleLineArguments(arguments []string) error {
	for _, argument := range arguments {
		if argument == "" || strings.ContainsAny(argument, "\r\n") {
			return errors.New("arguments must be non-empty single lines")
		}
	}
	return nil
}

type protocolError struct{ code string }
type authenticationError struct{ message string }

func (e protocolError) Error() string       { return e.code }
func (e authenticationError) Error() string { return e.message }
func request(cfg config, command string) ([]string, error) {
	if cfg.AccessToken != "" {
		return requestHTTP(cfg, command)
	}
	return requestSSH(cfg, command)
}

func requestSSH(cfg config, command string) ([]string, error) {
	ssh, identity, err := sshCommand(cfg, command)
	if err != nil {
		return nil, err
	}
	var stdout, stderr bytes.Buffer
	ssh.Stdout, ssh.Stderr = &stdout, &stderr
	if err := ssh.Run(); err != nil {
		return nil, sshCommandError(identity, stderr.String(), err)
	}
	return response(bufio.NewReader(&stdout))
}

func sshCommand(cfg config, command string) (*exec.Cmd, string, error) {
	identity := ""
	if cfg.Identity != "" {
		var err error
		identity, err = validateSSHIdentity(cfg.Identity)
		if err != nil {
			return nil, "", err
		}
	}
	host, port, err := net.SplitHostPort(defaultSSHServer)
	if err != nil || host == "" || port == "" {
		return nil, "", fmt.Errorf("invalid built-in SSH server address %q", defaultSSHServer)
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
	args = append(args, "--", sshUser+"@"+targetHost, command)
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

func subscribeSSH(cfg config, command, format string) error {
	ssh, identity, err := sshCommand(cfg, command)
	if err != nil {
		return err
	}
	stdout, err := ssh.StdoutPipe()
	if err != nil {
		return err
	}
	var stderr bytes.Buffer
	ssh.Stderr = &stderr
	if err := ssh.Start(); err != nil {
		return err
	}

	scanner := bufio.NewScanner(stdout)
	initial := true
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "ERR ") {
			_ = ssh.Process.Kill()
			parts := strings.Fields(line)
			if len(parts) > 1 {
				return protocolError{parts[1]}
			}
			return errors.New(line)
		}
		if initial && strings.HasPrefix(line, "OK") {
			printResponse([]string{line}, format)
			if format == "table" {
				fmt.Print("\nWatching Live changes. Press Ctrl-C to stop.\n\n")
			}
			initial = false
			continue
		}
		printSubscriptionLine(line, format)
		initial = false
	}
	if err := scanner.Err(); err != nil {
		_ = ssh.Process.Kill()
		return fmt.Errorf("read Live subscription: %w", err)
	}
	if err := ssh.Wait(); err != nil {
		return sshCommandError(identity, stderr.String(), err)
	}
	return nil
}

func printSubscriptionLine(line, format string) {
	switch format {
	case "json":
		encoded, _ := json.Marshal(map[string]string{"line": line})
		fmt.Println(string(encoded))
	default:
		fmt.Println(line)
	}
}

func requestHTTP(cfg config, command string) ([]string, error) {
	if cfg.AccessToken == "" {
		return nil, authenticationError{message: "web authentication is not configured; run `bibleit auth login`"}
	}
	if _, err := validatedWebURL(defaultWebURL); err != nil {
		return nil, err
	}
	body, err := json.Marshal(map[string]string{"command": command})
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequest(http.MethodPost, endpoint(defaultWebURL, "/api/cli/command"), bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+cfg.AccessToken)
	req.Header.Set("Content-Type", "application/json")
	res, err := cliHTTPClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("web command failed: %w", err)
	}
	defer res.Body.Close()
	responseBody, err := io.ReadAll(io.LimitReader(res.Body, 2<<20))
	if err != nil {
		return nil, err
	}
	if res.StatusCode == http.StatusUnauthorized {
		return nil, authenticationError{message: "cached web authentication was rejected; run `bibleit auth login` again"}
	}
	if res.StatusCode >= 500 {
		return nil, fmt.Errorf("web command failed with HTTP %d", res.StatusCode)
	}
	return response(bufio.NewReader(bytes.NewReader(responseBody)))
}

func browserAuthenticate(cfg *config) (string, error) {
	if _, err := validatedWebURL(defaultWebURL); err != nil {
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
	authorizeURL, err := url.Parse(endpoint(defaultWebURL, "/cli/auth"))
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

	fmt.Println("Opening your browser to authorize Bibleit CLI…")
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
	displayName, token, err := exchangeBrowserCode(defaultWebURL, received.code, verifier)
	if err != nil {
		return "", err
	}
	cfg.AccessToken = token
	if err := saveConfig(config{AccessToken: token}); err != nil {
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
	form := url.Values{"code": {code}, "code_verifier": {verifier}, "device_name": {"Bibleit CLI on " + deviceName}}
	res, err := cliHTTPClient.PostForm(endpoint(webURL, "/api/cli/token"), form)
	if err != nil {
		return "", "", fmt.Errorf("exchange browser authorization: %w", err)
	}
	defer res.Body.Close()
	body, err := io.ReadAll(io.LimitReader(res.Body, 1<<20))
	if err != nil {
		return "", "", err
	}
	var payload struct {
		Actor        string `json:"actor"`
		IdentityName string `json:"identity_name"`
		DisplayName  string `json:"display_name"`
		AccessToken  string `json:"access_token"`
		Error        string `json:"error"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		return "", "", fmt.Errorf("invalid token response (HTTP %d)", res.StatusCode)
	}
	if res.StatusCode != http.StatusOK || payload.AccessToken == "" {
		if payload.Error == "quota_exceeded" {
			return "", "", errors.New("token quota exceeded; revoke an old token in the dashboard and try again")
		}
		return "", "", fmt.Errorf("web authentication failed: %s", payload.Error)
	}
	if payload.IdentityName == "" {
		payload.IdentityName = payload.DisplayName
	}
	if payload.IdentityName == "" {
		payload.IdentityName = payload.Actor
	}
	return payload.IdentityName, payload.AccessToken, nil
}

func logout(cfg *config) error {
	if cfg.AccessToken != "" {
		if _, err := validatedWebURL(defaultWebURL); err != nil {
			return err
		}
		req, err := http.NewRequest(http.MethodPost, endpoint(defaultWebURL, "/api/cli/logout"), nil)
		if err == nil {
			req.Header.Set("Authorization", "Bearer "+cfg.AccessToken)
			res, requestErr := cliHTTPClient.Do(req)
			if requestErr == nil {
				_ = res.Body.Close()
			} else {
				return fmt.Errorf("revoke cached web authentication: %w", requestErr)
			}
		}
	}
	*cfg = config{}
	return saveConfig(config{})
}

func validatedWebURL(raw string) (*url.URL, error) {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Host == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, fmt.Errorf("invalid built-in web server URL %q", raw)
	}
	if parsed.Scheme == "http" && !oneOf(parsed.Hostname(), "127.0.0.1", "localhost", "::1") {
		return nil, fmt.Errorf("insecure built-in web server URL %q; remote web authentication requires HTTPS", raw)
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
	if len(parts) < 2 || parts[0] != "ssh-ed25519" {
		return "", authenticationError{message: "Bibleit requires an ssh-ed25519 public key"}
	}
	if _, err := base64.StdEncoding.DecodeString(parts[1]); err != nil {
		return "", authenticationError{message: fmt.Sprintf("decode SSH public key: %v", err)}
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
	var lines []string
	for {
		line, e := r.ReadString('\n')
		if e != nil {
			return nil, e
		}
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "ERR ") {
			return nil, protocolError{strings.Fields(line)[1]}
		}
		if line == "END" {
			return lines, nil
		}
		lines = append(lines, line)
		if strings.HasPrefix(line, "OK ") || line == "OK" { // continue only when server streams records
			if !strings.Contains(line, "count=") && !strings.Contains(line, "verses=") &&
				!strings.Contains(line, "results=") && !strings.Contains(line, "books=") {
				return lines, nil
			}
		}
	}
}
func parseRecords(lines []string) []outputRecord {
	records := make([]outputRecord, 0, len(lines))
	for _, line := range lines {
		parts := protocolWords(line)
		if len(parts) == 0 {
			continue
		}
		record := outputRecord{Type: strings.ToLower(parts[0]), Fields: map[string]string{}}
		for _, part := range parts[1:] {
			key, value, ok := strings.Cut(part, "=")
			if ok {
				record.Fields[key] = value
				record.order = append(record.order, key)
			}
		}
		records = append(records, record)
	}
	return records
}
func protocolWords(line string) []string {
	var words []string
	var word strings.Builder
	quoted, escaped := false, false
	flush := func() {
		if word.Len() > 0 {
			words = append(words, word.String())
			word.Reset()
		}
	}
	for _, character := range line {
		switch {
		case escaped:
			word.WriteRune(character)
			escaped = false
		case character == '\\':
			escaped = true
		case character == '"':
			quoted = !quoted
		case character == ' ' && !quoted:
			flush()
		default:
			word.WriteRune(character)
		}
	}
	if escaped {
		word.WriteByte('\\')
	}
	flush()
	return words
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
			fmt.Println(row.Fields["text"])
		}
		return
	}
	widths := make([]int, len(headers))
	for index, header := range headers {
		widths[index] = len(strings.ToUpper(header))
	}
	for _, row := range rows {
		for index, header := range headers {
			widths[index] = max(widths[index], len(row.Fields[header]))
		}
	}
	printTableRow(headers, widths, true)
	for _, row := range rows {
		values := make([]string, len(headers))
		for index, header := range headers {
			values[index] = row.Fields[header]
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
		fmt.Printf("%-*s  %s\n", width, strings.ToUpper(key), record.Fields[key])
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
	var authentication authenticationError
	if errors.As(err, &authentication) {
		return fail(exitUnauthenticated, "%v", err)
	}
	var p protocolError
	if errors.As(err, &p) {
		switch p.code {
		case "unauthorized", "invalid_token":
			return fail(exitUnauthenticated, p.code)
		case "forbidden":
			return fail(exitForbidden, p.code)
		case "not_found", "actor_not_found":
			return fail(exitNotFound, p.code)
		case "rate_limited":
			return fail(exitRateLimited, p.code)
		case "actor_exists", "quota_exceeded":
			return fail(exitConflict, p.code)
		}
	}
	return fail(exitFailure, "%v", err)
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
func loadConfig() (config, error) {
	b, e := os.ReadFile(configPath())
	if os.IsNotExist(e) {
		return config{}, nil
	}
	if e != nil {
		return config{}, e
	}
	var c config
	e = json.Unmarshal(b, &c)
	return c, e
}
func saveConfig(c config) error {
	p := configPath()
	if e := os.MkdirAll(filepath.Dir(p), 0700); e != nil {
		return e
	}
	var value any
	if c.AccessToken != "" {
		value = struct {
			AccessToken string `json:"access_token"`
		}{AccessToken: c.AccessToken}
	} else {
		value = struct {
			Identity string `json:"identity,omitempty"`
		}{Identity: c.Identity}
	}
	b, e := json.Marshal(value)
	if e != nil {
		return e
	}
	temporary, e := os.CreateTemp(filepath.Dir(p), ".config-*.json")
	if e != nil {
		return e
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if e = temporary.Chmod(0600); e == nil {
		_, e = temporary.Write(append(b, '\n'))
	}
	if closeError := temporary.Close(); e == nil {
		e = closeError
	}
	if e != nil {
		return e
	}
	return os.Rename(temporaryPath, p)
}
func usage() int {
	return fail(exitUsage, "usage: bibleit [--identity path] [--format table|raw|json] <command>\n\nRun \"bibleit help\" to list commands.")
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
			"Access control", "  auth         Verify SSH access and inspect the current actor.", "",
			"Server", "  server       Inspect the connected bibleit-server.", "",
			"Additional Commands:", "  help         Help about any command.", "  version      Print the CLI version.", "",
			"Flags:", "      --identity path             SSH Ed25519 private key", "      --format table|raw|json     Output format (default \"table\")", "  -h, --help                      Help for bibleit.", "  -v, --version                   Print the CLI version.", "",
			"Use \"bibleit [command] --help\" for more information about a command.",
		}
	case "auth":
		lines = []string{
			"Authenticate Bibleit CLI through the dashboard or SSH.", "",
			"`bibleit auth login` opens the dedicated CLI sign-in flow in your browser. `bibleit auth login ssh` first uses the SSH agent and identities selected by OpenSSH configuration. Pass --identity only when you need to choose a specific Ed25519 key.", "",
			"Usage:", "  bibleit auth login", "  bibleit auth login ssh [--identity <private-key>]", "  bibleit auth info|whoami|logout", "",
			"Commands:", "  login       Authenticate and cache the active profile.", "  info        Show the authenticated actor and permissions.", "  whoami      Alias for auth info.", "  logout      Revoke cached web authentication and clear the active profile.", "",
			"Examples:", "  bibleit auth login", "  bibleit auth login ssh", "  bibleit auth login ssh --identity ~/.ssh/bibleit_local_dev", "  bibleit live list",
		}
	case "live":
		lines = []string{
			"Create, inspect, and control Bibleit Live sessions.", "",
			"Usage:", "  bibleit live [command]", "",
			"Commands:", "  list                              List Lives visible to the authenticated actor.", "  create [name]                     Create an open Live.", "  delete all                        Delete every Live managed by the actor.", "  <id> info|stats                   Show Live details or connection statistics.", "  <id> start|stop                   Change the Live state.", "  <id> pause|resume                 Pause or resume its retained stack.", "  <id> clear                        Clear the stack.", "  <id> secret <value>               Enter a Live secret for this command.", "  <id> secret set|rotate|delete     Manage a Live secret.", "  <id> set name|reference|translations <value...>", "                                    Change Live options.", "  <id> stack info                   Show the current Live stack.", "  <id> stack push [translation] <book> [chapter] [verse]", "                                    Push a reading onto the stack.", "  <id> stack pop [count]            Pop entries from the stack.", "  <id> stack clear                  Clear the stack.", "  <id> subscribe                    Subscribe to a Live.", "  <id> delete                       Delete a Live.",
		}
	case "read":
		lines = []string{"Read a verse, chapter, or book.", "", "Usage:", "  bibleit read <translation> <book> [chapter] [verse]", "", "Examples:", "  bibleit read KJV John 3 16", "  bibleit read NVIPT Salmos 23"}
	case "search":
		lines = []string{"Search an installed translation.", "", "Usage:", "  bibleit search <translation> <query>", "", "Example:", "  bibleit search KJV \"love one another\""}
	case "translation":
		lines = []string{"Manage the translations enabled for your account.", "", "Usage:", "  bibleit translation list", "  bibleit translation add <translation>", "  bibleit translation remove <translation>", "", "Physical translation installation and deletion are server operator tasks and are not exposed by this CLI."}
	case "server":
		lines = []string{"Inspect the connected bibleit-server. This reports the remote server and protocol versions, not the CLI version.", "", "Usage:", "  bibleit server info"}
	default:
		return fail(exitUsage, "unknown help topic %q", key)
	}
	fmt.Println(strings.Join(lines, "\n"))
	return exitOK
}
func fail(code int, format string, args ...any) int {
	fmt.Fprintf(os.Stderr, "bibleit: "+format+"\n", args...)
	return code
}

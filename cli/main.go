// bibleit is a deliberately small, typed client for bibleit-server protocol v1.
package main

import (
	"bufio"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
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

const sshNamespace = "bibleit@bibleit.app"

type config struct {
	Server   string `json:"server,omitempty"`
	Identity string `json:"identity,omitempty"`
	CAFile   string `json:"ca_file,omitempty"`
	Insecure bool   `json:"insecure,omitempty"`
}
type outputRecord struct {
	Type   string
	Fields map[string]string
	order  []string
}

func main() { os.Exit(run(os.Args[1:])) }
func run(args []string) int {
	server, args := takeOption(args, "--server")
	format, args := takeOption(args, "--format")
	identity, args := takeOption(args, "--identity")
	caFile, args := takeOption(args, "--ca-file")
	insecure, args := takeFlag(args, "--insecure")
	cfg, err := loadConfig()
	if err != nil {
		return fail(exitFailure, "read configuration: %v", err)
	}
	if server != "" {
		cfg.Server = server
	}
	if identity != "" {
		cfg.Identity = identity
	}
	if caFile != "" {
		cfg.CAFile = caFile
	}
	if insecure {
		cfg.Insecure = true
	}
	if cfg.Server == "" {
		cfg.Server = "127.0.0.1:7443"
	}
	if cfg.Identity == "" {
		cfg.Identity = filepath.Join(homeDirectory(), ".ssh", "id_ed25519")
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
	if len(args) == 1 && oneOf(args[0], "auth", "live", "read", "search", "translation", "server") {
		return help(args)
	}
	if args[0] == "auth" {
		return authCommand(cfg, args[1:], format)
	}
	command, err := commandFor(args)
	if err != nil {
		return fail(exitUsage, "%v", err)
	}
	lines, err := request(cfg, command)
	if err != nil {
		return protocolFailure(err)
	}
	printResponse(lines, format)
	return exitOK
}
func authCommand(cfg config, args []string, format string) int {
	if len(args) == 0 {
		return help([]string{"auth"})
	}
	switch args[0] {
	case "help", "--help", "-h":
		return help([]string{"auth"})
	case "login":
		if len(args) != 1 {
			return usage()
		}
		lines, err := authenticatedRequest(cfg, "AUTH INFO")
		if err != nil {
			return protocolFailure(err)
		}
		printResponse(lines, format)
		return exitOK
	case "logout":
		fmt.Println("Logged out. Bibleit closes the authenticated TLS connection after each command.")
		return exitOK
	case "whoami", "info":
		lines, err := authenticatedRequest(cfg, "AUTH INFO")
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
			return "TRANSLATION LIST", nil
		}
		if len(a) == 3 && a[1] == "list" && a[2] == "all" {
			return "TRANSLATION LIST ALL", nil
		}
		if len(a) == 3 && a[1] == "delete" && a[2] == "all" {
			return "TRANSLATION DELETE ALL", nil
		}
		if len(a) == 3 && oneOf(a[1], "info", "catalog", "fetch", "delete") {
			return "TRANSLATION " + strings.ToUpper(a[1]) + " " + a[2], nil
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

func (e protocolError) Error() string { return e.code }
func request(cfg config, command string) ([]string, error) {
	lines, err := requestOnce(cfg, command, false)
	var protocol protocolError
	if !errors.As(err, &protocol) || protocol.code != "unauthorized" {
		return lines, err
	}
	return authenticatedRequest(cfg, command)
}

func authenticatedRequest(cfg config, command string) ([]string, error) {
	return requestOnce(cfg, command, true)
}

func requestOnce(cfg config, command string, authenticate bool) ([]string, error) {
	c, err := dialTLS(cfg)
	if err != nil {
		return nil, err
	}
	defer c.Close()
	_ = c.SetDeadline(time.Now().Add(15 * time.Second))
	r := bufio.NewReader(c)
	if _, err = r.ReadString('\n'); err != nil {
		return nil, err
	}
	if authenticate {
		if err := loginWithKey(c, r, cfg.Identity); err != nil {
			return nil, err
		}
	}
	if _, err = c.Write([]byte(command + "\n")); err != nil {
		return nil, err
	}
	return response(r)
}

func dialTLS(cfg config) (*tls.Conn, error) {
	dialer := &net.Dialer{Timeout: 5 * time.Second}
	address := cfg.Server
	host, _, err := net.SplitHostPort(address)
	if err != nil {
		return nil, fmt.Errorf("invalid --server address %q: %w", address, err)
	}
	tlsConfig := &tls.Config{ServerName: host, MinVersion: tls.VersionTLS13}
	if cfg.Insecure {
		tlsConfig.InsecureSkipVerify = true // explicitly opted in for local development
	}
	if cfg.CAFile != "" {
		pem, err := os.ReadFile(cfg.CAFile)
		if err != nil {
			return nil, fmt.Errorf("read CA certificate: %w", err)
		}
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(pem) {
			return nil, errors.New("CA file contains no certificates")
		}
		tlsConfig.RootCAs = pool
	}
	return tls.DialWithDialer(dialer, "tcp", address, tlsConfig)
}

func loginWithKey(c net.Conn, r *bufio.Reader, identity string) error {
	fingerprint, err := keyFingerprint(identity)
	if err != nil {
		return err
	}
	fields, err := sendOK(c, r, "AUTH LOGIN "+fingerprint)
	if err != nil {
		return err
	}
	challengeID, nonceText := fields["challenge"], fields["nonce"]
	nonce, err := base64.StdEncoding.DecodeString(nonceText)
	if err != nil || challengeID == "" {
		return errors.New("server returned an invalid SSH login challenge")
	}
	message := append([]byte("bibleit-auth-key-v1\x00"+challengeID+"\x00"), nonce...)
	signature, err := sshSignature(identity, message)
	if err != nil {
		return err
	}
	_, err = sendOK(c, r, "AUTH LOGIN PROVE "+challengeID+" "+signature)
	return err
}

func keyFingerprint(identity string) (string, error) {
	publicKeyPath := identity + ".pub"
	if strings.HasSuffix(identity, ".pub") {
		publicKeyPath = identity
	}
	contents, err := os.ReadFile(publicKeyPath)
	if err != nil {
		return "", fmt.Errorf("read SSH public key: %w", err)
	}
	parts := strings.Fields(string(contents))
	if len(parts) < 2 || parts[0] != "ssh-ed25519" {
		return "", errors.New("Bibleit requires an ssh-ed25519 public key")
	}
	blob, err := base64.StdEncoding.DecodeString(parts[1])
	if err != nil {
		return "", fmt.Errorf("decode SSH public key: %w", err)
	}
	sum := sha256.Sum256(blob)
	return "SHA256:" + strings.TrimRight(base64.StdEncoding.EncodeToString(sum[:]), "="), nil
}

func sshSignature(identity string, message []byte) (string, error) {
	command := exec.Command("ssh-keygen", "-Y", "sign", "-f", identity, "-n", sshNamespace)
	command.Stdin = strings.NewReader(string(message))
	output, err := command.Output()
	if err != nil {
		return "", fmt.Errorf("ssh-keygen could not sign the login challenge: %w", err)
	}
	var body strings.Builder
	for _, line := range strings.Split(string(output), "\n") {
		if line != "" && !strings.HasPrefix(line, "-----") {
			body.WriteString(line)
		}
	}
	if body.Len() == 0 {
		return "", errors.New("ssh-keygen returned an invalid SSH signature")
	}
	return body.String(), nil
}

func sendOK(c net.Conn, r *bufio.Reader, s string) (map[string]string, error) {
	if _, e := c.Write([]byte(s + "\n")); e != nil {
		return nil, e
	}
	lines, e := response(r)
	if e != nil || len(lines) == 0 {
		return nil, e
	}
	return parseFields(lines[0]), nil
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
func parseFields(line string) map[string]string {
	out := map[string]string{}
	for _, part := range strings.Fields(line) {
		kv := strings.SplitN(part, "=", 2)
		if len(kv) == 2 {
			out[kv[0]] = strings.Trim(kv[1], "\"")
		}
	}
	return out
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
	var p protocolError
	if errors.As(err, &p) {
		switch p.code {
		case "unauthorized", "invalid_token", "unknown_key", "invalid_signature", "expired_challenge":
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
func takeFlag(a []string, name string) (bool, []string) {
	for i, value := range a {
		if value == name {
			remaining := append([]string{}, a[:i]...)
			remaining = append(remaining, a[i+1:]...)
			return true, remaining
		}
	}
	return false, a
}
func configPath() string {
	if p := os.Getenv("BIBLEIT_CONFIG"); p != "" {
		return p
	}
	d, e := os.UserConfigDir()
	if e != nil {
		return ".bibleit.json"
	}
	return filepath.Join(d, "bibleit", "config.json")
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
	b, e := json.Marshal(c)
	if e != nil {
		return e
	}
	return os.WriteFile(p, b, 0600)
}
func usage() int {
	return fail(exitUsage, "usage: bibleit [--server host:port] [--identity path] [--ca-file path] [--insecure] [--format table|raw|json] <command>\n\nRun \"bibleit help\" to list commands.")
}
func help(topic []string) int {
	key := strings.Join(topic, " ")
	var lines []string
	switch key {
	case "", "root":
		lines = []string{
			"This is bibleit, the command line interface for bibleit-server.", "",
			"Usage:", "  bibleit [flags]", "  bibleit [command]", "",
			"Reading Scripture", "  read         Read a verse, chapter, or book.", "  search       Search an installed translation.", "  translation  Discover installed translations.", "",
			"Live sessions", "  live         Create, inspect, and control Lives you are allowed to manage.", "",
			"Access control", "  auth         Sign in, sign out, and inspect the current actor.", "",
			"Server", "  server       Inspect the connected bibleit-server.", "",
			"Additional Commands:", "  help         Help about any command.", "",
			"Flags:", "      --server host:port          Bibleit TLS server (default \"127.0.0.1:7443\")", "      --identity path             SSH Ed25519 private key (default \"~/.ssh/id_ed25519\")", "      --ca-file path              PEM CA certificate for TLS verification", "      --insecure                  Disable TLS verification (development only)", "      --format table|raw|json     Output format (default \"table\")", "  -h, --help                      Help for bibleit.", "",
			"Use \"bibleit [command] --help\" for more information about a command.",
		}
	case "auth":
		lines = []string{
			"Manage authentication for the local Bibleit CLI.", "",
			"The CLI uses your local SSH Ed25519 private key to sign a one-use server challenge. It never sends or stores the private key.", "",
			"Usage:", "  bibleit auth [command]", "",
			"Commands:", "  login       Verify that the configured SSH key can authenticate.", "  logout      End the local command session (no credential is stored).", "  whoami      Show the authenticated actor and permissions.", "",
			"Examples:", "  bibleit --ca-file ../server/priv/local-cert.pem auth login", "  bibleit auth whoami",
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
		lines = []string{"Discover and manage Bible translations.", "", "Usage:", "  bibleit translation list [all]", "  bibleit translation info|catalog|fetch|delete <translation>"}
	case "server":
		lines = []string{"Inspect the connected bibleit-server.", "", "Usage:", "  bibleit server info"}
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

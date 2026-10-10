package main

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	bibleit "github.com/mittel-labs/bibleit-cli/clients/go"
	"os"
	"sort"
	"strconv"
	"strings"
)

var activeFormat string

type stableRecord struct {
	Type    string          `json:"type"`
	Event   string          `json:"event,omitempty"`
	Raw     string          `json:"raw,omitempty"`
	Payload json.RawMessage `json:"payload,omitempty"`
	Fields  map[string]any  `json:"fields"`
}

func typedRecord(record outputRecord) (stableRecord, error) {
	result := stableRecord{Type: record.Type, Fields: map[string]any{}}
	for key, value := range record.Fields {
		switch {
		case oneOf(key, "paused", "owned", "protected", "retiring", "pong", "active", "removed", "credential_cached") || key == "auth" && record.Type == "ok" || key == "auth" && record.Type == "auth":
			if value != "true" && value != "false" {
				return result, fmt.Errorf("invalid boolean output field %s", key)
			}
			result.Fields[key] = value == "true"
		case oneOf(key, "protocol_version", "count", "verses", "chapters", "results", "books", "commands", "connections", "actor_connections", "anonymous_connections", "running_for_seconds", "revision", "stack_entries", "position", "issued_at", "created_at", "last_used_at", "expires_at", "connected_at", "connected_for_seconds", "plan_activated_at", "lives", "tokens", "keys", "used", "book", "chapter", "verse") || key == "translations" && (record.Fields["event"] == "verse" || record.Fields["lives"] != "") || key == "limit" && value != "unlimited":
			n, err := strconv.ParseInt(value, 10, 64)
			if err != nil || n < 0 {
				return result, fmt.Errorf("invalid numeric output field %s", key)
			}
			result.Fields[key] = n
		case oneOf(key, "roles", "permissions", "capabilities", "scopes", "translations"):
			values := []string{}
			if value != "" {
				values = strings.Split(value, ",")
			}
			result.Fields[key] = values
		default:
			result.Fields[key] = value
		}
	}
	return result, nil
}
func printResponse(lines []string, format string) int {
	if format == "raw" {
		fmt.Println(strings.Join(lines, "\n"))
		return exitOK
	}
	records := []outputRecord{}
	for _, line := range lines {
		if line == "END" {
			continue
		}
		record, err := bibleit.ParseRecord(line)
		if err != nil {
			return protocolFailure(err)
		}
		records = append(records, outputRecord{Type: record.Type, Fields: record.Fields, order: record.Order})
	}
	if format == "ndjson" {
		for _, line := range lines {
			if line == "END" {
				continue
			}
			if err := writeSubscriptionLine(line, format); err != nil {
				return protocolFailure(err)
			}
		}
		return exitOK
	}
	return printOutputRecords(records, format)
}
func printOutputRecords(records []outputRecord, format string) int {
	if format != "json" {
		printTable(records)
		return exitOK
	}
	values := []stableRecord{}
	for _, record := range records {
		value, err := typedRecord(record)
		if err != nil {
			return protocolFailure(err)
		}
		values = append(values, value)
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(map[string]any{"schema_version": 1, "ok": true, "records": values}); err != nil {
		return protocolFailure(err)
	}
	return exitOK
}
func printLocal(kind string, fields map[string]string, format string) int {
	order := []string{}
	for key := range fields {
		order = append(order, key)
	}
	sort.Strings(order)
	return printOutputRecords([]outputRecord{{Type: kind, Fields: fields, order: order}}, format)
}
func parseOptions(args []string, allowed map[string]bool) (map[string]string, []string, error) {
	values := map[string]string{}
	rest := []string{}
	for i := 0; i < len(args); i++ {
		if args[i] == "--" {
			rest = append(rest, args[i+1:]...)
			break
		}
		name, value, inline := strings.Cut(args[i], "=")
		takesValue, known := allowed[name]
		if !known {
			rest = append(rest, args[i])
			continue
		}
		if _, exists := values[name]; exists {
			return values, rest, fmt.Errorf("duplicate option %s", name)
		}
		if !takesValue {
			if inline {
				return values, rest, fmt.Errorf("option %s does not take a value", name)
			}
			values[name] = "true"
			continue
		}
		if !inline {
			if i+1 >= len(args) || strings.HasPrefix(args[i+1], "--") {
				return values, rest, fmt.Errorf("option %s requires a value", name)
			}
			i++
			value = args[i]
		}
		if value == "" {
			return values, rest, fmt.Errorf("option %s requires a value", name)
		}
		values[name] = value
	}
	return values, rest, nil
}
func outputError(code int, err error) int {
	if activeFormat != "json" && activeFormat != "ndjson" {
		fmt.Fprintf(os.Stderr, "bibleit: %v\n", err)
		return code
	}
	names := []string{"ok", "failure", "usage", "unauthenticated", "forbidden", "not_found", "conflict", "rate_limited"}
	detail := map[string]any{"code": names[code], "message": err.Error(), "fields": map[string]any{}}
	var confirmation *confirmationError
	if errors.As(err, &confirmation) {
		detail["code"] = confirmation.code
	}
	var serverErr *bibleit.ServerError
	var httpErr *bibleit.HTTPError
	if errors.As(err, &serverErr) {
		detail["code"] = serverErr.Code
		if serverErr.Fields != nil {
			detail["fields"] = serverErr.Fields
		}
	}
	if errors.As(err, &httpErr) {
		if httpErr.Code != "" {
			detail["code"] = httpErr.Code
		}
		detail["http_status"] = httpErr.StatusCode
		if httpErr.Fields != nil {
			detail["fields"] = httpErr.Fields
		}
	}
	_ = json.NewEncoder(os.Stderr).Encode(map[string]any{"schema_version": 1, "ok": false, "error": detail, "exit_code": code})
	return code
}

func humanValue(value string) string {
	var out strings.Builder
	for _, ch := range value {
		switch ch {
		case '\n':
			out.WriteString(`\n`)
		case '\r':
			out.WriteString(`\r`)
		case '\t':
			out.WriteString(`\t`)
		default:
			if ch < 32 || ch == 127 {
				fmt.Fprintf(&out, `\u%04x`, ch)
			} else {
				out.WriteRune(ch)
			}
		}
	}
	return out.String()
}
func writeSubscriptionLine(line, format string) error {
	if format != "ndjson" {
		value := line
		if format != "raw" {
			value = humanValue(line)
		}
		_, err := fmt.Fprintln(os.Stdout, value)
		return err
	}
	record, err := subscriptionRecord(line)
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"schema_version": 1, "record": record})
}
func subscriptionRecord(line string) (stableRecord, error) {
	parsed, err := bibleit.ParseRecord(line)
	if err != nil {
		return stableRecord{}, err
	}
	parts := strings.Fields(line)
	if parsed.Type == "event" && len(parts) > 1 && parts[1] == "verse" {
		if len(parts) != 3 {
			return stableRecord{}, errors.New("invalid verse event payload")
		}
		payload, err := base64.StdEncoding.DecodeString(parts[2])
		if err != nil || !json.Valid(payload) {
			return stableRecord{}, errors.New("invalid verse event payload")
		}
		return stableRecord{Type: "event", Event: "verse", Fields: map[string]any{}, Payload: json.RawMessage(payload), Raw: line}, nil
	}
	record, err := typedRecord(outputRecord{Type: parsed.Type, Fields: parsed.Fields})
	if err != nil {
		return record, err
	}
	record.Raw = line
	if parsed.Type == "event" {
		if len(parts) > 1 && !strings.Contains(parts[1], "=") {
			record.Event = parts[1]
		} else if _, ok := parsed.Fields["live"]; ok {
			record.Event = "live"
		}
	}
	return record, nil
}

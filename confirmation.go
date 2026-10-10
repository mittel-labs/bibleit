package main

import (
	"bufio"
	"fmt"
	"io"
	"strings"
)

type confirmationError struct{ code, message string }

func (e *confirmationError) Error() string { return e.message }

// Only validated command arguments reach this classification.
func destructiveAction(args []string) string {
	if len(args) == 3 && args[0] == "live" {
		if args[1] == "delete" && args[2] == "all" {
			return "Delete ALL Lives managed by the authenticated actor (including retained stacks and subscriber connections)"
		}
		switch args[2] {
		case "delete":
			return fmt.Sprintf("Delete Live %q, including its retained stack and subscriber connections", args[1])
		case "clear":
			return fmt.Sprintf("Clear every retained stack entry in Live %q", args[1])
		}
	}
	if len(args) >= 4 && args[0] == "live" {
		if args[2] == "stack" {
			switch args[3] {
			case "clear":
				return fmt.Sprintf("Clear every retained stack entry in Live %q", args[1])
			case "pop":
				count := "1"
				if len(args) == 5 {
					count = args[4]
				}
				return fmt.Sprintf("Pop up to %s retained stack entries from Live %q", count, args[1])
			}
		}
		if args[2] == "secret" {
			switch args[3] {
			case "rotate":
				return fmt.Sprintf("Replace the secret for Live %q; the previous audience secret will stop working", args[1])
			case "delete":
				return fmt.Sprintf("Remove secret protection from Live %q, opening audience access", args[1])
			}
		}
	}
	return ""
}

func confirmAction(cfg config, action, format string, input io.Reader, output io.Writer, interactive bool) error {
	context := fmt.Sprintf("%s. Profile %q, %s endpoint %q", action, cfg.Name, cfg.Transport, cfg.Endpoint)
	if !interactive || format == "json" || format == "ndjson" {
		return &confirmationError{"confirmation_required", context + "; rerun with --yes to confirm"}
	}
	answer := "yes"
	if strings.HasPrefix(action, "Delete ALL Lives") {
		answer = "delete all"
	}
	if _, err := fmt.Fprintf(output, "%s.\nType %q to confirm: ", humanValue(context), answer); err != nil {
		return err
	}
	// A single bounded line: never consume piped commands or accept a prefix.
	line, err := bufio.NewReader(io.LimitReader(input, 1025)).ReadString('\n')
	if err != nil || len(line) > 1024 || strings.TrimSpace(line) != answer {
		return &confirmationError{"cancelled", "cancelled; no request sent"}
	}
	return nil
}

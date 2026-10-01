package main

import (
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
		"translation list all":                "TRANSLATION LIST ALL",
		"translation catalog nvipt":           "TRANSLATION CATALOG nvipt",
		"translation delete all":              "TRANSLATION DELETE ALL",
		"ping":                                "PING",
	} {
		command, err := commandFor(strings.Fields(input))
		if err != nil || command != expected {
			t.Fatalf("%s: got %q, %v", input, command, err)
		}
	}
}

func TestCommandForRejectsLineBreaks(t *testing.T) {
	if _, err := commandFor([]string{"search", "KJV", "x\nLIVE DELETE ALL"}); err == nil {
		t.Fatal("newline injection must be rejected")
	}
}

func TestTakeOptionDoesNotOverwriteItsValue(t *testing.T) {
	value, rest := takeOption([]string{"--server", "127.0.0.1:7070", "auth", "login"}, "--server")
	if value != "127.0.0.1:7070" || len(rest) != 2 || rest[0] != "auth" {
		t.Fatalf("got %q and %#v", value, rest)
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

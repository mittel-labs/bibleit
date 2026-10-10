package bibleit

import (
	"encoding/json"
	"errors"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestSharedProtocolFixtures(t *testing.T) {
	body, err := os.ReadFile("../../contract/fixtures/responses-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixtures []struct {
		Name    string `json:"name"`
		Wire    string `json:"wire"`
		Records []struct {
			Type   string            `json:"type"`
			Fields map[string]string `json:"fields"`
		} `json:"records"`
		ErrorCode   string            `json:"error_code"`
		ErrorFields map[string]string `json:"error_fields"`
		Invalid     bool              `json:"invalid"`
	}
	if err := json.Unmarshal(body, &fixtures); err != nil {
		t.Fatal(err)
	}
	for _, f := range fixtures {
		t.Run(f.Name, func(t *testing.T) {
			result, err := DecodeResponse(strings.NewReader(f.Wire))
			if f.Invalid {
				if err == nil {
					t.Fatal("accepted invalid response")
				}
				return
			}
			if f.ErrorCode != "" {
				var serverErr *ServerError
				if !errors.As(err, &serverErr) || serverErr.Code != f.ErrorCode || !reflect.DeepEqual(serverErr.Fields, f.ErrorFields) {
					t.Fatalf("got %v, want %s with %v", err, f.ErrorCode, f.ErrorFields)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if len(result.Records) != len(f.Records) {
				t.Fatalf("got %#v", result)
			}
			for i, expected := range f.Records {
				actual := result.Records[i]
				if actual.Type != expected.Type || !reflect.DeepEqual(actual.Fields, expected.Fields) {
					t.Fatalf("record %d: %#v, want %#v", i, actual, expected)
				}
			}
			wireLines := strings.Split(strings.TrimSuffix(f.Wire, "\n"), "\n")
			if wireLines[len(wireLines)-1] == "END" {
				wireLines = wireLines[:len(wireLines)-1]
			}
			if !reflect.DeepEqual(result.Lines, wireLines) {
				t.Fatalf("raw lines changed: %#v", result.Lines)
			}
		})
	}
}

func TestResponseLimits(t *testing.T) {
	if _, err := DecodeResponse(strings.NewReader("OK text=\"" + strings.Repeat("a", maxResponseBytes) + "\"\n")); err == nil {
		t.Fatal("accepted oversized response")
	}
}

func TestRetryAfter(t *testing.T) {
	for value, want := range map[string]time.Duration{"250": 250 * time.Millisecond, "-1": 0, "bad": 0, "9223372036854775807": 0} {
		if got := (&ServerError{Fields: map[string]string{"retry_after_ms": value}}).RetryAfter(); got != want {
			t.Fatalf("%s: %v", value, got)
		}
	}
}

func TestCommandResponseFraming(t *testing.T) {
	add, _ := AddTranslationCommand("web")
	remove, _ := RemoveTranslationCommand("web")
	for _, cmd := range []Command{TranslationListCommand(), add, remove} {
		if _, err := DecodeCommandResponse(cmd, strings.NewReader("OK translation=web count=1\n")); err != nil {
			t.Fatalf("%s: %v", cmd.String(), err)
		}
	}
	if _, err := DecodeCommandResponse(LiveListCommand(), strings.NewReader("OK count=0\n")); err == nil {
		t.Fatal("accepted a truncated list reply")
	}
	if _, err := DecodeCommandResponse(add, strings.NewReader("OK count=1\nITEM id=1\n")); err == nil {
		t.Fatal("accepted an unterminated multi-record reply")
	}
}

func TestOpaqueCompoundResponseFields(t *testing.T) {
	line := `OK notifications=#{enabled => true,nested => [#{name => "a } b"}]} actor="reader"`
	record, err := ParseRecord(line)
	if err != nil {
		t.Fatal(err)
	}
	if record.Fields["notifications"] != `#{enabled => true,nested => [#{name => "a } b"}]}` || record.Fields["actor"] != "reader" {
		t.Fatalf("%+v", record)
	}
	for _, line := range []string{"OK notifications=#{enabled => true", "OK notifications=#{enabled => true]"} {
		if _, err := ParseRecord(line); err == nil {
			t.Fatal("accepted malformed compound value")
		}
	}
}

func TestMultilineOpaqueAccountField(t *testing.T) {
	wire := "OK actor=reader notifications=#{a => true,\n  b => false} plan=starter\n"
	result, err := DecodeResponse(strings.NewReader(wire))
	if err != nil {
		t.Fatal(err)
	}
	if result.Records[0].Fields["notifications"] != "#{a => true,\n  b => false}" || result.Records[0].Fields["plan"] != "starter" {
		t.Fatalf("%+v", result)
	}
	if len(result.Lines) != 1 || result.Lines[0] != strings.TrimSuffix(wire, "\n") {
		t.Fatal("changed original record")
	}
	if _, err := DecodeResponse(strings.NewReader("OK notifications=#{a => true,\n")); err == nil {
		t.Fatal("accepted incomplete map")
	}
	if _, err := ParseRecord("OK actor=reader\nplan=starter"); err == nil {
		t.Fatal("accepted newline outside compound")
	}
}

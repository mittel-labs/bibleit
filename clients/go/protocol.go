package bibleit

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

// Record preserves unknown v1 fields and their wire order.
type Record struct {
	Type   string
	Fields map[string]string
	Order  []string
}

// Response retains original lines for CLI raw output. END is excluded.
// Protocol v1 fields remain strings; future typed models can build on Records.
type Response struct {
	Lines   []string
	Records []Record
}

// ServerError preserves the server code and metadata, including unknown codes.
type ServerError struct {
	Code   string
	Fields map[string]string
}

func (e *ServerError) Error() string { return e.Code }
func (e *ServerError) RetryAfter() time.Duration {
	ms, err := strconv.ParseInt(e.Fields["retry_after_ms"], 10, 64)
	if err != nil || ms < 0 || ms > int64((1<<63-1)/time.Millisecond) {
		return 0
	}
	return time.Duration(ms) * time.Millisecond
}

var errIncompleteTerm = errors.New("unterminated protocol term")

// ParseRecord decodes response quoting and escaping, rejecting truncated strings.
func ParseRecord(line string) (Record, error) {
	if !utf8.ValidString(line) || strings.ContainsAny(line, "\x00") {
		return Record{}, errors.New("invalid protocol record")
	}
	var words []string
	var word strings.Builder
	quoted, escaped, active := false, false, false
	var compound []rune
	var termQuote rune
	termEscaped := false
	var unicodeEscape string
	unicodeRemaining := 0
	flush := func() {
		if active {
			words = append(words, word.String())
			word.Reset()
			active = false
		}
	}
	for _, ch := range line {
		if unicodeRemaining > 0 {
			if !strings.ContainsRune("0123456789abcdefABCDEF", ch) {
				return Record{}, errors.New("invalid protocol Unicode escape")
			}
			unicodeEscape += string(ch)
			unicodeRemaining--
			if unicodeRemaining == 0 {
				n, _ := strconv.ParseUint(unicodeEscape, 16, 16)
				if n >= 0xd800 && n <= 0xdfff {
					return Record{}, errors.New("invalid protocol Unicode scalar")
				}
				word.WriteRune(rune(n))
			}
			continue
		}
		// The current account encoder writes notifications as an Erlang map.
		// Retain balanced compound values as opaque text; never evaluate them.
		if len(compound) > 0 {
			word.WriteRune(ch)
			if termEscaped {
				termEscaped = false
				continue
			}
			if termQuote != 0 {
				if ch == '\\' {
					termEscaped = true
				} else if ch == termQuote {
					termQuote = 0
				}
				continue
			}
			switch ch {
			case '"', '\'':
				termQuote = ch
			case '{':
				compound = append(compound, '}')
			case '[':
				compound = append(compound, ']')
			case '(':
				compound = append(compound, ')')
			case '}', ']', ')':
				if compound[len(compound)-1] != ch {
					return Record{}, errors.New("mismatched protocol term")
				}
				compound = compound[:len(compound)-1]
			}
			continue
		}
		switch {
		case ch == '\r' || ch == '\n':
			return Record{}, errors.New("newline outside an opaque protocol term")
		case escaped:
			switch ch {
			case '\\', '"':
				word.WriteRune(ch)
			case 'n':
				word.WriteRune('\n')
			case 'r':
				word.WriteRune('\r')
			case 't':
				word.WriteRune('\t')
			case 'u':
				unicodeEscape = ""
				unicodeRemaining = 4
			default:
				return Record{}, errors.New("invalid protocol escape")
			}
			escaped = false
		case ch == '\\' && quoted:
			escaped = true
			active = true
		case ch == '"':
			quoted = !quoted
			active = true
		case !quoted && (ch == '{' || ch == '[' || ch == '(') && strings.Contains(word.String(), "="):
			word.WriteRune(ch)
			switch ch {
			case '{':
				compound = append(compound, '}')
			case '[':
				compound = append(compound, ']')
			case '(':
				compound = append(compound, ')')
			}
			active = true
		case (ch == ' ' || ch == '\t') && !quoted:
			flush()
		default:
			word.WriteRune(ch)
			active = true
		}
	}
	if len(compound) > 0 {
		return Record{}, errIncompleteTerm
	}
	if quoted || escaped || unicodeRemaining > 0 {
		return Record{}, errors.New("unterminated protocol string")
	}
	flush()
	if len(words) == 0 {
		return Record{}, errors.New("empty protocol record")
	}
	r := Record{Type: strings.ToLower(words[0]), Fields: map[string]string{}}
	for _, part := range words[1:] {
		key, value, ok := strings.Cut(part, "=")
		if !ok {
			continue
		} // EVENT records may have a positional event name.
		if key == "" {
			return Record{}, errors.New("empty protocol field")
		}
		if previous, exists := r.Fields[key]; exists {
			// Current LIVE STATS emits connections twice. Identical values are
			// unambiguous; conflicting duplicates remain malformed.
			if previous != value {
				return Record{}, fmt.Errorf("conflicting protocol field %q", key)
			}
			continue
		}
		r.Fields[key] = value
		r.Order = append(r.Order, key)
	}
	return r, nil
}

// DecodeResponse decodes one finite HTTP or SSH-exec reply, requiring END for
// multi-record replies. It is not a decoder for a persistent SSH subscription.
func DecodeResponse(reader io.Reader) (Response, error) {
	return decodeResponse(reader, false)
}

// DecodeCommandResponse uses the command's framing contract for a finite reply.
// Account translation replies contain count but are single records without END.
func DecodeCommandResponse(command Command, reader io.Reader) (Response, error) {
	if command.wire == "" || command.streaming {
		return Response{}, errors.New("a finite validated command is required")
	}
	return decodeResponse(reader, strings.HasPrefix(command.wire, "ACCOUNT TRANSLATION "))
}

func decodeResponse(reader io.Reader, singleRecord bool) (Response, error) {
	body, err := io.ReadAll(io.LimitReader(reader, maxResponseBytes+1))
	if err != nil {
		return Response{}, err
	}
	if len(body) > maxResponseBytes {
		return Response{}, errors.New("protocol response exceeds 2 MiB")
	}
	if len(body) == 0 || body[len(body)-1] != '\n' {
		return Response{}, io.ErrUnexpectedEOF
	}
	scanner := bufio.NewScanner(strings.NewReader(string(body)))
	scanner.Buffer(make([]byte, 4096), maxResponseBytes+1)
	var result Response
	size := 0
	ended := false
	var serverError *ServerError
	var pending string
	for scanner.Scan() {
		line := scanner.Text()
		size += len(line) + 1
		if size > maxResponseBytes {
			return Response{}, errors.New("protocol response exceeds 2 MiB")
		}
		if ended {
			return Response{}, errors.New("unexpected data after END")
		}
		if serverError != nil {
			return Response{}, errors.New("unexpected data after ERR")
		}
		if line == "END" {
			if len(result.Records) == 0 {
				return Response{}, errors.New("unexpected END")
			}
			ended = true
			continue
		}
		if pending != "" {
			line = pending + "\n" + line
		}
		record, err := ParseRecord(line)
		if errors.Is(err, errIncompleteTerm) {
			pending = line
			continue
		}
		if err != nil {
			return Response{}, err
		}
		pending = ""
		if len(result.Records) == 0 {
			if record.Type == "err" {
				words := strings.Fields(line)
				if len(words) < 2 || strings.Contains(words[1], "=") {
					return Response{}, errors.New("missing server error code")
				}
				serverError = &ServerError{Code: words[1], Fields: record.Fields}
				continue
			}
			if record.Type != "ok" {
				return Response{}, errors.New("response must start with OK or ERR")
			}
		} else if record.Type == "ok" || record.Type == "err" || record.Type == "event" {
			return Response{}, errors.New("unexpected response envelope")
		}
		result.Lines = append(result.Lines, line)
		result.Records = append(result.Records, record)
	}
	if err := scanner.Err(); err != nil {
		return Response{}, err
	}
	if pending != "" {
		return Response{}, io.ErrUnexpectedEOF
	}
	if serverError != nil {
		return Response{}, serverError
	}
	if len(result.Records) == 0 {
		return Response{}, io.ErrUnexpectedEOF
	}
	if !ended {
		if len(result.Records) > 1 || (!singleRecord && multiRecord(result.Records[0])) {
			return Response{}, io.ErrUnexpectedEOF
		}
	}
	return result, nil
}

func multiRecord(header Record) bool {
	for _, key := range []string{"count", "verses", "results", "books", "commands", "connections"} {
		if _, ok := header.Fields[key]; ok {
			return true
		}
	}
	_, translations := header.Fields["translations"]
	return header.Fields["event"] == "verse" && translations
}

package bibleit

import (
	"context"
	"errors"
	"testing"
)

func TestTypedTokenMetadata(t *testing.T) {
	c := discoveryClient(t, map[string]string{"ACCOUNT TOKEN LIST": "OK actor=user count=2 future=header\nTOKEN id=one source=manual issued_at=100 issued_by=user label=\"João\\nwork\\tkey\\u007f\" scopes=\"\" retiring=false future=row\nTOKEN id=two source=future-source issued_at=0 scopes=\"live.get,future.read\" expires_at=200 last_used_at=0 retiring=true\nEND\n"})
	value, err := c.ListTokens(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if value.Actor != "user" || len(value.Tokens) != 2 || value.Raw.Records[0].Fields["future"] != "header" {
		t.Fatalf("%+v", value)
	}
	one, two := value.Tokens[0], value.Tokens[1]
	if one.Label == nil || *one.Label != "João\nwork\tkey\x7f" || one.Scopes == nil || len(one.Scopes) != 0 || one.ExpiresAt != nil || one.LastUsedAt != nil || one.Retiring == nil || *one.Retiring || one.Fields["future"] != "row" {
		t.Fatalf("%+v", one)
	}
	if two.Source != "future-source" || two.ExpiresAt == nil || *two.ExpiresAt != 200 || two.LastUsedAt == nil || *two.LastUsedAt != 0 || two.Label != nil || two.IssuedBy != nil || len(two.Scopes) != 2 || two.Scopes[1] != "future.read" || two.Retiring == nil || !*two.Retiring {
		t.Fatalf("%+v", two)
	}
	c = discoveryClient(t, map[string]string{"ACCOUNT TOKEN LIST": "OK actor=user count=1\nTOKEN id=one source=manual issued_at=1\nEND\n"})
	value, err = c.ListTokens(context.Background())
	if err != nil || value.Tokens[0].Scopes != nil || value.Tokens[0].Retiring != nil {
		t.Fatalf("%+v %v", value, err)
	}
	c = discoveryClient(t, map[string]string{"ACCOUNT TOKEN LIST": "OK actor=user count=0\nEND\n"})
	value, err = c.ListTokens(context.Background())
	if err != nil || value.Tokens == nil || len(value.Tokens) != 0 {
		t.Fatalf("%+v %v", value, err)
	}
}

func TestMalformedTokenMetadata(t *testing.T) {
	for _, wire := range []string{
		"OK count=0\nEND\n",
		"OK actor=user count=2\nTOKEN id=a source=manual issued_at=1\nEND\n",
		"OK actor=user count=1\nKEY id=a source=manual issued_at=1\nEND\n",
		"OK actor=user count=1\nTOKEN source=manual issued_at=1\nEND\n",
		"OK actor=user count=1\nTOKEN id=a issued_at=1\nEND\n",
		"OK actor=user count=1\nTOKEN id=a source=manual\nEND\n",
		"OK actor=user count=1\nTOKEN id=a source=manual issued_at=-1\nEND\n",
		"OK actor=user count=1\nTOKEN id=a source=manual issued_at=1 expires_at=9223372036854775808\nEND\n",
		"OK actor=user count=1\nTOKEN id=a source=manual issued_at=1 last_used_at=x\nEND\n",
		"OK actor=user count=1\nTOKEN id=a source=manual issued_at=1 retiring=maybe\nEND\n",
		"OK actor=user count=2\nTOKEN id=a source=manual issued_at=1\nTOKEN id=a source=cli issued_at=2\nEND\n",
		"OK actor=user count=0\n",
	} {
		c := discoveryClient(t, map[string]string{"ACCOUNT TOKEN LIST": wire})
		if _, err := c.ListTokens(context.Background()); err == nil {
			t.Fatalf("accepted %q", wire)
		}
	}
	c := discoveryClient(t, map[string]string{"ACCOUNT TOKEN LIST": "ERR forbidden future=kept\n"})
	_, err := c.ListTokens(context.Background())
	var serverErr *ServerError
	if !errors.As(err, &serverErr) || serverErr.Code != "forbidden" || serverErr.Fields["future"] != "kept" {
		t.Fatalf("%v", err)
	}
}

func TestResponseControlEscapes(t *testing.T) {
	record, err := ParseRecord(`TOKEN label="a\r\n\t\u0001\u007F\\\"b"`)
	if err != nil || record.Fields["label"] != "a\r\n\t\x01\x7f\\\"b" {
		t.Fatalf("%+v %v", record, err)
	}
	for _, wire := range []string{`TOKEN label="\u12"`, `TOKEN label="\u12xz"`, `TOKEN label="\ud800"`, `TOKEN label="\q"`} {
		if _, err := ParseRecord(wire); err == nil {
			t.Fatalf("accepted %q", wire)
		}
	}
}

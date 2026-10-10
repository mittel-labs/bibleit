package bibleit

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"testing"
)

func discoveryClient(t *testing.T, responses map[string]string) *Client {
	t.Helper()
	return testClient(t, func(request *http.Request) (*http.Response, error) {
		var body map[string]string
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		wire, ok := responses[body["command"]]
		if !ok {
			t.Fatalf("unexpected command %q", body["command"])
		}
		return reply(200, wire), nil
	})
}
func TestTypedDiscoveryPreservesFutureFields(t *testing.T) {
	client := discoveryClient(t, map[string]string{
		"SERVER INFO":        "OK protocol_version=1 version=\"0.1\" capabilities=\"read,future\" future=enabled\n",
		"HELP ACCOUNT":       "OK auth=true commands=1\nCOMMAND usage=\"account info\" summary=\"Account details\" future=field\nEND\n",
		"ACCOUNT INFO":       "OK actor=user plan=starter plan_source=signup plan_activated_at=123 lives=0 translations=2 tokens=1 keys=0 display_name=\"Test User\" future=field\n",
		"ACCOUNT QUOTA LIST": "OK count=2\nQUOTA permission=live.create limit=0 used=0 future=field\nQUOTA permission=token.create limit=unlimited used=3\nEND\n",
	})
	ctx := context.Background()
	server, err := client.GetServerInfo(ctx)
	if err != nil || len(server.Capabilities) != 2 || server.Raw.Records[0].Fields["future"] != "enabled" {
		t.Fatalf("%+v %v", server, err)
	}
	help, err := client.Help(ctx, "account")
	if err != nil || len(help.Commands) != 1 || help.Commands[0].Auth != "none" || help.Commands[0].Fields["future"] != "field" {
		t.Fatalf("%+v %v", help, err)
	}
	account, err := client.GetAccountInfo(ctx)
	if err != nil || account.Tokens != 1 || account.DisplayName != "Test User" || account.Raw.Records[0].Fields["future"] != "field" {
		t.Fatalf("%+v %v", account, err)
	}
	quotas, err := client.ListQuotas(ctx)
	if err != nil || len(quotas.Quotas) != 2 {
		t.Fatalf("%+v %v", quotas, err)
	}
	if quotas.Quotas[0].Limit.Unlimited || quotas.Quotas[0].Limit.Value != 0 || !quotas.Quotas[1].Limit.Unlimited || quotas.Quotas[1].Used != 3 {
		t.Fatalf("%+v", quotas)
	}
}
func TestTypedQuotasRejectAmbiguousValues(t *testing.T) {
	for _, wire := range []string{
		"OK count=2\nQUOTA permission=live.create limit=1 used=0\nEND\n",
		"OK count=1\nQUOTA permission=live.create limit=-1 used=0\nEND\n",
		"OK count=1\nQUOTA permission=live.create limit=unknown used=0\nEND\n",
		"OK count=1\nQUOTA permission=live.create limit=1\nEND\n",
		"OK count=1\nQUOTA permission=live.create limit=1 used=9223372036854775808\nEND\n",
	} {
		client := discoveryClient(t, map[string]string{"ACCOUNT QUOTA LIST": wire})
		if _, err := client.ListQuotas(context.Background()); err == nil {
			t.Fatalf("accepted %q", wire)
		}
	}
}
func TestDiscoveryErrorAndInputValidation(t *testing.T) {
	client := discoveryClient(t, map[string]string{"HELP": "ERR forbidden reason=scope\n"})
	_, err := client.Help(context.Background(), "")
	var serverErr *ServerError
	if !errors.As(err, &serverErr) || serverErr.Code != "forbidden" || serverErr.Fields["reason"] != "scope" {
		t.Fatalf("%v", err)
	}
	for _, topic := range []string{"account\nLIVE DELETE ALL", "unsupported", "account extra"} {
		if _, err := HelpCommand(topic); err == nil {
			t.Fatalf("accepted %q", topic)
		}
	}
	for _, wire := range []string{"OK protocol_version=bad version=1\n", "OK protocol_version=1\n"} {
		client := discoveryClient(t, map[string]string{"SERVER INFO": wire})
		if _, err := client.GetServerInfo(context.Background()); err == nil {
			t.Fatal("accepted malformed discovery")
		}
	}
	client = discoveryClient(t, map[string]string{"HELP": "OK auth=maybe commands=0\nEND\n"})
	if _, err := client.Help(context.Background(), ""); err == nil || !strings.Contains(err.Error(), "auth") {
		t.Fatalf("%v", err)
	}
}

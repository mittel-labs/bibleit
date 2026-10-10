package bibleit

import (
	"context"
	"fmt"
	"strconv"
	"strings"
)

// Typed results retain Raw for unknown fields and original wire records.
type ServerInfo struct {
	ProtocolVersion int64
	Version         string
	Capabilities    []string
	Raw             Response
}
type HelpEntry struct {
	Usage, Summary string
	// Auth is "none" when the server omits the auth field.
	Auth   string
	Fields map[string]string
}
type HelpResult struct {
	Authenticated bool
	Commands      []HelpEntry
	Raw           Response
}
type AccountInfo struct {
	Actor, DisplayName, Handle, AvatarURL, Locale, Theme string
	Plan, PlanName, PlanSource                           string
	PlanActivatedAt                                      int64
	Lives, Translations, Tokens, Keys                    int64
	Raw                                                  Response
}
type QuotaLimit struct {
	Unlimited bool
	Value     int64 // Meaningful only when Unlimited is false.
}
type Quota struct {
	Permission string
	Limit      QuotaLimit
	Used       int64
	Fields     map[string]string
}
type QuotaResult struct {
	Quotas []Quota
	Raw    Response
}

func number(fields map[string]string, key string) (int64, error) {
	value, err := strconv.ParseInt(fields[key], 10, 64)
	if err != nil || value < 0 {
		return 0, fmt.Errorf("invalid response field %q: expected a non-negative integer", key)
	}
	return value, nil
}
func required(fields map[string]string, key string) (string, error) {
	value, ok := fields[key]
	if !ok || value == "" {
		return "", fmt.Errorf("missing response field %q", key)
	}
	return value, nil
}
func single(result Response) (map[string]string, error) {
	if len(result.Records) != 1 || result.Records[0].Type != "ok" {
		return nil, fmt.Errorf("expected a single OK response")
	}
	return result.Records[0].Fields, nil
}
func counted(result Response, key, kind string) (map[string]string, error) {
	if len(result.Records) == 0 || result.Records[0].Type != "ok" {
		return nil, fmt.Errorf("expected an OK response")
	}
	fields := result.Records[0].Fields
	count, err := number(fields, key)
	if err != nil {
		return nil, err
	}
	if count != int64(len(result.Records)-1) {
		return nil, fmt.Errorf("response %s does not match record count", key)
	}
	for _, record := range result.Records[1:] {
		if record.Type != kind {
			return nil, fmt.Errorf("expected %s record, received %s", kind, record.Type)
		}
	}
	return fields, nil
}

func (c *Client) GetServerInfo(ctx context.Context) (ServerInfo, error) {
	result, err := c.Execute(ctx, ServerInfoCommand())
	if err != nil {
		return ServerInfo{}, err
	}
	fields, err := single(result)
	if err != nil {
		return ServerInfo{}, err
	}
	value := ServerInfo{Raw: result}
	value.ProtocolVersion, err = number(fields, "protocol_version")
	if err != nil {
		return ServerInfo{}, err
	}
	value.Version, err = required(fields, "version")
	if err != nil {
		return ServerInfo{}, err
	}
	value.Capabilities = []string{}
	if fields["capabilities"] != "" {
		value.Capabilities = strings.Split(fields["capabilities"], ",")
	}
	return value, nil
}
func (c *Client) Help(ctx context.Context, topic string) (HelpResult, error) {
	cmd, err := HelpCommand(topic)
	if err != nil {
		return HelpResult{}, err
	}
	result, err := c.Execute(ctx, cmd)
	if err != nil {
		return HelpResult{}, err
	}
	fields, err := counted(result, "commands", "command")
	if err != nil {
		return HelpResult{}, err
	}
	if fields["auth"] != "true" && fields["auth"] != "false" {
		return HelpResult{}, fmt.Errorf("invalid response field auth")
	}
	value := HelpResult{Authenticated: fields["auth"] == "true", Commands: []HelpEntry{}, Raw: result}
	for _, record := range result.Records[1:] {
		usage, err := required(record.Fields, "usage")
		if err != nil {
			return HelpResult{}, err
		}
		summary, err := required(record.Fields, "summary")
		if err != nil {
			return HelpResult{}, err
		}
		auth := record.Fields["auth"]
		if auth == "" {
			auth = "none"
		}
		value.Commands = append(value.Commands, HelpEntry{Usage: usage, Summary: summary, Auth: auth, Fields: record.Fields})
	}
	return value, nil
}
func (c *Client) GetAccountInfo(ctx context.Context) (AccountInfo, error) {
	result, err := c.Execute(ctx, AccountInfoCommand())
	if err != nil {
		return AccountInfo{}, err
	}
	fields, err := single(result)
	if err != nil {
		return AccountInfo{}, err
	}
	value := AccountInfo{Raw: result, DisplayName: fields["display_name"], Handle: fields["handle"], AvatarURL: fields["avatar_url"], Locale: fields["locale"], Theme: fields["theme"], PlanName: fields["plan_name"]}
	for key, target := range map[string]*string{"actor": &value.Actor, "plan": &value.Plan, "plan_source": &value.PlanSource} {
		*target, err = required(fields, key)
		if err != nil {
			return AccountInfo{}, err
		}
	}
	for key, target := range map[string]*int64{"lives": &value.Lives, "translations": &value.Translations, "tokens": &value.Tokens, "keys": &value.Keys, "plan_activated_at": &value.PlanActivatedAt} {
		*target, err = number(fields, key)
		if err != nil {
			return AccountInfo{}, err
		}
	}
	return value, nil
}
func (c *Client) ListQuotas(ctx context.Context) (QuotaResult, error) {
	result, err := c.Execute(ctx, AccountQuotasCommand())
	if err != nil {
		return QuotaResult{}, err
	}
	_, err = counted(result, "count", "quota")
	if err != nil {
		return QuotaResult{}, err
	}
	value := QuotaResult{Quotas: []Quota{}, Raw: result}
	for _, record := range result.Records[1:] {
		quota := Quota{Fields: record.Fields}
		quota.Permission, err = required(record.Fields, "permission")
		if err != nil {
			return QuotaResult{}, err
		}
		quota.Used, err = number(record.Fields, "used")
		if err != nil {
			return QuotaResult{}, err
		}
		if record.Fields["limit"] == "unlimited" {
			quota.Limit.Unlimited = true
		} else {
			quota.Limit.Value, err = number(record.Fields, "limit")
			if err != nil {
				return QuotaResult{}, err
			}
		}
		value.Quotas = append(value.Quotas, quota)
	}
	return value, nil
}

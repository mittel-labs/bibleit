package bibleit

import (
	"context"
	"errors"
	"os"
	"strings"
	"testing"
	"time"
)

// Enabled only by scripts/check_server.py's isolated fixture harness.
func TestServerHTTPIntegration(t *testing.T) {
	if os.Getenv("BIBLEIT_CLIENT_TEST_DISPOSABLE") != "1" {
		t.Skip("run python3 scripts/check_server.py --integration")
	}
	c, err := NewClient(Config{Endpoint: os.Getenv("BIBLEIT_INTEGRATION_ENDPOINT"), Token: os.Getenv("BIBLEIT_INTEGRATION_TOKEN")})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	result, err := c.Ping(ctx)
	if err != nil || result.Records[0].Fields["pong"] != "true" {
		t.Fatalf("ping: %v", err)
	}
	result, err = c.Identity(ctx)
	if err != nil || result.Records[0].Fields["actor"] != "security-owner" {
		t.Fatalf("identity: %v", err)
	}

	t.Run("typed token metadata", func(t *testing.T) {
		value, err := c.ListTokens(ctx)
		if err != nil {
			t.Fatal(err)
		}
		if value.Actor != "security-owner" || len(value.Tokens) != 3 {
			t.Fatalf("actor=%s tokens=%d", value.Actor, len(value.Tokens))
		}
		foundManual, foundScoped := false, false
		for _, token := range value.Tokens {
			if token.IssuedAt <= 0 || token.IssuedBy == nil || *token.IssuedBy != "security-owner" || token.Retiring == nil || *token.Retiring {
				t.Fatal("invalid issuer/timestamp/retirement metadata")
			}
			for _, secret := range []string{os.Getenv("BIBLEIT_INTEGRATION_TOKEN"), os.Getenv("BIBLEIT_SCOPED_TOKEN"), os.Getenv("BIBLEIT_DENIED_TOKEN"), os.Getenv("BIBLEIT_EXPIRED_TOKEN")} {
				if strings.Contains(strings.Join(value.Raw.Lines, "\n"), secret) {
					t.Fatal("token list exposed a bearer value")
				}
			}
			if token.ID == os.Getenv("BIBLEIT_MANUAL_TOKEN_ID") {
				foundManual = token.Source == "manual" && token.Scopes != nil && len(token.Scopes) == 0 && token.ExpiresAt == nil && token.LastUsedAt != nil
			}
			if token.ID == os.Getenv("BIBLEIT_SCOPED_TOKEN_ID") {
				foundScoped = token.Source == "cli" && len(token.Scopes) == 1 && token.Scopes[0] == "token.get" && token.ExpiresAt != nil && token.Label != nil && *token.Label == "Scoped fixture\nlabel"
			}
		}
		if !foundManual || !foundScoped {
			t.Fatal("missing manual/scoped metadata")
		}
		scoped, err := NewClient(Config{Endpoint: os.Getenv("BIBLEIT_INTEGRATION_ENDPOINT"), Token: os.Getenv("BIBLEIT_SCOPED_TOKEN")})
		if err != nil {
			t.Fatal(err)
		}
		if _, err = scoped.ListTokens(ctx); err != nil {
			t.Fatal(err)
		}
		denied, err := NewClient(Config{Endpoint: os.Getenv("BIBLEIT_INTEGRATION_ENDPOINT"), Token: os.Getenv("BIBLEIT_DENIED_TOKEN")})
		if err != nil {
			t.Fatal(err)
		}
		_, err = denied.ListTokens(ctx)
		var serverErr *ServerError
		if !errors.As(err, &serverErr) || serverErr.Code != "forbidden" {
			t.Fatalf("scope rejection: %v", err)
		}
	})

	t.Run("typed authorization exchange and revocation", func(t *testing.T) {
		auth, err := NewAuthClient(AuthConfig{Endpoint: os.Getenv("BIBLEIT_INTEGRATION_ENDPOINT")})
		if err != nil {
			t.Fatal(err)
		}
		request := CodeExchange{Code: os.Getenv("BIBLEIT_AUTH_CODE"), Verifier: os.Getenv("BIBLEIT_AUTH_VERIFIER"), DeviceName: "Go authorization integration"}
		result, err := auth.ExchangeCode(ctx, request)
		if err != nil {
			t.Fatal(err)
		}
		if result.Actor != "security-owner" || result.TokenID == "" || result.IdentityName == "" || result.AccessToken == "" {
			t.Fatal("missing authorization metadata")
		}
		credential, err := NewClient(Config{Endpoint: os.Getenv("BIBLEIT_INTEGRATION_ENDPOINT"), Token: result.AccessToken})
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = credential.RevokeCredential(context.Background()) })
		identity, err := credential.GetIdentity(ctx)
		if err != nil || identity.Actor != "security-owner" {
			t.Fatal("exchanged credential did not authenticate", err)
		}
		assertAuthError := func(err error, status int, code string) {
			t.Helper()
			var httpErr *HTTPError
			if !errors.As(err, &httpErr) || httpErr.StatusCode != status || httpErr.Code != code {
				t.Fatalf("authorization error: %v", err)
			}
		}
		_, err = auth.ExchangeCode(ctx, request)
		assertAuthError(err, 400, "invalid_authorization_code")
		invalid := CodeExchange{Code: os.Getenv("BIBLEIT_AUTH_BAD_CODE"), Verifier: "wrong-verifier", DeviceName: "Invalid verifier integration"}
		_, err = auth.ExchangeCode(ctx, invalid)
		assertAuthError(err, 400, "invalid_code_verifier")
		invalid.Verifier = request.Verifier
		_, err = auth.ExchangeCode(ctx, invalid)
		assertAuthError(err, 400, "invalid_authorization_code")
		if err = credential.RevokeCredential(ctx); err != nil {
			t.Fatal(err)
		}
		_, err = credential.Ping(ctx)
		var serverErr *ServerError
		if !errors.As(err, &serverErr) || serverErr.Code != "unauthorized" {
			t.Fatalf("revoked credential accepted: %v", err)
		}
		assertAuthError(credential.RevokeCredential(ctx), 401, "unauthorized")
	})

	t.Run("expired token", func(t *testing.T) {
		token := os.Getenv("BIBLEIT_EXPIRED_TOKEN")
		if token == "" {
			t.Fatal("missing expired-token fixture")
		}
		expired, err := NewClient(Config{Endpoint: os.Getenv("BIBLEIT_INTEGRATION_ENDPOINT"), Token: token})
		if err != nil {
			t.Fatal(err)
		}
		_, err = expired.Ping(ctx)
		var httpErr *HTTPError
		var serverErr *ServerError
		if !(errors.As(err, &httpErr) && httpErr.StatusCode == 401) && !(errors.As(err, &serverErr) && serverErr.Code == "unauthorized") {
			t.Fatalf("expired credential: %v", err)
		}
	})
	t.Run("translations and read", func(t *testing.T) {
		for _, makeCommand := range []func(string) (Command, error){AddTranslationCommand, RemoveTranslationCommand, AddTranslationCommand} {
			cmd, err := makeCommand("web")
			if err != nil {
				t.Fatal(err)
			}
			if _, err := c.Execute(ctx, cmd); err != nil {
				t.Fatal(err)
			}
		}
		if _, err := c.ListTranslations(ctx); err != nil {
			t.Fatal(err)
		}
		result, err := c.Read(ctx, Reference{Translation: "web", Book: "Psalms", Chapter: 23, Verse: 1})
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(result.Records[0].Fields["text"], "shepherd") {
			t.Fatal("unexpected verse text")
		}
		result, err = c.Read(ctx, Reference{Translation: "web", Book: "19", Chapter: 23})
		if err != nil || len(result.Records) != 3 {
			t.Fatalf("chapter: records=%d error=%v", len(result.Records), err)
		}
		result, err = c.Search(ctx, "web", "shepherd")
		if err != nil || len(result.Records) < 2 {
			t.Fatalf("search: records=%d error=%v", len(result.Records), err)
		}
	})

	t.Run("typed identity and reading", func(t *testing.T) {
		identity, err := c.GetIdentity(ctx)
		if err != nil || !identity.Authenticated || identity.Actor != "security-owner" || len(identity.Permissions) == 0 {
			t.Fatalf("identity: %+v %v", identity, err)
		}
		verse, err := c.ReadVerses(ctx, Reference{Translation: "web", Book: "Psalms", Chapter: 23, Verse: 1})
		if err != nil || len(verse.Verses) != 1 || verse.Verse == nil || *verse.Verse != 1 {
			t.Fatalf("verse: %+v %v", verse, err)
		}
		chapter, err := c.ReadVerses(ctx, Reference{Translation: "web", Book: "19", Chapter: 23})
		if err != nil || len(chapter.Verses) != 2 || chapter.Verse != nil {
			t.Fatalf("chapter: %+v %v", chapter, err)
		}
		book, err := c.ReadVerses(ctx, Reference{Translation: "web", Book: "19"})
		if err != nil || len(book.Verses) != 3 || book.Chapter != nil {
			t.Fatalf("book: %+v %v", book, err)
		}
		search, err := c.SearchVerses(ctx, "web", "shepherd")
		if err != nil || len(search.Verses) != 2 || search.Book != nil {
			t.Fatalf("search: %+v %v", search, err)
		}
		empty, err := c.SearchVerses(ctx, "web", "no-match-xyz")
		if err != nil || len(empty.Verses) != 0 {
			t.Fatalf("empty search: %+v %v", empty, err)
		}
	})
	t.Run("typed discovery and account", func(t *testing.T) {
		info, err := c.GetServerInfo(ctx)
		if err != nil || info.ProtocolVersion != 1 || len(info.Capabilities) == 0 {
			t.Fatalf("server info: %+v %v", info, err)
		}
		help, err := c.Help(ctx, "account")
		if err != nil || !help.Authenticated || len(help.Commands) == 0 {
			t.Fatalf("help: %v", err)
		}
		account, err := c.GetAccountInfo(ctx)
		if err != nil || account.Actor != "security-owner" || account.Tokens != 1 {
			t.Fatalf("account: %+v %v", account, err)
		}
		quotas, err := c.ListQuotas(ctx)
		if err != nil || len(quotas.Quotas) == 0 {
			t.Fatalf("quotas: %v", err)
		}
	})

	t.Run("translation metadata", func(t *testing.T) {
		info, err := c.GetTranslationInfo(ctx, "web")
		if err != nil || info.ShortName != "WEB" || info.RightsStatus != "public_domain" {
			t.Fatalf("metadata: %+v %v", info, err)
		}
	})
	t.Run("translation catalogue", func(t *testing.T) {
		catalog, err := c.GetTranslationCatalog(ctx, "web")
		if err != nil {
			t.Fatal(err)
		}
		if len(catalog.Books) != 19 {
			t.Fatalf("books: %d", len(catalog.Books))
		}
		book := catalog.Books[18]
		if book.ID != 19 || book.Name != "Psalms" || len(book.Chapters) != 2 || book.Chapters[1].Number != 23 || book.Chapters[1].Verses != 2 {
			t.Fatalf("Psalms: %+v", book)
		}
		_, err = c.GetTranslationCatalog(ctx, "not-a-translation")
		var serverErr *ServerError
		if !errors.As(err, &serverErr) || serverErr.Code != "translation_not_found" {
			t.Fatalf("missing translation: %v", err)
		}
	})
	created, err := c.CreateLive(ctx, "Client integration")
	if err != nil {
		t.Fatal(err)
	}
	id := created.Live.ID
	var command Command
	if id == "" {
		t.Fatal("missing Live id")
	}
	defer func() {
		if _, err := c.ControlLive(ctx, id, LiveDelete); err != nil {
			t.Errorf("delete Live: %v", err)
		}
	}()

	t.Run("live quota", func(t *testing.T) {
		cmd, _ := CreateLiveCommand("Exceeds starter allowance")
		_, err := c.Execute(ctx, cmd)
		var serverErr *ServerError
		if !errors.As(err, &serverErr) || serverErr.Code != "quota_exceeded" {
			t.Fatalf("Live quota: %v", err)
		}
	})
	t.Run("live push", func(t *testing.T) {
		cmd, err := PushLiveCommand(id, Reference{Translation: "web", Book: "Psalms", Chapter: 23, Verse: 1})
		if err != nil {
			t.Fatal(err)
		}
		result, err := c.Execute(ctx, cmd)
		if err != nil {
			t.Fatal(err)
		}
		if len(result.Records) < 2 || !strings.Contains(result.Records[1].Fields["text"], "shepherd") {
			t.Fatal("missing pushed verse")
		}
	})

	t.Run("typed Live results", func(t *testing.T) {
		live, err := c.GetLive(ctx, id)
		if err != nil || live.Live.ID != id || live.Live.Owned == nil || !*live.Live.Owned {
			t.Fatalf("Live: %+v %v", live, err)
		}
		list, err := c.ListLives(ctx)
		if err != nil || len(list.Lives) != 1 || list.Lives[0].ID != id {
			t.Fatalf("list: %+v %v", list, err)
		}
		updated, err := c.SetLive(ctx, id, LiveName, "Typed integration")
		if err != nil || updated.Live.Name != "Typed integration" {
			t.Fatalf("set: %+v %v", updated, err)
		}
		stats, err := c.GetLiveStats(ctx, id)
		if err != nil || stats.StackEntries != 1 || len(stats.Connections) != 0 {
			t.Fatalf("stats: %+v %v", stats, err)
		}
		stack, err := c.GetLiveStack(ctx, id)
		if err != nil || len(stack.Entries) != 1 || stack.Entries[0].Position != 1 {
			t.Fatalf("stack: %+v %v", stack, err)
		}
		push, err := c.PushLive(ctx, id, Reference{Translation: "web", Book: "19", Chapter: 23, Verse: 2})
		if err != nil || push.Event != "verse" || len(push.Verses) != 2 {
			t.Fatalf("push: %+v %v", push, err)
		}
		pop, err := c.PopLive(ctx, id, 1)
		if err != nil || pop.Event != "verse" || len(pop.Verses) != 1 {
			t.Fatalf("pop: %+v %v", pop, err)
		}
		for _, action := range []LiveAction{LivePause, LiveResume, LiveStop, LiveStart, LiveClear} {
			if _, err := c.ControlLive(ctx, id, action); err != nil {
				t.Fatalf("%s: %v", action, err)
			}
		}
		stack, err = c.GetLiveStack(ctx, id)
		if err != nil || len(stack.Entries) != 0 {
			t.Fatalf("cleared stack: %+v %v", stack, err)
		}
	})
	for _, action := range []LiveAction{LiveInfo, LiveStats, LivePause, LiveStop, LiveStart} {
		command, err = LiveCommand(id, action)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = c.Execute(ctx, command); err != nil {
			t.Fatalf("%s: %v", action, err)
		}
	}
	result, err = c.Execute(ctx, LiveListCommand())
	if err != nil || len(result.Records) < 2 {
		t.Fatalf("Live list: %v", err)
	}
	cmd, _ := LiveCommand("not-a-live", LiveInfo)
	_, err = c.Execute(ctx, cmd)
	var serverErr *ServerError
	if !errors.As(err, &serverErr) || serverErr.Code != "not_found" {
		t.Fatalf("missing Live: %v", err)
	}
}

package bibleit

import (
	"context"
	"errors"
	"strings"
	"testing"
)

func TestTypedIdentity(t *testing.T) {
	client := discoveryClient(t, map[string]string{"AUTH INFO": "OK actor=user auth=true display_name=\"Test User\" identity_name=@user auth_provider=github roles=\"member,future-role\" permissions=\"live.get,future.read\" key_fingerprint=SHA256:test future=kept\n"})
	value, err := client.GetIdentity(context.Background())
	if err != nil || !value.Authenticated || value.Actor != "user" || value.IdentityName != "@user" || value.KeyFingerprint != "SHA256:test" || len(value.Roles) != 2 || value.Permissions[1] != "future.read" || value.Raw.Records[0].Fields["future"] != "kept" {
		t.Fatalf("%+v %v", value, err)
	}
	client = discoveryClient(t, map[string]string{"AUTH INFO": "OK actor=user auth=maybe\n"})
	if _, err := client.GetIdentity(context.Background()); err == nil {
		t.Fatal("accepted invalid authentication boolean")
	}
}
func TestTypedReadings(t *testing.T) {
	client := discoveryClient(t, map[string]string{
		"READ web 19 23 1":  "OK translation=web book=19 chapter=23 verse=1 text=\"Verse text\" future=single\n",
		"READ web 19 23":    "OK translation=web book=19 chapter=23 verses=2\nVERSE text=\"Psalms 23:1 First\" future=row\nVERSE text=\"Psalms 23:2 Second\"\nEND\n",
		"SEARCH web absent": "OK translation=web results=0\nEND\n",
	})
	ctx := context.Background()
	verse, err := client.ReadVerses(ctx, Reference{Translation: "web", Book: "19", Chapter: 23, Verse: 1})
	if err != nil || verse.Book == nil || *verse.Book != 19 || verse.Verse == nil || *verse.Verse != 1 || verse.Verses[0].Text != "Verse text" || verse.Verses[0].Fields["future"] != "single" {
		t.Fatalf("%+v %v", verse, err)
	}
	chapter, err := client.ReadVerses(ctx, Reference{Translation: "web", Book: "19", Chapter: 23})
	if err != nil || chapter.Verse != nil || len(chapter.Verses) != 2 || chapter.Verses[0].Fields["future"] != "row" {
		t.Fatalf("%+v %v", chapter, err)
	}
	empty, err := client.SearchVerses(ctx, "web", "absent")
	if err != nil || len(empty.Verses) != 0 || empty.Book != nil || empty.Chapter != nil || empty.Verse != nil {
		t.Fatalf("%+v %v", empty, err)
	}
	for _, wire := range []string{
		"OK translation=web book=19 chapter=23 verses=2\nVERSE text=x\nEND\n",
		"OK translation=web book=19 chapter=23 verses=1\nVERSE future=value\nEND\n",
		"OK translation=web book=19 chapter=0 verses=0\nEND\n",
		"OK translation=web book=19 verse=1 text=x\n",
		"OK translation=web book=19 chapter=23 verse=1\n",
	} {
		response, err := DecodeResponse(strings.NewReader(wire))
		if err != nil {
			t.Fatal(err)
		}
		if _, err := reading(response, false); err == nil {
			t.Fatalf("accepted %q", wire)
		}
	}
}

func TestTypedLiveOptionalFieldsAndUnknownStatus(t *testing.T) {
	client := discoveryClient(t, map[string]string{
		"LIVE live INFO":  "OK id=live name=\"\" status=future-status paused=false future=kept\n",
		"LIVE owner INFO": "OK id=owner name=Owned status=running paused=false owned=false protected=false created_at=0 owner=user reference=\"\"\n",
	})
	value, err := client.GetLive(context.Background(), "live")
	if err != nil || value.Live.Name != "" || value.Live.Status != "future-status" || value.Live.Owned != nil || value.Live.Protected != nil || value.Live.Owner != nil || value.Live.CreatedAt != nil || value.Live.Fields["future"] != "kept" {
		t.Fatalf("%+v %v", value, err)
	}
	owner, err := client.GetLive(context.Background(), "owner")
	if err != nil || owner.Live.Owned == nil || *owner.Live.Owned || owner.Live.Protected == nil || *owner.Live.Protected || owner.Live.CreatedAt == nil || *owner.Live.CreatedAt != 0 || owner.Live.Reference == nil {
		t.Fatalf("%+v %v", owner, err)
	}
}
func TestTypedLiveStatisticsAndStack(t *testing.T) {
	client := discoveryClient(t, map[string]string{
		"LIVE live STATS":      "OK id=live connections=1 connections=1 actor_connections=1 anonymous_connections=0 running_for_seconds=0 revision=2 stack_entries=1 future=stats\nCONNECTION actor=user access=actor connected_at=100 connected_for_seconds=0 future=row\nEND\n",
		"LIVE live STACK INFO": "OK id=live count=1\nSTACK position=1 translation=web reference=\"\" text=Verse future=entry\nEND\n",
	})
	stats, err := client.GetLiveStats(context.Background(), "live")
	if err != nil || stats.Revision != 2 || len(stats.Connections) != 1 || stats.Connections[0].Actor != "user" || stats.Connections[0].Fields["future"] != "row" {
		t.Fatalf("%+v %v", stats, err)
	}
	stack, err := client.GetLiveStack(context.Background(), "live")
	if err != nil || len(stack.Entries) != 1 || stack.Entries[0].Position != 1 || stack.Entries[0].Reference != "" || stack.Entries[0].Fields["future"] != "entry" {
		t.Fatalf("%+v %v", stack, err)
	}
}
func TestMalformedLiveResults(t *testing.T) {
	for _, wire := range []string{
		"OK id=live name=Name status=running paused=maybe\n",
		"OK id=live name=Name status=running paused=false protected=unknown\n",
		"OK id=live name=Name status=running paused=false created_at=-1\n",
		"OK name=Name status=running paused=false\n",
	} {
		client := discoveryClient(t, map[string]string{"LIVE live INFO": wire})
		if _, err := client.GetLive(context.Background(), "live"); err == nil {
			t.Fatalf("accepted %q", wire)
		}
	}
	for _, wire := range []string{
		"OK id=live count=1\nSTACK position=2 translation=web text=Verse\nEND\n",
		"OK id=live count=2\nSTACK position=1 translation=web text=Verse\nSTACK position=1 translation=web text=Verse\nEND\n",
	} {
		client := discoveryClient(t, map[string]string{"LIVE live STACK INFO": wire})
		if _, err := client.GetLiveStack(context.Background(), "live"); err == nil {
			t.Fatal("accepted invalid stack position")
		}
	}
	client := discoveryClient(t, map[string]string{"LIVE live STATS": "OK id=live connections=0 actor_connections=1 anonymous_connections=0 running_for_seconds=0 revision=0 stack_entries=0\nEND\n"})
	if _, err := client.GetLiveStats(context.Background(), "live"); err == nil {
		t.Fatal("accepted inconsistent connection counts")
	}
}
func TestTypedLiveMutationsAndErrors(t *testing.T) {
	client := discoveryClient(t, map[string]string{
		"LIVE live STACK PUSH web 19 23 1": "OK event=verse translations=1\nVERSE translation=web reference=\"\" text=Verse\nEND\n",
		"LIVE live STACK POP 1":            "OK event=clear\n",
		"LIVE live PAUSE":                  "OK paused=true\n",
		"LIVE live DELETE":                 "OK event=deleted\n",
		"LIVE missing INFO":                "ERR not_found future=kept\n",
	})
	ctx := context.Background()
	push, err := client.PushLive(ctx, "live", Reference{Translation: "web", Book: "19", Chapter: 23, Verse: 1})
	if err != nil || push.Event != "verse" || len(push.Verses) != 1 {
		t.Fatalf("%+v %v", push, err)
	}
	pop, err := client.PopLive(ctx, "live", 1)
	if err != nil || pop.Event != "clear" || len(pop.Verses) != 0 {
		t.Fatalf("%+v %v", pop, err)
	}
	pause, err := client.ControlLive(ctx, "live", LivePause)
	if err != nil || pause.Paused == nil || !*pause.Paused || pause.State != nil {
		t.Fatalf("%+v %v", pause, err)
	}
	deleted, err := client.ControlLive(ctx, "live", LiveDelete)
	if err != nil || deleted.Event != "deleted" {
		t.Fatalf("%+v %v", deleted, err)
	}
	_, err = client.GetLive(ctx, "missing")
	var serverErr *ServerError
	if !errors.As(err, &serverErr) || serverErr.Code != "not_found" || serverErr.Fields["future"] != "kept" {
		t.Fatalf("%v", err)
	}
	if _, err := client.ControlLive(ctx, "live", LiveSubscribe); err == nil {
		t.Fatal("accepted streaming control action")
	}
}

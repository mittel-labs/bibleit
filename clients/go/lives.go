package bibleit

import (
	"context"
	"fmt"
)

type LiveState struct {
	ID, Name, Status                            string
	Paused                                      bool
	Reference, Owner, CreatedBy, OrganizationID *string
	Owned, Protected                            *bool
	CreatedAt                                   *int64
	Translations                                []string
	Fields                                      map[string]string
}
type LiveResult struct {
	Live LiveState
	Raw  Response
}
type LiveList struct {
	Lives []LiveState
	Raw   Response
}
type LiveConnection struct {
	Actor, Access                    string
	ConnectedAt, ConnectedForSeconds int64
	Fields                           map[string]string
}
type LiveStatistics struct {
	ID                                                                                string
	RunningForSeconds, Revision, StackEntries, ActorConnections, AnonymousConnections int64
	Connections                                                                       []LiveConnection
	Raw                                                                               Response
}
type LiveVerse struct {
	Translation, Reference, Text string
	Fields                       map[string]string
}
type StackEntry struct {
	Position int64
	LiveVerse
}
type LiveStack struct {
	ID      string
	Entries []StackEntry
	Raw     Response
}
type LiveVerseResult struct {
	Event  string
	Verses []LiveVerse
	Raw    Response
}

// LiveActionResult reflects the server acknowledgement without fetching state.
type LiveActionResult struct {
	State  *LiveState
	Paused *bool
	Event  string
	Raw    Response
}

func liveState(fields map[string]string) (LiveState, error) {
	value := LiveState{Fields: fields, Translations: commaList(fields["translations"]), Reference: optionalString(fields, "reference"), Owner: optionalString(fields, "owner"), CreatedBy: optionalString(fields, "created_by"), OrganizationID: optionalString(fields, "organization_id")}
	var err error
	value.ID, err = required(fields, "id")
	if err != nil {
		return LiveState{}, err
	}
	value.Name, err = present(fields, "name")
	if err != nil {
		return LiveState{}, err
	}
	value.Status, err = required(fields, "status")
	if err != nil {
		return LiveState{}, err
	}
	value.Paused, err = boolean(fields, "paused")
	if err != nil {
		return LiveState{}, err
	}
	value.Owned, err = optionalBoolean(fields, "owned")
	if err != nil {
		return LiveState{}, err
	}
	value.Protected, err = optionalBoolean(fields, "protected")
	if err != nil {
		return LiveState{}, err
	}
	value.CreatedAt, err = optionalNumber(fields, "created_at")
	if err != nil {
		return LiveState{}, err
	}
	return value, nil
}
func (c *Client) liveResult(ctx context.Context, cmd Command) (LiveResult, error) {
	result, err := c.Execute(ctx, cmd)
	if err != nil {
		return LiveResult{}, err
	}
	fields, err := single(result)
	if err != nil {
		return LiveResult{}, err
	}
	state, err := liveState(fields)
	if err != nil {
		return LiveResult{}, err
	}
	return LiveResult{Live: state, Raw: result}, nil
}
func (c *Client) CreateLive(ctx context.Context, name string) (LiveResult, error) {
	cmd, err := CreateLiveCommand(name)
	if err != nil {
		return LiveResult{}, err
	}
	return c.liveResult(ctx, cmd)
}
func (c *Client) GetLive(ctx context.Context, id string) (LiveResult, error) {
	cmd, err := LiveCommand(id, LiveInfo)
	if err != nil {
		return LiveResult{}, err
	}
	return c.liveResult(ctx, cmd)
}
func (c *Client) SetLive(ctx context.Context, id string, field LiveField, values ...string) (LiveResult, error) {
	cmd, err := SetLiveCommand(id, field, values...)
	if err != nil {
		return LiveResult{}, err
	}
	return c.liveResult(ctx, cmd)
}
func (c *Client) ListLives(ctx context.Context) (LiveList, error) {
	result, err := c.Execute(ctx, LiveListCommand())
	if err != nil {
		return LiveList{}, err
	}
	if _, err := counted(result, "count", "live"); err != nil {
		return LiveList{}, err
	}
	value := LiveList{Lives: []LiveState{}, Raw: result}
	seen := map[string]bool{}
	for _, record := range result.Records[1:] {
		state, err := liveState(record.Fields)
		if err != nil {
			return LiveList{}, err
		}
		if seen[state.ID] {
			return LiveList{}, fmt.Errorf("duplicate Live id")
		}
		seen[state.ID] = true
		value.Lives = append(value.Lives, state)
	}
	return value, nil
}
func (c *Client) GetLiveStats(ctx context.Context, id string) (LiveStatistics, error) {
	cmd, err := LiveCommand(id, LiveStats)
	if err != nil {
		return LiveStatistics{}, err
	}
	result, err := c.Execute(ctx, cmd)
	if err != nil {
		return LiveStatistics{}, err
	}
	fields, err := counted(result, "connections", "connection")
	if err != nil {
		return LiveStatistics{}, err
	}
	value := LiveStatistics{Raw: result, Connections: []LiveConnection{}}
	value.ID, err = required(fields, "id")
	if err != nil {
		return LiveStatistics{}, err
	}
	for key, target := range map[string]*int64{"running_for_seconds": &value.RunningForSeconds, "revision": &value.Revision, "stack_entries": &value.StackEntries, "actor_connections": &value.ActorConnections, "anonymous_connections": &value.AnonymousConnections} {
		*target, err = number(fields, key)
		if err != nil {
			return LiveStatistics{}, err
		}
	}
	if value.ActorConnections > int64(len(result.Records)-1) || value.AnonymousConnections != int64(len(result.Records)-1)-value.ActorConnections {
		return LiveStatistics{}, fmt.Errorf("inconsistent Live connection totals")
	}
	for _, record := range result.Records[1:] {
		entry := LiveConnection{Fields: record.Fields}
		entry.Actor, err = required(record.Fields, "actor")
		if err != nil {
			return LiveStatistics{}, err
		}
		entry.Access, err = required(record.Fields, "access")
		if err != nil {
			return LiveStatistics{}, err
		}
		entry.ConnectedAt, err = number(record.Fields, "connected_at")
		if err != nil {
			return LiveStatistics{}, err
		}
		entry.ConnectedForSeconds, err = number(record.Fields, "connected_for_seconds")
		if err != nil {
			return LiveStatistics{}, err
		}
		value.Connections = append(value.Connections, entry)
	}
	return value, nil
}
func liveVerse(fields map[string]string) (LiveVerse, error) {
	value := LiveVerse{Reference: fields["reference"], Fields: fields}
	var err error
	value.Translation, err = required(fields, "translation")
	if err != nil {
		return LiveVerse{}, err
	}
	value.Text, err = present(fields, "text")
	return value, err
}
func (c *Client) GetLiveStack(ctx context.Context, id string) (LiveStack, error) {
	cmd, err := LiveStackCommand(id, StackInfo)
	if err != nil {
		return LiveStack{}, err
	}
	result, err := c.Execute(ctx, cmd)
	if err != nil {
		return LiveStack{}, err
	}
	fields, err := counted(result, "count", "stack")
	if err != nil {
		return LiveStack{}, err
	}
	value := LiveStack{Raw: result, Entries: []StackEntry{}}
	value.ID, err = required(fields, "id")
	if err != nil {
		return LiveStack{}, err
	}
	for i, record := range result.Records[1:] {
		position, err := positive(record.Fields, "position")
		if err != nil {
			return LiveStack{}, err
		}
		if position != int64(i+1) {
			return LiveStack{}, fmt.Errorf("invalid stack position")
		}
		verse, err := liveVerse(record.Fields)
		if err != nil {
			return LiveStack{}, err
		}
		value.Entries = append(value.Entries, StackEntry{Position: position, LiveVerse: verse})
	}
	return value, nil
}
func (c *Client) liveVerses(ctx context.Context, cmd Command) (LiveVerseResult, error) {
	result, err := c.Execute(ctx, cmd)
	if err != nil {
		return LiveVerseResult{}, err
	}
	value := LiveVerseResult{Raw: result, Verses: []LiveVerse{}}
	if len(result.Records) == 0 {
		return LiveVerseResult{}, fmt.Errorf("missing Live verse reply")
	}
	value.Event = result.Records[0].Fields["event"]
	if value.Event == "clear" {
		if _, err := single(result); err != nil {
			return LiveVerseResult{}, err
		}
		return value, nil
	}
	if value.Event != "verse" {
		return LiveVerseResult{}, fmt.Errorf("expected Live verse or clear event")
	}
	if _, err := counted(result, "translations", "verse"); err != nil {
		return LiveVerseResult{}, err
	}
	for _, record := range result.Records[1:] {
		verse, err := liveVerse(record.Fields)
		if err != nil {
			return LiveVerseResult{}, err
		}
		value.Verses = append(value.Verses, verse)
	}
	return value, nil
}
func (c *Client) PushLive(ctx context.Context, id string, ref Reference) (LiveVerseResult, error) {
	cmd, err := PushLiveCommand(id, ref)
	if err != nil {
		return LiveVerseResult{}, err
	}
	return c.liveVerses(ctx, cmd)
}
func (c *Client) PopLive(ctx context.Context, id string, count int) (LiveVerseResult, error) {
	cmd, err := PopLiveCommand(id, count)
	if err != nil {
		return LiveVerseResult{}, err
	}
	return c.liveVerses(ctx, cmd)
}
func (c *Client) ControlLive(ctx context.Context, id string, action LiveAction) (LiveActionResult, error) {
	switch action {
	case LiveStart, LiveStop, LivePause, LiveResume, LiveClear, LiveDelete:
	default:
		return LiveActionResult{}, fmt.Errorf("unsupported Live control action")
	}
	cmd, err := LiveCommand(id, action)
	if err != nil {
		return LiveActionResult{}, err
	}
	result, err := c.Execute(ctx, cmd)
	if err != nil {
		return LiveActionResult{}, err
	}
	fields, err := single(result)
	if err != nil {
		return LiveActionResult{}, err
	}
	value := LiveActionResult{Raw: result}
	switch action {
	case LiveStart, LiveStop:
		state, err := liveState(fields)
		if err != nil {
			return LiveActionResult{}, err
		}
		value.State = &state
	case LivePause, LiveResume:
		paused, err := boolean(fields, "paused")
		if err != nil {
			return LiveActionResult{}, err
		}
		value.Paused = &paused
	case LiveClear, LiveDelete:
		expected := "clear"
		if action == LiveDelete {
			expected = "deleted"
		}
		if fields["event"] != expected {
			return LiveActionResult{}, fmt.Errorf("unexpected Live control event")
		}
		value.Event = expected
	}
	return value, nil
}

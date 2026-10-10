// Package bibleit provides a client for Bibleit Server protocol v1.
// It does not read CLI configuration, open browsers, or manage credentials.
package bibleit

import (
	"errors"
	"fmt"
	"strconv"
	"strings"
)

// Command is a validated customer operation. Its zero value is invalid.
// String exposes the wire representation for transport adapters; it may contain secrets.
type Command struct {
	wire      string
	streaming bool
}

func (c Command) String() string  { return c.wire }
func (c Command) Streaming() bool { return c.streaming }

// Reference identifies a book, chapter, or verse. Zero chapter/verse means omitted.
type Reference struct {
	Translation string
	Book        string
	Chapter     int
	Verse       int
}

func (r Reference) arguments(requireTranslation bool) ([]string, error) {
	if r.Chapter < 0 || r.Chapter > 255 || r.Verse < 0 || r.Verse > 255 || (r.Verse != 0 && r.Chapter == 0) {
		return nil, errors.New("invalid chapter or verse")
	}
	args := []string{}
	if requireTranslation || r.Translation != "" {
		args = append(args, r.Translation)
	}
	args = append(args, r.Book)
	if r.Chapter != 0 {
		args = append(args, strconv.Itoa(r.Chapter))
	}
	if r.Verse != 0 {
		args = append(args, strconv.Itoa(r.Verse))
	}
	return args, nil
}

func command(prefix string, args ...string) (Command, error) {
	for _, arg := range args {
		// The server's v1 request tokenizer has no escaped-quote syntax.
		if arg == "" || strings.ContainsAny(arg, "\r\n\x00\"") {
			return Command{}, errors.New("arguments must be non-empty single lines without double quotes or NUL")
		}
		if strings.ContainsAny(arg, " \t") {
			arg = "\"" + arg + "\""
		}
		prefix += " " + arg
	}
	return Command{wire: prefix}, nil
}

func PingCommand() Command            { return Command{wire: "PING"} }
func ServerInfoCommand() Command      { return Command{wire: "SERVER INFO"} }
func IdentityCommand() Command        { return Command{wire: "AUTH INFO"} }
func AccountTokensCommand() Command   { return Command{wire: "ACCOUNT TOKEN LIST"} }
func TranslationListCommand() Command { return Command{wire: "ACCOUNT TRANSLATION LIST"} }
func AddTranslationCommand(slug string) (Command, error) {
	return command("ACCOUNT TRANSLATION ADD", slug)
}
func RemoveTranslationCommand(slug string) (Command, error) {
	return command("ACCOUNT TRANSLATION REMOVE", slug)
}
func ReadCommand(ref Reference) (Command, error) {
	args, err := ref.arguments(true)
	if err != nil {
		return Command{}, err
	}
	return command("READ", args...)
}
func SearchCommand(translation, query string) (Command, error) {
	return command("SEARCH", translation, query)
}
func LiveListCommand() Command { return Command{wire: "LIVE LIST"} }
func CreateLiveCommand(name string) (Command, error) {
	if name == "" {
		return command("LIVE CREATE")
	}
	return command("LIVE CREATE", name)
}
func DeleteAllLivesCommand() Command { return Command{wire: "LIVE DELETE ALL"} }

type LiveAction string

const (
	LiveInfo      LiveAction = "INFO"
	LiveStats     LiveAction = "STATS"
	LiveStart     LiveAction = "START"
	LiveStop      LiveAction = "STOP"
	LivePause     LiveAction = "PAUSE"
	LiveResume    LiveAction = "RESUME"
	LiveClear     LiveAction = "CLEAR"
	LiveDelete    LiveAction = "DELETE"
	LiveSubscribe LiveAction = "SUBSCRIBE"
)

func LiveCommand(id string, action LiveAction) (Command, error) {
	switch action {
	case LiveInfo, LiveStats, LiveStart, LiveStop, LivePause, LiveResume, LiveClear, LiveDelete, LiveSubscribe:
	default:
		return Command{}, fmt.Errorf("unsupported Live action %q", action)
	}
	c, err := command("LIVE", id)
	if err != nil {
		return Command{}, err
	}
	c.wire += " " + string(action)
	c.streaming = action == LiveSubscribe
	return c, err
}

type LiveField string

const (
	LiveName         LiveField = "NAME"
	LiveReference    LiveField = "REFERENCE"
	LiveTranslations LiveField = "TRANSLATIONS"
)

func SetLiveCommand(id string, field LiveField, values ...string) (Command, error) {
	switch field {
	case LiveName, LiveReference:
		if len(values) != 1 {
			return Command{}, errors.New("name and reference require one value")
		}
	case LiveTranslations:
	default:
		return Command{}, errors.New("unsupported Live field")
	}
	if len(values) == 0 {
		return Command{}, errors.New("missing Live value")
	}
	c, err := command("LIVE", id)
	if err != nil {
		return Command{}, err
	}
	return command(c.wire+" SET "+string(field), values...)
}

type SecretAction string

const (
	SecretAuthenticate SecretAction = ""
	SecretCreate       SecretAction = "CREATE"
	SecretRotate       SecretAction = "ROTATE"
	SecretDelete       SecretAction = "DELETE"
)

func LiveSecretCommand(id string, action SecretAction, value string) (Command, error) {
	c, err := command("LIVE", id)
	if err != nil {
		return Command{}, err
	}
	switch action {
	case SecretAuthenticate:
		if strings.EqualFold(value, "create") || strings.EqualFold(value, "rotate") || strings.EqualFold(value, "delete") {
			return Command{}, errors.New("secret conflicts with a protocol keyword")
		}
		return command(c.wire+" SECRET", value)
	case SecretCreate, SecretRotate, SecretDelete:
		if value != "" {
			return Command{}, errors.New("unexpected secret value")
		}
		return command(c.wire + " SECRET " + string(action))
	default:
		return Command{}, errors.New("unsupported secret action")
	}
}

type StackAction string

const (
	StackInfo  StackAction = "INFO"
	StackClear StackAction = "CLEAR"
)

func LiveStackCommand(id string, action StackAction) (Command, error) {
	if action != StackInfo && action != StackClear {
		return Command{}, errors.New("unsupported stack action")
	}
	c, err := command("LIVE", id)
	if err != nil {
		return Command{}, err
	}
	return command(c.wire + " STACK " + string(action))
}
func PushLiveCommand(id string, ref Reference) (Command, error) {
	c, err := command("LIVE", id)
	if err != nil {
		return Command{}, err
	}
	args, err := ref.arguments(false)
	if err != nil {
		return Command{}, err
	}
	return command(c.wire+" STACK PUSH", args...)
}
func PopLiveCommand(id string, count int) (Command, error) {
	c, err := command("LIVE", id)
	if err != nil {
		return Command{}, err
	}
	if count == 0 {
		return command(c.wire + " STACK POP")
	}
	return command(c.wire+" STACK POP", strconv.Itoa(count))
}

// HelpCommand asks the server for commands visible to the current principal.
// An empty topic selects the root. The server decides permission visibility.
func HelpCommand(topic string) (Command, error) {
	if topic == "" {
		return command("HELP")
	}
	switch strings.ToUpper(topic) {
	case "ROOT", "SERVER", "ACCOUNT", "AUTH", "TRANSLATION", "LIVE":
		return command("HELP", strings.ToUpper(topic))
	default:
		return Command{}, errors.New("unsupported help topic")
	}
}
func AccountInfoCommand() Command   { return Command{wire: "ACCOUNT INFO"} }
func AccountQuotasCommand() Command { return Command{wire: "ACCOUNT QUOTA LIST"} }

func TranslationInfoCommand(slug string) (Command, error) {
	return command("TRANSLATION INFO", slug)
}
func TranslationCatalogCommand(slug string) (Command, error) {
	return command("TRANSLATION CATALOG", slug)
}

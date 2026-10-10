package bibleit

import "testing"

func TestCommandArgumentsCannotChangeOperations(t *testing.T) {
	for _, input := range []string{"x\nLIVE DELETE ALL", "x\rPING", "bad\"quote", "bad\x00value", ""} {
		constructors := []func() (Command, error){
			func() (Command, error) { return SearchCommand(input, "query") },
			func() (Command, error) { return SearchCommand("web", input) },
			func() (Command, error) { return LiveCommand(input, LiveStart) },
			func() (Command, error) { return ReadCommand(Reference{Translation: "web", Book: input}) },
		}
		for _, build := range constructors {
			if _, err := build(); err == nil {
				t.Fatalf("accepted %q", input)
			}
		}
	}
	c, err := SearchCommand("web", `love \ peace`)
	if err != nil || c.String() != `SEARCH web "love \ peace"` {
		t.Fatalf("%q, %v", c.String(), err)
	}
}

func TestCommandEnumsAreValidated(t *testing.T) {
	if _, err := LiveCommand("abc", LiveAction("DELETE ALL")); err == nil {
		t.Fatal("accepted invalid action")
	}
	if _, err := SetLiveCommand("abc", LiveField("SECRET"), "value"); err == nil {
		t.Fatal("accepted invalid field")
	}
	if _, err := LiveSecretCommand("abc", SecretAction("SET"), "value"); err == nil {
		t.Fatal("accepted unsupported secret set")
	}
	if _, err := ReadCommand(Reference{Translation: "web", Book: "John", Verse: 16}); err == nil {
		t.Fatal("accepted verse without chapter")
	}
}

func TestSecretCommandsMatchServerGrammar(t *testing.T) {
	for action, expected := range map[SecretAction]string{SecretAuthenticate: "LIVE abc SECRET audience-secret", SecretCreate: "LIVE abc SECRET CREATE", SecretRotate: "LIVE abc SECRET ROTATE", SecretDelete: "LIVE abc SECRET DELETE"} {
		value := ""
		if action == SecretAuthenticate {
			value = "audience-secret"
		}
		c, err := LiveSecretCommand("abc", action, value)
		if err != nil || c.String() != expected {
			t.Fatalf("%q, %v", c.String(), err)
		}
	}
}

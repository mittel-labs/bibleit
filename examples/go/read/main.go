// Read a verse using explicit server credentials supplied by the application.
package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"

	bibleit "github.com/mittel-labs/bibleit/clients/go"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run() error {
	client, err := bibleit.NewClient(bibleit.Config{Endpoint: os.Getenv("BIBLEIT_ENDPOINT"), Token: os.Getenv("BIBLEIT_TOKEN")})
	if err != nil {
		return err
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt)
	defer cancel()
	result, err := client.ReadVerses(ctx, bibleit.Reference{Translation: "web", Book: "John", Chapter: 3, Verse: 16})
	if err != nil {
		return err
	}
	for _, verse := range result.Verses {
		fmt.Println(verse.Text)
	}
	return nil
}

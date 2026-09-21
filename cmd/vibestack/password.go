package main

import (
	"bytes"
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"strings"
	"time"
	"unicode/utf8"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
	"golang.org/x/term"
)

func isWorkspaceCommand(command string) bool {
	switch command {
	case "exec", "shell", "jobs", "files", "screenshot", "apps", "windows", "clipboard", "status", "display", "services", "logs", "setup", "account", "ssh-keys":
		return true
	}
	return false
}
func readPassword(stdin bool) ([]byte, error) {
	var secret []byte
	if stdin {
		var err error
		secret, err = io.ReadAll(io.LimitReader(os.Stdin, 259))
		if err != nil || len(secret) > 258 {
			clear(secret)
			return nil, errors.New("could not read password input")
		}
		secret = bytes.TrimSuffix(secret, []byte("\n"))
		secret = bytes.TrimSuffix(secret, []byte("\r"))
	} else {
		if !term.IsTerminal(int(os.Stdin.Fd())) {
			return nil, errors.New("interactive password input requires a terminal; use --password-stdin explicitly")
		}
		fmt.Fprint(os.Stderr, "Linux password: ")
		var err error
		secret, err = term.ReadPassword(int(os.Stdin.Fd()))
		fmt.Fprintln(os.Stderr)
		if err != nil {
			clear(secret)
			return nil, errors.New("password prompt interrupted")
		}
		fmt.Fprint(os.Stderr, "Confirm password: ")
		confirmation, err := term.ReadPassword(int(os.Stdin.Fd()))
		fmt.Fprintln(os.Stderr)
		match := bytes.Equal(secret, confirmation)
		clear(confirmation)
		if err != nil || !match {
			clear(secret)
			return nil, errors.New("password confirmation did not match or was interrupted")
		}
	}
	valid := utf8.Valid(secret) && len(secret) >= 12 && len(secret) <= 256 && strings.TrimSpace(string(secret)) != ""
	for _, b := range secret {
		if b < 32 || b == 127 {
			valid = false
		}
	}
	if !valid {
		clear(secret)
		return nil, errors.New("password must contain 12–256 UTF-8 bytes without control characters or only whitespace")
	}
	return secret, nil
}
func submitPassword(ctx context.Context, client *api.Client, id string, stdin bool) (any, error) {
	secret, err := readPassword(stdin)
	if err != nil {
		return nil, err
	}
	defer clear(secret)
	var response any
	_, err = client.JSON(ctx, "POST", api.RunnerAPI+"/instances/"+url.PathEscape(id)+"/password", map[string]string{"password": string(secret)}, &response, true, nil)
	if err != nil {
		var httpErr *api.HTTPError
		if errors.As(err, &httpErr) {
			return nil, err
		}
		return nil, errors.New("password completion is uncertain; inspect the desktop before explicitly trying again (not retried)")
	}
	return response, nil
}
func instancePassword(ctx context.Context, client *api.Client, args []string, g globalOptions) error {
	if len(args) < 1 {
		return errors.New("instances password requires ID [--password-stdin]")
	}
	fs := flag.NewFlagSet("instances password", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	stdin := fs.Bool("password-stdin", false, "read password from stdin")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if fs.NArg() != 0 {
		return errors.New("password accepts no positional secret")
	}
	value, err := submitPassword(ctx, client, args[0], *stdin)
	if err != nil {
		return err
	}
	return printValue(value, g)
}
func createWithPassword(ctx context.Context, client *api.Client, body any, key string, stdin bool, g globalOptions) error {
	var envelope struct {
		Operation api.Operation `json:"operation"`
	}
	if _, err := client.JSON(ctx, "POST", api.RunnerAPI+"/instances", body, &envelope, true, map[string]string{"Idempotency-Key": key}); err != nil {
		return err
	}
	id := envelope.Operation.InstanceID
	incomplete := func(err error) error {
		return fmt.Errorf("desktop %s retained; credential setup incomplete: %w", id, err)
	}
	fmt.Fprintf(os.Stderr, "Provisioning desktop %s (operation %s).\n", id, envelope.Operation.ID)
	for envelope.Operation.Status != "succeeded" {
		if envelope.Operation.Status == "failed" {
			return incomplete(&remoteOperationError{ID: envelope.Operation.ID, Code: envelope.Operation.ErrorCode, Message: envelope.Operation.ErrorMessage})
		}
		select {
		case <-ctx.Done():
			return incomplete(ctx.Err())
		case <-time.After(500 * time.Millisecond):
		}
		if _, err := client.JSON(ctx, "GET", api.RunnerAPI+"/operations/"+envelope.Operation.ID, nil, &envelope, true, nil); err != nil {
			return incomplete(err)
		}
	}
	value, err := submitPassword(ctx, client, id, stdin)
	if err != nil {
		return incomplete(err)
	}
	return printValue(value, g)
}

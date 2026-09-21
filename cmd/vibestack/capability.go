package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"syscall"
	"time"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
)

var capabilityID = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_]{0,63}$`)

func capabilityCommand(ctx context.Context, client *api.Client, profile api.Profile, args []string, g globalOptions) error {
	if err := requireWorkspace(profile); err != nil {
		return err
	}
	if client.InstanceID != "" {
		return errors.New("registered capabilities require a direct workspace profile")
	}
	if len(args) == 1 {
		switch args[0] {
		case "list":
			return jsonRequest(ctx, client, http.MethodGet, "/api/v1/capabilities", nil, true, g)
		case "schema":
			return jsonRequest(ctx, client, http.MethodGet, "/api/capabilities.openapi.json", nil, true, g)
		}
	}
	if len(args) < 2 || args[0] != "call" || !capabilityID.MatchString(args[1]) {
		return errors.New("usage: capability list | schema | call ID [--input FILE|-]")
	}
	flags := flag.NewFlagSet("capability call", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	input := flags.String("input", "", "JSON object file, or - for stdin; default {}")
	if flags.Parse(args[2:]) != nil || flags.NArg() != 0 {
		return errors.New("usage: capability call ID [--input FILE|-]")
	}
	data := []byte("{}")
	if *input != "" {
		var err error
		data, err = readInputFile(*input, 24<<20)
		if err != nil {
			return err
		}
	}
	trimmed := bytes.TrimSpace(data)
	if len(trimmed) == 0 || trimmed[0] != '{' || !json.Valid(trimmed) {
		return errors.New("capability input must be one JSON object")
	}
	// Preserve the original object, including duplicate keys, for the service's
	// strict schema validator. No automatic replay or client-side operation table.
	selected := *client
	transport := *client.HTTP
	transport.Timeout = 310 * time.Second // registry operations have a 300s maximum
	selected.HTTP = &transport
	return jsonRequest(ctx, &selected, http.MethodPost, "/api/v1/capabilities/"+url.PathEscape(args[1])+"/invoke", json.RawMessage(trimmed), true, g)
}

func readInputFile(path string, limit int64) ([]byte, error) {
	reader := os.Stdin
	if path != "-" {
		file, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NONBLOCK, 0)
		if err != nil {
			return nil, errors.New("input file could not be opened")
		}
		defer file.Close()
		info, err := file.Stat()
		if err != nil || !info.Mode().IsRegular() || info.Size() > limit {
			return nil, errors.New("input file must be regular and within the request limit")
		}
		reader = file
	}
	data, err := io.ReadAll(io.LimitReader(reader, limit+1))
	if err != nil || int64(len(data)) > limit {
		return nil, errors.New("request input is unavailable or over limit")
	}
	return data, nil
}

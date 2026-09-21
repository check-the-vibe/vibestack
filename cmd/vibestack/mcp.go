package main

import (
	"context"
	"errors"
	"flag"
	"io"
	"os"
	"os/signal"
	"syscall"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
)

func mcpCommand(ctx context.Context, client *api.Client, profile api.Profile, args []string) error {
	if err := requireWorkspace(profile); err != nil {
		return err
	}
	flags := flag.NewFlagSet("mcp", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	gateway := flags.String("gateway-token-file", profile.GatewayTokenFile, "protected GitHub private gateway credential file")
	if flags.Parse(args) != nil || flags.NArg() != 0 {
		return errors.New("usage: vibestack --profile NAME mcp [--gateway-token-file PATH]")
	}
	ctx, cancel := signal.NotifyContext(ctx, os.Interrupt, syscall.SIGTERM)
	defer cancel()
	return api.MCPBridge(ctx, profile, client, *gateway, api.MCPStdio(os.Stdin, &protocolStdout{}))
}

type protocolStdout struct{}

func (*protocolStdout) Write(p []byte) (int, error) { return os.Stdout.Write(p) }
func (*protocolStdout) Close() error                { return nil }

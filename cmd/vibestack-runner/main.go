package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/signal"
	"runtime"
	"strings"
	"syscall"
	"time"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
	"github.com/check-the-vibe/vibestack/runner"
)

const defaultConfig = "/etc/vibestack-runner/config.json"

func main() {
	if runtime.GOOS != "linux" {
		fatal(errors.New("vibestack-runner supports Linux Docker hosts only"))
	}
	if err := run(os.Args[1:]); err != nil {
		fatal(err)
	}
}
func fatal(err error) { fmt.Fprintf(os.Stderr, "vibestack-runner: %v\n", err); os.Exit(1) }

func run(args []string) error {
	if len(args) == 0 || args[0] == "help" {
		usage()
		return nil
	}
	if args[0] == "version" {
		fmt.Fprintln(os.Stdout, api.Version)
		return nil
	}
	fs := flag.NewFlagSet(args[0], flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	configPath := fs.String("config", defaultConfig, "configuration path")
	switch args[0] {
	case "init":
		state := fs.String("state-dir", "/var/lib/vibestack-runner", "private state directory")
		if err := fs.Parse(args[1:]); err != nil {
			return err
		}
		if _, err := os.Stat(*configPath); err == nil {
			return errors.New("configuration already exists and was preserved")
		}
		if err := os.MkdirAll(*state, 0700); err != nil {
			return err
		}
		if err := runner.WriteDefaultConfig(*configPath, *state); err != nil {
			return err
		}
		fmt.Fprintf(os.Stdout, "Created %s. Review it, then start vibestack-runner serve.\n", *configPath)
		return nil
	case "serve", "doctor", "templates", "pairings", "clients", "instances", "drives", "environment-sets", "snapshots":
		if err := fs.Parse(args[1:]); err != nil {
			return err
		}
	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
	config, err := runner.LoadConfig(*configPath)
	if err != nil {
		return err
	}
	store, err := runner.OpenStore(config.StateDir)
	if err != nil {
		return err
	}
	defer store.Close()
	if _, err := store.ConfigureAuthentication(context.Background(), config.AuthenticationMode); err != nil {
		return err
	}
	if config.AuthenticationMode == runner.AuthTrustedTailnet && (args[0] == "pairings" || args[0] == "clients") {
		return errors.New("trusted-tailnet mode does not use client credentials or pairing")
	}
	manager, err := runner.NewManager(config, store)
	if err != nil {
		return err
	}
	defer manager.Close()
	ctx := context.Background()
	switch args[0] {
	case "doctor":
		value, err := manager.Doctor(ctx)
		if err != nil {
			return err
		}
		if err := printJSON(value); err != nil {
			return err
		}
		if ok, _ := value["ok"].(bool); !ok {
			return errors.New("one or more host readiness checks failed")
		}
		return nil
	case "templates":
		return templates(ctx, store, manager, fs.Args())
	case "pairings":
		return pairings(ctx, store, fs.Args())
	case "clients":
		return clients(ctx, store, fs.Args())
	case "instances":
		return hostInstances(ctx, manager, fs.Args())
	case "drives", "environment-sets", "snapshots":
		return hostStorage(ctx, store, manager, args[0], fs.Args())
	case "serve":
		if err := manager.Reconcile(ctx); err != nil {
			return err
		}
		server := runner.NewServer(config, store, manager)
		signals := make(chan os.Signal, 1)
		signal.Notify(signals, syscall.SIGINT, syscall.SIGTERM)
		go func() {
			<-signals
			shutdown, cancel := context.WithTimeout(context.Background(), 15*time.Second)
			defer cancel()
			_ = server.Shutdown(shutdown)
		}()
		fmt.Fprintf(os.Stderr, "[runner] listening on %s\n", config.Listen)
		err := server.Serve()
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	}
	return nil
}

func hostInstances(ctx context.Context, manager *runner.Manager, args []string) error {
	if len(args) != 2 || args[0] != "purge" {
		return errors.New("instances supports purge ID for removed instances")
	}
	if err := manager.PurgeRemoved(ctx, args[1]); err != nil {
		return err
	}
	fmt.Fprintln(os.Stdout, "purged")
	return nil
}

func templates(ctx context.Context, store *runner.Store, manager *runner.Manager, args []string) error {
	if len(args) == 0 || args[0] == "list" {
		values, err := store.Templates(ctx)
		if err != nil {
			return err
		}
		return printJSON(map[string]any{"templates": values})
	}
	if args[0] != "add" {
		return errors.New("templates supports list or add")
	}
	fs := flag.NewFlagSet("templates add", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	flatpak := fs.Bool("flatpak", false, "enable explicit nested Flatpak policy")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	remaining := fs.Args()
	if len(remaining) != 2 {
		return errors.New("templates add requires NAME IMAGE")
	}
	if !validName(remaining[0]) {
		return errors.New("template name must use lowercase letters, digits, or hyphens")
	}
	digest, err := manager.ResolveImage(ctx, remaining[1])
	if err != nil {
		return fmt.Errorf("inspect approved image: %w", err)
	}
	value := runner.Template{Name: remaining[0], Image: remaining[1], Digest: digest, Flatpak: *flatpak}
	if err := store.AddTemplate(ctx, value); err != nil {
		return err
	}
	fmt.Fprintf(os.Stdout, "Approved %s at immutable %s\n", remaining[0], digest)
	return nil
}

func pairings(ctx context.Context, store *runner.Store, args []string) error {
	if len(args) == 0 || args[0] == "list" {
		values, err := store.Pairings(ctx)
		if err != nil {
			return err
		}
		return printJSON(map[string]any{"pairings": values})
	}
	if len(args) != 2 || (args[0] != "approve" && args[0] != "deny") {
		return errors.New("pairings supports list, approve CODE, or deny CODE")
	}
	value, err := store.ApprovePairing(ctx, strings.ToUpper(args[1]), args[0] == "approve")
	if err != nil {
		return err
	}
	return printJSON(map[string]any{"pairing": value})
}

func clients(ctx context.Context, store *runner.Store, args []string) error {
	if len(args) == 0 || args[0] == "list" {
		values, err := store.Clients(ctx)
		if err != nil {
			return err
		}
		return printJSON(map[string]any{"clients": values})
	}
	if len(args) != 2 || args[0] != "revoke" {
		return errors.New("clients supports list or revoke ID")
	}
	if err := store.RevokeClient(ctx, args[1]); err != nil {
		return err
	}
	fmt.Fprintln(os.Stdout, "revoked")
	return nil
}

func validName(value string) bool {
	if len(value) < 1 || len(value) > 48 {
		return false
	}
	for _, r := range value {
		if !(r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '-') {
			return false
		}
	}
	return true
}
func printJSON(value any) error {
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	return encoder.Encode(value)
}
func usage() {
	fmt.Fprintln(os.Stdout, `vibestack-runner 0.2.0

Usage: vibestack-runner COMMAND [--config FILE]

  init                 Create a reviewable default configuration
  doctor               Check Docker, resources, architecture, and disk
  templates list       List approved immutable image digests
  templates add N I    Approve a locally inspected image
  pairings list        Show pending device pairings
  pairings approve C   Approve a displayed verification code
  pairings deny C      Deny a verification code
  clients list         List individually revocable clients
  clients revoke ID    Revoke a client
  instances purge ID   Purge removed desktop private state; retain file drives
  drives list OWNER    List a principal's registered drives
  drives create NAME OWNER   Register a managed file volume
  drives register NAME OWNER PATH   Register a dedicated host folder
  drives purge ID      Purge an unattached managed volume or unregister a folder
  environment-sets add NAME OWNER FILE   Store private JSON values
  environment-sets list OWNER   List names and keys only
  snapshots list OWNER List private stopped-state snapshots
  snapshots purge ID   Permanently remove an unused snapshot
  serve                Run the authenticated loopback API`)
}

func hostStorage(ctx context.Context, store *runner.Store, manager *runner.Manager, kind string, args []string) error {
	if len(args) == 2 && args[0] == "list" {
		switch kind {
		case "drives":
			v, err := store.Drives(ctx, args[1])
			if err != nil {
				return err
			}
			return printJSON(map[string]any{"drives": v})
		case "environment-sets":
			v, err := store.Environments(ctx, args[1])
			if err != nil {
				return err
			}
			return printJSON(map[string]any{"environment_sets": v})
		case "snapshots":
			v, err := store.Snapshots(ctx, args[1])
			if err != nil {
				return err
			}
			return printJSON(map[string]any{"snapshots": v})
		}
	}
	if len(args) == 2 && args[0] == "purge" {
		switch kind {
		case "drives":
			return manager.PurgeDrive(ctx, args[1])
		case "snapshots":
			return manager.PurgeSnapshot(ctx, args[1])
		}
	}
	if kind == "drives" && len(args) == 3 && args[0] == "create" {
		v, err := store.RegisterDrive(ctx, args[1], args[2], "volume", "")
		if err != nil {
			return err
		}
		return printJSON(map[string]any{"drive": v})
	}
	if kind == "drives" && len(args) == 4 && args[0] == "register" {
		v, err := store.RegisterDrive(ctx, args[1], args[2], "bind", args[3])
		if err != nil {
			return err
		}
		return printJSON(map[string]any{"drive": v})
	}
	if kind == "environment-sets" && len(args) == 4 && args[0] == "add" {
		f, err := os.Open(args[3])
		if err != nil {
			return errors.New("environment file is unavailable")
		}
		defer f.Close()
		info, err := f.Stat()
		if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 65536 {
			return errors.New("environment file must be a private regular file of at most 64 KiB")
		}
		var values map[string]string
		decoder := json.NewDecoder(io.LimitReader(f, 65537))
		if err := decoder.Decode(&values); err != nil {
			return errors.New("environment file must contain a JSON string map")
		}
		if err := decoder.Decode(&struct{}{}); err != io.EOF {
			return errors.New("environment file contains trailing data")
		}
		v, err := store.AddEnvironment(ctx, args[1], args[2], values)
		if err != nil {
			return err
		}
		return printJSON(map[string]any{"environment_set": v})
	}
	return errors.New("invalid storage command; see help")
}

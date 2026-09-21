package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/check-the-vibe/vibestack/service"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run(args []string) error {
	if len(args) == 0 {
		return errors.New("usage: vibestack-service serve | credential <create|list|revoke>")
	}
	command := args[0]
	if command == "credential" {
		if len(args) < 2 {
			return errors.New("credential requires create, list or revoke")
		}
		command = "credential-" + args[1]
		args = args[1:]
	}
	fs := flag.NewFlagSet(command, flag.ContinueOnError)
	state := fs.String("state-dir", "/data/vibestack", "protected persistent workspace state")
	listen := fs.String("listen", "127.0.0.1:7996", "loopback service listener")
	public := fs.String("public-url", os.Getenv("VIBESTACK_PUBLIC_URL"), "canonical HTTPS origin")
	static := fs.String("static-root", "/usr/share/vibestack/public", "published files only")
	label := fs.String("label", "workspace client", "credential label")
	owner := fs.Bool("owner", false, "grant local-owner administration")
	caps := fs.String("capabilities", "", "comma-separated operation IDs; empty grants workspace operations")
	lifetime := fs.Duration("expires-in", 30*24*time.Hour, "credential lifetime, at most one year")
	output := fs.String("output", "", "new protected credential file; plaintext is never printed")
	id := fs.String("id", "", "credential ID to revoke")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if fs.NArg() != 0 {
		return errors.New("unexpected positional arguments")
	}
	if command != "serve" && command != "credential-create" && command != "credential-list" && command != "credential-revoke" {
		return errors.New("unknown service command")
	}
	s, err := service.NewStore(*state)
	if err != nil {
		return err
	}
	defer s.Close()
	switch command {
	case "credential-list":
		list, err := s.List()
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]any{"instance_id": s.Identity, "credentials": list})
	case "credential-revoke":
		if err := s.Revoke(*id); err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]any{"revoked": *id})
	case "credential-create":
		if *output == "" || !filepath.IsAbs(*output) {
			return errors.New("--output requires a new absolute credential-file path")
		}
		if err := os.MkdirAll(filepath.Dir(*output), 0700); err != nil {
			return errors.New("credential output directory is unavailable")
		}
		file, err := os.OpenFile(*output, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return errors.New("credential output must be a new file; existing files are preserved")
		}
		ok := false
		defer func() {
			file.Close()
			if !ok {
				os.Remove(*output)
			}
		}()
		var allowed []string
		if *caps != "" {
			allowed = strings.Split(*caps, ",")
		}
		credential, token, err := s.Issue(*label, *owner, allowed, *lifetime)
		if err != nil {
			return err
		}
		if _, err = file.WriteString(token + "\n"); err == nil {
			err = file.Sync()
		}
		if err != nil {
			s.Revoke(credential.ID)
			return errors.New("credential file could not be written; new grant revoked")
		}
		if err := file.Close(); err != nil {
			s.Revoke(credential.ID)
			return errors.New("credential file could not be closed; new grant revoked")
		}
		ok = true
		return json.NewEncoder(os.Stdout).Encode(map[string]any{"instance_id": s.Identity, "credential": credential, "credential_file": *output})
	}
	host, _, err := net.SplitHostPort(*listen)
	if err != nil || (host != "localhost" && (net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback())) {
		return errors.New("the service must listen on loopback")
	}
	server, err := service.NewServer(service.Config{Store: s, PublicURL: *public, StaticRoot: *static, AllowedHosts: strings.Split(os.Getenv("VIBESTACK_ALLOWED_HOSTS"), ","), AutomationURL: "http://127.0.0.1:7997", ControlURL: "http://127.0.0.1:7998", SetupURL: "http://127.0.0.1:7999"})
	if err != nil {
		return err
	}
	defer server.Close()
	listener, err := net.Listen("tcp", *listen)
	if err != nil {
		return errors.New("workspace listener unavailable")
	}
	httpServer := &http.Server{Handler: server, ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 35 * time.Second, WriteTimeout: 330 * time.Second, IdleTimeout: 65 * time.Second, MaxHeaderBytes: 16 << 10}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		httpServer.Shutdown(shutdown)
	}()
	fmt.Fprintln(os.Stderr, "VibeStack workspace service ready on loopback")
	err = httpServer.Serve(listener)
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return errors.New("workspace HTTP service stopped unexpectedly")
}

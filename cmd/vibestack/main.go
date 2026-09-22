package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	assets "github.com/check-the-vibe/vibestack"
	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
)

type globalOptions struct {
	instance string
	profile  string
	json     bool
	ca       string
}

type remoteJobError struct {
	ID, Status string
	ExitCode   int
}

type remoteOperationError struct {
	ID, Code, Message string
}

func (e *remoteOperationError) Error() string {
	if e.Code != "" {
		return fmt.Sprintf("remote operation %s failed (%s): %s", e.ID, e.Code, e.Message)
	}
	return fmt.Sprintf("remote operation %s failed: %s", e.ID, e.Message)
}

func (e *remoteJobError) Error() string {
	return fmt.Sprintf("remote job %s finished with status %s (exit %d)", e.ID, e.Status, e.ExitCode)
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		var remote *api.HTTPError
		if errors.As(err, &remote) && remote.Code != "" {
			fmt.Fprintf(os.Stderr, "vibestack: %s: %v\n", remote.Code, remote)
		} else {
			fmt.Fprintf(os.Stderr, "vibestack: %v\n", err)
		}
		os.Exit(exitCode(err))
	}
}

func exitCode(err error) int {
	var job *remoteJobError
	if errors.As(err, &job) && job.ExitCode > 0 && job.ExitCode <= 125 {
		return job.ExitCode
	}
	var operation *remoteOperationError
	if errors.As(err, &operation) {
		return 3
	}
	var remote *api.HTTPError
	if errors.As(err, &remote) {
		switch remote.Status {
		case 401, 403:
			return 4
		case 404:
			return 5
		case 409, 412:
			return 6
		default:
			return 3
		}
	}
	return 2
}

func run(args []string) error {
	g, command, rest, err := parseGlobal(args)
	if err != nil {
		return err
	}
	if command == "" || command == "help" || command == "--help" || command == "-h" {
		usage(os.Stdout)
		return nil
	}
	if command == "version" {
		fmt.Fprintln(os.Stdout, api.Version)
		return nil
	}
	ctx := context.Background()
	switch command {
	case "connect":
		return connect(ctx, rest, g)
	case "profiles":
		return profiles(rest, g)
	case "skill":
		return skill(rest, g)
	}
	profile, client, err := selectedClient(g, "")
	if err != nil {
		return err
	}
	if (isWorkspaceCommand(command) || g.instance != "" && (command == "api" || command == "capabilities")) && profile.Kind == "runner" {
		if g.instance == "" {
			return errors.New("runner workspace commands require explicit --instance ID")
		}
		var selected struct {
			Instance api.Instance `json:"instance"`
		}
		if _, err := client.JSON(ctx, "GET", api.RunnerAPI+"/instances/"+url.PathEscape(g.instance), nil, &selected, true, nil); err != nil {
			return err
		}
		if command == "account" {
			fmt.Fprintln(os.Stdout, selected.Instance.URLs["password_setup"])
			return nil
		}
		client.InstanceID = selected.Instance.ID
		profile.Kind = "workspace"
	} else if g.instance != "" {
		return errors.New("--instance is supported only for workspace commands through a runner profile")
	}
	switch command {
	case "mcp":
		return mcpCommand(ctx, client, profile, rest)
	case "capability":
		return capabilityCommand(ctx, client, profile, rest, g)
	case "doctor":
		return doctor(ctx, client, profile, g)
	case "capabilities":
		root := api.WorkspaceAPI
		if profile.Kind == "runner" {
			root = api.RunnerAPI
		}
		return jsonRequest(ctx, client, http.MethodGet, root, nil, true, g)
	case "exec":
		return commandExec(ctx, client, profile, rest, false, g)
	case "shell":
		return commandExec(ctx, client, profile, rest, true, g)
	case "jobs":
		return jobs(ctx, client, profile, rest, g)
	case "screenshot":
		return screenshot(ctx, client, profile, rest, g)
	case "apps":
		return apps(ctx, client, profile, rest, g)
	case "windows":
		return windows(ctx, client, profile, rest, g)
	case "clipboard":
		return clipboard(ctx, client, profile, rest, g)
	case "files":
		return files(ctx, client, profile, rest, g)
	case "status", "display", "services", "logs":
		return control(ctx, client, profile, command, rest, g)
	case "setup":
		if err := requireWorkspace(profile); err != nil {
			return err
		}
		return jsonRequest(ctx, client, http.MethodGet, "/setup/api/state", nil, true, g)
	case "account":
		if err := requireWorkspace(profile); err != nil {
			return err
		}
		fmt.Fprintln(os.Stdout, strings.TrimSuffix(profile.URL, "/")+"/vnc/")
		return nil
	case "ssh-keys":
		return sshKeys(ctx, client, rest, g)
	case "instances":
		return instances(ctx, client, profile, rest, g)
	case "operations":
		return operations(ctx, client, profile, rest, g)
	case "docs":
		return docs(ctx, client, profile, rest)
	case "api":
		return rawAPI(ctx, client, rest, g)
	default:
		return fmt.Errorf("unknown command %q", command)
	}
}

func parseGlobal(args []string) (globalOptions, string, []string, error) {
	var g globalOptions
	for len(args) > 0 {
		switch args[0] {
		case "--json":
			g.json = true
			args = args[1:]
		case "--instance":
			if len(args) < 2 || args[1] == "" {
				return g, "", nil, errors.New("--instance requires an ID")
			}
			g.instance = args[1]
			args = args[2:]
		case "--profile":
			if len(args) < 2 {
				return g, "", nil, errors.New("--profile requires a name")
			}
			g.profile = args[1]
			args = args[2:]
		case "--ca":
			if len(args) < 2 {
				return g, "", nil, errors.New("--ca requires a file")
			}
			g.ca = args[1]
			args = args[2:]
		default:
			return g, args[0], args[1:], nil
		}
	}
	return g, "", nil, nil
}

func usage(w io.Writer) {
	fmt.Fprintln(w, "VibeStack client "+api.Version+`

Usage: vibestack [--profile NAME] [--instance ID] [--json] COMMAND [OPTIONS]

Connection: connect, profiles, doctor, capabilities
Work:       exec, shell, jobs, files, screenshot, apps, windows, clipboard
Workspace:  status, display, services, logs, setup, account, ssh-keys
Runner:     instances, operations
Agent:      capability, mcp, skill, docs, api

Trusted-tailnet brokers connect without pairing or a bearer credential.
Workspace commands through a runner require --instance ID before COMMAND.
instances password ID [--password-stdin] prompts privately by default.
instances create supports --prompt-password or --password-stdin; provisions first.
Passwords have no argument or environment-variable input.
When more than one compatible profile exists, --profile is required.`)
}

func selectedClient(g globalOptions, kind string) (api.Profile, *api.Client, error) {
	profile, err := api.SelectProfile(g.profile, kind)
	if err != nil {
		return api.Profile{}, nil, err
	}
	ca := g.ca
	if ca == "" {
		ca = profile.CAFile
	}
	client, err := api.NewClient(profile.URL, profile.Credential, ca)
	if err == nil {
		client.AuthenticationMode = profile.AuthenticationMode
		client.GatewayTokenFile = profile.GatewayTokenFile
		if profile.Kind == "workspace" {
			if len(profile.Identity) != 32 || strings.Trim(profile.Identity, "0123456789abcdef") != "" {
				return profile, nil, errors.New("workspace profile has no valid identity; reconnect explicitly")
			}
			client.ExpectedIdentity = profile.Identity
		}
		err = client.ValidateGateway()
	}
	return profile, client, err
}

func connect(ctx context.Context, args []string, g globalOptions) error {
	fs := flag.NewFlagSet("connect", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	name := fs.String("name", "", "profile name")
	rawURL := fs.String("url", "", "server origin")
	label := fs.String("label", hostname(), "device label")
	tokenStdin := fs.Bool("token-stdin", false, "read a legacy token from stdin")
	gatewayFile := fs.String("gateway-token-file", "", "protected private Codespaces gateway token file")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *name == "" || *rawURL == "" {
		return errors.New("connect requires --name and --url")
	}
	if len(*name) > 64 || strings.ContainsAny(*name, " /\\\t\r\n") {
		return errors.New("profile name must be 1-64 characters without whitespace or slashes")
	}
	client, err := api.NewClient(*rawURL, "", g.ca)
	if err != nil {
		return err
	}
	if *gatewayFile != "" {
		*gatewayFile, err = filepath.Abs(*gatewayFile)
		if err != nil {
			return errors.New("gateway credential path is invalid")
		}
		client.GatewayTokenFile = *gatewayFile
		if err := client.ValidateGateway(); err != nil {
			return err
		}
	}
	discovery, err := client.Discover(ctx)
	if err != nil {
		return err
	}
	profilesFile, err := api.LoadProfiles()
	if err != nil {
		return err
	}
	if _, ok := profilesFile.Profiles[*name]; ok {
		return errors.New("profile name already exists; it was preserved (remove it explicitly before reconnecting)")
	}
	credential := ""
	clientID := ""
	if discovery.AuthenticationMode == "trusted-tailnet" {
		if *tokenStdin {
			return errors.New("trusted-tailnet mode does not accept a stored token")
		}
		client.AuthenticationMode = discovery.AuthenticationMode
	} else if *tokenStdin {
		secret, readErr := io.ReadAll(io.LimitReader(os.Stdin, 1025))
		if readErr != nil {
			return readErr
		}
		if len(secret) > 1024 {
			for i := range secret {
				secret[i] = 0
			}
			return errors.New("stdin token exceeds 1024 bytes")
		}
		credential = strings.TrimSpace(string(secret))
		for i := range secret {
			secret[i] = 0
		}
		if credential == "" || strings.ContainsAny(credential, " \t\r\n") {
			return errors.New("stdin did not contain one token")
		}
	} else {
		permissions := discovery.Pairing.Permissions
		if len(permissions) == 0 {
			return errors.New("server does not advertise pairing")
		}
		requestPath := discovery.Pairing.Request
		var pairing api.PairingRequest
		if _, err := client.JSON(ctx, http.MethodPost, requestPath, map[string]any{"device_label": *label, "permissions": permissions}, &pairing, false, nil); err != nil {
			return err
		}
		fmt.Fprintf(os.Stderr, "Approve verification code %s for %s.\n", pairing.VerificationCode, *label)
		if discovery.Pairing.Approval != "" {
			approval := discovery.Pairing.Approval
			if strings.HasPrefix(approval, "/") {
				approval = strings.TrimSuffix(*rawURL, "/") + approval
			}
			fmt.Fprintf(os.Stderr, "Approval: %s\n", approval)
		}
		pollPath := strings.TrimSuffix(requestPath, "/") + "/" + pairing.PairingID + "/poll"
		interval := time.Duration(pairing.IntervalSeconds) * time.Second
		if interval < time.Second {
			interval = 2 * time.Second
		}
		deadline := time.Now().Add(11 * time.Minute)
		for {
			if time.Now().After(deadline) {
				return errors.New("pairing timed out")
			}
			var result api.PairingResult
			_, pollErr := client.JSON(ctx, http.MethodPost, pollPath, map[string]string{"polling_secret": pairing.PollingSecret}, &result, false, nil)
			if pollErr != nil {
				return pollErr
			}
			if result.Status == "approved" {
				credential, clientID = result.Credential, result.ClientID
				break
			}
			if result.Status != "pending" {
				return fmt.Errorf("pairing ended with status %s", result.Status)
			}
			time.Sleep(interval)
		}
	}
	if discovery.Kind == "workspace" && discovery.Endpoints["capabilities"] != "" {
		client.Credential, client.ExpectedIdentity = credential, discovery.Identity
		var catalog struct {
			InstanceID string `json:"instance_id"`
		}
		if _, err := client.JSON(ctx, http.MethodGet, "/api/v1/capabilities", nil, &catalog, true, nil); err != nil {
			return err
		}
		if catalog.InstanceID != discovery.Identity {
			return errors.New("authenticated response did not match the discovered workspace")
		}
	}
	profilesFile.Profiles[*name] = api.Profile{AuthenticationMode: discovery.AuthenticationMode, Name: *name, URL: strings.TrimSuffix(*rawURL, "/"), Kind: discovery.Kind, Identity: discovery.Identity, Credential: credential, CAFile: g.ca, ClientID: clientID, GatewayTokenFile: *gatewayFile}
	if err := api.SaveProfiles(profilesFile); err != nil {
		return err
	}
	if g.json {
		return printJSON(map[string]any{"profile": *name, "kind": discovery.Kind, "identity": discovery.Identity, "authentication_mode": discovery.AuthenticationMode, "paired": !*tokenStdin && discovery.AuthenticationMode != "trusted-tailnet"})
	}
	fmt.Fprintf(os.Stdout, "Connected profile %q to %s %s.\n", *name, discovery.Kind, discovery.Identity)
	return nil
}

func hostname() string {
	value, err := os.Hostname()
	if err != nil || value == "" {
		return runtime.GOOS + "-client"
	}
	if len(value) > 80 {
		return value[:80]
	}
	return value
}

func profiles(args []string, g globalOptions) error {
	value, err := api.LoadProfiles()
	if err != nil {
		return err
	}
	action := "list"
	if len(args) > 0 {
		action = args[0]
	}
	switch action {
	case "list":
		if g.json {
			clean := make([]map[string]string, 0, len(value.Profiles))
			for _, name := range api.ProfileNames(value) {
				p := value.Profiles[name]
				clean = append(clean, map[string]string{"name": name, "url": p.URL, "kind": p.Kind, "identity": p.Identity})
			}
			return printJSON(map[string]any{"profiles": clean})
		}
		for _, name := range api.ProfileNames(value) {
			p := value.Profiles[name]
			fmt.Fprintf(os.Stdout, "%s\t%s\t%s\n", name, p.Kind, p.URL)
		}
		return nil
	case "show":
		if len(args) != 2 {
			return errors.New("profiles show requires a name")
		}
		p, ok := value.Profiles[args[1]]
		if !ok {
			return errors.New("profile does not exist")
		}
		return printJSON(map[string]any{"name": p.Name, "url": p.URL, "kind": p.Kind, "identity": p.Identity, "ca_file": p.CAFile, "client_id": p.ClientID})
	case "remove":
		if len(args) != 2 {
			return errors.New("profiles remove requires a name")
		}
		if _, ok := value.Profiles[args[1]]; !ok {
			return errors.New("profile does not exist")
		}
		delete(value.Profiles, args[1])
		return api.SaveProfiles(value)
	default:
		return errors.New("profiles supports list, show, or remove")
	}
}

func doctor(ctx context.Context, client *api.Client, profile api.Profile, g globalOptions) error {
	discovery, err := client.Discover(ctx)
	if err != nil {
		return err
	}
	if discovery.AuthenticationMode != profile.AuthenticationMode && !(profile.AuthenticationMode == "" && discovery.AuthenticationMode == "paired") {
		return errors.New("server authentication mode no longer matches profile; reconnect explicitly")
	}
	if discovery.Identity != profile.Identity {
		return errors.New("server identity no longer matches the profile")
	}
	compatible := false
	for _, version := range discovery.APIVersions {
		if version == "1" {
			compatible = true
		}
	}
	if !compatible {
		return fmt.Errorf("server does not advertise compatible API version 1 (offered %v)", discovery.APIVersions)
	}
	root := api.WorkspaceAPI
	if profile.Kind == "runner" {
		root = api.RunnerAPI
	}
	var capabilities map[string]any
	requestID, err := client.JSON(ctx, http.MethodGet, root, nil, &capabilities, true, nil)
	if err != nil {
		return err
	}
	result := map[string]any{"ok": true, "profile": profile.Name, "kind": profile.Kind, "identity": discovery.Identity, "server_version": discovery.Version, "api_versions": discovery.APIVersions, "request_id": requestID}
	if g.json {
		return printJSON(result)
	}
	fmt.Fprintf(os.Stdout, "OK %s %s (server %s, request %s)\n", profile.Kind, discovery.Identity, discovery.Version, requestID)
	return nil
}

func requireWorkspace(profile api.Profile) error {
	if profile.Kind != "workspace" {
		return errors.New("command requires a workspace profile")
	}
	return nil
}

func requireRunner(profile api.Profile) error {
	if profile.Kind != "runner" {
		return errors.New("command requires a runner profile")
	}
	return nil
}

func commandExec(ctx context.Context, client *api.Client, profile api.Profile, args []string, shell bool, g globalOptions) error {
	if err := requireWorkspace(profile); err != nil {
		return err
	}
	fs := flag.NewFlagSet("exec", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	async := fs.Bool("async", false, "return job id")
	desktop := fs.Bool("desktop", false, "use Desktop root")
	cwd := fs.String("cwd", "", "root-relative cwd")
	timeout := fs.Int("timeout", 30, "timeout seconds")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	root := "projects"
	if *desktop {
		root = "desktop"
	}
	body := map[string]any{"cwd": *cwd, "root": root, "timeout_seconds": *timeout}
	endpoint := api.WorkspaceAPI + "/commands"
	if shell {
		if len(remaining) != 1 {
			return errors.New("shell requires exactly one command string")
		}
		body["command"] = remaining[0]
		endpoint = api.WorkspaceAPI + "/shell"
	} else {
		if len(remaining) == 0 {
			return errors.New("exec requires an argv after --")
		}
		body["argv"] = remaining
	}
	var envelope api.JobEnvelope
	requestID, err := client.JSON(ctx, http.MethodPost, endpoint, body, &envelope, true, nil)
	if err != nil {
		return err
	}
	if *async {
		if g.json {
			return printJSON(map[string]any{"job": envelope.Job, "request_id": requestID})
		}
		fmt.Fprintln(os.Stdout, envelope.Job.ID)
		return nil
	}
	job, err := waitJob(ctx, client, envelope.Job.ID)
	if err != nil {
		return err
	}
	if g.json {
		stdout, _ := readJobOutput(ctx, client, job.ID, "stdout")
		stderr, _ := readJobOutput(ctx, client, job.ID, "stderr")
		return printJSON(map[string]any{"job": job, "request_id": requestID, "stdout_base64": base64.StdEncoding.EncodeToString(stdout), "stderr_base64": base64.StdEncoding.EncodeToString(stderr)})
	}
	stdout, outErr := readJobOutput(ctx, client, job.ID, "stdout")
	if outErr != nil {
		return outErr
	}
	stderr, errErr := readJobOutput(ctx, client, job.ID, "stderr")
	if errErr != nil {
		return errErr
	}
	if _, err := os.Stdout.Write(stdout); err != nil {
		return err
	}
	if _, err := os.Stderr.Write(stderr); err != nil {
		return err
	}
	if job.Status != "succeeded" || (job.ExitCode != nil && *job.ExitCode != 0) {
		code := 1
		if job.ExitCode != nil && *job.ExitCode > 0 {
			code = *job.ExitCode
		}
		return &remoteJobError{ID: job.ID, Status: job.Status, ExitCode: code}
	}
	return nil
}

func waitJob(ctx context.Context, client *api.Client, id string) (api.Job, error) {
	for {
		var envelope api.JobEnvelope
		if _, err := client.JSON(ctx, http.MethodGet, api.WorkspaceAPI+"/jobs/"+id, nil, &envelope, true, nil); err != nil {
			return api.Job{}, err
		}
		switch envelope.Job.Status {
		case "succeeded", "failed", "cancelled", "timed_out", "interrupted":
			return envelope.Job, nil
		}
		select {
		case <-ctx.Done():
			return api.Job{}, ctx.Err()
		case <-time.After(300 * time.Millisecond):
		}
	}
}

func readJobOutput(ctx context.Context, client *api.Client, id, stream string) ([]byte, error) {
	var result bytes.Buffer
	cursor := int64(0)
	for {
		var page api.OutputPage
		path := fmt.Sprintf("%s/jobs/%s/output?stream=%s&cursor=%d&limit=262144", api.WorkspaceAPI, id, stream, cursor)
		if _, err := client.JSON(ctx, http.MethodGet, path, nil, &page, true, nil); err != nil {
			return nil, err
		}
		chunk, err := base64.StdEncoding.DecodeString(page.Data)
		if err != nil {
			return nil, err
		}
		result.Write(chunk)
		cursor = page.NextCursor
		if page.EOF {
			return result.Bytes(), nil
		}
		time.Sleep(150 * time.Millisecond)
	}
}

func jobs(ctx context.Context, client *api.Client, profile api.Profile, args []string, g globalOptions) error {
	if err := requireWorkspace(profile); err != nil {
		return err
	}
	if len(args) < 2 {
		return errors.New("jobs requires get, wait, output, or cancel and a job id")
	}
	action, id := args[0], args[1]
	switch action {
	case "get":
		return jsonRequest(ctx, client, http.MethodGet, api.WorkspaceAPI+"/jobs/"+id, nil, true, g)
	case "wait":
		job, err := waitJob(ctx, client, id)
		if err != nil {
			return err
		}
		if err := printValue(job, g); err != nil {
			return err
		}
		if job.Status != "succeeded" || (job.ExitCode != nil && *job.ExitCode != 0) {
			code := 1
			if job.ExitCode != nil && *job.ExitCode > 0 {
				code = *job.ExitCode
			}
			return &remoteJobError{ID: job.ID, Status: job.Status, ExitCode: code}
		}
		return nil
	case "cancel":
		return jsonRequest(ctx, client, http.MethodPost, api.WorkspaceAPI+"/jobs/"+id+"/cancel", map[string]any{}, true, g)
	case "output":
		stream := "stdout"
		if len(args) > 2 {
			stream = args[2]
		}
		data, err := readJobOutput(ctx, client, id, stream)
		if err != nil {
			return err
		}
		_, err = os.Stdout.Write(data)
		return err
	default:
		return errors.New("jobs supports get, wait, output, or cancel")
	}
}

func screenshot(ctx context.Context, client *api.Client, profile api.Profile, args []string, g globalOptions) error {
	if err := requireWorkspace(profile); err != nil {
		return err
	}
	fs := flag.NewFlagSet("screenshot", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	output := fs.String("output", "screenshot.png", "local output file")
	remote := fs.String("remote", "", "Desktop-relative storage path")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *remote != "" {
		return jsonRequest(ctx, client, http.MethodPost, api.WorkspaceAPI+"/screenshot", map[string]string{"filename": *remote}, true, g)
	}
	resp, err := client.Do(ctx, http.MethodPost, api.WorkspaceAPI+"/screenshot", bytes.NewReader([]byte("{}")), "application/json", true, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 17<<20))
	if err != nil {
		return err
	}
	if len(data) > 16<<20 || len(data) < 8 || !bytes.Equal(data[:8], []byte("\x89PNG\r\n\x1a\n")) {
		return errors.New("server returned an invalid or oversized PNG")
	}
	if err := writeAtomic(*output, data, 0600); err != nil {
		return err
	}
	if g.json {
		return printJSON(map[string]any{"path": *output, "bytes": len(data), "request_id": resp.Header.Get("X-Request-ID")})
	}
	fmt.Fprintf(os.Stdout, "%s (%d bytes)\n", *output, len(data))
	return nil
}

func apps(ctx context.Context, client *api.Client, profile api.Profile, args []string, g globalOptions) error {
	if err := requireWorkspace(profile); err != nil {
		return err
	}
	if len(args) == 0 || args[0] == "list" {
		return jsonRequest(ctx, client, http.MethodGet, api.WorkspaceAPI+"/applications", nil, true, g)
	}
	if len(args) != 2 || (args[0] != "start" && args[0] != "stop") {
		return errors.New("apps supports list, start ID, or stop ID")
	}
	return jsonRequest(ctx, client, http.MethodPost, api.WorkspaceAPI+"/applications/"+url.PathEscape(args[1])+"/"+args[0], map[string]any{}, true, g)
}

func windows(ctx context.Context, client *api.Client, profile api.Profile, args []string, g globalOptions) error {
	if err := requireWorkspace(profile); err != nil {
		return err
	}
	if len(args) == 0 || args[0] == "list" {
		return jsonRequest(ctx, client, http.MethodGet, api.WorkspaceAPI+"/windows", nil, true, g)
	}
	if len(args) != 3 || args[0] != "state" {
		return errors.New("windows supports list or state ID STATE")
	}
	return jsonRequest(ctx, client, http.MethodPost, api.WorkspaceAPI+"/windows/"+url.PathEscape(args[1])+"/state", map[string]string{"state": args[2]}, true, g)
}

func clipboard(ctx context.Context, client *api.Client, profile api.Profile, args []string, g globalOptions) error {
	if err := requireWorkspace(profile); err != nil {
		return err
	}
	if len(args) == 0 || args[0] == "get" {
		resp, err := client.Do(ctx, http.MethodGet, api.WorkspaceAPI+"/clipboard", nil, "", true, nil)
		if err != nil {
			return err
		}
		defer resp.Body.Close()
		_, err = io.Copy(os.Stdout, io.LimitReader(resp.Body, 1<<20))
		return err
	}
	if len(args) != 1 || args[0] != "set" {
		return errors.New("clipboard supports get or set (set reads stdin)")
	}
	data, err := io.ReadAll(io.LimitReader(os.Stdin, (1<<20)+1))
	if err != nil {
		return err
	}
	if len(data) > 1<<20 {
		return errors.New("clipboard input exceeds 1 MiB")
	}
	resp, err := client.Do(ctx, http.MethodPut, api.WorkspaceAPI+"/clipboard", bytes.NewReader(data), "text/plain; charset=utf-8", true, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	return copyJSONOrRaw(resp.Body, g)
}

func escapeFilePath(value string) (string, error) {
	if value == "" || strings.HasPrefix(value, "/") {
		return "", errors.New("remote path must be relative")
	}
	parts := strings.Split(value, "/")
	encoded := make([]string, len(parts))
	for i, part := range parts {
		if part == "" || part == "." || part == ".." {
			return "", errors.New("remote path contains an invalid component")
		}
		encoded[i] = url.PathEscape(part)
	}
	return strings.Join(encoded, "/"), nil
}

func files(ctx context.Context, client *api.Client, profile api.Profile, args []string, g globalOptions) error {
	if err := requireWorkspace(profile); err != nil {
		return err
	}
	fs := flag.NewFlagSet("files", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	desktop := fs.Bool("desktop", false, "use Desktop file root")
	ifMatch := fs.String("if-match", "", "conditional ETag")
	ifNone := fs.String("if-none-match", "", "conditional ETag")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if len(remaining) < 2 {
		return errors.New("files requires get, put, or head and a remote path")
	}
	encoded, err := escapeFilePath(remaining[1])
	if err != nil {
		return err
	}
	root := "/projects/"
	if *desktop {
		root = "/files/"
	}
	endpoint := api.WorkspaceAPI + root + encoded
	headers := map[string]string{}
	if *ifMatch != "" {
		headers["If-Match"] = *ifMatch
	}
	if *ifNone != "" {
		headers["If-None-Match"] = *ifNone
	}
	switch remaining[0] {
	case "get":
		output := ""
		if len(remaining) == 3 {
			output = remaining[2]
		}
		if len(remaining) > 3 {
			return errors.New("files get accepts at most one local path")
		}
		resp, err := client.Do(ctx, http.MethodGet, endpoint, nil, "", true, headers)
		if err != nil {
			return err
		}
		defer resp.Body.Close()
		if output == "" {
			_, err = io.Copy(os.Stdout, resp.Body)
			return err
		}
		data, err := io.ReadAll(io.LimitReader(resp.Body, (16<<20)+1))
		if err != nil {
			return err
		}
		if len(data) > 16<<20 {
			return errors.New("download exceeds 16 MiB")
		}
		return writeAtomic(output, data, 0600)
	case "put":
		if len(remaining) != 3 {
			return errors.New("files put requires a local path or -")
		}
		var input io.Reader = os.Stdin
		var file *os.File
		if remaining[2] != "-" {
			file, err = os.Open(remaining[2])
			if err != nil {
				return err
			}
			defer file.Close()
			input = file
		}
		data, err := io.ReadAll(io.LimitReader(input, (16<<20)+1))
		if err != nil {
			return err
		}
		if len(data) > 16<<20 {
			return errors.New("upload exceeds 16 MiB")
		}
		resp, err := client.Do(ctx, http.MethodPut, endpoint, bytes.NewReader(data), "application/octet-stream", true, headers)
		if err != nil {
			return err
		}
		defer resp.Body.Close()
		return copyJSONOrRaw(resp.Body, g)
	case "head":
		resp, err := client.Do(ctx, http.MethodHead, endpoint, nil, "", true, headers)
		if err != nil {
			return err
		}
		defer resp.Body.Close()
		return printJSON(map[string]any{"etag": resp.Header.Get("ETag"), "content_length": resp.ContentLength, "request_id": resp.Header.Get("X-Request-ID")})
	default:
		return errors.New("files supports get, put, or head")
	}
}

func control(ctx context.Context, client *api.Client, profile api.Profile, command string, args []string, g globalOptions) error {
	if err := requireWorkspace(profile); err != nil {
		return err
	}
	switch command {
	case "status":
		return jsonRequest(ctx, client, http.MethodGet, "/api/v1/status", nil, true, g)
	case "display":
		if len(args) == 0 || args[0] == "get" {
			return jsonRequest(ctx, client, http.MethodGet, "/api/v1/display", nil, true, g)
		}
		if len(args) == 2 && args[0] == "set" {
			return jsonRequest(ctx, client, http.MethodPut, "/api/v1/display", map[string]string{"resolution": args[1]}, true, g)
		}
	case "services":
		if len(args) == 2 && (args[0] == "start" || args[0] == "stop" || args[0] == "restart") {
			return jsonRequest(ctx, client, http.MethodPost, "/api/v1/services/"+url.PathEscape(args[1])+"/"+args[0], map[string]any{}, true, g)
		}
	case "logs":
		if len(args) >= 1 {
			endpoint := "/api/v1/logs/" + url.PathEscape(args[0])
			if len(args) == 2 {
				endpoint += "?cursor=" + url.QueryEscape(args[1])
			}
			return jsonRequest(ctx, client, http.MethodGet, endpoint, nil, true, g)
		}
	}
	return fmt.Errorf("invalid %s command", command)
}

func sshKeys(ctx context.Context, client *api.Client, args []string, g globalOptions) error {
	if len(args) == 0 || args[0] == "list" {
		return jsonRequest(ctx, client, http.MethodGet, api.WorkspaceAPI+"/ssh-keys", nil, true, g)
	}
	if args[0] == "add" && len(args) == 2 {
		return jsonRequest(ctx, client, http.MethodPost, api.WorkspaceAPI+"/ssh-keys", map[string]string{"public_key": args[1]}, true, g)
	}
	if args[0] == "remove" && len(args) == 2 {
		return jsonRequest(ctx, client, http.MethodPost, api.WorkspaceAPI+"/ssh-keys/"+url.PathEscape(args[1])+"/remove", map[string]any{}, true, g)
	}
	return errors.New("ssh-keys supports list, add PUBLIC_KEY, or remove ID")
}

func instances(ctx context.Context, client *api.Client, profile api.Profile, args []string, g globalOptions) error {
	if err := requireRunner(profile); err != nil {
		return err
	}
	if len(args) == 0 || args[0] == "list" {
		return jsonRequest(ctx, client, http.MethodGet, api.RunnerAPI+"/instances", nil, true, g)
	}
	action := args[0]
	if action == "password" {
		return instancePassword(ctx, client, args[1:], g)
	}
	if action == "inspect" && len(args) == 2 {
		return jsonRequest(ctx, client, http.MethodGet, api.RunnerAPI+"/instances/"+url.PathEscape(args[1]), nil, true, g)
	}
	if action == "create" {
		fs := flag.NewFlagSet("instances create", flag.ContinueOnError)
		fs.SetOutput(io.Discard)
		name := fs.String("name", "", "instance name")
		passwordStdin := fs.Bool("password-stdin", false, "read password privately from stdin after provisioning")
		promptPassword := fs.Bool("prompt-password", false, "prompt privately with confirmation after provisioning")
		template := fs.String("template", "", "approved template")
		key := fs.String("idempotency-key", "", "retry key")
		httpPort := fs.Int("http-port", 0, "requested loopback HTTP port")
		sshPort := fs.Int("ssh-port", 0, "requested loopback SSH port")
		vncPort := fs.Int("vnc-port", 0, "requested loopback VNC port")
		memory := fs.Int64("memory-bytes", 0, "memory limit")
		cpus := fs.Int64("nano-cpus", 0, "CPU limit in billionths")
		pids := fs.Int64("pids", 0, "PID limit")
		if err := fs.Parse(args[1:]); err != nil {
			return err
		}
		if *passwordStdin && *promptPassword {
			return errors.New("choose --password-stdin or --prompt-password")
		}
		if fs.NArg() != 0 || *name == "" || *template == "" || *key == "" {
			return errors.New("instances create requires --name, --template, and --idempotency-key")
		}
		ports := map[string]int{}
		for name, value := range map[string]int{"http": *httpPort, "ssh": *sshPort, "vnc": *vncPort} {
			if value != 0 {
				ports[name] = value
			}
		}
		resources := map[string]int64{}
		for name, value := range map[string]int64{"memory_bytes": *memory, "nano_cpus": *cpus, "pids": *pids} {
			if value != 0 {
				resources[name] = value
			}
		}
		body := map[string]any{"name": *name, "template": *template}
		if len(ports) != 0 {
			body["ports"] = ports
		}
		if len(resources) != 0 {
			body["resources"] = resources
		}
		if *passwordStdin || *promptPassword {
			return createWithPassword(ctx, client, body, *key, *passwordStdin, g)
		}
		return jsonRequestHeaders(ctx, client, http.MethodPost, api.RunnerAPI+"/instances", body, true, g, map[string]string{"Idempotency-Key": *key})
	}
	if action == "update" {
		if len(args) < 2 {
			return errors.New("instances update requires ID, --template, and --idempotency-key")
		}
		instanceID := args[1]
		fs := flag.NewFlagSet("instances update", flag.ContinueOnError)
		fs.SetOutput(io.Discard)
		template := fs.String("template", "", "approved template")
		key := fs.String("idempotency-key", "", "retry key")
		memory := fs.Int64("memory-bytes", 0, "memory limit")
		cpus := fs.Int64("nano-cpus", 0, "CPU limit in billionths")
		pids := fs.Int64("pids", 0, "PID limit")
		if err := fs.Parse(args[2:]); err != nil {
			return err
		}
		if fs.NArg() != 0 || instanceID == "" || *template == "" || *key == "" {
			return errors.New("instances update requires ID, --template, and --idempotency-key")
		}
		resources := map[string]int64{}
		for name, value := range map[string]int64{"memory_bytes": *memory, "nano_cpus": *cpus, "pids": *pids} {
			if value != 0 {
				resources[name] = value
			}
		}
		body := map[string]any{"template": *template}
		if len(resources) != 0 {
			body["resources"] = resources
		}
		return jsonRequestHeaders(ctx, client, http.MethodPost, api.RunnerAPI+"/instances/"+url.PathEscape(instanceID)+"/update", body, true, g, map[string]string{"Idempotency-Key": *key})
	}
	if (action == "start" || action == "stop" || action == "restart" || action == "remove") && len(args) == 2 {
		return jsonRequest(ctx, client, http.MethodPost, api.RunnerAPI+"/instances/"+url.PathEscape(args[1])+"/"+action, map[string]any{}, true, g)
	}
	return errors.New("instances supports list, inspect, create, password, update, start, stop, restart, or remove")
}

func operations(ctx context.Context, client *api.Client, profile api.Profile, args []string, g globalOptions) error {
	if err := requireRunner(profile); err != nil {
		return err
	}
	if len(args) == 0 || args[0] == "list" {
		return jsonRequest(ctx, client, http.MethodGet, api.RunnerAPI+"/operations", nil, true, g)
	}
	if len(args) == 1 {
		return jsonRequest(ctx, client, http.MethodGet, api.RunnerAPI+"/operations/"+url.PathEscape(args[0]), nil, true, g)
	}
	if len(args) == 2 && args[0] == "wait" {
		for {
			var envelope struct {
				Operation api.Operation `json:"operation"`
			}
			if _, err := client.JSON(ctx, http.MethodGet, api.RunnerAPI+"/operations/"+url.PathEscape(args[1]), nil, &envelope, true, nil); err != nil {
				return err
			}
			if envelope.Operation.Status == "succeeded" || envelope.Operation.Status == "failed" {
				if err := printValue(envelope, g); err != nil {
					return err
				}
				if envelope.Operation.Status == "failed" {
					return &remoteOperationError{ID: envelope.Operation.ID, Code: envelope.Operation.ErrorCode, Message: envelope.Operation.ErrorMessage}
				}
				return nil
			}
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(500 * time.Millisecond):
			}
		}
	}
	return errors.New("operations accepts list, an operation id, or wait ID")
}

func skill(args []string, g globalOptions) error {
	if len(args) == 0 {
		return errors.New("skill requires install or export")
	}
	destination := ""
	switch args[0] {
	case "install":
		if len(args) != 2 || args[1] != "--claude" {
			return errors.New("skill install currently requires --claude")
		}
		home, err := os.UserHomeDir()
		if err != nil {
			return err
		}
		destination = filepath.Join(home, ".claude", "skills", "vibestack")
	case "export":
		if len(args) != 2 {
			return errors.New("skill export requires a destination directory")
		}
		destination = filepath.Join(args[1], "vibestack")
	default:
		return errors.New("skill supports install --claude or export DIRECTORY")
	}
	if info, err := os.Lstat(destination); err == nil && info.IsDir() {
		return errors.New("destination skill directory already exists; it was preserved")
	} else if err == nil || !errors.Is(err, os.ErrNotExist) {
		return errors.New("destination is occupied or inaccessible")
	}
	parent := filepath.Dir(destination)
	if err := os.MkdirAll(parent, 0755); err != nil {
		return err
	}
	temporary, err := os.MkdirTemp(parent, ".vibestack-skill-*")
	if err != nil {
		return err
	}
	defer os.RemoveAll(temporary)
	if err := os.Mkdir(filepath.Join(temporary, "references"), 0755); err != nil {
		return err
	}
	for source, target := range map[string]string{
		"skills/vibestack/SKILL.md":                 "SKILL.md",
		"skills/vibestack/references/CLI.md":        "references/CLI.md",
		"skills/vibestack/references/AUTOMATION.md": "references/AUTOMATION.md",
		"skills/vibestack/references/RUNNER.md":     "references/RUNNER.md",
	} {
		data, readErr := assets.Files.ReadFile(source)
		if readErr != nil {
			return readErr
		}
		if writeErr := os.WriteFile(filepath.Join(temporary, target), data, 0644); writeErr != nil {
			return writeErr
		}
	}
	if err := os.Rename(temporary, destination); err != nil {
		return err
	}
	if g.json {
		return printJSON(map[string]string{"installed": destination})
	}
	fmt.Fprintln(os.Stdout, destination)
	return nil
}

func docs(ctx context.Context, client *api.Client, profile api.Profile, args []string) error {
	name := "agents"
	if len(args) > 0 {
		name = args[0]
	}
	paths := map[string]string{"agents": "/AGENTS.md", "cli": "/CLI.md", "automation": "/AUTOMATION.md", "runner": "/RUNNER.md"}
	endpoint, ok := paths[name]
	if !ok {
		return errors.New("docs supports agents, cli, automation, or runner")
	}
	resp, err := client.Do(ctx, http.MethodGet, endpoint, nil, "", false, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	_, err = io.Copy(os.Stdout, io.LimitReader(resp.Body, 4<<20))
	return err
}

func rawAPI(ctx context.Context, client *api.Client, args []string, g globalOptions) error {
	fs := flag.NewFlagSet("api", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	method := fs.String("method", "GET", "HTTP method")
	key := fs.String("idempotency-key", "", "operation retry key")
	dataFile := fs.String("data-file", "", "request body file, or -")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if len(fs.Args()) != 1 {
		return errors.New("api requires one relative path")
	}
	endpoint := fs.Args()[0]
	if !strings.HasPrefix(endpoint, "/api/") && !strings.HasPrefix(endpoint, "/setup/api/") {
		return errors.New("api path must be beneath /api/ or /setup/api/")
	}
	var input io.Reader
	contentType := ""
	if *dataFile != "" {
		contentType = "application/json"
		data, err := readInputFile(*dataFile, 16<<20)
		if err != nil {
			return err
		}
		if len(data) > 16<<20 {
			return errors.New("API request body exceeds 16 MiB")
		}
		input = bytes.NewReader(data)
	}
	headers := map[string]string{}
	if *key != "" {
		headers["Idempotency-Key"] = *key
	}
	resp, err := client.Do(ctx, strings.ToUpper(*method), endpoint, input, contentType, true, headers)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	return copyJSONOrRaw(resp.Body, g)
}

func jsonRequest(ctx context.Context, client *api.Client, method, path string, body any, auth bool, g globalOptions) error {
	return jsonRequestHeaders(ctx, client, method, path, body, auth, g, nil)
}

func jsonRequestHeaders(ctx context.Context, client *api.Client, method, path string, body any, auth bool, g globalOptions, headers map[string]string) error {
	var value any
	requestID, err := client.JSON(ctx, method, path, body, &value, auth, headers)
	if err != nil {
		return err
	}
	if object, ok := value.(map[string]any); ok && requestID != "" {
		object["request_id"] = requestID
	}
	return printValue(value, g)
}

func copyJSONOrRaw(reader io.Reader, g globalOptions) error {
	data, err := io.ReadAll(io.LimitReader(reader, (16<<20)+1))
	if err != nil {
		return err
	}
	if len(data) > 16<<20 {
		return errors.New("response exceeds 16 MiB")
	}
	if g.json {
		var value any
		if json.Unmarshal(data, &value) == nil {
			return printJSON(value)
		}
	}
	_, err = os.Stdout.Write(data)
	if err == nil && len(data) > 0 && data[len(data)-1] != '\n' {
		_, err = fmt.Fprintln(os.Stdout)
	}
	return err
}

func printValue(value any, g globalOptions) error {
	if g.json {
		return printJSON(value)
	}
	switch typed := value.(type) {
	case string:
		fmt.Fprintln(os.Stdout, typed)
	default:
		return printJSON(typed)
	}
	return nil
}

func printJSON(value any) error {
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	return encoder.Encode(value)
}

func writeAtomic(path string, data []byte, mode os.FileMode) error {
	directory := filepath.Dir(path)
	temporary, err := os.CreateTemp(directory, ".vibestack-download-*")
	if err != nil {
		return err
	}
	name := temporary.Name()
	defer os.Remove(name)
	if err := temporary.Chmod(mode); err != nil {
		temporary.Close()
		return err
	}
	if _, err := temporary.Write(data); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	return os.Rename(name, path)
}

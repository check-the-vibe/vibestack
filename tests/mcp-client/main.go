// The independent Go SDK acceptance client reads protected credential files.
// It prints only fixed verification metadata, never SDK errors or payloads.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"
	"syscall"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type authenticated struct {
	origin, token, gateway, instance string
}

func (a authenticated) RoundTrip(r *http.Request) (*http.Response, error) {
	if r.URL.Scheme+"://"+r.URL.Host != a.origin {
		return nil, errors.New("unexpected origin")
	}
	r = r.Clone(r.Context())
	if a.token != "" {
		r.Header.Set("Authorization", "Bearer "+a.token)
	}
	if a.gateway != "" {
		r.Header.Set("X-GitHub-Token", a.gateway)
	}
	if a.instance != "" {
		r.Header.Set("X-VibeStack-Expected-Instance", a.instance)
	}
	return http.DefaultTransport.RoundTrip(r)
}

func credential(path, pattern string) (string, error) {
	f, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return "", errors.New("credential file unavailable")
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return "", errors.New("credential file unavailable")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 4096 || stat.Nlink != 1 || int(stat.Uid) != os.Geteuid() {
		return "", errors.New("unsafe credential file")
	}
	data, err := io.ReadAll(io.LimitReader(f, 4097))
	value := strings.TrimSpace(string(data))
	if err != nil || len(data) > 4096 || !regexp.MustCompile(pattern).MatchString(value) {
		return "", errors.New("invalid credential file")
	}
	return value, nil
}

func run() error {
	origin, err := url.Parse(os.Getenv("VIBESTACK_MCP_BASE_URL"))
	if err != nil || origin.User != nil || origin.Host == "" || (origin.Path != "" && origin.Path != "/") || origin.RawQuery != "" || origin.Fragment != "" {
		return errors.New("configuration")
	}
	if origin.Scheme != "https" && !(origin.Scheme == "http" && (origin.Hostname() == "localhost" || origin.Hostname() == "127.0.0.1" || origin.Hostname() == "::1")) {
		return errors.New("configuration")
	}
	token, err := credential(os.Getenv("VIBESTACK_MCP_CREDENTIAL_FILE"), `^vss_[A-Za-z0-9_-]{43}$`)
	if err != nil {
		return errors.New("credential configuration")
	}
	auth := authenticated{origin: origin.Scheme + "://" + origin.Host, token: token, instance: os.Getenv("VIBESTACK_MCP_EXPECTED_INSTANCE")}
	if path := os.Getenv("VIBESTACK_MCP_GATEWAY_FILE"); path != "" {
		auth.gateway, err = credential(path, `^[A-Za-z0-9_]+$`)
		if err != nil {
			return errors.New("gateway configuration")
		}
	}
	httpClient := &http.Client{Transport: auth, Timeout: 15 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	client := mcp.NewClient(&mcp.Implementation{Name: "vibestack-go-acceptance", Version: "1"}, nil)
	session, err := client.Connect(ctx, &mcp.StreamableClientTransport{Endpoint: auth.origin + "/mcp", HTTPClient: httpClient, MaxRetries: -1, DisableStandaloneSSE: true}, nil)
	if err != nil {
		return errors.New("connect")
	}
	defer session.Close()
	list, err := session.ListTools(ctx, nil)
	if err != nil {
		return errors.New("list tools")
	}
	found := false
	for _, tool := range list.Tools {
		found = found || tool.Name == "project_summary"
		if tool.Name == "host_inspect" || tool.Name == "instance_create" {
			return errors.New("host authority isolation")
		}
	}
	if !found {
		return errors.New("project tool missing")
	}
	result, err := session.CallTool(ctx, &mcp.CallToolParams{Name: "project_summary", Arguments: map[string]any{"project": "vst-mcp-client-probe"}})
	if err != nil || result.IsError {
		return errors.New("call tool")
	}
	raw, _ := json.Marshal(result.StructuredContent)
	var envelope struct {
		Instance   string `json:"instance_id"`
		Request    string `json:"request_id"`
		Capability string `json:"capability"`
	}
	id := regexp.MustCompile(`^[a-f0-9]{32}$`)
	if json.Unmarshal(raw, &envelope) != nil || !id.MatchString(envelope.Instance) || !id.MatchString(envelope.Request) || envelope.Capability != "project_summary" || (auth.instance != "" && auth.instance != envelope.Instance) {
		return errors.New("result identity")
	}
	bad, err := session.CallTool(ctx, &mcp.CallToolParams{Name: "project_summary", Arguments: map[string]any{"project": "../data"}})
	if err != nil || !bad.IsError {
		return errors.New("schema denial")
	}
	for _, tc := range []struct {
		header, value string
		status        int
	}{{"Authorization", "", 401}, {"Origin", "https://attacker.invalid", 403}, {"Mcp-Session-Id", "replay", 400}} {
		probeAuth := auth
		if tc.header == "Authorization" {
			probeAuth.token = ""
		}
		probeClient := *httpClient
		probeClient.Transport = probeAuth
		r, _ := http.NewRequestWithContext(ctx, "POST", auth.origin+"/mcp", strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`))
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Accept", "application/json, text/event-stream")
		r.Header.Set(tc.header, tc.value)
		response, err := probeClient.Do(r)
		if err != nil {
			return errors.New("admission probe")
		}
		io.Copy(io.Discard, io.LimitReader(response.Body, 4096))
		response.Body.Close()
		if response.StatusCode != tc.status {
			return errors.New("admission denial")
		}
	}
	version := session.InitializeResult().ProtocolVersion
	if version != "2026-07-28" {
		return errors.New("protocol negotiation")
	}
	fmt.Printf("PASS Go SDK 1.7.0 protocol %s: authenticated discovery, tool list, call, schema/origin/session/missing-token denial\n", version)
	return nil
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "FAIL Go MCP client verification at", err.Error(), "(credential and payload details suppressed)")
		os.Exit(1)
	}
}

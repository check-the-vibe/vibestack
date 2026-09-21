package vibestack

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func TestMCPBridgeUsesLiveRemoteToolsAndRevocation(t *testing.T) {
	const identity = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	const credential = "disposable-test-credential"
	var revoked, second atomic.Bool
	var calls atomic.Int64
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	handler := mcp.NewStreamableHTTPHandler(func(*http.Request) *mcp.Server {
		s := mcp.NewServer(&mcp.Implementation{Name: "fixture"}, &mcp.ServerOptions{Logger: logger, Capabilities: &mcp.ServerCapabilities{Tools: &mcp.ToolCapabilities{}}})
		name := "first"
		if second.Load() {
			name = "second"
		}
		s.AddTool(&mcp.Tool{Name: name, InputSchema: map[string]any{"type": "object", "additionalProperties": false}}, func(context.Context, *mcp.CallToolRequest) (*mcp.CallToolResult, error) {
			calls.Add(1)
			return &mcp.CallToolResult{StructuredContent: map[string]any{"value": 42}, Content: []mcp.Content{&mcp.TextContent{Text: "fixture result"}}}, nil
		})
		return s
	}, &mcp.StreamableHTTPOptions{Stateless: true, JSONResponse: true, Logger: logger})
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if revoked.Load() || r.Header.Get("Authorization") != "Bearer "+credential || r.Header.Get("X-VibeStack-Expected-Instance") != identity {
			http.Error(w, "private-upstream-error-body", 401)
			return
		}
		handler.ServeHTTP(w, r)
	}))
	defer upstream.Close()
	client, err := NewClient(upstream.URL, credential, "")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	bridge, harness := mcp.NewInMemoryTransports()
	done := make(chan error, 1)
	go func() {
		done <- MCPBridge(ctx, Profile{Kind: "workspace", Identity: identity}, client, "", bridge)
	}()
	peer := mcp.NewClient(&mcp.Implementation{Name: "local-fixture"}, &mcp.ClientOptions{Logger: logger})
	session, err := peer.Connect(ctx, harness, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer session.Close()
	tools, err := session.ListTools(ctx, nil)
	if err != nil || len(tools.Tools) != 1 || tools.Tools[0].Name != "first" {
		t.Fatal("initial authenticated tool discovery failed")
	}
	result, err := session.CallTool(ctx, &mcp.CallToolParams{Name: "first", Arguments: map[string]any{}})
	if err != nil || result.IsError || calls.Load() != 1 || result.StructuredContent.(map[string]any)["value"] != float64(42) {
		t.Fatal("bridge did not preserve the tool result or invoked it more than once")
	}
	second.Store(true)
	tools, err = session.ListTools(ctx, nil)
	if err != nil || len(tools.Tools) != 1 || tools.Tools[0].Name != "second" {
		t.Fatal("bridge cached stale tool grants")
	}
	revoked.Store(true)
	_, err = session.ListTools(ctx, nil)
	if err == nil || strings.Contains(err.Error(), "private-upstream-error-body") || strings.Contains(err.Error(), credential) {
		t.Fatal("revocation failed or upstream error data escaped")
	}
	_, err = session.CallTool(ctx, &mcp.CallToolParams{Name: "second", Arguments: map[string]any{}})
	if err == nil || calls.Load() != 1 {
		t.Fatal("revoked bridge executed or replayed a tool")
	}
	session.Close()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("bridge did not close after the harness disconnected")
	}
}

func TestMCPBridgeRejectsHostAuthorityAndMisplacedGateway(t *testing.T) {
	client, err := NewClient("http://127.0.0.1:1", "fixture", "")
	if err != nil {
		t.Fatal(err)
	}
	for _, profile := range []Profile{{Kind: "runner", Identity: strings.Repeat("a", 32)}, {Kind: "workspace"}, {Kind: "workspace", Identity: strings.Repeat("a", 32), AuthenticationMode: "trusted-tailnet"}} {
		if MCPBridge(context.Background(), profile, client, "", nil) == nil {
			t.Fatal("bridge accepted host authority or an unpinned/uncredentialed profile")
		}
	}
	if MCPBridge(context.Background(), Profile{Kind: "workspace", Identity: strings.Repeat("a", 32)}, client, "/not-read", nil) == nil {
		t.Fatal("bridge would send a GitHub credential to a non-gateway origin")
	}
}

func TestMCPGatewayFileIsProtectedAndReRead(t *testing.T) {
	path := filepath.Join(t.TempDir(), "gateway")
	if err := os.WriteFile(path, []byte("fixture_first\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if got, err := readGatewayCredential(path); err != nil || got != "fixture_first" {
		t.Fatal("protected gateway fixture rejected")
	}
	os.WriteFile(path, []byte("fixture_rotated\n"), 0600)
	if got, err := readGatewayCredential(path); err != nil || got != "fixture_rotated" {
		t.Fatal("gateway credential rotation was cached")
	}
	link := path + "-link"
	os.Symlink(path, link)
	if _, err := readGatewayCredential(link); err == nil {
		t.Fatal("symlinked credential accepted")
	}
	os.Chmod(path, 0644)
	if _, err := readGatewayCredential(path); err == nil {
		t.Fatal("readable-by-others credential accepted")
	}
	os.Chmod(path, 0600)
	os.Link(path, path+"-hardlink")
	if _, err := readGatewayCredential(path); err == nil {
		t.Fatal("hardlinked credential accepted")
	}
}

func TestMCPProfileFileRejectsLinksAndSpecialFiles(t *testing.T) {
	dir := t.TempDir()
	if err := os.Chmod(dir, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "profiles.json")
	t.Setenv("VIBESTACK_CONFIG", path)
	value := ProfileFile{Version: 1, Profiles: map[string]Profile{}}
	if err := SaveProfiles(value); err != nil {
		t.Fatal(err)
	}
	if err := os.Link(path, path+"-link"); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadProfiles(); err == nil {
		t.Fatal("hardlinked profile accepted")
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(path+"-link", path); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadProfiles(); err == nil {
		t.Fatal("symlinked profile accepted")
	}
	t.Setenv("VIBESTACK_CONFIG", dir)
	if _, err := LoadProfiles(); err == nil {
		t.Fatal("directory profile accepted")
	}
}

func TestMCPBridgeBoundsFramesAndHTTPBodies(t *testing.T) {
	input := io.NopCloser(strings.NewReader(strings.Repeat("x", mcpFrameLimit+1)))
	transport := MCPStdio(input, &discardCloser{})
	connection, err := transport.Connect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	if _, err := connection.Read(context.Background()); err == nil {
		t.Fatal("oversized local frame accepted")
	}
	body := &bridgeBody{Reader: strings.NewReader("12345"), Closer: io.NopCloser(strings.NewReader("")), remaining: 4}
	if _, err := io.ReadAll(body); err == nil {
		t.Fatal("oversized upstream body accepted")
	}
	if _, err := body.Read(make([]byte, 8)); err == nil {
		t.Fatal("body continued after its limit error")
	}
}

func TestMCPStdioRejectsOversizedRPCIdentity(t *testing.T) {
	frame := `{"jsonrpc":"2.0","id":"do-not-reflect-` + strings.Repeat("x", 8192) + `","method":"tools/list"}` + "\n"
	transport := MCPStdio(io.NopCloser(strings.NewReader(frame)), &discardCloser{})
	connection, err := transport.Connect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	if _, err := connection.Read(context.Background()); err == nil || strings.Contains(err.Error(), "do-not-reflect") {
		t.Fatal("oversized local RPC identity was accepted or reflected")
	}
}

type discardCloser struct{}

func (*discardCloser) Write(p []byte) (int, error) { return len(p), nil }
func (*discardCloser) Close() error                { return nil }

package runner

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
)

func runnerRequest(t *testing.T, server *Server, method, path, credential string, body any) *httptest.ResponseRecorder {
	t.Helper()
	var input bytes.Buffer
	if body != nil {
		if err := json.NewEncoder(&input).Encode(body); err != nil {
			t.Fatal(err)
		}
	}
	request := httptest.NewRequest(method, "https://runner.example"+path, &input)
	request.Host = strings.TrimPrefix(server.Config.PublicURL, "https://")
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	if credential != "" {
		request.Header.Set("Authorization", "Bearer "+credential)
	}
	response := httptest.NewRecorder()
	server.HTTP.Handler.ServeHTTP(response, request)
	return response
}

func TestRunnerHTTPPairingDiscoveryRevocationAndPermissions(t *testing.T) {
	store, err := OpenStore(filepath.Join(t.TempDir(), "state"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	config := DefaultConfig()
	config.PublicURL = "https://runner.example"
	server := NewServer(config, store, nil)

	discovery := runnerRequest(t, server, http.MethodGet, "/.well-known/vibestack", "", nil)
	if discovery.Code != http.StatusOK || strings.Contains(discovery.Body.String(), "approved_templates") || strings.Contains(discovery.Body.String(), "credential") {
		t.Fatalf("unsafe discovery response %d: %s", discovery.Code, discovery.Body.String())
	}

	requestResponse := runnerRequest(t, server, http.MethodPost, APIRoot+"/pairing/requests", "", map[string]any{
		"device_label": "agent laptop",
		"permissions":  []string{"instances:read", "instances:write"},
	})
	if requestResponse.Code != http.StatusCreated {
		t.Fatalf("pairing request %d: %s", requestResponse.Code, requestResponse.Body.String())
	}
	var requested struct {
		PairingID        string `json:"pairing_id"`
		VerificationCode string `json:"verification_code"`
		PollingSecret    string `json:"polling_secret"`
	}
	if err := json.Unmarshal(requestResponse.Body.Bytes(), &requested); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ApprovePairing(context.Background(), requested.VerificationCode, true); err != nil {
		t.Fatal(err)
	}
	poll := runnerRequest(t, server, http.MethodPost, APIRoot+"/pairing/requests/"+requested.PairingID+"/poll", "", map[string]string{"polling_secret": requested.PollingSecret})
	if poll.Code != http.StatusOK {
		t.Fatalf("pairing poll %d: %s", poll.Code, poll.Body.String())
	}
	var delivered struct {
		ClientID   string `json:"client_id"`
		Credential string `json:"credential"`
	}
	if err := json.Unmarshal(poll.Body.Bytes(), &delivered); err != nil {
		t.Fatal(err)
	}
	if delivered.Credential == "" || strings.Contains(requestResponse.Body.String(), delivered.Credential) {
		t.Fatal("credential was missing or appeared before one-time delivery")
	}
	if second := runnerRequest(t, server, http.MethodPost, APIRoot+"/pairing/requests/"+requested.PairingID+"/poll", "", map[string]string{"polling_secret": requested.PollingSecret}); second.Code == http.StatusOK {
		t.Fatal("credential was delivered twice")
	}

	capabilities := runnerRequest(t, server, http.MethodGet, APIRoot, delivered.Credential, nil)
	if capabilities.Code != http.StatusOK || !strings.Contains(capabilities.Body.String(), "approved_templates") {
		t.Fatalf("authenticated capabilities %d: %s", capabilities.Code, capabilities.Body.String())
	}
	if missing := runnerRequest(t, server, http.MethodGet, APIRoot, "", nil); missing.Code != http.StatusUnauthorized {
		t.Fatalf("missing credential returned %d", missing.Code)
	}
	if err := store.RevokeClient(context.Background(), delivered.ClientID); err != nil {
		t.Fatal(err)
	}
	if revoked := runnerRequest(t, server, http.MethodGet, APIRoot, delivered.Credential, nil); revoked.Code != http.StatusUnauthorized {
		t.Fatalf("revoked credential returned %d", revoked.Code)
	}

	readCredential := "vsr_read_only_test_credential_0000000000000000"
	readID := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	if _, err := store.db.Exec(`INSERT INTO clients(id,label,permissions_json,credential_hash,created_at) VALUES(?,?,?,?,?)`, readID, "reader", `["instances:read"]`, HashCredential(readCredential), nowISO()); err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(http.MethodPost, "https://runner.example"+APIRoot+"/instances", bytes.NewBufferString(`{"name":"blocked","template":"default"}`))
	request.Host = "runner.example"
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Authorization", "Bearer "+readCredential)
	request.Header.Set("Idempotency-Key", "permission-check")
	response := httptest.NewRecorder()
	server.HTTP.Handler.ServeHTTP(response, request)
	if response.Code != http.StatusForbidden {
		t.Fatalf("read-only create returned %d: %s", response.Code, response.Body.String())
	}
}

func TestRunnerAllowsOnlySafeCrossSiteTopLevelNavigation(t *testing.T) {
	store, err := OpenStore(filepath.Join(t.TempDir(), "state"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	config := DefaultConfig()
	config.PublicURL = "https://runner.example"
	server := NewServer(config, store, nil)

	for _, destination := range []string{"document", "empty"} {
		request := httptest.NewRequest(http.MethodGet, "https://runner.example/.well-known/vibestack", nil)
		request.Host = "runner.example"
		request.Header.Set("Sec-Fetch-Site", "cross-site")
		request.Header.Set("Sec-Fetch-Mode", "navigate")
		request.Header.Set("Sec-Fetch-Dest", destination)
		response := httptest.NewRecorder()
		server.HTTP.Handler.ServeHTTP(response, request)
		if response.Code != http.StatusOK {
			t.Fatalf("safe top-level %s navigation returned %d: %s", destination, response.Code, response.Body.String())
		}
	}

	request := httptest.NewRequest(http.MethodGet, "https://runner.example/.well-known/vibestack", nil)
	request.Host = "runner.example"
	request.Header.Set("Sec-Fetch-Site", "cross-site")
	request.Header.Set("Sec-Fetch-Mode", "cors")
	request.Header.Set("Sec-Fetch-Dest", "empty")
	response := httptest.NewRecorder()
	server.HTTP.Handler.ServeHTTP(response, request)
	if response.Code != http.StatusForbidden {
		t.Fatalf("cross-site subresource returned %d: %s", response.Code, response.Body.String())
	}
}

package vibestack

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type fixtureRoundTrip func(*http.Request) (*http.Response, error)

func (f fixtureRoundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestPrivateGatewayIsExplicitFreshAndNeverRedirected(t *testing.T) {
	t.Setenv("GITHUB_TOKEN", "ambient_fixture_must_not_be_read")
	file := filepath.Join(t.TempDir(), "gateway")
	os.WriteFile(file, []byte("fixture_first"), 0600)
	c, _ := NewClient("https://fixture-8080.app.github.dev", "service_fixture", "")
	c.ExpectedIdentity = strings.Repeat("a", 32)
	var calls int
	want := ""
	c.HTTP.Transport = fixtureRoundTrip(func(r *http.Request) (*http.Response, error) {
		calls++
		if r.Header.Get("X-GitHub-Token") != want || r.Header.Get("Authorization") != "Bearer service_fixture" || r.Header.Get("X-VibeStack-Expected-Instance") != c.ExpectedIdentity {
			t.Fatal("wrong authentication boundary")
		}
		return &http.Response{StatusCode: 307, Header: http.Header{"Location": []string{c.Base.String() + "/login"}}, Body: io.NopCloser(strings.NewReader("<html>login</html>")), Request: r}, nil
	})
	for _, token := range []string{"", "fixture_first", "fixture_rotated"} {
		want = token
		if token != "" {
			c.GatewayTokenFile = file
			os.WriteFile(file, []byte(token), 0600)
		}
		if _, err := c.Do(context.Background(), "POST", "/api/v1/capabilities/example/invoke", strings.NewReader("{}"), "application/json", true, nil); err == nil {
			t.Fatal("login redirect accepted")
		}
	}
	if calls != 3 {
		t.Fatal("request was replayed or redirected")
	}
	os.Chmod(file, 0644)
	if _, err := c.Do(context.Background(), "GET", "/api/v1/capabilities", nil, "", true, nil); err == nil || calls != 3 {
		t.Fatal("unsafe file was used")
	}
	for _, origin := range []string{"https://other.example", "http://localhost", "https://fixture.app.github.dev:8443", "https://app.github.dev.evil.example"} {
		other, _ := NewClient(origin, "", "")
		other.GatewayTokenFile = file
		if other.ValidateGateway() == nil {
			t.Fatal("unsafe gateway destination accepted")
		}
	}
}

func TestGenericJSONKeepsLargeIntegersAndRejectsLoginHTML(t *testing.T) {
	c, _ := NewClient("https://fixture.example", "fixture", "")
	body := `{"value":9007199254740993}`
	c.HTTP.Transport = fixtureRoundTrip(func(r *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Header: http.Header{}, Body: io.NopCloser(strings.NewReader(body)), Request: r}, nil
	})
	var value any
	if _, err := c.JSON(context.Background(), "GET", "/api/v1/capabilities", nil, &value, true, nil); err != nil {
		t.Fatal(err)
	}
	encoded, _ := json.Marshal(value)
	if string(encoded) != body {
		t.Fatal("integer precision was lost")
	}
	for _, bad := range []string{"<html>sign in</html>", "{} {}"} {
		body = bad
		if _, err := c.JSON(context.Background(), "GET", "/api/v1/capabilities", nil, &value, true, nil); err == nil {
			t.Fatal("invalid JSON accepted")
		}
	}
}

"""Source contracts for container isolation, logging, and service wiring."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def supervisor_section(source: str, name: str) -> str:
    match = re.search(
        rf"^\[{re.escape(name)}\]\n(.*?)(?=^\[|\Z)",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError(f"missing Supervisor section {name}")
    return match.group(1)


class InfrastructureContractTests(unittest.TestCase):
    def test_official_ubuntu_sources_switch_to_https_after_ca_bootstrap(self) -> None:
        dockerfile = read("Dockerfile")
        expression = re.search(r"RUN sed -Ei '([^']+)' /etc/apt/sources.list.d/ubuntu.sources", dockerfile)
        self.assertIsNotNone(expression)
        self.assertLess(dockerfile.index("ca-certificates curl"), expression.start())
        original = ("URIs: http://archive.ubuntu.com/ubuntu/ http://security.ubuntu.com/ubuntu/\n"
                    "URIs: http://ports.ubuntu.com/ubuntu-ports/\n"
                    "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n"
                    "URIs: https://archive.ubuntu.com/ubuntu/\n"
                    "URIs: http://operator.example/ubuntu/\n")
        result = subprocess.run(["sed", "-E", expression.group(1)], input=original,
                                text=True, capture_output=True, check=True).stdout
        expected = original.replace("http://archive.ubuntu.com/", "https://archive.ubuntu.com/")
        expected = expected.replace("http://security.ubuntu.com/", "https://security.ubuntu.com/")
        expected = expected.replace("http://ports.ubuntu.com/", "https://ports.ubuntu.com/")
        self.assertEqual(result, expected)

    def test_base_image_has_pinned_multiarch_automation_dependencies(self) -> None:
        dockerfile = read("Dockerfile")
        self.assertIn("FROM ubuntu:24.04", dockerfile)
        for package in (
            "libgtk-3-bin",
            "desktop-file-utils",
            "x11-utils",
            "xauth",
            "xclip",
            "wmctrl",
        ):
            self.assertRegex(dockerfile, rf"\b{re.escape(package)}\b")
        self.assertIn("ARG TARGETARCH", dockerfile)
        self.assertIn("amd64) ttyd_asset=x86_64", dockerfile)
        self.assertIn("arm64) ttyd_asset=aarch64", dockerfile)
        self.assertIn(
            "8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55",
            dockerfile,
        )
        self.assertIn(
            "b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165",
            dockerfile,
        )
        self.assertIn('echo "${ttyd_sha256}  /tmp/ttyd" | sha256sum -c -', dockerfile)

    def test_external_oauth_uses_chrome_instead_of_looping_into_chatgpt(self) -> None:
        dockerfile = read("Dockerfile")
        installer = read("bin/vibestack-install")
        catalog = read("setup/catalog.json")
        acceptance = read("bin/vibestack-check")
        helper = read("chrome/google-chrome-xfce-helper.desktop")

        self.assertIn("configure_chrome_default_browser", installer)
        self.assertIn("remove_web_url_handlers", installer)
        self.assertIn(
            "patch_desktop_entry /usr/share/applications/com.google.Chrome.desktop",
            installer,
        )
        self.assertIn("x-scheme-handler/http x-scheme-handler/https text/html", installer)
        self.assertIn("update-desktop-database /usr/share/applications", installer)
        self.assertIn("CHROME_XFCE_HELPER_SRC", installer)
        self.assertIn(
            "COPY chrome/google-chrome-xfce-helper.desktop",
            dockerfile,
        )
        self.assertIn("X-XFCE-Binaries=vibestack-app;", helper)
        self.assertIn(
            "X-XFCE-CommandsWithParameter=%B /usr/bin/google-chrome-stable \"%s\";",
            helper,
        )
        self.assertRegex(
            catalog,
            r'"id": "chatgpt"[\s\S]*?"requires": \[\s*"chrome"\s*\]',
        )
        self.assertIn('AC-45 HTTP opens in Chrome', acceptance)
        self.assertIn('AC-45 XFCE Chrome helper is wrapped', acceptance)
        self.assertIn('AC-45 ChatGPT keeps its callback handler', acceptance)
        self.assertIn('x-scheme-handler/codex', acceptance)
        self.assertIn('AC-45 ChatGPT is not a web handler', acceptance)

    def test_sudo_and_runtime_assets_are_narrowly_scoped(self) -> None:
        dockerfile = read("Dockerfile")
        self.assertNotIn("NOPASSWD:ALL", dockerfile)
        self.assertIn("vibe ALL=(ALL:ALL) ALL", dockerfile)
        self.assertIn(
            "NOPASSWD: /usr/local/bin/vibestack-install, /usr/local/bin/vibestack-control",
            dockerfile,
        )
        self.assertIn("/usr/local/bin/vibestack-password", dockerfile)
        self.assertIn("usermod --lock vibe", dockerfile)
        self.assertIn("visudo -cf /etc/sudoers.d/vibe", dockerfile)
        self.assertIn("openssl", dockerfile)
        self.assertIn("COPY automation/ /usr/share/vibestack-automation/", dockerfile)
        self.assertIn(
            "COPY supervisord.conf /etc/supervisor/supervisord.conf", dockerfile
        )
        self.assertIn(
            'CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]',
            dockerfile,
        )
        self.assertIn(
            "COPY runtime/AGENTS.md runtime/CLAUDE.md docs/AUTOMATION.md /usr/share/doc/vibestack/",
            dockerfile,
        )
        self.assertIn(
            "ln -s /usr/share/doc/vibestack/AGENTS.md /AGENTS.md",
            dockerfile,
        )
        self.assertIn(
            "ln -s /usr/share/doc/vibestack/AGENTS.md /home/vibe/AGENTS.md",
            dockerfile,
        )
        self.assertIn("COPY desktop-config/etc/xdg/ /etc/xdg/", dockerfile)
        self.assertIn("COPY desktop-config/usr/share/ /usr/share/", dockerfile)
        self.assertIn("bin/vibestack-bootstrap", dockerfile)
        self.assertIn("bin/vibestack-password", dockerfile)
        self.assertIn("bin/vibestack-desktop-action", dockerfile)
        self.assertIn('CMD ["/usr/local/bin/vibestack-healthcheck"]', dockerfile)
        self.assertIn("chown root:vibe /data", dockerfile)
        self.assertIn("chmod 1770 /data", dockerfile)
        self.assertIn("/data/.vibestack-state-v1", dockerfile)
        self.assertNotIn("marker_info.st_uid", read("bin/vibestack-bootstrap"))
        self.assertIn(
            '$acceptance_data/.vibestack-state-v1', read("bin/vibestack-dev")
        )
        self.assertIn(
            "bin/vibestack-dev accept vibestack:test",
            read(".github/workflows/publish-docker.yml"),
        )
        self.assertNotIn("chown -R vibe:vibe /home/vibe /data", dockerfile)

        entrypoint = read("entrypoint.sh")
        marker_creation = entrypoint[
            entrypoint.index("VIBESTACK_FLATPAK_ENABLED") : entrypoint.index(
                "# A new image starts"
            )
        ]
        self.assertIn("/run/vibestack/host/flatpak-enabled", marker_creation)
        self.assertIn("-o root -g root -m 0444", marker_creation)
        self.assertLess(
            entrypoint.index("/usr/local/bin/vibestack-bootstrap"),
            entrypoint.index("VIBESTACK_FLATPAK_ENABLED"),
        )

        bootstrap = entrypoint.index("/usr/local/bin/vibestack-bootstrap")
        restore = entrypoint.index("/usr/local/bin/vibestack-password restore")
        unprivileged = entrypoint.index(
            "/usr/sbin/runuser -u vibe -- /usr/local/bin/vibestack-persist"
        )
        self.assertLess(bootstrap, restore)
        self.assertLess(restore, unprivileged)

    def test_x11_and_browser_transports_are_loopback_only(self) -> None:
        supervisor = read("supervisord.conf")
        self.assertNotIn("/tmp/runtime-vibe", supervisor)
        self.assertIn('XDG_RUNTIME_DIR="/run/vibestack/runtime"', supervisor)
        xvfb = supervisor_section(supervisor, "program:xvfb")
        self.assertIn("-nolisten tcp", xvfb)
        self.assertIn("-auth /run/vibestack/Xauthority", xvfb)
        self.assertNotRegex(xvfb, r"(?:^|\s)-ac(?:\s|$)")

        x11vnc = supervisor_section(supervisor, "program:x11vnc")
        self.assertIn("-listen 127.0.0.1", x11vnc)
        self.assertIn("-auth /run/vibestack/Xauthority", x11vnc)
        native_vnc = supervisor_section(supervisor, "program:native-vnc")
        self.assertIn("-noshm", native_vnc)

        novnc = supervisor_section(supervisor, "program:novnc")
        self.assertIn("--heartbeat=30", novnc)
        self.assertIn("--auth-plugin=websockify_auth.ProxyOnly", novnc)
        self.assertIn("--auth-source=vibestack-nginx-proxy-v1", novnc)
        self.assertIn("127.0.0.1:%(ENV_NOVNC_PORT)s", novnc)
        self.assertIn("127.0.0.1:%(ENV_VNC_PORT)s", novnc)
        self.assertIn('PYTHONPATH="/usr/share/vibestack-proxy"', novnc)

        ttyd = supervisor_section(supervisor, "program:ttyd")
        self.assertIn("-i 127.0.0.1", ttyd)
        self.assertIn("-O -H X-VibeStack-Proxy", ttyd)

        acceptance = read("bin/vibestack-check")
        self.assertIn('"403:0"', acceptance)
        self.assertIn('"000:52"', acceptance)

        dockerfile = read("Dockerfile")
        proxy_dir = "RUN install -d -m 0755 /usr/share/vibestack-proxy"
        proxy_copy = (
            "COPY --chown=root:root --chmod=0444 proxy/websockify_auth.py "
            "/usr/share/vibestack-proxy/websockify_auth.py"
        )
        self.assertIn(proxy_dir, dockerfile)
        self.assertIn(
            proxy_copy,
            dockerfile,
        )
        self.assertLess(dockerfile.index(proxy_dir), dockerfile.index(proxy_copy))

    def test_browser_stream_backends_require_nginx_proxy_marker(self) -> None:
        nginx = read("nginx.conf")
        terminal = nginx[
            nginx.index("location /terminal/") : nginx.index("location = /vnc")
        ]
        websocket = nginx[
            nginx.index("location = /vnc/websockify") : nginx.index("location /vnc/")
        ]
        for location in (terminal, websocket):
            self.assertIn("proxy_set_header Host $http_host;", location)
            self.assertIn(
                "proxy_set_header X-VibeStack-Proxy vibestack-nginx-proxy-v1;",
                location,
            )
            self.assertNotIn("$http_x_vibestack_proxy", location.lower())

        plugin = read("proxy/websockify_auth.py")
        self.assertIn('PROXY_HEADER = "X-VibeStack-Proxy"', plugin)
        self.assertIn("headers.get_all(PROXY_HEADER, [])", plugin)
        self.assertIn("compare_digest(candidate, self._expected)", plugin)

        acceptance = read("bin/vibestack-check")
        self.assertIn("direct websockify missing proxy marker rejected", acceptance)
        self.assertIn("direct websockify wrong proxy marker rejected", acceptance)
        self.assertIn("direct ttyd missing proxy marker rejected", acceptance)
        self.assertIn(
            'direct_ws_forbidden http://127.0.0.1:7681/ws tty', acceptance
        )

    def test_root_launcher_and_embedded_terminal_keep_same_origin_routes(self) -> None:
        nginx = read("nginx.conf")
        root_location = nginx[
            nginx.index("location = /") : nginx.index("location = /setup")
        ]
        self.assertIn("root /usr/share/vibestack/desktop;", root_location)
        self.assertIn("try_files /launcher.html =404;", root_location)
        self.assertIn('Content-Security-Policy "default-src \'self\'', root_location)
        terminal_location = nginx[
            nginx.index("location /terminal/") : nginx.index("location = /vnc")
        ]
        self.assertIn("proxy_pass http://127.0.0.1:7681/;", terminal_location)

        for route, document in (
            ("/AGENTS.md", "/usr/share/doc/vibestack/AGENTS.md"),
            ("/AUTOMATION.md", "/usr/share/doc/vibestack/AUTOMATION.md"),
        ):
            location = nginx[
                nginx.index(f"location = {route}") : nginx.index("}", nginx.index(f"location = {route}"))
            ]
            self.assertIn(f"alias {document};", location)
            self.assertIn("default_type text/markdown;", location)
            self.assertIn("charset_types text/markdown;", location)
            self.assertIn('add_header Cache-Control "no-cache" always;', location)

        acceptance = read("bin/vibestack-check")
        self.assertIn('AC-3 / serves Desktop landing', acceptance)
        self.assertIn('AC-26 configured setup redirects to launcher', acceptance)
        self.assertIn('AC-26 locked account stays in onboarding', acceptance)

    def test_optional_acceptance_install_records_setup_state(self) -> None:
        acceptance = read("bin/vibestack-check")
        self.assertIn(
            'check "AC-30 install editors" vibestack-setup install editors',
            acceptance,
        )
        self.assertNotIn(
            'check "AC-30 install editors" sudo -n vibestack-install editors',
            acceptance,
        )

    def test_disposable_acceptance_proves_catalog_and_flatpak_restore(self) -> None:
        helper = read("bin/vibestack-dev")
        probe = read("tests/runtime_onboarding_check.py")

        install = helper.index(
            "vibestack-setup install godot build-essential flatpak"
        )
        flatpak_install = helper.index("org.gnome.Calculator", install)
        initial_probe = helper.index("catalog-installed", install)
        recreate = helper.index('docker rm -f "$acceptance_container"', initial_probe)
        restored_probe = helper.index("verify-catalog-restored", recreate)
        browser = helper.index("npm run test:browser", restored_probe)
        self.assertLess(install, initial_probe)
        self.assertLess(install, flatpak_install)
        self.assertLess(flatpak_install, initial_probe)
        self.assertLess(initial_probe, recreate)
        self.assertLess(recreate, restored_probe)
        self.assertLess(restored_probe, browser)
        self.assertIn("VIBESTACK_ACCEPTANCE_RESTORE_TIMEOUT_SECONDS", helper)
        self.assertIn("wait_for_catalog_restore(timeout_seconds)", probe)
        self.assertIn(
            'CATALOG_COMPONENTS = ("godot", "build-essential", "flatpak")',
            probe,
        )
        self.assertIn('FLATPAK_LINK_REVIEW_APP = "org.videolan.VLC"', probe)
        self.assertIn('"install-url"', probe)
        self.assertIn('"/usr/sbin/runuser"', probe)
        self.assertIn('component["probe"]', probe)
        self.assertIn('"XDG_DATA_HOME=/home/vibe/.local/share"', probe)
        self.assertIn("/data/godot-config", probe)
        self.assertIn("/data/godot-data", probe)
        self.assertIn("os.O_EXCL", probe)
        self.assertIn("os.O_NOFOLLOW", probe)
        self.assertIn("verify_persistent_sentinels()", probe)
        self.assertIn("validate_persistent_hash(secret)", probe)
        self.assertIn("verify_godot()", probe)
        self.assertIn("verify_flatpak()", probe)
        self.assertIn('FLATPAK_SMOKE_APP = "org.gnome.Calculator"', probe)
        self.assertIn("--security-opt seccomp=unconfined", helper)
        self.assertIn("--security-opt apparmor=unconfined", helper)
        self.assertIn("--security-opt systempaths=unconfined", helper)

    def test_password_acceptance_is_status_only_and_never_embeds_a_secret(self) -> None:
        acceptance = read("bin/vibestack-check")
        self.assertIn("AC-47 password status agrees with root helper", acceptance)
        self.assertIn("AC-47 account lock follows password state", acceptance)
        self.assertIn("vibestack-password status", acceptance)
        self.assertIn("passwd --status vibe", acceptance)
        self.assertNotIn("vibestack-password set", acceptance)

    def test_acceptance_forces_wizard_when_setup_is_complete(self) -> None:
        acceptance = read("bin/vibestack-check")
        wizard_check = next(
            line for line in acceptance.splitlines() if '"AC-23 wizard served"' in line
        )
        self.assertIn(
            'curl -fs "http://localhost/setup/?force=1" | grep -q "VibeStack"',
            wizard_check,
        )
        self.assertNotIn("curl -fs http://localhost/setup/ | grep", wizard_check)

    def test_automation_acceptance_cancels_only_after_observing_running(self) -> None:
        acceptance = read("bin/vibestack-automation-check")
        helper_start = acceptance.index("def wait_for_running_job(")
        helper = acceptance[helper_start : acceptance.index("\ndef run_job(", helper_start)]
        self.assertIn('if status == "running":', helper)
        self.assertIn("if status in TERMINAL_JOB_STATES:", helper)

        cancel_start = acceptance.index("def check_cancel_and_timeout(")
        cancel_check = acceptance[
            cancel_start : acceptance.index("\ndef check_mutating(", cancel_start)
        ]
        observed = cancel_check.index('wait_for_running_job(client, str(job["id"]))')
        cancelled = cancel_check.index('"POST", "%s/jobs/%s/cancel"')
        self.assertLess(observed, cancelled)

    def test_supervisor_logs_are_persistent_bounded_and_safely_combined(self) -> None:
        supervisor = read("supervisord.conf")
        main = supervisor_section(supervisor, "supervisord")
        self.assertIn("logfile=/data/logs/vibestack/supervisord.log", main)
        self.assertIn("logfile_maxbytes=", main)
        self.assertIn("logfile_backups=", main)

        combined = (
            "program:dbus-system",
            "program:xvfb",
            "program:x11vnc",
            "program:novnc",
            "program:xfce4",
            "program:ttyd",
            "program:vibestack-setup",
            "program:vibestack-control",
            "program:vibestack-automation",
        )
        for name in combined:
            section = supervisor_section(supervisor, name)
            self.assertIn("redirect_stderr=true", section, name)
            self.assertIn("stdout_logfile=/data/logs/vibestack/", section, name)
            self.assertIn("stdout_logfile_maxbytes=", section, name)
            self.assertIn("stdout_logfile_backups=", section, name)
            self.assertNotIn("stderr_logfile=", section, name)

        nginx = supervisor_section(supervisor, "program:nginx")
        self.assertIn("redirect_stderr=false", nginx)
        self.assertIn("stdout_logfile=/data/logs/vibestack/nginx/access.jsonl", nginx)
        self.assertIn("stderr_logfile=/data/logs/vibestack/nginx/error.log", nginx)
        for key in (
            "stdout_logfile_maxbytes=",
            "stdout_logfile_backups=",
            "stderr_logfile_maxbytes=",
            "stderr_logfile_backups=",
        ):
            self.assertIn(key, nginx)

        helper = read("bin/vibestack-dev")
        self.assertIn(
            "automation-audit) echo /data/logs/vibestack/automation-audit.jsonl",
            helper,
        )
        self.assertIn(
            "desktop-actions) echo /data/logs/vibestack/desktop/actions.jsonl",
            helper,
        )

    def test_setup_shutdown_contains_privileged_installer_descendants(self) -> None:
        supervisor = read("supervisord.conf")
        setup = supervisor_section(supervisor, "program:vibestack-setup")
        self.assertIn("stopasgroup=true", setup)
        self.assertIn("killasgroup=true", setup)

    def test_automation_service_and_proxy_share_the_security_contract(self) -> None:
        supervisor = read("supervisord.conf")
        automation = supervisor_section(supervisor, "program:vibestack-automation")
        for value in (
            'AUTOMATION_PORT="%(ENV_AUTOMATION_PORT)s"',
            'AUTOMATION_TOKEN_FILE="/home/vibe/.vibestack/automation.token"',
            'AUTOMATION_AUDIT_LOG="/data/logs/vibestack/automation-audit.jsonl"',
            'AUTOMATION_SESSION_ENV_FILE="/run/vibestack/session.env"',
        ):
            self.assertIn(value, automation)

        nginx = read("nginx.conf")
        self.assertIn("location = /api/v1/automation", nginx)
        self.assertIn("location ^~ /api/v1/automation/", nginx)
        self.assertIn("client_max_body_size 16m", nginx)
        self.assertIn("proxy_pass http://127.0.0.1:7997;", nginx)
        self.assertIn("proxy_set_header Authorization $http_authorization", nginx)
        self.assertIn("proxy_set_header X-Request-ID $request_id", nginx)

    def test_access_log_is_json_metadata_without_secrets_or_query_strings(self) -> None:
        nginx = read("nginx.conf")
        self.assertIn("log_format vibestack_json escape=json", nginx)
        self.assertIn("access_log /dev/stdout vibestack_json", nginx)
        self.assertIn('"requestId":"$request_id"', nginx)
        self.assertIn('"path":"$uri"', nginx)
        self.assertNotIn("$request_uri", nginx)
        log_format = nginx[nginx.index("log_format vibestack_json") : nginx.index("access_log")]
        for secret in ("authorization", "cookie", "request_body", "args"):
            self.assertNotIn(secret, log_format.lower())

    def test_nginx_rejects_hosts_outside_loopback_and_tailscale(self) -> None:
        nginx = read("nginx.conf")
        self.assertIn("map $http_host $vibestack_host_allowed", nginx)
        self.assertIn("if ($vibestack_host_allowed = 0)", nginx)
        self.assertIn("return 421", nginx)
        self.assertIn("localhost|127\\.0\\.0\\.1", nginx)
        self.assertIn("\\[::1\\]", nginx)
        self.assertIn("ts\\.net", nginx)
        self.assertNotIn('Host: example:9999', read("bin/vibestack-check"))
        self.assertIn('Host: attacker.example', read("bin/vibestack-check"))

        host_map = nginx[
            nginx.index("map $http_host $vibestack_host_allowed") : nginx.index(
                'map "$http_origin|$http_host"'
            )
        ]
        expressions = re.findall(r'^\s*"(~\*?[^\"]+)"\s+1;', host_map, re.MULTILINE)
        self.assertEqual(3, len(expressions))

        def allowed(host: str) -> bool:
            for expression in expressions:
                flags = re.IGNORECASE if expression.startswith("~*") else 0
                pattern = expression[2:] if flags else expression[1:]
                if re.fullmatch(pattern, host, flags=flags):
                    return True
            return False

        for host in (
            "localhost",
            "LOCALHOST:8080",
            "127.0.0.1:80",
            "[::1]",
            "[::1]:9443",
            "vibestack.example-tailnet.ts.net",
            "VIBE.EXAMPLE.TS.NET:443",
        ):
            self.assertTrue(allowed(host), host)
        for host in (
            "",
            "evil.example",
            "ts.net",
            "tailnet.ts.net",
            "bad_name.tailnet.ts.net",
            "-bad.tailnet.ts.net",
            "bad-.tailnet.ts.net",
            "good.tailnet.ts.net.evil",
            "user@good.tailnet.ts.net",
            "good.tailnet.ts.net/path",
            "localhost.evil",
            "127.0.0.1.evil",
            "localhost:123456",
        ):
            self.assertFalse(allowed(host), host)

        self.assertIn(
            'map "$http_origin|$http_host" $vibestack_origin_allowed', nginx
        )
        self.assertIn(
            'map "$request_method|$http_sec_fetch_site|$http_sec_fetch_mode|$http_sec_fetch_dest" $vibestack_fetch_site_allowed',
            nginx,
        )
        self.assertIn("if ($vibestack_origin_allowed = 0)", nginx)
        self.assertIn("if ($vibestack_fetch_site_allowed = 0)", nginx)
        origin_map = nginx[
            nginx.index('map "$http_origin|$http_host"') : nginx.index(
                'map "$request_method|$http_sec_fetch_site'
            )
        ]
        origin_expressions = re.findall(
            r'^\s*"(~\*?[^\"]+)"\s+1;', origin_map, re.MULTILINE
        )
        self.assertEqual(2, len(origin_expressions))

        def origin_allowed(origin: str, host: str) -> bool:
            combined = f"{origin}|{host}"
            for expression in origin_expressions:
                flags = re.IGNORECASE if expression.startswith("~*") else 0
                pattern = expression[2:] if flags else expression[1:]
                if re.search(pattern, combined, flags=flags):
                    return True
            return False

        for origin, host in (
            ("", "localhost"),
            ("http://localhost", "localhost"),
            ("https://localhost:8080", "localhost:8080"),
            ("https://[::1]:9443", "[::1]:9443"),
            (
                "https://vibe.example-tailnet.ts.net:9443",
                "vibe.example-tailnet.ts.net:9443",
            ),
            ("HTTPS://VIBE.TAILNET.TS.NET", "vibe.tailnet.ts.net"),
        ):
            self.assertTrue(origin_allowed(origin, host), (origin, host))
        for origin, host in (
            ("null", "localhost"),
            ("https://attacker.example", "localhost"),
            ("https://one.tailnet.ts.net", "two.tailnet.ts.net"),
            ("https://vibe.tailnet.ts.net.evil", "vibe.tailnet.ts.net"),
            ("https://user@localhost", "localhost"),
            ("https://localhost/", "localhost"),
            ("https://localhost?query", "localhost"),
            ("https://localhost#fragment", "localhost"),
            ("https://localhost, https://localhost", "localhost"),
            ("https://local host", "localhost"),
        ):
            self.assertFalse(origin_allowed(origin, host), (origin, host))

        fetch_map = nginx[
            nginx.index('map "$request_method|$http_sec_fetch_site') : nginx.index("server {")
        ]
        self.assertIn(
            r"(?:GET|HEAD)\|(?:cross-site|same-site)\|navigate\|(?:document|empty)$",
            fetch_map,
        )
        self.assertIn(r"(?:none|same-origin)\|[^|]*\|[^|]*$", fetch_map)
        self.assertNotIn("POST|cross-site", fetch_map)
        self.assertNotIn(r"(?:cross-site|same-site)\|[^|]*\|[^|]*$", fetch_map)
        self.assertIn('"fetchSite":"$http_sec_fetch_site"', nginx)
        self.assertIn('"fetchMode":"$http_sec_fetch_mode"', nginx)
        self.assertIn('"fetchDest":"$http_sec_fetch_dest"', nginx)

        acceptance = read("bin/vibestack-check")
        self.assertIn(
            '{\\"desktop\\",\\"vnc\\",\\"terminal\\",\\"setup\\",\\"ssh\\",\\"native-vnc\\",\\"editor\\"}',
            acceptance,
        )
        self.assertIn("terminal cross-origin WS rejected", acceptance)
        self.assertIn("VNC cross-origin WS rejected", acceptance)
        self.assertIn("cross-origin static rejected", acceptance)
        self.assertIn("cross-site setup rejected", acceptance)
        self.assertGreaterEqual(nginx.count("proxy_set_header Origin $http_origin"), 6)

    def test_acceptance_cleanup_is_exact_and_reclaims_root_owned_state(self) -> None:
        helper = read("bin/vibestack-dev")
        self.assertIn(
            "mktemp -d /tmp/vibestack-acceptance.XXXXXXXXXX", helper
        )
        self.assertIn(
            "^/tmp/vibestack-acceptance\\.[A-Za-z0-9]{10}$", helper
        )
        self.assertIn('! -L "$cleanup_dir"', helper)
        self.assertIn("--pids-limit=512 --entrypoint /usr/bin/chown", helper)
        self.assertIn('-v "$cleanup_dir:/cleanup"', helper)
        self.assertIn('-R "$(id -u):$(id -g)" /cleanup', helper)
        self.assertIn('rm -rf -- "$cleanup_dir"', helper)

    def test_acceptance_rechecks_project_owner_inside_container(self) -> None:
        helper = read("bin/vibestack-dev")
        self.assertIn(
            'docker exec "$acceptance_container" /usr/bin/stat -c \'%u:%g\'',
            helper,
        )
        self.assertIn("/projects/ownership-sentinel", helper)
        self.assertNotIn(
            '[[ "$(stat -c \'%u:%g\' '
            '"$acceptance_data/projects/ownership-sentinel")"',
            helper,
        )

    def test_static_text_compression_does_not_touch_websocket_configuration(self) -> None:
        nginx = read("nginx.conf")
        self.assertIn("gzip on;", nginx)
        self.assertIn("gzip_min_length 1024;", nginx)
        self.assertIn("application/javascript", nginx)
        self.assertIn("image/svg+xml", nginx)
        websocket = nginx[nginx.index("location = /vnc/websockify") :]
        self.assertIn("proxy_set_header Upgrade $http_upgrade;", websocket)

    def test_entrypoint_generates_private_persistent_credentials(self) -> None:
        entrypoint = read("entrypoint.sh")
        bootstrap = read("bin/vibestack-bootstrap")
        token_helper = read("bin/vibestack-api-token")
        bootstrap_call = entrypoint.index("/usr/local/bin/vibestack-bootstrap")
        persist_call = entrypoint.index(
            "/usr/sbin/runuser -u vibe -- /usr/local/bin/vibestack-persist"
        )
        self.assertLess(bootstrap_call, persist_call)
        self.assertIn("runtime_dir=/run/vibestack", entrypoint)
        self.assertIn('xauthority_file="$runtime_dir/Xauthority"', entrypoint)
        self.assertIn("MIT-MAGIC-COOKIE-1", entrypoint)
        self.assertIn('chown root:vibe "$xauthority_file"', entrypoint)
        self.assertIn('chmod 0640 "$xauthority_file"', entrypoint)
        self.assertIn(
            "/usr/sbin/runuser -u vibe -- /usr/local/bin/vibestack-api-token ensure >/dev/null",
            entrypoint,
        )
        self.assertIn("secrets.token_urlsafe(32)", token_helper)
        self.assertNotIn('echo "$token', entrypoint)
        self.assertNotIn("chown vibe:vibe /projects", entrypoint)
        self.assertIn("data_fd, data_info, uid=root_uid, gid=vibe_gid, mode=0o1770", bootstrap)

    def test_persistence_script_never_runs_privileged_metadata_operations(self) -> None:
        persist = read("bin/vibestack-persist")
        self.assertIn("if (( EUID == 0 )); then", persist)
        for operation in ("chown ", "chmod "):
            self.assertNotIn(operation, persist)

    def test_privileged_installer_uses_private_downloads_and_user_desktop_writes(self) -> None:
        installer = read("bin/vibestack-install")
        self.assertNotIn("/tmp/chrome.deb", installer)
        self.assertNotIn("/tmp/chatgpt.deb", installer)
        self.assertIn(
            "mktemp -d /var/tmp/vibestack-install.XXXXXXXXXX", installer
        )
        self.assertIn('chmod 0700 "$INSTALL_TMPDIR"', installer)
        self.assertIn("trap cleanup_install_tmp EXIT", installer)
        self.assertIn(
            'remove_private_directory "$INSTALL_TMPDIR" /var/tmp', installer
        )
        self.assertIn('[[ "$metadata" == "directory:${expected_uid}:${expected_gid}:700" ]]', installer)
        self.assertIn('! "$suffix" =~ ^[A-Za-z0-9]{10}$', installer)
        self.assertIn('rm -rf -- "$path"', installer)
        self.assertIn("stat -c '%u:%g:%h'", installer)
        self.assertIn('[[ "$metadata" == "0:0:1" ]]', installer)
        self.assertIn('dpkg-deb --info "$download_path"', installer)
        self.assertIn("$INSTALL_TMPDIR/$name", installer)
        self.assertIn("cd /", installer)
        self.assertIn("/usr/bin/python3 -I -", installer)

        shortcut = installer[
            installer.index("add_shortcut()") : installer.index("npm_global()")
        ]
        self.assertIn("/usr/sbin/runuser -u vibe --", shortcut)
        self.assertIn("/usr/bin/install -m 0755", shortcut)
        self.assertNotIn("install -o vibe", shortcut)
        self.assertNotRegex(installer, r"chown\s+-R\s+vibe:vibe\s+\"?\$DESKTOP_DIR")

    def test_default_launcher_is_confined_and_flatpak_mode_is_explicit(self) -> None:
        startup = read("startup.sh")
        default_arguments = startup[
            startup.index('run_args=(-d --name') : startup.index(
                'if [[ "${FLATPAK_MODE}" == "true" ]]'
            )
        ]
        flatpak_arguments = startup[
            startup.index('if [[ "${FLATPAK_MODE}" == "true" ]]') : startup.index(
                'PREVIOUS_CONTAINER=""'
            )
        ]
        self.assertNotIn("security-opt", default_arguments)
        self.assertIn("--flatpak", startup)
        self.assertIn("VIBESTACK_FLATPAK_ENABLED=1", flatpak_arguments)
        for option in (
            "seccomp=unconfined",
            "apparmor=unconfined",
            "systempaths=unconfined",
        ):
            self.assertEqual(1, flatpak_arguments.count(option))
        self.assertNotIn("--privileged", startup)
        self.assertNotIn("--cap-add", startup)

        helper = read("bin/vibestack-dev")
        self.assertIn("VIBESTACK_FLATPAK_ENABLED=1", helper)
        self.assertIn("VIBESTACK_PIDS_LIMIT:-1024", startup)
        self.assertIn("VIBESTACK_PIDS_LIMIT:-1024", helper)
        self.assertIn('--pids-limit="$PIDS_LIMIT"', startup)
        self.assertIn('--pids-limit="$PIDS_LIMIT"', helper)
        workflow = read(".github/workflows/publish-docker.yml")
        self.assertIn("runs-on: ubuntu-24.04", workflow)
        self.assertNotIn("seccomp=unconfined", workflow)
        self.assertIn(
            "sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0",
            workflow,
        )
        self.assertNotIn("--privileged", workflow)
        self.assertIn("bin/vibestack-dev accept vibestack:test", workflow)

    def test_healthcheck_reads_one_complete_supervisor_snapshot(self) -> None:
        healthcheck = read("bin/vibestack-healthcheck")
        self.assertEqual(
            1,
            healthcheck.count(
                '${SUPERVISORCTL} -c "${SUPERVISOR_CONFIG}" status'
            ),
        )
        self.assertIn(
            "SUPERVISOR_CONFIG=/etc/supervisor/supervisord.conf", healthcheck
        )
        for service in (
            "xvfb",
            "x11vnc",
            "novnc",
            "xfce4",
            "ttyd",
            "vibestack-setup",
            "vibestack-control",
            "vibestack-automation",
            "nginx",
        ):
            self.assertRegex(healthcheck, rf"(?m)^  {re.escape(service)}$")
        self.assertIn('[[ "$state" != "RUNNING" ]]', healthcheck)


if __name__ == "__main__":
    unittest.main()

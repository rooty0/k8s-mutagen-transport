#!/usr/bin/env python3
import pytest
from common import is_k8s_destination, parse_host, strip_k8s_host
from main import parse_destination, parse_ssh_argv
from scp import parse_k8s_destination, parse_scp_argv


# ---------------------------------------------------------------------------
# parse_host / strip_k8s_host (common)
# ---------------------------------------------------------------------------

class TestIsK8sDestination:
    def test_k8s_prefix(self):
        assert is_k8s_destination("k8s--my-pod") is True

    def test_k8s_with_path(self):
        assert is_k8s_destination("k8s--my-pod:/data") is True

    def test_k8s_with_container(self):
        assert is_k8s_destination("app@k8s--my-pod") is True

    def test_non_k8s(self):
        assert is_k8s_destination("somehost") is False

    def test_regular_ssh(self):
        assert is_k8s_destination("user@somehost") is False


class TestParseHost:
    def test_pod_only(self):
        assert parse_host("my-pod") == ("my-pod", None, None)

    def test_pod_and_namespace(self):
        assert parse_host("my-pod.default") == ("my-pod", "default", None)

    def test_pod_namespace_context(self):
        assert parse_host("my-pod.default.my-context") == ("my-pod", "default", "my-context")

    def test_context_with_dots(self):
        assert parse_host("my-pod.default.prod.us-east") == ("my-pod", "default", "prod.us-east")


class TestStripK8sHost:
    def test_k8s_prefix(self):
        assert strip_k8s_host("k8s--my-pod") == "my-pod"

    def test_ssh_url_prefix(self):
        assert strip_k8s_host("ssh://my-pod.default") == "my-pod.default"

    def test_port_stripped(self):
        assert strip_k8s_host("k8s--my-pod.default:22") == "my-pod.default"

    def test_no_prefix(self):
        assert strip_k8s_host("my-pod") == "my-pod"


# ---------------------------------------------------------------------------
# parse_destination (ssh)
# ---------------------------------------------------------------------------

class TestParseDestination:
    def test_pod_only(self):
        assert parse_destination("k8s--my-pod") == (None, "my-pod", None, None)

    def test_pod_and_namespace(self):
        assert parse_destination("k8s--my-pod.default") == (None, "my-pod", "default", None)

    def test_pod_namespace_context(self):
        assert parse_destination("k8s--my-pod.default.my-context") == (None, "my-pod", "default", "my-context")

    def test_context_with_dots(self):
        assert parse_destination("k8s--my-pod.default.prod.us-east") == (None, "my-pod", "default", "prod.us-east")

    def test_container(self):
        assert parse_destination("app@k8s--my-pod.default") == ("app", "my-pod", "default", None)

    def test_container_with_context(self):
        assert parse_destination("app@k8s--my-pod.default.my-context") == ("app", "my-pod", "default", "my-context")

    def test_ssh_url_prefix(self):
        assert parse_destination("ssh://my-pod.default") == (None, "my-pod", "default", None)

    def test_port_stripped(self):
        assert parse_destination("k8s--my-pod.default:22") == (None, "my-pod", "default", None)

    def test_empty_pod_raises(self):
        with pytest.raises(ValueError, match="Empty pod name"):
            parse_destination("k8s--")


# ---------------------------------------------------------------------------
# parse_ssh_argv
# ---------------------------------------------------------------------------

class TestParseSshArgv:
    def test_simple(self):
        dest, cmd = parse_ssh_argv(["k8s--my-pod", "uname -s"])
        assert dest == "k8s--my-pod"
        assert cmd == "uname -s"

    def test_flags_before_dest(self):
        dest, cmd = parse_ssh_argv(["-o", "StrictHostKeyChecking=no", "-T", "k8s--my-pod", "echo hi"])
        assert dest == "k8s--my-pod"
        assert cmd == "echo hi"

    def test_inline_o_flag(self):
        dest, cmd = parse_ssh_argv(["-oStrictHostKeyChecking=no", "k8s--my-pod", "ls"])
        assert dest == "k8s--my-pod"

    def test_no_command(self):
        dest, cmd = parse_ssh_argv(["k8s--my-pod"])
        assert dest == "k8s--my-pod"
        assert cmd == ""

    def test_no_destination_raises(self):
        with pytest.raises(ValueError, match="No destination"):
            parse_ssh_argv(["-T", "-o", "Foo=bar"])


# ---------------------------------------------------------------------------
# parse_k8s_destination (scp)
# ---------------------------------------------------------------------------

class TestParseK8sDestination:
    def test_pod_only(self):
        assert parse_k8s_destination("k8s--my-pod:/data") == (None, "my-pod", None, "/data", None)

    def test_pod_and_namespace(self):
        assert parse_k8s_destination("k8s--my-pod.default:/data") == (None, "my-pod", "default", "/data", None)

    def test_pod_namespace_context(self):
        assert parse_k8s_destination("k8s--my-pod.default.my-context:/data") == (None, "my-pod", "default", "/data", "my-context")

    def test_context_with_dots(self):
        assert parse_k8s_destination("k8s--my-pod.default.prod.us-east:/data") == (None, "my-pod", "default", "/data", "prod.us-east")

    def test_container(self):
        assert parse_k8s_destination("app@k8s--my-pod.default:/data") == ("app", "my-pod", "default", "/data", None)

    def test_container_with_context(self):
        assert parse_k8s_destination("app@k8s--my-pod.default.my-context:/data") == ("app", "my-pod", "default", "/data", "my-context")

    def test_remote_path_with_colons(self):
        # Only the first colon separates host from path
        container, pod, ns, path, ctx = parse_k8s_destination("k8s--my-pod:/some:weird:path")
        assert pod == "my-pod"
        assert path == "/some:weird:path"

    def test_relative_remote_path(self):
        _, _, _, path, _ = parse_k8s_destination("k8s--my-pod:~/project")
        assert path == "~/project"


# ---------------------------------------------------------------------------
# parse_scp_argv
# ---------------------------------------------------------------------------

class TestParseScpArgv:
    def test_simple_local_to_remote(self):
        flags, src, dst = parse_scp_argv(["/local/file", "k8s--my-pod:/remote"])
        assert flags == []
        assert src == "/local/file"
        assert dst == "k8s--my-pod:/remote"

    def test_flags(self):
        flags, src, dst = parse_scp_argv(["-r", "-P", "22", "/local", "k8s--my-pod:/remote"])
        assert "-r" in flags
        assert "-P" in flags
        assert "22" in flags
        assert src == "/local"
        assert dst == "k8s--my-pod:/remote"

    def test_remote_to_local(self):
        _, src, dst = parse_scp_argv(["k8s--my-pod:/remote", "/local"])
        assert src == "k8s--my-pod:/remote"
        assert dst == "/local"

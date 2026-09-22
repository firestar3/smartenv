"""Tests for the cloud secret manager sources.

The provider SDKs (``boto3``, ``google-cloud-secret-manager`` and
``azure-keyvault-secrets`` + ``azure-identity``) are optional and not installed
in the test environment, so the tests inject fake modules into
:mod:`sys.modules` to exercise the happy paths, and rely on their absence for
the ImportError paths.
"""

from __future__ import annotations

import asyncio
import base64
import builtins
import contextvars
import json
import sys
import threading
import types
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import pytest

from smartenv.exceptions import CloudAuthError
from smartenv.sources import BaseSource, resolve_source
from smartenv.sources.aws_source import AwsSource
from smartenv.sources.azure_source import AzureSource
from smartenv.sources.base import CloudSource, parse_secret_payload
from smartenv.sources.gcp_source import GcpSource

# --- helpers -----------------------------------------------------------------


def block_sdk_import(monkeypatch: pytest.MonkeyPatch, prefix: str) -> None:
    """Simulate a missing SDK even when extras are installed.

    Args:
        monkeypatch: Fixture restoring the import hook after the test.
        prefix: Module name, including its submodules, to make unavailable.
    """
    real_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: Optional[Dict[str, Any]] = None,
        locals: Optional[Dict[str, Any]] = None,
        fromlist: Tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == prefix or name.startswith(prefix + "."):
            raise ImportError("SDK is unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


class RecordingClient:
    """Fake cloud client counting every call made against it."""

    def __init__(self) -> None:
        self.calls: List[str] = []

    def record(self, call: str) -> None:
        """Append ``call`` to the call log.

        Args:
            call: Description of the performed call.
        """
        self.calls.append(call)


def install_fake_module(name: str, **attributes: Any) -> types.ModuleType:
    """Create a fake module with ``attributes`` and register it in sys.modules.

    Args:
        name: Dotted module name to register.
        **attributes: Attributes exposed by the fake module.

    Returns:
        The registered module.
    """
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def uninstall_fake_modules(*names: str) -> None:
    """Remove the given modules (and their parents) from sys.modules.

    Args:
        names: Dotted module names to remove.
    """
    for name in names:
        sys.modules.pop(name, None)
        while "." in name:
            name = name.rsplit(".", 1)[0]
            sys.modules.pop(name, None)


class CloudStub(CloudSource):
    """Minimal cloud source used to test the shared CloudSource machinery."""

    def __init__(
        self,
        values: Dict[str, str],
        cache: bool = True,
        fail_first: int = 0,
        cache_ttl: Optional[float] = None,
    ) -> None:
        super().__init__(cache=cache, cache_ttl=cache_ttl)
        self.values = values
        self.fail_first = fail_first
        self.fetches = 0

    @property
    def name(self) -> str:
        """Return the identifier of the source.

        Returns:
            A fixed ``"stub"`` identifier.
        """
        return "stub"

    def _fetch(self) -> Dict[str, str]:
        """Return the canned values, failing the first ``fail_first`` calls.

        Returns:
            The configured values.

        Raises:
            CloudAuthError: While the failure budget is not spent.
        """
        self.fetches += 1
        if self.fetches <= self.fail_first:
            raise CloudAuthError("stub", reason="simulated outage")
        return dict(self.values)


# --- parse_secret_payload ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"PORT": "8080", "HOST": "db"}', {"PORT": "8080", "HOST": "db"}),
        ('{"db": {"host": "db", "port": 5432}}', {"DB__HOST": "db", "DB__PORT": "5432"}),
        ("plain-token", {"SECRET": "plain-token"}),
        ('["a", "b"]', {"SECRET": '["a", "b"]'}),
        ('"just a json string"', {"SECRET": '"just a json string"'}),
        ("42", {"SECRET": "42"}),
        ("{'broken'".replace("'", '"'), {"SECRET": "{'broken'".replace("'", '"')}),
        ("", {"SECRET": ""}),
        ('{"flag": true, "none": null}', {"FLAG": "true", "NONE": ""}),
    ],
)
def test_parse_secret_payload(raw: str, expected: Dict[str, str]) -> None:
    assert parse_secret_payload(raw) == expected


def test_parse_secret_payload_is_trimmed() -> None:
    assert parse_secret_payload('  {"A": "1"}  \n') == {"A": "1"}


def test_parse_secret_payload_preserves_plain_whitespace() -> None:
    assert parse_secret_payload("  token\n") == {"SECRET": "  token\n"}


def test_parse_secret_payload_custom_fallback_preserves_json_keys() -> None:
    assert parse_secret_payload("token", default_key="AWS_SECRET") == {"AWS_SECRET": "token"}
    assert parse_secret_payload('{"SECRET": "token"}', default_key="AWS_SECRET") == {
        "SECRET": "token"
    }


# --- CloudSource caching / async ---------------------------------------------


def test_cloud_source_load_is_cached_per_instance() -> None:
    first = CloudStub({"A": "1"})
    second = CloudStub({"A": "2"})

    assert first.load() == {"A": "1"}
    assert first.load() == {"A": "1"}
    assert first.fetches == 1
    assert second.load() == {"A": "2"}
    assert second.fetches == 1


def test_cloud_source_cache_off_fetches_every_time() -> None:
    source = CloudStub({"A": "1"}, cache=False)

    assert source.load() == {"A": "1"}
    assert source.load() == {"A": "1"}
    assert source.fetches == 2


def test_cloud_source_cache_clear_refetches() -> None:
    source = CloudStub({"A": "1"})

    source.load()
    source.cache_clear()
    source.load()

    assert source.fetches == 2


def test_cloud_source_cache_failure_is_not_cached() -> None:
    source = CloudStub({"A": "1"}, fail_first=1)

    with pytest.raises(CloudAuthError):
        source.load()
    assert source.load() == {"A": "1"}
    assert source.fetches == 2


def test_cloud_source_cache_returns_copies() -> None:
    source = CloudStub({"A": "1"})

    snapshot = source.load()
    snapshot["B"] = "2"

    assert source.load() == {"A": "1"}


def test_cloud_source_is_a_base_source() -> None:
    assert isinstance(CloudStub({}), BaseSource)


def test_cloud_source_concurrent_loads_fetch_once() -> None:
    source = CloudStub({"A": "1"})
    barrier = threading.Barrier(5)
    results: List[Dict[str, str]] = []

    def reader() -> None:
        barrier.wait(timeout=10)
        results.append(source.load())

    threads = [threading.Thread(target=reader) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert results == [{"A": "1"}] * 5
    assert source.fetches == 1


def test_cloud_source_concurrent_failures_then_success() -> None:
    source = CloudStub({"A": "1"}, fail_first=1)
    outcomes: List[str] = []
    barrier = threading.Barrier(4)

    def reader() -> None:
        barrier.wait(timeout=10)
        try:
            source.load()
        except CloudAuthError:
            outcomes.append("error")
        else:
            outcomes.append("ok")

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert outcomes.count("ok") >= 1
    assert source.load() == {"A": "1"}


def test_cloud_source_aload_returns_values() -> None:
    source = CloudStub({"A": "1"})

    assert asyncio.run(source.aload()) == {"A": "1"}


def test_cloud_source_aload_works_without_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(asyncio, "to_thread", raising=False)
    source = CloudStub({"A": "1"})
    caller_thread = threading.get_ident()
    worker_threads: List[int] = []
    original_fetch = source._fetch

    def recording_fetch() -> Dict[str, str]:
        worker_threads.append(threading.get_ident())
        return original_fetch()

    monkeypatch.setattr(source, "_fetch", recording_fetch)
    assert asyncio.run(source.aload()) == {"A": "1"}
    assert worker_threads and worker_threads[0] != caller_thread


def test_cloud_source_aload_propagates_cloud_auth_error() -> None:
    source = CloudStub({}, fail_first=99)

    with pytest.raises(CloudAuthError):
        asyncio.run(source.aload())


@pytest.mark.parametrize("ttl", [0, -1, float("nan"), float("inf"), float("-inf"), True])
def test_cloud_source_rejects_invalid_ttl(ttl: float) -> None:
    with pytest.raises(ValueError, match="cache_ttl"):
        CloudStub({}, cache_ttl=ttl)


def test_cloud_source_ttl_starts_after_fetch_and_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [10.0]
    monkeypatch.setattr("smartenv.sources.base.time.monotonic", lambda: clock[0])
    source = CloudStub({"TOKEN": "first"}, cache_ttl=5)
    original_fetch = source._fetch

    def slow_fetch() -> Dict[str, str]:
        clock[0] += 10
        return original_fetch()

    monkeypatch.setattr(source, "_fetch", slow_fetch)
    assert source.load() == {"TOKEN": "first"}
    source.values["TOKEN"] = "rotated"
    clock[0] = 24.9
    assert source.load() == {"TOKEN": "first"}
    clock[0] = 25
    assert source.load() == {"TOKEN": "rotated"}
    assert source.fetches == 2


def test_cloud_source_failed_refresh_does_not_extend_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("smartenv.sources.base.time.monotonic", lambda: clock[0])
    source = CloudStub({"TOKEN": "first"}, cache_ttl=1)
    assert source.load() == {"TOKEN": "first"}
    source.fail_first = 2
    clock[0] = 1
    with pytest.raises(CloudAuthError):
        source.load()
    source.values["TOKEN"] = "rotated"
    assert source.load() == {"TOKEN": "rotated"}
    assert source.fetches == 3


def test_cloud_source_ttl_concurrent_refresh_fetches_once(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("smartenv.sources.base.time.monotonic", lambda: clock[0])
    source = CloudStub({"TOKEN": "first"}, cache_ttl=1)
    source.load()
    source.values["TOKEN"] = "rotated"
    clock[0] = 1
    barrier = threading.Barrier(5)
    results: List[Dict[str, str]] = []

    def reader() -> None:
        barrier.wait(timeout=10)
        results.append(source.load())

    threads = [threading.Thread(target=reader) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert results == [{"TOKEN": "rotated"}] * 5
    assert source.fetches == 2


def test_cloud_source_aload_preserves_contextvars(monkeypatch: pytest.MonkeyPatch) -> None:
    request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="unset")
    source = CloudStub({}, cache=False)
    monkeypatch.setattr(source, "_fetch", lambda: {"REQUEST_ID": request_id.get()})
    token = request_id.set("request-123")
    try:
        assert asyncio.run(source.aload()) == {"REQUEST_ID": "request-123"}
    finally:
        request_id.reset(token)


# --- AwsSource ----------------------------------------------------------------


class FakeSecretsManagerClient(RecordingClient):
    """Fake ``boto3`` Secrets Manager client serving canned secrets."""

    def __init__(self, secrets: Dict[str, str], error: Optional[Exception] = None) -> None:
        super().__init__()
        self.secrets = secrets
        self.error = error
        self.region: Optional[str] = None

    def get_secret_value(self, SecretId: str) -> Dict[str, Any]:  # noqa: N803
        """Return the canned payload for ``SecretId``.

        Args:
            SecretId: Name or ARN of the requested secret (boto3 keyword style).

        Returns:
            A response mapping shaped like the boto3 one.

        Raises:
            Exception: When the fake was configured to fail.
        """
        self.record(f"get_secret_value:{SecretId}")
        if self.error is not None:
            raise self.error
        return {"SecretString": self.secrets[SecretId]}


@pytest.fixture()
def fake_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[[], FakeSecretsManagerClient]]:
    """Install a fake boto3 and clean up afterwards.

    Args:
        monkeypatch: Pytest fixture providing ``setenv``/``delenv``.

    Yields:
        A callable returning the fake Secrets Manager client.
    """
    client = FakeSecretsManagerClient(secrets={"prod/myapp": '{"PORT": "8080"}'})

    def factory(service: str, region_name: Optional[str] = None) -> FakeSecretsManagerClient:
        """Return the pre-created fake Secrets Manager client.

        Args:
            service: Requested AWS service name.
            region_name: Region forwarded by the source, remembered on the client.

        Returns:
            The fake client.
        """
        assert service == "secretsmanager"
        client.region = region_name
        return client

    def the_client() -> FakeSecretsManagerClient:
        """Return the fake client used by every source in the test.

        Returns:
            The fake client created at fixture setup.
        """
        return client

    install_fake_module("boto3", client=factory)
    yield the_client
    uninstall_fake_modules("boto3")


@pytest.fixture(autouse=True)
def clean_aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip AWS configuration from the environment for every test.

    Args:
        monkeypatch: Pytest fixture providing ``delenv``.
    """
    for name in ("AWS_SECRET_NAME", "AWS_REGION"):
        monkeypatch.delenv(name, raising=False)


def test_aws_source_load_json_payload(
    fake_aws: Callable[..., FakeSecretsManagerClient],
) -> None:
    source = AwsSource(secret_name="prod/myapp", region="eu-west-1")

    assert source.load() == {"PORT": "8080"}
    assert fake_aws().calls == ["get_secret_value:prod/myapp"]


def test_aws_source_load_plain_payload(
    fake_aws: Callable[..., FakeSecretsManagerClient],
) -> None:
    fake_aws().secrets["prod/myapp"] = "raw-token-value"
    source = AwsSource(secret_name="prod/myapp", region="eu-west-1")

    assert source.load() == {"AWS_SECRET": "raw-token-value"}


def test_aws_source_json_secret_key_is_not_renamed(
    fake_aws: Callable[..., FakeSecretsManagerClient],
) -> None:
    fake_aws().secrets["prod/myapp"] = '{"SECRET": "raw-token-value"}'
    source = AwsSource(secret_name="prod/myapp")

    assert source.load() == {"SECRET": "raw-token-value"}


def test_aws_source_load_is_cached(
    fake_aws: Callable[..., FakeSecretsManagerClient],
) -> None:
    source = AwsSource(secret_name="prod/myapp", region="eu-west-1")

    assert source.load() == {"PORT": "8080"}
    assert source.load() == {"PORT": "8080"}
    assert fake_aws().calls == ["get_secret_value:prod/myapp"]


def test_aws_source_cache_off_refetches(
    fake_aws: Callable[..., FakeSecretsManagerClient],
) -> None:
    source = AwsSource(secret_name="prod/myapp", region="eu-west-1", cache=False)

    source.load()
    source.load()

    assert fake_aws().calls == [
        "get_secret_value:prod/myapp",
        "get_secret_value:prod/myapp",
    ]


def test_aws_source_env_fallbacks(
    fake_aws: Callable[..., FakeSecretsManagerClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_SECRET_NAME", "prod/myapp")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")

    source = AwsSource()

    assert source.secret_name == "prod/myapp"
    assert source.region == "ap-south-1"
    assert source.load() == {"PORT": "8080"}
    assert fake_aws().region == "ap-south-1"


def test_aws_source_region_default(
    fake_aws: Callable[..., FakeSecretsManagerClient],
) -> None:
    source = AwsSource(secret_name="prod/myapp")

    assert source.region == "us-east-1"
    assert source.load() == {"PORT": "8080"}
    assert fake_aws().region == "us-east-1"


def test_aws_source_missing_name_fails_before_api_request(
    fake_aws: Callable[..., FakeSecretsManagerClient],
) -> None:
    source = AwsSource()

    with pytest.raises(CloudAuthError, match="AWS_SECRET_NAME"):
        source.load()

    assert fake_aws().calls == []


def test_aws_source_name() -> None:
    assert AwsSource(secret_name="prod/myapp").name == "aws_secrets"


def test_aws_source_repr() -> None:
    source = AwsSource(secret_name="prod/myapp", region="eu-west-1")

    assert repr(source) == "<AwsSource name='aws_secrets'>"


def test_aws_source_api_error_wrapped(
    fake_aws: Callable[..., FakeSecretsManagerClient],
) -> None:
    fake_aws().error = RuntimeError("AccessDeniedException: not authorized")
    source = AwsSource(secret_name="prod/myapp", region="eu-west-1")

    with pytest.raises(CloudAuthError) as excinfo:
        source.load()

    assert excinfo.value.provider == "aws"
    assert "not authorized" in str(excinfo.value)


def test_aws_source_cache_failure_is_not_cached(
    fake_aws: Callable[..., FakeSecretsManagerClient],
) -> None:
    fake_aws().error = RuntimeError("throttled")

    with pytest.raises(CloudAuthError):
        AwsSource(secret_name="prod/myapp").load()

    fake_aws().error = None
    assert AwsSource(secret_name="prod/myapp").load() == {"PORT": "8080"}


def test_aws_source_aload(fake_aws: Callable[..., FakeSecretsManagerClient]) -> None:
    source = AwsSource(secret_name="prod/myapp", region="eu-west-1")

    assert asyncio.run(source.aload()) == {"PORT": "8080"}


def test_aws_source_without_boto3_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    block_sdk_import(monkeypatch, "boto3")
    source = AwsSource(secret_name="prod/myapp")

    with pytest.raises(CloudAuthError) as excinfo:
        source.load()

    assert "pip install smartenv[aws]" in str(excinfo.value)


def test_aws_source_nested_json_is_flattened(
    fake_aws: Callable[..., FakeSecretsManagerClient],
) -> None:
    fake_aws().secrets["prod/myapp"] = json.dumps({"db": {"host": "db.local", "port": 5432}})
    source = AwsSource(secret_name="prod/myapp", region="eu-west-1")

    assert source.load() == {"DB__HOST": "db.local", "DB__PORT": "5432"}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b'{"PORT": 9000}', {"PORT": "9000"}),
        (bytearray(b"token"), {"AWS_SECRET": "token"}),
        (b"dG9rZW4=", {"AWS_SECRET": "dG9rZW4="}),
        (base64.b64encode(b'{"PORT": 9000}').decode("ascii"), {"PORT": "9000"}),
    ],
)
def test_aws_source_binary_payload(
    fake_aws: Callable[[], FakeSecretsManagerClient],
    monkeypatch: pytest.MonkeyPatch,
    payload: Any,
    expected: Dict[str, str],
) -> None:
    monkeypatch.setattr(fake_aws(), "get_secret_value", lambda **kwargs: {"SecretBinary": payload})
    assert AwsSource(secret_name="prod/myapp").load() == expected


@pytest.mark.parametrize(
    "response",
    [{"SecretBinary": b"\xff"}, {"SecretBinary": "not-base64!"}, {}, {"SecretString": None}],
)
def test_aws_source_malformed_payload_is_wrapped(
    fake_aws: Callable[[], FakeSecretsManagerClient],
    monkeypatch: pytest.MonkeyPatch,
    response: Dict[str, Any],
) -> None:
    monkeypatch.setattr(fake_aws(), "get_secret_value", lambda **kwargs: response)
    with pytest.raises(CloudAuthError) as error:
        AwsSource(secret_name="prod/myapp").load()
    assert error.value.provider == "aws"


def test_aws_source_client_creation_error_wrapped(
    fake_aws: Callable[[], FakeSecretsManagerClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_client(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("credentials unavailable")

    monkeypatch.setattr(sys.modules["boto3"], "client", failed_client)
    with pytest.raises(CloudAuthError, match="credentials unavailable"):
        AwsSource(secret_name="prod/myapp").load()


# --- GcpSource ----------------------------------------------------------------


class FakeSecretManagerClient(RecordingClient):
    """Fake ``google.cloud.secretmanager`` client serving canned secrets."""

    def __init__(
        self,
        secrets: Dict[str, str],
        error: Optional[Exception] = None,
        project: str = "my-project",
    ) -> None:
        super().__init__()
        self.secrets = secrets
        self.error = error
        self.project = project

    def project_path(self, project: str) -> str:
        """Return the canned project resource path.

        Args:
            project: Project identifier.

        Returns:
            A ``projects/<id>`` style path.
        """
        self.record(f"project_path:{project}")
        return f"projects/{project}"

    def secret_path(self, project: str, secret: str) -> str:
        """Return the canned secret resource path.

        Args:
            project: Project identifier.
            secret: Secret identifier.

        Returns:
            A ``projects/<p>/secrets/<s>`` style path.
        """
        return f"projects/{project}/secrets/{secret}"

    def list_secrets(self, request: Dict[str, str]) -> List[Any]:
        """List the secrets of the requested project.

        Args:
            request: Request mapping with a ``parent`` key.

        Returns:
            Fake secret entries with ``name`` resource paths.

        Raises:
            Exception: When the fake was configured to fail.
        """
        self.record(f"list_secrets:{request['parent']}")
        if self.error is not None:
            raise self.error
        return [
            FakeSecretBundle(name=f"{request['parent']}/secrets/{name}") for name in self.secrets
        ]

    def access_secret_version(self, request: Dict[str, str]) -> FakeSecretBundle:
        """Return the canned payload of a secret version.

        Args:
            request: Request mapping with a ``name`` key.

        Returns:
            A response object shaped like the Google SDK one.

        Raises:
            Exception: When the fake was configured to fail.
        """
        self.record(f"access:{request['name']}")
        if self.error is not None:
            raise self.error
        secret = request["name"].rsplit("/secrets/", 1)[-1].split("/versions/")[0]
        return FakeSecretBundle(payload=FakeSecretBundle(data=self.secrets[secret].encode("utf-8")))


class FakeSecretBundle:
    """Attribute holder mimicking a Google SDK protobuf object."""

    def __init__(self, **attributes: Any) -> None:
        self.__dict__.update(attributes)


@pytest.fixture()
def fake_gcp(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[], FakeSecretManagerClient]]:
    """Install a fake ``google.cloud.secretmanager`` module and clean up.

    Args:
        monkeypatch: Pytest fixture providing ``delenv``.

    Yields:
        A callable returning the fake Secret Manager client.
    """
    for name in ("GCP_PROJECT_ID", "GCP_SECRET_ID"):
        monkeypatch.delenv(name, raising=False)
    client = FakeSecretManagerClient(secrets={"myapp-config": '{"PORT": "8080", "HOST": "db"}'})

    def factory() -> FakeSecretManagerClient:
        """Return the pre-created fake Secret Manager client.

        Returns:
            The fake client created at fixture setup.
        """
        return client

    cloud_module = install_fake_module("google.cloud")
    secretmanager_module = install_fake_module(
        "google.cloud.secretmanager", SecretManagerServiceClient=factory
    )
    cloud_module.secretmanager = secretmanager_module  # type: ignore[attr-defined]
    yield lambda: client
    uninstall_fake_modules("google.cloud.secretmanager", "google.cloud")


def test_gcp_source_load_json_payload(
    fake_gcp: Callable[[], FakeSecretManagerClient],
) -> None:
    source = GcpSource(project_id="my-project", secret_id="myapp-config")

    assert source.load() == {"PORT": "8080", "HOST": "db"}
    assert "access:projects/my-project/secrets/myapp-config/versions/latest" in fake_gcp().calls


def test_gcp_source_load_plain_payload(
    fake_gcp: Callable[[], FakeSecretManagerClient],
) -> None:
    fake_gcp().secrets["myapp-config"] = "raw-token-value"
    source = GcpSource(project_id="my-project", secret_id="myapp-config")

    assert source.load() == {"SECRET": "raw-token-value"}


def test_gcp_source_version(fake_gcp: Callable[[], FakeSecretManagerClient]) -> None:
    source = GcpSource(project_id="my-project", secret_id="myapp-config", version="3")

    source.load()

    assert "access:projects/my-project/secrets/myapp-config/versions/3" in fake_gcp().calls


def test_gcp_source_load_is_cached(
    fake_gcp: Callable[[], FakeSecretManagerClient],
) -> None:
    source = GcpSource(project_id="my-project", secret_id="myapp-config")

    assert source.load() == {"PORT": "8080", "HOST": "db"}
    assert source.load() == {"PORT": "8080", "HOST": "db"}
    assert len([c for c in fake_gcp().calls if c.startswith("access:")]) == 1


def test_gcp_source_cache_off_refetches(
    fake_gcp: Callable[[], FakeSecretManagerClient],
) -> None:
    source = GcpSource(project_id="my-project", secret_id="myapp-config", cache=False)

    source.load()
    source.load()

    assert len([c for c in fake_gcp().calls if c.startswith("access:")]) == 2


def test_gcp_source_fetch_all_secrets(
    fake_gcp: Callable[[], FakeSecretManagerClient],
) -> None:
    fake_gcp().secrets.clear()
    fake_gcp().secrets["alpha"] = '{"A": "1"}'
    fake_gcp().secrets["beta"] = "plain"
    fake_gcp().secrets["gamma"] = "another plain"
    source = GcpSource(project_id="my-project")

    assert source.load() == {"A": "1", "BETA": "plain", "GAMMA": "another plain"}
    assert "list_secrets:projects/my-project" in fake_gcp().calls


def test_gcp_source_env_fallbacks(
    fake_gcp: Callable[[], FakeSecretManagerClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "env-project")
    monkeypatch.setenv("GCP_SECRET_ID", "myapp-config")

    source = GcpSource()

    assert source.project_id == "env-project"
    assert source.secret_id == "myapp-config"
    assert source.load() == {"PORT": "8080", "HOST": "db"}


def test_gcp_source_name_and_repr() -> None:
    source = GcpSource(project_id="my-project", secret_id="myapp-config")

    assert source.name == "gcp_secrets"
    assert repr(source) == "<GcpSource name='gcp_secrets'>"


def test_gcp_source_api_error_wrapped(
    fake_gcp: Callable[[], FakeSecretManagerClient],
) -> None:
    fake_gcp().error = RuntimeError("permission denied on secret")
    source = GcpSource(project_id="my-project", secret_id="myapp-config")

    with pytest.raises(CloudAuthError) as excinfo:
        source.load()

    assert excinfo.value.provider == "gcp"
    assert "permission denied" in str(excinfo.value)


def test_gcp_source_client_creation_error_wrapped(
    fake_gcp: Callable[[], FakeSecretManagerClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_client() -> None:
        raise RuntimeError("credentials unavailable")

    monkeypatch.setattr(
        sys.modules["google.cloud.secretmanager"], "SecretManagerServiceClient", failing_client
    )
    with pytest.raises(CloudAuthError, match="credentials unavailable") as excinfo:
        GcpSource(project_id="my-project", secret_id="myapp-config").load()

    assert excinfo.value.provider == "gcp"


def test_gcp_source_aload(fake_gcp: Callable[[], FakeSecretManagerClient]) -> None:
    source = GcpSource(project_id="my-project", secret_id="myapp-config")

    assert asyncio.run(source.aload()) == {"PORT": "8080", "HOST": "db"}


def test_gcp_source_without_sdk_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    block_sdk_import(monkeypatch, "google.cloud")
    source = GcpSource(project_id="my-project", secret_id="myapp-config")

    with pytest.raises(CloudAuthError) as excinfo:
        source.load()

    assert "pip install smartenv[gcp]" in str(excinfo.value)


def test_gcp_source_missing_project_fails_before_request(
    fake_gcp: Callable[[], FakeSecretManagerClient],
) -> None:
    with pytest.raises(CloudAuthError, match="GCP_PROJECT_ID"):
        GcpSource(secret_id="myapp-config").load()
    assert fake_gcp().calls == []


@pytest.mark.parametrize("secret_id", [None, "myapp-config"])
@pytest.mark.parametrize("data", [b"\xff", None, 123])
def test_gcp_source_invalid_payload_is_wrapped(
    fake_gcp: Callable[[], FakeSecretManagerClient],
    monkeypatch: pytest.MonkeyPatch,
    secret_id: Optional[str],
    data: Any,
) -> None:
    monkeypatch.setattr(
        fake_gcp(),
        "access_secret_version",
        lambda **kwargs: FakeSecretBundle(payload=FakeSecretBundle(data=data)),
    )
    with pytest.raises(CloudAuthError) as error:
        GcpSource(project_id="my-project", secret_id=secret_id).load()
    assert error.value.provider == "gcp"


def test_gcp_source_listing_error_is_wrapped(
    fake_gcp: Callable[[], FakeSecretManagerClient],
) -> None:
    fake_gcp().error = RuntimeError("list denied")
    with pytest.raises(CloudAuthError, match="list denied"):
        GcpSource(project_id="my-project").load()


# --- AzureSource --------------------------------------------------------------


class FakeKeyVaultClient(RecordingClient):
    """Fake ``azure.keyvault.secrets.SecretClient`` serving canned secrets."""

    def __init__(
        self,
        secrets: Dict[str, str],
        error: Optional[Exception] = None,
    ) -> None:
        super().__init__()
        self.secrets = secrets
        self.error = error
        self.region: Optional[str] = None
        self.vault_url = ""
        self.credential: Any = None

    def get_secret(self, name: str) -> FakeSecretBundle:
        """Return the canned value of a secret.

        Args:
            name: Name of the requested secret.

        Returns:
            A fake secret object with a ``value`` attribute.

        Raises:
            Exception: When the fake was configured to fail.
        """
        self.record(f"get_secret:{name}")
        if self.error is not None:
            raise self.error
        return FakeSecretBundle(value=self.secrets[name])

    def list_properties_of_secrets(self) -> List[FakeSecretBundle]:
        """List the properties of every secret in the vault.

        Returns:
            Fake property objects with a ``name`` attribute.

        Raises:
            Exception: When the fake was configured to fail.
        """
        self.record("list_properties_of_secrets")
        if self.error is not None:
            raise self.error
        return [FakeSecretBundle(name=name) for name in self.secrets]


@pytest.fixture()
def fake_azure(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[], FakeKeyVaultClient]]:
    """Install fake ``azure.*`` modules and clean up afterwards.

    Args:
        monkeypatch: Pytest fixture providing ``delenv``.

    Yields:
        A callable returning the fake Key Vault client.
    """
    monkeypatch.delenv("AZURE_VAULT_URL", raising=False)
    client = FakeKeyVaultClient(secrets={"db-password": "s3cret", "api-key": "tok-1"})

    def client_factory(vault_url: str, credential: Any) -> FakeKeyVaultClient:
        """Build the fake Key Vault client.

        Args:
            vault_url: Vault URL forwarded by the source.
            credential: Credential object forwarded by the source.

        Returns:
            The fake client, remembering the vault URL.
        """
        client.vault_url = vault_url
        client.credential = credential
        return client

    def credential_factory() -> str:
        """Build the fake DefaultAzureCredential.

        Returns:
            A marker string identifying the fake credential.
        """
        return "fake-credential"

    secrets_module = install_fake_module("azure.keyvault.secrets", SecretClient=client_factory)
    install_fake_module("azure.identity", DefaultAzureCredential=credential_factory)
    install_fake_module("azure.keyvault", secrets=secrets_module)
    install_fake_module("azure")
    yield lambda: client
    uninstall_fake_modules("azure.keyvault.secrets", "azure.identity", "azure.keyvault", "azure")


def test_azure_source_load_named_secrets(
    fake_azure: Callable[[], FakeKeyVaultClient],
) -> None:
    source = AzureSource(vault_url="https://vault.example", secret_names=["db-password", "api-key"])

    assert source.load() == {"DB-PASSWORD": "s3cret", "API-KEY": "tok-1"}
    assert fake_azure().vault_url == "https://vault.example"
    assert fake_azure().calls == ["get_secret:db-password", "get_secret:api-key"]


def test_azure_source_load_all_secrets(
    fake_azure: Callable[[], FakeKeyVaultClient],
) -> None:
    source = AzureSource(vault_url="https://vault.example")

    assert source.load() == {"DB-PASSWORD": "s3cret", "API-KEY": "tok-1"}
    assert "list_properties_of_secrets" in fake_azure().calls


def test_azure_source_explicit_empty_names_do_not_list(
    fake_azure: Callable[[], FakeKeyVaultClient],
) -> None:
    source = AzureSource(vault_url="https://vault.example", secret_names=[])

    assert source.load() == {}
    assert fake_azure().calls == []


def test_azure_source_load_is_cached(
    fake_azure: Callable[[], FakeKeyVaultClient],
) -> None:
    source = AzureSource(vault_url="https://vault.example", secret_names=["db-password"])

    assert source.load() == {"DB-PASSWORD": "s3cret"}
    assert source.load() == {"DB-PASSWORD": "s3cret"}
    assert fake_azure().calls == ["get_secret:db-password"]


def test_azure_source_cache_off_refetches(
    fake_azure: Callable[[], FakeKeyVaultClient],
) -> None:
    source = AzureSource(
        vault_url="https://vault.example", secret_names=["db-password"], cache=False
    )

    source.load()
    source.load()

    assert fake_azure().calls == ["get_secret:db-password", "get_secret:db-password"]


def test_azure_source_env_fallback(
    fake_azure: Callable[[], FakeKeyVaultClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZURE_VAULT_URL", "https://env.vault.example")

    source = AzureSource()

    assert source.vault_url == "https://env.vault.example"
    assert source.load() == {"DB-PASSWORD": "s3cret", "API-KEY": "tok-1"}


def test_azure_source_json_secret_keeps_its_value(
    fake_azure: Callable[[], FakeKeyVaultClient],
) -> None:
    fake_azure().secrets["config"] = '{"db": {"host": "db.local"}}'
    source = AzureSource(vault_url="https://vault.example", secret_names=["config"])

    assert source.load() == {"CONFIG": '{"db": {"host": "db.local"}}'}


def test_azure_source_name_and_repr() -> None:
    source = AzureSource(vault_url="https://vault.example")

    assert source.name == "azure_secrets"
    assert repr(source) == "<AzureSource name='azure_secrets'>"


def test_azure_source_api_error_wrapped(
    fake_azure: Callable[[], FakeKeyVaultClient],
) -> None:
    fake_azure().error = RuntimeError("Forbidden by vault policy")
    source = AzureSource(vault_url="https://vault.example", secret_names=["db-password"])

    with pytest.raises(CloudAuthError) as excinfo:
        source.load()

    assert excinfo.value.provider == "azure"
    assert "Forbidden" in str(excinfo.value)


def test_azure_source_aload(fake_azure: Callable[[], FakeKeyVaultClient]) -> None:
    source = AzureSource(vault_url="https://vault.example", secret_names=["api-key"])

    assert asyncio.run(source.aload()) == {"API-KEY": "tok-1"}


def test_azure_source_without_sdk_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    block_sdk_import(monkeypatch, "azure")
    source = AzureSource(vault_url="https://vault.example")

    with pytest.raises(CloudAuthError) as excinfo:
        source.load()

    assert "pip install smartenv[azure]" in str(excinfo.value)


def test_azure_source_missing_vault_fails_before_request(
    fake_azure: Callable[[], FakeKeyVaultClient],
) -> None:
    with pytest.raises(CloudAuthError, match="AZURE_VAULT_URL"):
        AzureSource(secret_names=["api-key"]).load()
    assert fake_azure().calls == []


def test_azure_source_client_creation_error_wrapped(
    fake_azure: Callable[[], FakeKeyVaultClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_credential() -> None:
        raise RuntimeError("credentials unavailable")

    monkeypatch.setattr(sys.modules["azure.identity"], "DefaultAzureCredential", failed_credential)
    with pytest.raises(CloudAuthError, match="credentials unavailable"):
        AzureSource(vault_url="https://vault.example").load()


def test_azure_source_pagination_error_is_wrapped(
    fake_azure: Callable[[], FakeKeyVaultClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_pagination() -> Iterator[FakeSecretBundle]:
        yield FakeSecretBundle(name="api-key")
        raise RuntimeError("page fetch failed")

    monkeypatch.setattr(fake_azure(), "list_properties_of_secrets", failed_pagination)
    with pytest.raises(CloudAuthError, match="page fetch failed"):
        AzureSource(vault_url="https://vault.example").load()


def test_provider_ttl_refreshes_are_available(
    fake_aws: Callable[[], FakeSecretsManagerClient],
    fake_gcp: Callable[[], FakeSecretManagerClient],
    fake_azure: Callable[[], FakeKeyVaultClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr("smartenv.sources.base.time.monotonic", lambda: clock[0])
    sources = [
        AwsSource(secret_name="prod/myapp", cache_ttl=10),
        GcpSource(project_id="my-project", secret_id="myapp-config", cache_ttl=10),
        AzureSource(vault_url="https://vault.example", secret_names=["api-key"], cache_ttl=10),
    ]
    original = [source.load() for source in sources]
    fake_aws().secrets["prod/myapp"] = "rotated"
    fake_gcp().secrets["myapp-config"] = "rotated"
    fake_azure().secrets["api-key"] = "rotated"
    assert [source.load() for source in sources] == original
    clock[0] = 10
    assert [source.load() for source in sources] == [
        {"AWS_SECRET": "rotated"},
        {"SECRET": "rotated"},
        {"API-KEY": "rotated"},
    ]


# --- resolve_source -----------------------------------------------------------


@pytest.mark.parametrize(
    ("argument", "expected"),
    [
        ("aws_secrets", "AwsSource"),
        ("gcp_secrets", "GcpSource"),
        ("azure_secrets", "AzureSource"),
        ("AWS_SECRETS", "AwsSource"),
    ],
)
def test_resolve_source_builds_cloud_sources(argument: str, expected: str) -> None:
    source = resolve_source(argument)

    assert type(source).__name__ == expected


def test_resolve_source_cloud_sources_are_base_sources() -> None:
    for argument in ("aws_secrets", "gcp_secrets", "azure_secrets"):
        source = resolve_source(argument)

        assert isinstance(source, BaseSource)

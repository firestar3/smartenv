"""Google Secret Manager source (requires the ``smartenv-config[gcp]`` extra).

:class:`GcpSource` reads one secret version (or one version of every secret when
no ``secret_id`` is given) from Google Secret Manager::

    from smartenv.sources import GcpSource

    source = GcpSource(project_id="my-project", secret_id="myapp-config")
    values = source.load()          # {"PORT": "8080", "HOST": "db.example"}

A secret payload may be a JSON object — flattened with the same rules as the
JSON source — or any plain string, served under the ``SECRET`` key for a
selected secret, or its uppercased secret ID when fetching all secrets. The module
imports :mod:`google.cloud.secretmanager` lazily, so a plain
``import smartenv.sources`` never pulls it in.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from smartenv.exceptions import CloudAuthError
from smartenv.sources.base import CloudSource, parse_secret_payload

__all__ = ["GcpSource"]


class GcpSource(CloudSource):
    """Source backed by Google Secret Manager.

    Args:
        project_id: GCP project identifier. When omitted it is read from the
            ``GCP_PROJECT_ID`` environment variable.
        secret_id: Identifier of the secret to fetch. When omitted it is read
            from the ``GCP_SECRET_ID`` environment variable; when neither is
            available, every secret of the project is fetched (which requires
            the additional ``secretmanager.secrets.list`` permission).
        version: Version of the secret to read, ``"latest"`` by default.
        cache: When ``True``, the first successful fetch is cached and reused.
        cache_ttl: Positive finite cache lifetime in seconds, or ``None`` for
            indefinite caching. Expiration is checked when loading.

    Attributes:
        project_id: Resolved project identifier, or ``""`` when unset.
        secret_id: Resolved secret identifier, or ``""`` for "fetch all".
        version: Secret version to read.
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        secret_id: Optional[str] = None,
        version: str = "latest",
        cache: bool = True,
        cache_ttl: Optional[float] = None,
    ) -> None:
        super().__init__(cache=cache, cache_ttl=cache_ttl)
        self.project_id = project_id or os.environ.get("GCP_PROJECT_ID", "")
        self.secret_id = secret_id or os.environ.get("GCP_SECRET_ID", "")
        self.version = version
        self._client: Any = None

    @property
    def name(self) -> str:
        """Return the identifier of the source.

        Returns:
            Always ``"gcp_secrets"``.
        """
        return "gcp_secrets"

    def _fetch(self) -> Dict[str, str]:
        """Fetch the secret(s) from Google Secret Manager.

        Returns:
            A flat mapping of key to string value; a JSON object payload is
            flattened, any other payload is served as ``{"SECRET": ...}``. When
            several secrets are fetched, each payload is merged into the result.

        Raises:
            CloudAuthError: If the SDK is missing or the API call fails.
        """
        try:
            from google.cloud import secretmanager
        except ImportError as exc:
            raise CloudAuthError(
                "gcp",
                message=(
                    "the gcp_secrets source needs google-cloud-secret-manager, "
                    f"which is unavailable ({exc}); install it with: "
                    "pip install smartenv-config[gcp]"
                ),
            ) from exc
        if not self.project_id.strip():
            raise CloudAuthError(
                "gcp", message="provide project_id or set the GCP_PROJECT_ID environment variable"
            )
        if not self.version.strip():
            raise CloudAuthError("gcp", message="provide a non-empty secret version")
        try:
            if self._client is None:
                self._client = secretmanager.SecretManagerServiceClient()
            if self.secret_id:
                return self._fetch_one(self._client)
            return self._fetch_all(self._client)
        except CloudAuthError:
            raise
        except Exception as exc:
            raise CloudAuthError("gcp", reason=str(exc)) from exc

    def _fetch_one(self, client: Any) -> Dict[str, str]:
        """Fetch a single secret version.

        Args:
            client: Secret Manager client from the Google SDK.

        Returns:
            The parsed payload of the secret.

        Raises:
            CloudAuthError: If the API call fails.
        """
        resource = client.secret_path(self.project_id, self.secret_id)
        request = {"name": f"{resource}/versions/{self.version}"}
        try:
            response = client.access_secret_version(request=request)
        except Exception as exc:
            raise CloudAuthError("gcp", reason=str(exc)) from exc
        return parse_secret_payload(_payload_text(response))

    def _fetch_all(self, client: Any) -> Dict[str, str]:
        """Fetch every secret of the configured project.

        Args:
            client: Secret Manager client from the Google SDK.

        Returns:
            A mapping merging the parsed payloads of each secret. Plain
            payloads use their uppercased secret ID as the key.

        Raises:
            CloudAuthError: If listing or accessing a secret fails.
        """
        project = client.project_path(self.project_id)
        values: Dict[str, str] = {}
        try:
            listed: List[Any] = list(client.list_secrets(request={"parent": project}))
        except Exception as exc:
            raise CloudAuthError("gcp", reason=str(exc)) from exc
        for item in listed:
            secret_name = str(item.name).rsplit("/", 1)[-1]
            resource = client.secret_path(self.project_id, secret_name)
            request = {"name": f"{resource}/versions/{self.version}"}
            try:
                response = client.access_secret_version(request=request)
            except Exception as exc:
                raise CloudAuthError("gcp", reason=str(exc)) from exc
            values.update(
                parse_secret_payload(_payload_text(response), default_key=secret_name.upper())
            )
        return values


def _payload_text(response: Any) -> str:
    """Decode the payload of an ``access_secret_version`` response.

    Args:
        response: Response object from the Google SDK.

    Returns:
        The UTF-8 decoded payload.

    Raises:
        ValueError: If the payload is absent or not text or bytes.
        UnicodeDecodeError: If binary data is not valid UTF-8.
    """
    payload = getattr(response, "payload", None)
    if payload is None and isinstance(response, dict):
        payload = response.get("payload")
    if payload is None:
        raise ValueError("response is missing a secret payload")
    data = getattr(payload, "data", None)
    if data is None and isinstance(payload, dict):
        data = payload.get("data")
    if isinstance(data, str):
        return data
    if isinstance(data, (bytes, bytearray)):
        return data.decode("utf-8")
    raise ValueError("secret payload data must contain text or bytes")

"""AWS Secrets Manager source (requires the ``smartenv[aws]`` extra).

:class:`AwsSource` reads a single secret from AWS Secrets Manager and turns it
into a flat configuration mapping::

    from smartenv.sources import AwsSource

    source = AwsSource(secret_name="prod/myapp", region="eu-west-1")
    values = source.load()          # {"PORT": "8080", "HOST": "db.example"}

The secret payload may be a JSON object — flattened with the same rules as the
JSON source — or any plain string, which is served under the ``AWS_SECRET`` key.
Binary secrets must contain UTF-8 text; SDK bytes are decoded directly while
base64 string responses are decoded once before parsing the payload.
The module imports :mod:`boto3` lazily, so a plain ``import smartenv.sources``
never pulls it in.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, Optional

from smartenv.exceptions import CloudAuthError
from smartenv.sources.base import CloudSource, parse_secret_payload

__all__ = ["AwsSource"]

_DEFAULT_REGION = "us-east-1"


class AwsSource(CloudSource):
    """Source backed by a single AWS Secrets Manager secret.

    Args:
        secret_name: Name (or ARN) of the secret. When omitted it is read from
            the ``AWS_SECRET_NAME`` environment variable.
        region: AWS region of the secret. When omitted it is read from the
            ``AWS_REGION`` environment variable, falling back to
            ``"us-east-1"``.
        cache: When ``True``, the first successful fetch is cached and reused.
        cache_ttl: Positive finite cache lifetime in seconds, or ``None`` for
            indefinite caching. Expiration is checked when loading.

    Attributes:
        secret_name: Resolved secret name, or ``""`` when unset.
        region: Resolved region.
    """

    def __init__(
        self,
        secret_name: Optional[str] = None,
        region: Optional[str] = None,
        cache: bool = True,
        cache_ttl: Optional[float] = None,
    ) -> None:
        super().__init__(cache=cache, cache_ttl=cache_ttl)
        self.secret_name = secret_name or os.environ.get("AWS_SECRET_NAME", "")
        self.region = region or os.environ.get("AWS_REGION", _DEFAULT_REGION)
        self._client: Any = None

    @property
    def name(self) -> str:
        """Return the identifier of the source.

        Returns:
            Always ``"aws_secrets"``.
        """
        return "aws_secrets"

    def _fetch(self) -> Dict[str, str]:
        """Fetch the secret from AWS Secrets Manager.

        Returns:
            A flat mapping of key to string value; a JSON object payload is
            flattened, any other payload is served as ``{"AWS_SECRET": ...}``.

        Raises:
            CloudAuthError: If ``boto3`` is missing or the API call fails.
        """
        try:
            import boto3
        except ImportError as exc:
            raise CloudAuthError(
                "aws",
                message=(
                    "the aws_secrets source needs boto3, which is unavailable "
                    f"({exc}); install it with: pip install smartenv[aws]"
                ),
            ) from exc
        if not self.secret_name.strip():
            raise CloudAuthError(
                "aws", message="provide secret_name or set the AWS_SECRET_NAME environment variable"
            )
        try:
            if self._client is None:
                self._client = boto3.client("secretsmanager", region_name=self.region)
            response = self._client.get_secret_value(SecretId=self.secret_name)
            if "SecretString" in response:
                raw = response["SecretString"]
                if not isinstance(raw, str):
                    raise ValueError("SecretString must contain text")
            elif "SecretBinary" in response:
                binary = response["SecretBinary"]
                # Botocore already decodes wire base64 into bytes. Support an
                # encoded string response too, but never decode SDK bytes twice.
                if isinstance(binary, str):
                    binary = base64.b64decode(binary, validate=True)
                if not isinstance(binary, (bytes, bytearray)):
                    raise ValueError("SecretBinary must contain bytes or base64 text")
                raw = binary.decode("utf-8")
            else:
                raise ValueError("response contains neither SecretString nor SecretBinary")
            return parse_secret_payload(raw, default_key="AWS_SECRET")
        except Exception as exc:  # botocore exposes a deep, versioned hierarchy.
            raise CloudAuthError("aws", reason=str(exc)) from exc

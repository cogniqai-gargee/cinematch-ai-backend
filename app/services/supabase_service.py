from typing import Any

from app.config import Settings

try:
    from supabase import Client, create_client
except ImportError:  # pragma: no cover - handled in health response
    Client = Any
    create_client = None


class SupabaseService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client: Client | None = None
        self.initialization_error: str | None = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        if not self.settings.has_supabase_credentials:
            return

        if create_client is None:
            self.initialization_error = "supabase package is not installed"
            return

        try:
            self.client = create_client(
                self.settings.supabase_url,
                self.settings.supabase_anon_key,
            )
        except Exception as exc:
            self.initialization_error = str(exc)
            self.client = None

    def get_client(self) -> Any | None:
        return self.client

    def status(self) -> dict[str, bool | str | None]:
        connected, error = self.check_connection()

        return {
            "configured": self.settings.has_supabase_credentials,
            "client_initialized": self.client is not None,
            "connected": connected,
            "error": error,
        }

    def check_connection(self) -> tuple[bool, str | None]:
        if not self.settings.has_supabase_credentials:
            return False, "SUPABASE_URL and SUPABASE_ANON_KEY are required"

        if self.client is None:
            return False, self.initialization_error or "Supabase client is not initialized"

        return self._try_health_rpc()

    def _try_health_rpc(self) -> tuple[bool, str | None]:
        try:
            response = self.client.rpc("health_check").execute()
            data = getattr(response, "data", None)
            if data == "ok":
                return True, None

            return False, f"health_check returned {data!r}"
        except Exception as exc:
            return False, str(exc)

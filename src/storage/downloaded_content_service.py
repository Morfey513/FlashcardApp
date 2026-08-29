"""Explicit, server-checked lifecycle for downloaded content packages."""


class DownloadedContentService:
    def __init__(self, library, metadata_repository, body_repository):
        self.library = library
        self.metadata = metadata_repository
        self.bodies = body_repository

    def get_cached_state(self, kind, content_id, user_id="guest"):
        """Return presentation-safe local package state without cache paths or body data."""
        manifest = next((item.get("manifest", item) for item in self.library.list_downloaded(kind)
                         if str(item.get("content_id")) == str(content_id)), None)
        if manifest is None:
            return {"state": "not_downloaded", "downloaded": False}
        accessible = self.library.can_access(manifest, user_id)
        return {
            "state": manifest.get("cache_state", "available_offline") if accessible else "locked",
            "downloaded": True,
            "accessible": accessible,
            "package_projection": manifest.get("package_projection") or manifest.get("quiz_projection"),
            "media_state": manifest.get("media_state", "unavailable"),
            "downloaded_bytes": int(manifest.get("downloaded_bytes") or 0),
            "content_version": manifest.get("content_version"),
            "visibility": manifest.get("visibility"),
        }

    def check(self, kind, content_id, user_id="guest"):
        package_exists = self.library.has_package(kind, content_id)
        cached = self.library.get_downloaded(kind, content_id, user_id)
        inaccessible_state = "locked" if package_exists and cached is None else "not_downloaded"
        try:
            code, remote = self._metadata_result(kind, content_id)
            if code == 401:
                return self._authentication_failure(
                    kind, content_id, cached, inaccessible_state
                )
            if code in {403, 404}:
                if package_exists:
                    self.library.record_check(kind, content_id, "available_offline")
                    self._record_authoritative_absence(kind, content_id, user_id, code)
                    return {"state": "locked", "metadata": None}
                return {"state": "not_downloaded", "metadata": None}
            if code != 200:
                raise ConnectionError(f"metadata request failed ({code})")
            if remote.get("status") in {"banned", "deleted"}:
                if package_exists:
                    self.library.record_check(kind, content_id, "available_offline")
                    self.library.mark_globally_revoked(kind, content_id, remote["status"])
                return {
                    "state": "locked" if package_exists else "not_downloaded",
                    "metadata": remote,
                }
            if remote.get("offline_download_allowed") is False:
                return {"state": "download_unavailable", "metadata": remote}
            if kind == "quiz" and remote.get("package_projection") not in {None, "practice_only"}:
                return {"state": "download_unavailable", "metadata": remote}
        except Exception as exc:
            if cached:
                self.library.record_check(kind, content_id, "stale", error=exc)
            return {"state": "stale" if cached else inaccessible_state, "metadata": None}

        if package_exists:
            self.library.clear_global_revocation(kind, content_id)
            if remote.get("visibility") != "public":
                self.library.authorize_account(kind, content_id, user_id)
            else:
                self.library.clear_revocation(kind, content_id, user_id)
        cached = self.library.get_downloaded(kind, content_id, user_id)
        state = self.library.update_state(
            kind, content_id, remote.get("content_version"), user_id
        )
        if cached:
            if (
                cached.get("cache_state") == "update_failed"
                and cached.get("failed_server_version") == remote.get("content_version")
            ):
                state = "update_failed"
                self.library.record_retry_available(kind, content_id)
            else:
                self.library.record_check(kind, content_id, state)
        return {"state": state, "metadata": remote}

    def update(self, kind, content_id, user_id="guest"):
        package_exists = self.library.has_package(kind, content_id)
        cached = self.library.get_downloaded(kind, content_id, user_id)
        try:
            code, metadata = self._metadata_result(kind, content_id)
            if code == 401:
                return self._authentication_failure(
                    kind, content_id, cached,
                    "locked" if package_exists else "authentication_required",
                )
            if code in {403, 404}:
                if package_exists:
                    self.library.record_check(kind, content_id, "available_offline")
                    self._record_authoritative_absence(kind, content_id, user_id, code)
                return {"state": "locked" if package_exists else "not_downloaded"}
            if code != 200:
                raise ConnectionError(f"metadata request failed ({code})")
            if metadata.get("status") in {"banned", "deleted"}:
                if package_exists:
                    self.library.record_check(kind, content_id, "available_offline")
                    self.library.mark_globally_revoked(kind, content_id, metadata["status"])
                return {"state": "locked" if package_exists else "not_downloaded"}
            if metadata.get("offline_download_allowed") is False:
                return {"state": "download_unavailable", "metadata": metadata}
            if kind == "quiz" and metadata.get("package_projection") not in {None, "practice_only"}:
                return {"state": "download_unavailable", "metadata": metadata}
            if package_exists:
                self.library.clear_global_revocation(kind, content_id)
                if metadata.get("visibility") != "public":
                    self.library.authorize_account(kind, content_id, user_id)
                else:
                    self.library.clear_revocation(kind, content_id, user_id)
            cached = self.library.get_downloaded(kind, content_id, user_id)
            if cached:
                self.library.record_updating(kind, content_id)
            body_code, body = self._practice_result(kind, content_id)
            if body_code != 200 or not isinstance(body, dict):
                raise ConnectionError(f"body request failed ({body_code})")
            if metadata.get("content_version") != body.get("content_version"):
                raise ValueError("Content metadata and body revisions do not match")
            if (kind == "quiz" and metadata.get("package_projection") == "practice_only"
                    and body.get("package_type") != "offline_practice"):
                raise ValueError("Quiz practice package is missing its offline_practice marker")
            descriptor_code, descriptors = self._media_manifest_result(
                kind, content_id, metadata.get("content_version")
            )
            if descriptor_code not in {200, 404}:
                raise ConnectionError(f"media manifest request failed ({descriptor_code})")
            descriptors = descriptors if descriptor_code == 200 else []
            media = self._download_media(kind, content_id, metadata, descriptors)
            if not cached:
                # Initial downloads are allowed; restricted access is bound to this actor.
                allowed = list(metadata.get("allowed_account_ids") or [])
                if (metadata.get("visibility") != "public" or (
                    kind == "quiz" and metadata.get("package_projection") is None
                )) and user_id != "guest":
                    allowed.append(str(user_id))
                self.library.store_download(kind, content_id, body,
                    name=metadata["name"], visibility=metadata.get("visibility", "public"),
                    owner_id=metadata.get("owner_id"), allowed_account_ids=allowed,
                    content_version=metadata.get("content_version"), remote_updated_at=metadata.get("updated_at"),
                    offline_access=("content_visibility" if metadata.get("package_projection") == "practice_only"
                                    else "downloader_only" if kind == "quiz" else "content_visibility"),
                    quiz_projection=(metadata.get("package_projection") or
                                     ("editor_full" if kind == "quiz" else "study")), media=media)
            else:
                self.library.refresh_download(kind, content_id, metadata, body, user_id, media=media)
            return {"state": "synchronized", "metadata": metadata}
        except Exception as exc:
            if package_exists:
                self.library.record_update_failure(
                    kind, content_id, exc,
                    (metadata or {}).get("content_version")
                    if "metadata" in locals() and isinstance(metadata, dict) else None,
                )
            return {
                "state": "update_failed" if package_exists else "failed",
                "error": str(exc),
            }

    def _authentication_failure(self, kind, content_id, cached, inaccessible_state):
        """A missing/expired session is not evidence of content revocation."""
        if cached:
            error = "Authentication is required to check for updates"
            self.library.record_check(kind, content_id, "stale", error=error)
            return {"state": "stale", "metadata": None, "error": error}
        return {"state": inaccessible_state, "metadata": None}

    def _record_authoritative_absence(self, kind, content_id, user_id, code):
        """Persist only confirmed revocation; public 404 is content-global.

        403 is account authorization.  A public 404 is a lifecycle absence
        because the endpoint intentionally does not disclose restricted ids.
        Restricted packages retain their per-account authorization boundary.
        """
        manifest = next(
            (item.get("manifest", item) for item in self.library.list_downloaded(kind)
             if str(item.get("content_id")) == str(content_id)),
            None,
        )
        if code == 404 and manifest and manifest.get("visibility") == "public":
            self.library.mark_globally_revoked(kind, content_id, "not_found")
        else:
            self.library.mark_revoked(kind, content_id, user_id, "unauthorized")

    def _metadata_result(self, kind, content_id):
        if hasattr(self.metadata, "get_by_id_result"):
            code, value = self.metadata.get_by_id_result(kind, content_id)
            return code, value if code == 200 and isinstance(value, dict) else None
        value = self.metadata.get_by_id(kind, content_id)
        return (200, value) if isinstance(value, dict) else (404, None)

    def _body_result(self, kind, content_id):
        if kind == "quiz":
            if hasattr(self.bodies, "get_quiz_result"):
                return self.bodies.get_quiz_result(content_id)
            value = self.bodies.get_quiz(content_id)
        else:
            if hasattr(self.bodies, "get_flashcard_deck_result"):
                return self.bodies.get_flashcard_deck_result(content_id)
            value = self.bodies.get_flashcard_deck(content_id)
        return (200, value) if isinstance(value, dict) else (404, None)

    def _practice_result(self, kind, content_id):
        """Use the dedicated projection endpoint when supplied by the adapter."""
        method = getattr(self.bodies, "get_practice_package_result", None)
        if method:
            return method(kind, content_id)
        method = getattr(self.bodies, "get_practice_package", None)
        if method:
            value = method(kind, content_id)
            return (200, value) if isinstance(value, dict) else (404, None)
        return self._body_result(kind, content_id)

    def _media_manifest_result(self, kind, content_id, content_version):
        method = getattr(self.bodies, "get_media_manifest_result", None)
        if method:
            code, value = method(kind, content_id)
            return self._normalize_media_manifest(code, value, kind, content_id, content_version)
        method = getattr(self.bodies, "get_media_manifest", None)
        if method:
            value = method(kind, content_id)
            return self._normalize_media_manifest(200, value, kind, content_id, content_version)
        return 404, None

    @staticmethod
    def _normalize_media_manifest(code, value, kind, content_id, content_version):
        """Accept the API wrapper, but fail before byte retrieval on incoherence."""
        if code != 200:
            return code, None
        # Preserve a list-only adapter as a small backwards-compatible test seam.
        if isinstance(value, list):
            return 200, value
        if not isinstance(value, dict):
            raise ValueError("Media manifest is malformed")
        if str(value.get("content_id", "")) != str(content_id):
            raise ValueError("Media manifest belongs to different content")
        if value.get("content_kind") != kind:
            raise ValueError("Media manifest kind does not match content")
        if value.get("content_version") != content_version:
            raise ValueError("Media manifest revision does not match content")
        attachments = value.get("attachments")
        if not isinstance(attachments, list):
            raise ValueError("Media manifest attachments are malformed")
        return 200, attachments

    def _download_media(self, kind, content_id, metadata, descriptors):
        if not isinstance(descriptors, list):
            raise ValueError("Media manifest is malformed")
        result = []
        for descriptor in descriptors:
            if not isinstance(descriptor, dict):
                raise ValueError("Media descriptor is malformed")
            if str(descriptor.get("content_id", "")) != str(content_id):
                raise ValueError("Media descriptor belongs to different content")
            if descriptor.get("content_version") != metadata.get("content_version"):
                raise ValueError("Media descriptor revision does not match content")
            code, payload = self._media_bytes_result(
                kind, content_id, descriptor.get("media_id") or descriptor.get("id"),
                metadata.get("content_version"),
            )
            if code == 200:
                result.append({"descriptor": descriptor, "bytes": payload})
            elif descriptor.get("required", False):
                raise ConnectionError(f"required media request failed ({code})")
            else:
                result.append({"descriptor": descriptor, "bytes": None})
        return result

    def _media_bytes_result(self, kind, content_id, media_id, content_version):
        if not media_id:
            raise ValueError("Media descriptor is missing media_id")
        method = getattr(self.bodies, "get_media_bytes_result", None)
        if method:
            return method(kind, content_id, media_id, content_version)
        method = getattr(self.bodies, "get_media_bytes", None)
        if method:
            value = method(kind, content_id, media_id, content_version)
            return (200, value) if isinstance(value, (bytes, bytearray)) else (404, None)
        # No media adapter is a valid Phase 6A-compatible state: no descriptors
        # means no bytes must be retrieved.
        return 404, None

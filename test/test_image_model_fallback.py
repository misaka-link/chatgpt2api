from __future__ import annotations

import unittest
from unittest import mock

from services.config import config
from services.openai_backend_api import (
    ImagePollTimeoutError,
    ImageStreamHardTimeoutError,
    OpenAIBackendAPI,
)
from services.protocol import conversation


class ImageModelSlugTests(unittest.TestCase):
    def test_gpt_image_2_uses_configured_web_model_slug(self) -> None:
        with mock.patch.dict(
            config.data,
            {"image_web_model_slug": "gpt-5-5-thinking"},
            clear=False,
        ):
            backend = OpenAIBackendAPI()
            try:
                self.assertEqual(backend._image_model_slug("gpt-image-2"), "gpt-5-5-thinking")
                self.assertEqual(backend._image_model_slug("gpt-image-2", "gpt-5-3"), "gpt-5-3")
            finally:
                backend.close()

    def test_image_model_slug_candidates_respect_fallback_settings(self) -> None:
        with mock.patch.dict(
            config.data,
            {
                "image_web_model_slug": "gpt-5-5-thinking",
                "image_web_fallback_enabled": True,
                "image_web_fallback_model_slugs": ["gpt-5-5", "gpt-5-3", "gpt-5-5-thinking"],
            },
            clear=False,
        ):
            self.assertEqual(
                conversation.image_model_slug_candidates("gpt-image-2"),
                ["gpt-5-5-thinking", "gpt-5-5", "gpt-5-3"],
            )
            self.assertEqual(
                conversation.image_model_slug_candidates("codex-gpt-image-2"),
                ["codex-gpt-image-2"],
            )


class ImageModelFallbackTests(unittest.TestCase):
    def test_generate_single_image_falls_back_on_no_image_generated(self) -> None:
        request = conversation.ConversationRequest(prompt="cat", model="gpt-image-2")
        calls: list[str] = []
        success = [conversation.ImageOutput(kind="result", model="gpt-image-2", index=1, total=1, data=[{"url": "http://example.test/image.png"}])]

        def fake_attempt(_request, _index, _total, image_model_slug: str):
            calls.append(image_model_slug)
            if image_model_slug == "gpt-5-5-thinking":
                raise conversation.ImageGenerationError("upstream completed without generating images", code="no_image_generated")
            return success

        with (
            mock.patch.dict(
                config.data,
                {
                    "image_web_model_slug": "gpt-5-5-thinking",
                    "image_web_fallback_enabled": True,
                    "image_web_fallback_model_slugs": ["gpt-5-5", "gpt-5-3"],
                },
                clear=False,
            ),
            mock.patch.object(conversation, "_generate_single_image_with_model_slug", side_effect=fake_attempt),
        ):
            outputs = conversation._generate_single_image(request, 1, 1)

        self.assertEqual(calls, ["gpt-5-5-thinking", "gpt-5-5"])
        self.assertEqual(outputs, success)

    def test_generate_single_image_falls_back_on_timeout(self) -> None:
        request = conversation.ConversationRequest(prompt="cat", model="gpt-image-2")
        calls: list[str] = []
        success = [conversation.ImageOutput(kind="result", model="gpt-image-2", index=1, total=1, data=[{"url": "http://example.test/image.png"}])]

        def fake_attempt(_request, _index, _total, image_model_slug: str):
            calls.append(image_model_slug)
            if image_model_slug == "gpt-5-5-thinking":
                raise ImagePollTimeoutError("timeout")
            return success

        with (
            mock.patch.dict(
                config.data,
                {
                    "image_web_model_slug": "gpt-5-5-thinking",
                    "image_web_fallback_enabled": True,
                    "image_web_fallback_model_slugs": ["gpt-5-5"],
                },
                clear=False,
            ),
            mock.patch.object(conversation, "_generate_single_image_with_model_slug", side_effect=fake_attempt),
        ):
            outputs = conversation._generate_single_image(request, 1, 1)

        self.assertEqual(calls, ["gpt-5-5-thinking", "gpt-5-5"])
        self.assertEqual(outputs, success)

    def test_generate_single_image_does_not_fall_back_on_policy_error(self) -> None:
        request = conversation.ConversationRequest(prompt="cat", model="gpt-image-2")
        calls: list[str] = []

        def fake_attempt(_request, _index, _total, image_model_slug: str):
            calls.append(image_model_slug)
            raise conversation.ImageGenerationError(
                "blocked by policy",
                status_code=400,
                error_type="invalid_request_error",
                code="content_policy_violation",
            )

        with (
            mock.patch.dict(
                config.data,
                {
                    "image_web_model_slug": "gpt-5-5-thinking",
                    "image_web_fallback_enabled": True,
                    "image_web_fallback_model_slugs": ["gpt-5-5"],
                },
                clear=False,
            ),
            mock.patch.object(conversation, "_generate_single_image_with_model_slug", side_effect=fake_attempt),
        ):
            with self.assertRaises(conversation.ImageGenerationError) as ctx:
                conversation._generate_single_image(request, 1, 1)

        self.assertEqual(calls, ["gpt-5-5-thinking"])
        self.assertEqual(ctx.exception.code, "content_policy_violation")


class ImageStreamHardTimeoutTests(unittest.TestCase):
    def test_stream_picture_conversation_maps_hard_timeout_to_poll_timeout(self) -> None:
        backend = OpenAIBackendAPI(access_token="token")
        response = mock.Mock()

        with (
            mock.patch.dict(config.data, {"image_stream_hard_timeout_secs": 7}, clear=False),
            mock.patch.object(backend, "_upload_image", return_value={"asset_pointer": "file-service://x"}),
            mock.patch.object(backend, "_bootstrap"),
            mock.patch.object(backend, "_get_chat_requirements", return_value=mock.Mock()),
            mock.patch.object(backend, "_prepare_image_conversation", return_value="conduit"),
            mock.patch.object(backend, "_start_image_generation", return_value=response),
            mock.patch.object(
                backend,
                "_iter_sse_payloads_capped",
                side_effect=ImageStreamHardTimeoutError("hard timeout"),
            ) as capped,
        ):
            with self.assertRaises(ImagePollTimeoutError) as ctx:
                list(backend._stream_picture_conversation("prompt", "gpt-image-2", []))

        self.assertIn("SSE 流超时", str(ctx.exception))
        self.assertTrue(getattr(ctx.exception, "sse_hard_timeout", False))
        capped.assert_called_once_with(response, 7.0)
        backend.close()

    def test_iter_sse_payloads_capped_passes_through_payloads_before_close(self) -> None:
        backend = OpenAIBackendAPI(access_token="token")
        response = mock.Mock()

        with mock.patch(
            "services.openai_backend_api.iter_sse_payloads",
            return_value=iter(["data: first", "data: second"]),
        ):
            payloads = list(backend._iter_sse_payloads_capped(response, 1.0))

        self.assertEqual(payloads, ["data: first", "data: second"])
        response.close.assert_called()
        backend.close()


if __name__ == "__main__":
    unittest.main()

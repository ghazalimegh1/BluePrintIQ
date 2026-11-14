import importlib.util
import json
import sys
from contextlib import nullcontext
from tempfile import TemporaryDirectory
from types import ModuleType
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import ingestion, main
from backend.app.llm_interpreter import (
    InterpreterError,
    _call_chat_completions,
    interpret_with_provider,
)
from backend.app.gemini_vision import (
    DEFAULT_GEMINI_MODEL,
    GeminiVisionError,
    gemini_vl_configured,
    review_detection_semantics,
)
from backend.app.ocr import OCRLine, OCRUnavailable, paddle_ocr_is_available
from backend.app.routing import _raster_vision_answer, answer_question
from backend.app.scene import build_ifc_scene, build_raster_scene
from backend.app.schemas import (
    AskRequest,
    DocumentRecord,
    EvidenceRef,
    LLMProviderConfig,
    QuestionSpec,
    SceneResponse,
    SceneSelectionRequest,
    ToolResult,
)
from backend.app.tools import interpret_question
from backend.app.vision_models import (
    Detection,
    ImageTile,
    SourceImage,
    VisionInferenceError,
    _load_paddle_ocr,
    detect_objects,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "junction-dataset-preview" / "data"


class RealDocumentTests(unittest.TestCase):
    @unittest.skipUnless(
        importlib.util.find_spec("ifcopenshell"),
        "IfcOpenShell is not installed",
    )
    def test_ifc_scene_contains_native_global_id_mesh_and_explicit_provenance(self):
        relative = "data/ifc_models/bsc-esplanades_1807-ep-ar-v18.ifc"
        path = DATA / "ifc_models" / "bsc-esplanades_1807-ep-ar-v18.ifc"
        if not path.is_file():
            self.skipTest("The optional local dataset is not present.")
        scene = build_ifc_scene(
            "ifc-scene-test",
            relative,
            path,
            limit=2,
        )

        self.assertEqual(scene.status, "ready")
        self.assertEqual(scene.coordinate_system, "ifc_world_m")
        self.assertEqual(scene.unit, "m")
        self.assertEqual(len(scene.elements), 2)
        first = scene.elements[0]
        self.assertTrue(first.global_id)
        self.assertEqual(first.id, f"ifc:{first.global_id}")
        self.assertEqual(first.geometry_kind, "triangle_mesh")
        self.assertEqual(len(first.vertices) % 3, 0)
        self.assertEqual(len(first.indices) % 3, 0)
        self.assertEqual(first.provenance["status"], "explicit")
        self.assertEqual(first.provenance["source_tool"], "ifcopenshell.geom")
        self.assertEqual(first.provenance["source_document_id"], "ifc-scene-test")

    @unittest.skipUnless(
        importlib.util.find_spec("shapely"),
        "Shapely is not installed",
    )
    def test_raster_scene_uses_detected_regions_and_marks_extrusion_illustrative(self):
        from PIL import Image

        source = SourceImage(
            image=Image.new("RGB", (100, 100), color="white"),
            coordinate_system="image_pixels",
            native_width=100,
            native_height=100,
            page_number=1,
        )
        regions = [{
            "label": "wall",
            "score": 0.91,
            "bbox": [10, 10, 80, 80],
            "points": [[10, 10], [80, 10], [80, 80], [10, 80]],
        }]
        with patch(
            "backend.app.vision_models.load_source_image",
            return_value=source,
        ), patch(
            "backend.app.vision_models.segment_floorplan_cubicasa",
            return_value=regions,
        ):
            scene = build_raster_scene(
                "raster-scene-test",
                "upload/plan.png",
                Path("plan.png"),
                "png",
            )

        self.assertEqual(scene.status, "partial")
        self.assertEqual(scene.coordinate_system, "source_pixels_display_only")
        self.assertEqual(len(scene.elements), 1)
        wall = scene.elements[0]
        self.assertEqual(wall.entity_type, "wall")
        self.assertEqual(wall.provenance["status"], "detected")
        self.assertEqual(wall.provenance["confidence"], 0.91)
        self.assertIsNone(wall.properties["height"]["value"])
        self.assertEqual(wall.properties["display_height"]["status"], "illustrative")
        self.assertTrue(scene.warnings)

    @unittest.skipUnless(
        importlib.util.find_spec("shapely"),
        "Shapely is not installed",
    )
    def test_raster_scene_links_symbol_to_detected_room_evidence(self):
        from PIL import Image

        source = SourceImage(
            image=Image.new("RGB", (200, 120), color="white"),
            coordinate_system="image_pixels",
            native_width=200,
            native_height=120,
            page_number=1,
        )
        regions = [
            {
                "label": "bedroom",
                "score": 0.92,
                "bbox": [10, 10, 100, 100],
                "points": [[10, 10], [100, 10], [100, 100], [10, 100]],
            },
            {
                "label": "window",
                "score": 0.87,
                "bbox": [40, 40, 60, 60],
                "points": [[40, 40], [60, 40], [60, 60], [40, 60]],
            },
        ]
        with patch(
            "backend.app.vision_models.load_source_image",
            return_value=source,
        ), patch(
            "backend.app.vision_models.segment_floorplan_cubicasa",
            return_value=regions,
        ):
            scene = build_raster_scene(
                "raster-relationship-test",
                "upload/plan.png",
                Path("plan.png"),
                "png",
            )

        room, window = scene.elements
        self.assertEqual(room.entity_type, "room")
        self.assertEqual(window.entity_type, "window")
        self.assertEqual(window.properties["evidence_id"]["status"], "explicit")
        self.assertEqual(window.provenance["source_evidence_id"], window.properties["evidence_id"]["value"])
        self.assertEqual(window.relationships[0].relationship_type, "detected_inside_room")
        self.assertEqual(window.relationships[0].target_id, room.id)
        self.assertEqual(window.relationships[0].provenance_status, "detected")

    def test_scene_api_validates_pagination_and_forwards_requested_page(self):
        document = DocumentRecord(
            document_id="a" * 24,
            path="data/model.ifc",
            source="test",
            format="ifc",
            size_bytes=1,
        )
        scene = SceneResponse(
            document_id=document.document_id,
            source_path=document.path,
            source_format="ifc",
            status="ready",
            coordinate_system="ifc_world_m",
            unit="m",
        )
        with patch(
            "backend.app.main.ingestion.find_document",
            return_value=(document, Path("model.ifc")),
        ), patch("backend.app.main.build_scene", return_value=scene) as build:
            response = main.document_scene(document.document_id, offset=20, limit=30, page=2)

        self.assertEqual(response, scene)
        self.assertEqual(build.call_args.kwargs["offset"], 20)
        self.assertEqual(build.call_args.kwargs["limit"], 30)
        self.assertEqual(build.call_args.kwargs["page_number"], 2)

        with self.assertRaises(HTTPException) as raised:
            main.document_scene(document.document_id, offset=-1, limit=30, page=2)
        self.assertEqual(raised.exception.status_code, 422)

    def test_selected_scene_api_only_accepts_ifc_and_forwards_global_ids(self):
        document = DocumentRecord(
            document_id="b" * 24,
            path="data/model.ifc",
            source="test",
            format="ifc",
            size_bytes=1,
        )
        scene = SceneResponse(
            document_id=document.document_id,
            source_path=document.path,
            source_format="ifc",
            status="ready",
            coordinate_system="ifc_world_m",
            unit="m",
        )
        selected = SceneSelectionRequest(element_ids=["0ABCDEFGHIJKLMNOPQRSTU"])
        with patch(
            "backend.app.main.ingestion.find_document",
            return_value=(document, Path("model.ifc")),
        ), patch("backend.app.main.build_scene", return_value=scene) as build:
            response = main.selected_scene_elements(document.document_id, selected)

        self.assertEqual(response, scene)
        self.assertEqual(
            build.call_args.kwargs["selected_ids"],
            selected.element_ids,
        )

        image = document.model_copy(update={"format": "png"})
        with patch(
            "backend.app.main.ingestion.find_document",
            return_value=(image, Path("plan.png")),
        ):
            with self.assertRaises(HTTPException) as raised:
                main.selected_scene_elements(image.document_id, selected)
        self.assertEqual(raised.exception.status_code, 415)

    def test_paddle_ocr_requires_cached_weights_or_explicit_download_opt_in(self):
        fake_paddleocr = ModuleType("paddleocr")
        fake_paddleocr.PaddleOCR = MagicMock()
        try:
            with TemporaryDirectory() as directory:
                with patch.dict(
                    "os.environ",
                    {
                        "PADDLE_PDX_CACHE_HOME": directory,
                        "STOA_OCR_DOWNLOAD_MODELS": "false",
                    },
                    clear=False,
                ):
                    self.assertFalse(paddle_ocr_is_available())
                    with patch.dict(sys.modules, {"paddleocr": fake_paddleocr}):
                        _load_paddle_ocr.cache_clear()
                        with self.assertRaisesRegex(
                            VisionInferenceError, "PaddleOCR weights are missing"
                        ):
                            _load_paddle_ocr()
                        fake_paddleocr.PaddleOCR.assert_not_called()
        finally:
            _load_paddle_ocr.cache_clear()

    def test_paddle_ocr_uses_cpu_without_onednn_for_cached_weights(self):
        fake_paddleocr = ModuleType("paddleocr")

        class FakePaddleOCR:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_paddleocr.PaddleOCR = FakePaddleOCR
        try:
            with TemporaryDirectory() as directory:
                cache = Path(directory) / "official_models"
                for model_name in ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"):
                    model_dir = cache / model_name
                    model_dir.mkdir(parents=True)
                    (model_dir / "inference.json").touch()
                    (model_dir / "inference.pdiparams").touch()
                with patch.dict(
                    sys.modules, {"paddleocr": fake_paddleocr}
                ), patch.dict(
                    "os.environ",
                    {
                        "PADDLE_PDX_CACHE_HOME": directory,
                        "STOA_OCR_CPU_THREADS": "2",
                    },
                    clear=False,
                ):
                    _load_paddle_ocr.cache_clear()
                    ocr = _load_paddle_ocr()
                    self.assertEqual(ocr.kwargs["device"], "cpu")
                    self.assertFalse(ocr.kwargs["enable_mkldnn"])
                    self.assertEqual(ocr.kwargs["cpu_threads"], 2)
        finally:
            _load_paddle_ocr.cache_clear()

    def test_paddle_ocr_accepts_finnish_language_configuration(self):
        fake_paddleocr = ModuleType("paddleocr")

        class FakePaddleOCR:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_paddleocr.PaddleOCR = FakePaddleOCR
        try:
            with patch.dict(
                sys.modules, {"paddleocr": fake_paddleocr}
            ), patch.dict(
                "os.environ",
                {"STOA_OCR_LANGUAGE": "fi", "STOA_OCR_DOWNLOAD_MODELS": "true"},
                clear=False,
            ), patch(
                "backend.app.vision_models.paddle_ocr_models_cached",
                return_value=False,
            ):
                _load_paddle_ocr.cache_clear()
                ocr = _load_paddle_ocr()
                self.assertEqual(ocr.kwargs["lang"], "fi")
        finally:
            _load_paddle_ocr.cache_clear()

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is not installed")
    def test_raster_ocr_search_returns_pixel_aligned_text_evidence(self):
        from PIL import Image

        with TemporaryDirectory() as directory:
            path = Path(directory) / "drawing.png"
            Image.new("RGB", (100, 50), color="white").save(path)
            with patch(
                "backend.app.tools.extract_paddle_ocr_lines",
                return_value=[OCRLine("Door D1", 0.97, (10, 5, 50, 20))],
            ):
                result = answer_question(
                    "raster-ocr-test",
                    "upload/drawing.png",
                    path,
                    "png",
                    "Find the D1 label.",
                )

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.evidence[0].extracted_content, "Door D1")
        self.assertEqual(result.evidence[0].bbox, [10, 5, 50, 20])
        self.assertEqual(result.evidence[0].coordinate_system, "image_pixels")
        self.assertEqual(result.overlays[0].overlay_type, "text_region")
        self.assertEqual(result.overlays[0].source_tool, "local_ocr_text_search")
        self.assertIn("recognition errors", result.warnings[0])

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is not installed")
    def test_raster_ocr_without_local_model_abstains_explicitly(self):
        from PIL import Image

        with TemporaryDirectory() as directory:
            path = Path(directory) / "drawing.png"
            Image.new("RGB", (40, 20), color="white").save(path)
            with patch(
                "backend.app.tools.extract_paddle_ocr_lines",
                side_effect=OCRUnavailable("English OCR weights are missing."),
            ):
                result = answer_question(
                    "raster-ocr-unavailable-test",
                    "upload/drawing.png",
                    path,
                    "png",
                    "Find readable text on this drawing.",
                )

        self.assertEqual(result.status, "unable")
        self.assertIn("English OCR weights are missing.", result.trace[2].summary)
        self.assertFalse(result.evidence)

    @unittest.skipUnless(importlib.util.find_spec("pymupdf"), "PyMuPDF is not installed")
    def test_scanned_pdf_ocr_maps_rendered_pixels_to_pdf_points(self):
        import pymupdf

        with TemporaryDirectory() as directory:
            path = Path(directory) / "scanned.pdf"
            document = pymupdf.open()
            document.new_page(width=200, height=100)
            document.save(path)
            document.close()
            with patch(
                "backend.app.tools.extract_paddle_ocr_lines",
                return_value=[OCRLine("Door D1", 0.91, (17, 17, 34, 34))],
            ):
                result = answer_question(
                    "pdf-ocr-test",
                    "upload/scanned.pdf",
                    path,
                    "pdf",
                    "Find the D1 label.",
                    page_number=1,
                )

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.evidence[0].page, 1)
        self.assertEqual(result.evidence[0].coordinate_system, "pdf_points")
        self.assertEqual(len(result.evidence), 1)
        for actual, expected in zip(result.evidence[0].bbox, [10, 10, 20, 20]):
            self.assertAlmostEqual(actual, expected)
        self.assertTrue(any(step.tool_name == "local_ocr_text_search" for step in result.trace))

    @unittest.skipUnless(importlib.util.find_spec("ezdxf"), "ezdxf is not installed")
    def test_explicit_dxf_door_layer_count_returns_projected_geometry(self):
        import ezdxf

        with TemporaryDirectory() as directory:
            path = Path(directory) / "door-layer.dxf"
            document = ezdxf.new()
            document.layers.new("DOOR")
            document.modelspace().add_lwpolyline([(1, 1), (2, 1)], dxfattribs={"layer": "DOOR"})
            document.modelspace().add_arc(
                center=(1.5, 1), radius=0.5, start_angle=0, end_angle=180,
                dxfattribs={"layer": "DOOR"},
            )
            document.saveas(path)

            result = answer_question(
                "dxf-door-layer-test",
                "upload/door-layer.dxf",
                path,
                "dxf",
                "How many doors are shown?",
            )

        self.assertEqual(result.status, "supported")
        self.assertEqual(result.value, 1)
        self.assertIn("door geometries", result.answer)
        self.assertEqual(result.evidence[0].entity_type, "LWPOLYLINE:DOOR")
        self.assertEqual(result.overlays[0].overlay_type, "polyline")
        self.assertIn("rendered_points", result.evidence[0].geometry)

    @unittest.skipUnless(importlib.util.find_spec("ezdxf"), "ezdxf is not installed")
    def test_real_dxf_closed_room_areas_are_calculated_with_exclusions(self):
        relative = "data/swiss_dwellings/site52_bldg298_floor1183.dxf"
        path = DATA / "swiss_dwellings" / "site52_bldg298_floor1183.dxf"
        result = answer_question(
            "real-dxf-area-test",
            relative,
            path,
            "dxf",
            "What is the total area of the rooms in square meters?",
        )

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.unit, "m2")
        self.assertGreater(result.value, 0)
        self.assertTrue(result.warnings)
        self.assertIn("closed room polygon areas", result.calculation[0])
        self.assertEqual(len(result.evidence), len(result.overlays))
        self.assertAlmostEqual(
            result.value,
            sum(ref.geometry["area_m2"] for ref in result.evidence),
        )

    @unittest.skipUnless(importlib.util.find_spec("ezdxf"), "ezdxf is not installed")
    def test_dxf_block_count_has_rendered_evidence_location(self):
        import ezdxf

        with TemporaryDirectory() as directory:
            path = Path(directory) / "door-plan.dxf"
            document = ezdxf.new()
            block = document.blocks.new("DOOR_SINGLE")
            block.add_line((0, 0), (1, 0))
            document.modelspace().add_blockref("DOOR_SINGLE", (5, 7))
            document.saveas(path)

            result = answer_question(
                "dxf-count-test",
                "upload/door-plan.dxf",
                path,
                "dxf",
                "How many doors are shown?",
            )
            preview = ingestion.render_dxf_preview(path)

        self.assertEqual(result.status, "supported")
        self.assertEqual(result.value, 1)
        evidence = result.evidence[0]
        self.assertEqual(evidence.page, 1)
        self.assertEqual(evidence.geometry["point"], [5.0, 7.0])
        self.assertIn("rendered_point", evidence.geometry)
        overlay_point = result.overlays[0].geometry["point"]
        expected_point = preview.transform_point(5, 7)
        self.assertAlmostEqual(overlay_point[0], expected_point[0])
        self.assertAlmostEqual(overlay_point[1], expected_point[1])

    def test_svg_text_search_returns_native_anchor_evidence(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "plan.svg"
            path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="10 20 100 50">'
                '<text id="room-101" x="25" y="30">Room 101</text></svg>',
                encoding="utf-8",
            )
            result = answer_question(
                "svg-text-test",
                "upload/plan.svg",
                path,
                "svg",
                "Find the Room 101 label.",
            )

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.evidence[0].entity_type, "svg_text")
        self.assertEqual(result.evidence[0].geometry, {"point": [25.0, 30.0]})
        self.assertEqual(result.overlays[0].overlay_type, "point")
        self.assertEqual(result.overlays[0].coordinate_system, "svg_viewbox")

    def test_dwg_is_recognized_but_not_claimed_as_readable_without_converter(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "plan.dwg"
            path.write_bytes(b"not-a-dwg")
            capabilities, _, status = ingestion._capabilities(path)

        self.assertEqual(status, "limited")
        self.assertEqual(capabilities[0].capability_type, "dwg_conversion")
        self.assertFalse(capabilities[0].available)

    def test_selected_groq_model_uses_environment_and_calls_registered_tool(self):
        response = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "function": {
                            "name": "plan_document_question",
                            "arguments": json.dumps({
                                "operation": "count",
                                "entity_concepts": ["door"],
                                "recommended_tools": ["ifc_entity_count"],
                                "scope": None,
                                "output_unit": None,
                                "ambiguities": [],
                            }),
                        },
                    }],
                }
            }]
        }
        provider = LLMProviderConfig(provider="groq", model="chosen-groq-model")
        with patch.dict(
            "os.environ",
            {"GROQ_API_KEY": "test-key", "GROQ_MODEL": "env-selected-model"},
            clear=False,
        ):
            with patch("backend.app.llm_interpreter._call_chat_completions", return_value=response) as call:
                spec, source = interpret_with_provider(
                    "How many doors are in this model?",
                    provider,
                    allowed_tools=["ifc_entity_count"],
                )

        self.assertEqual(source, "groq:env-selected-model")
        self.assertEqual(spec.entity_concepts, ["door"])
        self.assertEqual(spec.recommended_tools, ["ifc_entity_count"])
        self.assertEqual(call.call_args.args[0].model, "env-selected-model")
        self.assertEqual(
            call.call_args.args[1]["tool_choice"]["function"]["name"],
            "plan_document_question",
        )

    def test_router_uses_groq_only_for_planning_and_local_ifc_evidence_for_answer(self):
        plan = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "function": {
                            "name": "plan_document_question",
                            "arguments": json.dumps({
                                "operation": "count",
                                "entity_concepts": ["door"],
                                "recommended_tools": ["ifc_entity_count"],
                                "scope": None,
                                "output_unit": None,
                                "ambiguities": [],
                            }),
                        }
                    }]
                }
            }]
        }
        tool_result = ToolResult(
            status="supported",
            value=1,
            evidence=[EvidenceRef(
                document_id="ifc-test",
                path="upload/model.ifc",
                entity_id="door-1",
                entity_type="IfcDoor",
                extraction_method="test",
                source_tool_version="test",
            )],
        )
        provider = LLMProviderConfig(provider="groq", model="chosen-groq-model")
        with patch.dict(
            "os.environ",
            {"GROQ_API_KEY": "test-key", "GROQ_MODEL": "env-selected-model"},
            clear=False,
        ):
            with patch(
                "backend.app.routing.available_tools",
                return_value=[{
                    "name": "ifc_entity_count",
                    "input_formats": ["ifc"],
                    "available": True,
                }],
            ):
                with patch(
                    "backend.app.routing.query_ifc_count",
                    return_value=tool_result,
                ):
                    with patch(
                        "backend.app.llm_interpreter._call_chat_completions",
                        return_value=plan,
                    ) as call:
                        result = answer_question(
                            "ifc-test",
                            "upload/model.ifc",
                            Path("unused.ifc"),
                            "ifc",
                            "How many doors are in this model?",
                            provider,
                        )

        self.assertEqual(result.status, "supported")
        self.assertEqual(result.value, 1)
        self.assertEqual(result.answer, "1 door")
        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(call.call_count, 1)

    def test_api_key_cannot_be_submitted_in_provider_request_config(self):
        with self.assertRaises(ValidationError):
            LLMProviderConfig(provider="groq", model="chosen-groq-model", api_key="not-allowed")

    def test_selected_groq_model_requires_backend_environment_key(self):
        provider = LLMProviderConfig(provider="groq", model="chosen-groq-model")
        with patch.dict("os.environ", {}, clear=False):
            __import__("os").environ.pop("GROQ_API_KEY", None)
            with self.assertRaisesRegex(InterpreterError, "GROQ_API_KEY"):
                interpret_with_provider("How many doors?", provider)

    def test_groq_sdk_retries_timeout_and_rate_limits_without_echoing_credentials(self):
        class FakeAPIError(Exception):
            pass

        class FakeRateLimitError(FakeAPIError):
            pass

        class FakeTimeoutError(FakeAPIError):
            pass

        provider = LLMProviderConfig(provider="groq", model="test-model")
        for error_type, message in (
            (FakeRateLimitError, "rate limit"),
            (FakeTimeoutError, "timed out"),
        ):
            with self.subTest(error_type=error_type.__name__):
                secret = "secret-that-must-not-appear"
                sdk = ModuleType("groq")
                sdk.APIConnectionError = FakeAPIError
                sdk.APIError = FakeAPIError
                sdk.APIStatusError = FakeAPIError
                sdk.APITimeoutError = FakeTimeoutError
                sdk.RateLimitError = FakeRateLimitError
                client_options = []

                class FakeCompletions:
                    def create(self, **kwargs):
                        raise error_type(secret)

                class FakeClient:
                    def __init__(self, *, api_key, timeout, max_retries):
                        client_options.append((api_key, timeout, max_retries))
                        self.chat = type("Chat", (), {
                            "completions": FakeCompletions(),
                        })()

                sdk.Groq = FakeClient
                with patch.dict(sys.modules, {"groq": sdk}):
                    with patch.dict("os.environ", {"GROQ_API_KEY": secret}, clear=False):
                        with self.assertRaisesRegex(InterpreterError, message) as caught:
                            _call_chat_completions(provider, {})

                self.assertNotIn(secret, str(caught.exception))
                self.assertEqual(client_options, [(secret, 30.0, 2)])

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is not installed")
    def test_gemini_semantic_review_uses_free_model_image_and_structured_schema(self):
        import base64
        from types import SimpleNamespace

        from google import genai
        from PIL import Image

        captured = {}
        output = {"matches": [{
            "candidate_id": "candidate-1",
            "matches_label": True,
            "note": "The opening symbol is consistent with a window.",
        }]}

        class FakeInteractions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(output_text=json.dumps(output))

        class FakeClient:
            def __init__(self, *, api_key, http_options):
                captured["api_key"] = api_key
                captured["http_options"] = http_options
                self.interactions = FakeInteractions()

        with patch.dict(
            "os.environ",
            {
                "GEMINI_API_KEY": "test-gemini-key",
                "GEMINI_MODEL": DEFAULT_GEMINI_MODEL,
            },
            clear=False,
        ):
            with patch.object(genai, "Client", FakeClient):
                result = review_detection_semantics(
                    Image.new("RGB", (80, 40), color="white"),
                    "Does this candidate look like a window?",
                    [{
                        "candidate_id": "candidate-1",
                        "label": "window",
                        "bbox_normalized": [0.1, 0.2, 0.5, 0.8],
                        "score": 0.91,
                    }],
                )

        self.assertEqual(result["model"], DEFAULT_GEMINI_MODEL)
        self.assertEqual(result["matches"], output["matches"])
        self.assertEqual(captured["model"], DEFAULT_GEMINI_MODEL)
        self.assertEqual(captured["api_key"], "test-gemini-key")
        self.assertEqual(captured["response_format"]["mime_type"], "application/json")
        self.assertEqual(captured["response_format"]["schema"]["required"], ["matches"])
        image_part = captured["input"][1]
        self.assertEqual(image_part["type"], "image")
        self.assertEqual(image_part["mime_type"], "image/jpeg")
        self.assertTrue(base64.b64decode(image_part["data"]).startswith(b"\xff\xd8"))
        self.assertIn("does this candidate", captured["input"][0]["text"].casefold())
        self.assertIn("candidate-1", captured["input"][0]["text"])

    def test_gemini_rejects_non_free_models_without_fallback(self):
        from PIL import Image

        with patch.dict(
            "os.environ",
            {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "gemini-4-carbon"},
            clear=False,
        ):
            self.assertFalse(gemini_vl_configured())
            with self.assertRaisesRegex(GeminiVisionError, "allowlisted free-tier model"):
                review_detection_semantics(
                    Image.new("RGB", (20, 20)),
                    "Review this candidate",
                    [{
                        "candidate_id": "candidate-1",
                        "label": "window",
                        "bbox_normalized": [0.1, 0.1, 0.9, 0.9],
                    }],
                )

    def test_gemini_rate_limit_is_explicit_and_never_echoes_credentials(self):
        from google import genai
        from PIL import Image

        secret = "gemini-secret-that-must-not-appear"

        class FakeAPIError(Exception):
            code = 429

        class FakeInteractions:
            def create(self, **kwargs):
                raise FakeAPIError(secret)

        class FakeClient:
            def __init__(self, *, api_key, http_options):
                self.interactions = FakeInteractions()

        with patch.dict(
            "os.environ",
            {"GEMINI_API_KEY": secret, "GEMINI_MODEL": DEFAULT_GEMINI_MODEL},
            clear=False,
        ):
            with patch.object(genai, "Client", FakeClient):
                with patch("google.genai.errors.APIError", FakeAPIError):
                    with self.assertRaisesRegex(GeminiVisionError, "rate limit or quota") as caught:
                        review_detection_semantics(
                            Image.new("RGB", (20, 20)),
                            "Review this candidate",
                            [{
                                "candidate_id": "candidate-1",
                                "label": "window",
                                "bbox_normalized": [0.1, 0.1, 0.9, 0.9],
                            }],
                        )

        self.assertNotIn(secret, str(caught.exception))

    def test_gemini_rejects_structured_responses_with_invented_candidate_ids(self):
        from types import SimpleNamespace

        from google import genai
        from PIL import Image

        class FakeInteractions:
            def create(self, **kwargs):
                return SimpleNamespace(output_text=json.dumps({
                    "matches": [{
                        "candidate_id": "invented",
                        "matches_label": True,
                        "note": "",
                    }],
                }))

        class FakeClient:
            def __init__(self, *, api_key, http_options):
                self.interactions = FakeInteractions()

        with patch.dict(
            "os.environ",
            {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": DEFAULT_GEMINI_MODEL},
            clear=False,
        ):
            with patch.object(genai, "Client", FakeClient):
                with self.assertRaisesRegex(GeminiVisionError, "invalid structured"):
                    review_detection_semantics(
                        Image.new("RGB", (20, 20)),
                        "Review this candidate",
                        [{
                            "candidate_id": "candidate-1",
                            "label": "window",
                            "bbox_normalized": [0.1, 0.1, 0.9, 0.9],
                        }],
                    )

    def test_gemini_review_cannot_change_local_detection_count(self):
        from PIL import Image

        from backend.app.vision_models import Detection, ImageTile, SourceImage

        image = Image.new("RGB", (100, 50), color="white")
        tile = ImageTile(image=image, x=0, y=0, index=0)
        detection = Detection(
            label="window",
            score=0.91,
            bbox=(10.0, 5.0, 30.0, 25.0),
            tile=tile,
            tile_bbox=(10.0, 5.0, 30.0, 25.0),
        )
        source = SourceImage(image, "image_pixels", 100, 50, 1)
        spec = QuestionSpec(
            original_question="How many windows are shown?",
            operation="count",
            entity_concepts=["window"],
        )

        with patch("backend.app.routing.load_source_image", return_value=source):
            with patch("backend.app.routing.detect_objects", return_value=[detection]):
                with patch(
                    "backend.app.routing.review_detection_semantics",
                    return_value={
                        "model": DEFAULT_GEMINI_MODEL,
                        "matches": [{
                            "candidate_id": "doc-dino-p1-0",
                            "matches_label": False,
                            "note": "The symbol is ambiguous.",
                        }],
                    },
                ):
                    result = _raster_vision_answer(
                        "doc",
                        "upload/drawing.png",
                        Path("unused.png"),
                        "png",
                        spec.original_question,
                        spec,
                        ["grounding_dino_detection", "gemini_vl_semantic_review"],
                        [],
                        page_number=1,
                        gemini_vl_consent=True,
                    )

        self.assertEqual(result.value, 1)
        self.assertEqual(result.status, "partial")
        self.assertIn("1 window detected", result.answer)
        self.assertTrue(any("Gemini semantic review" in warning for warning in result.warnings))

    def test_gemini_requires_explicit_request_consent_by_default(self):
        request = AskRequest(
            document_id="document-1234",
            question="Review the window symbol",
        )
        self.assertFalse(request.gemini_vl_consent)

    def test_raster_question_uses_local_detector_without_selected_provider(self):
        relative = "data/cubicasa5k/colorful-11397.png"
        path = DATA / "cubicasa5k" / "colorful-11397.png"
        detector_tool = {
            "name": "grounding_dino_detection",
            "input_formats": ["png"],
            "available": True,
        }
        with (
            patch("backend.app.routing.available_tools", return_value=[detector_tool]),
            patch("backend.app.routing.detect_objects", return_value=[]) as detect,
        ):
            result = answer_question(
                "raster-local-only-test",
                relative,
                path,
                "png",
                "How many windows are shown on this floor plan?",
            )

        self.assertEqual(result.status, "unable")
        self.assertIn("No objects were detected", result.answer)
        self.assertFalse(any(step.tool_name == "gemini_vl_semantic_review" for step in result.trace))
        self.assertTrue(any(step.tool_name == "grounding_dino_detection" for step in result.trace))
        detect.assert_called_once()

    def test_window_count_routes_to_cubicasa_and_returns_region_evidence(self):
        relative = "data/cubicasa5k/colorful-11397.png"
        path = DATA / "cubicasa5k" / "colorful-11397.png"
        source = SourceImage(
            image=__import__("PIL.Image", fromlist=["Image"]).new("RGB", (200, 120)),
            coordinate_system="image_pixels",
            native_width=200,
            native_height=120,
            page_number=1,
        )
        tools = [
            {
                "name": "grounding_dino_detection",
                "input_formats": ["png"],
                "available": True,
            },
            {
                "name": "cubicasa_floorplan_segmentation",
                "input_formats": ["png"],
                "available": True,
            },
        ]
        windows = [
            {
                "label": "window",
                "score": 0.88,
                "bbox": [10, 10, 30, 20],
                "points": [[10, 10], [30, 10], [30, 20], [10, 20]],
            },
            {
                "label": "window",
                "score": 0.79,
                "bbox": [80, 10, 100, 20],
                "points": [[80, 10], [100, 10], [100, 20], [80, 20]],
            },
            {
                "label": "door",
                "score": 0.91,
                "bbox": [50, 50, 70, 90],
                "points": [[50, 50], [70, 50], [70, 90], [50, 90]],
            },
        ]
        tile = ImageTile(image=source.image, x=0, y=0, index=0)
        detector_windows = [
            Detection("window", 0.84, (10.0, 10.0, 30.0, 20.0), tile, (10.0, 10.0, 30.0, 20.0)),
            Detection("window", 0.81, (80.0, 10.0, 100.0, 20.0), tile, (80.0, 10.0, 100.0, 20.0)),
        ]
        with (
            patch("backend.app.routing.available_tools", return_value=tools),
            patch("backend.app.routing.load_source_image", return_value=source),
            patch("backend.app.routing.segment_floorplan_cubicasa", return_value=windows) as segment,
            patch("backend.app.routing.detect_objects", return_value=detector_windows) as detect,
        ):
            result = answer_question(
                "raster-window-count-test",
                relative,
                path,
                "png",
                "How many windows are shown on this floor plan?",
            )

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.value, 2)
        self.assertEqual(len(result.evidence), 2)
        self.assertEqual(len(result.overlays), 2)
        self.assertEqual(result.question_spec.entity_concepts, ["window"])
        self.assertTrue(any(step.tool_name == "cubicasa_floorplan_segmentation" for step in result.trace))
        self.assertTrue(any("Cross-check" in warning for warning in result.warnings))
        detect.assert_called_once()

    def test_room_count_routes_to_cubicasa_room_labels(self):
        from PIL import Image

        regions = [
            {"label": "bedroom", "score": 0.95, "bbox": [0, 0, 10, 10], "points": [[0, 0], [10, 0], [10, 10]]},
            {"label": "kitchen", "score": 0.92, "bbox": [12, 0, 20, 10], "points": [[12, 0], [20, 0], [20, 10]]},
            {"label": "wall", "score": 0.99, "bbox": [0, 12, 20, 14], "points": [[0, 12], [20, 12], [20, 14]]},
        ]
        with patch("backend.app.routing.segment_floorplan_cubicasa", return_value=regions) as segment, patch(
            "backend.app.routing.load_source_image",
            return_value=SourceImage(
                image=Image.new("RGB", (20, 20), "white"),
                coordinate_system="image_pixels",
                native_width=20,
                native_height=20,
                page_number=1,
            ),
        ):
            result = answer_question(
                "raster-room-count-test",
                "data/cubicasa5k/colorful-11397.png",
                DATA / "cubicasa5k" / "colorful-11397.png",
                "png",
                "How many rooms are shown?",
            )
        self.assertEqual(result.value, 2)
        self.assertIn("2 rooms", result.answer)
        self.assertEqual(len(result.evidence), 2)
        segment.assert_called_once()

    def test_backend_key_alone_never_sends_image_without_ui_provider_selection(self):
        relative = "data/cubicasa5k/colorful-11397.png"
        path = DATA / "cubicasa5k" / "colorful-11397.png"
        tools = [
            {"name": "grounding_dino_detection", "input_formats": ["png"], "available": True},
            {"name": "gemini_vl_semantic_review", "input_formats": ["png"], "available": True},
        ]
        with patch.dict(
            "os.environ",
            {"GROQ_API_KEY": "test-key", "GEMINI_API_KEY": "test-key"},
            clear=False,
        ):
            with (
                patch("backend.app.routing.available_tools", return_value=tools),
                patch("backend.app.routing.detect_objects", return_value=[]),
                patch("backend.app.gemini_vision.review_detection_semantics") as call,
            ):
                result = answer_question(
                    "raster-no-consent-test",
                    relative,
                    path,
                    "png",
                    "Count the doors.",
                )

        self.assertEqual(result.status, "unable")
        call.assert_not_called()

    def test_uploaded_document_lookup_does_not_rescan_dataset(self):
        with TemporaryDirectory() as directory:
            upload_root = Path(directory)
            path = upload_root / "sample.svg"
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
            document_id = ingestion._doc_id("upload/sample.svg")
            with patch.object(ingestion, "UPLOAD_ROOT", upload_root):
                with patch.object(ingestion, "list_documents", side_effect=AssertionError("dataset scan")):
                    document, resolved_path = ingestion.find_document(document_id)

        self.assertEqual(document.source, "uploaded")
        self.assertEqual(document.path, "upload/sample.svg")
        self.assertEqual(resolved_path, path)

    def test_document_catalog_defers_expensive_capability_inspection(self):
        with TemporaryDirectory() as directory:
            dataset_root = Path(directory)
            data_root = dataset_root / "data"
            source_root = data_root / "fixtures"
            source_root.mkdir(parents=True)
            (source_root / "drawing.png").write_bytes(b"not inspected during cataloging")
            with (
                patch.object(ingestion, "DATASET_ROOT", dataset_root),
                patch.object(ingestion, "DATA_ROOT", data_root),
                patch.object(ingestion, "UPLOAD_ROOT", dataset_root / "uploads"),
                patch.object(
                    ingestion,
                    "_capabilities",
                    side_effect=AssertionError("catalog listing must defer inspection"),
                ),
            ):
                ingestion.list_documents.cache_clear()
                try:
                    documents = ingestion.list_documents()
                finally:
                    ingestion.list_documents.cache_clear()

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].ingestion_status, "uninspected")
        self.assertEqual(documents[0].capabilities, [])

    def test_ifc_details_use_companion_document_preview_format(self):
        ifc = DocumentRecord(
            document_id="ifc-document",
            path="data/ifc_models/model.ifc",
            source="ifc_models",
            format="ifc",
            size_bytes=1,
            companion_document_id="plan-document",
        )
        plan = DocumentRecord(
            document_id="plan-document",
            path="data/ifc_models/model_plan.pdf",
            source="ifc_models",
            format="pdf",
            size_bytes=1,
        )
        path = Path("model.ifc")
        with (
            patch.object(main.ingestion, "find_document", return_value=(ifc, path)),
            patch.object(main.ingestion, "build_document_record", return_value=ifc),
            patch.object(main.ingestion, "list_documents", return_value=[ifc, plan]),
        ):
            details = main.document_details("ifc-document")

        self.assertEqual(details["preview_document_id"], "plan-document")
        self.assertEqual(details["preview_format"], "pdf")

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is not installed")
    def test_grounding_dino_receives_flattened_text_prompts(self):
        from PIL import Image

        class Batch(dict):
            input_ids = ["test-tokens"]

            def __init__(self):
                super().__init__(input_ids=self.input_ids)

            def to(self, _device):
                return self

        processor = MagicMock(return_value=Batch())
        processor.post_process_grounded_object_detection.return_value = [
            {"boxes": [], "scores": [], "text_labels": []}
        ]
        model = MagicMock()
        model.device = "cpu"
        torch = MagicMock()
        torch.inference_mode.return_value = nullcontext()
        source = SourceImage(
            image=Image.new("RGB", (32, 32), "white"),
            coordinate_system="image_pixels",
            native_width=32,
            native_height=32,
            page_number=1,
        )

        with patch(
            "backend.app.vision_models._load_grounding_dino",
            return_value=(torch, processor, model),
        ):
            detections = detect_objects(source, ["window", "door"], threshold=0.35)

        self.assertEqual(detections, [])
        self.assertEqual(processor.call_args.kwargs["text"], "a window. a door.")

    @unittest.skipUnless(importlib.util.find_spec("ifcopenshell"), "IfcOpenShell is not installed")
    def test_scoped_ifc_count_has_typed_entity_evidence(self):
        relative = "data/ifc_models/bsc-esplanades_1807-ep-ar-v18.ifc"
        path = DATA / "ifc_models" / "bsc-esplanades_1807-ep-ar-v18.ifc"
        result = answer_question(
            "real-ifc-test",
            relative,
            path,
            "ifc",
            "How many doors are shown on the floor plan of '1.korrus'?",
        )
        self.assertEqual(result.status, "supported")
        self.assertGreater(result.value, 0)

    @unittest.skipUnless(importlib.util.find_spec("ifcopenshell"), "IfcOpenShell is not installed")
    def test_unscoped_ifc_count_explains_multi_storey_context(self):
        relative = "data/ifc_models/bsc-esplanades_1807-ep-ar-v18.ifc"
        path = DATA / "ifc_models" / "bsc-esplanades_1807-ep-ar-v18.ifc"
        result = answer_question(
            "real-ifc-multistorey-test",
            relative,
            path,
            "ifc",
            "How many doors are in this model?",
        )
        self.assertEqual(result.status, "partial")
        self.assertIn("across 5 storeys", result.answer)
        self.assertTrue(any("companion drawing may show only one level" in warning for warning in result.warnings))
        self.assertEqual(result.value, len(result.evidence))
        self.assertTrue(all(ref.entity_type == "IfcDoor" for ref in result.evidence))
        self.assertTrue(all(ref.entity_id for ref in result.evidence))
        self.assertEqual(result.evidence[0].coordinate_system, "ifc_model_coordinates")

    @unittest.skipUnless(importlib.util.find_spec("ifcopenshell"), "IfcOpenShell is not installed")
    def test_ifc_floor_question_counts_building_storeys(self):
        relative = "data/ifc_models/bsc-esplanades_1807-ep-ar-v18.ifc"
        path = DATA / "ifc_models" / "bsc-esplanades_1807-ep-ar-v18.ifc"
        result = answer_question(
            "real-ifc-storey-test",
            relative,
            path,
            "ifc",
            "How many floors does this model have?",
        )
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.value, 5)
        self.assertIn("5 storey", result.answer)
        self.assertEqual(result.question_spec.entity_concepts, ["storey"])
        self.assertTrue(all(ref.entity_type == "IfcBuildingStorey" for ref in result.evidence))

    @unittest.skipUnless(importlib.util.find_spec("pymupdf"), "PyMuPDF is not installed")
    def test_pdf_search_returns_real_page_box_and_overlay(self):
        relative = "data/opening_design/Sports_Complex/Sheets - Current Set/A-801 - Door and Finish Schedules & Wall Types.pdf"
        path = DATA / "opening_design" / "Sports_Complex" / "Sheets - Current Set" / "A-801 - Door and Finish Schedules & Wall Types.pdf"
        result = answer_question(
            "real-pdf-test",
            relative,
            path,
            "pdf",
            "Find the room schedule and show its text evidence.",
        )
        self.assertEqual(result.status, "partial")
        self.assertTrue(result.evidence)
        first = result.evidence[0]
        self.assertEqual(first.page, 1)
        self.assertEqual(first.coordinate_system, "pdf_points")
        self.assertEqual(len(first.bbox), 4)
        self.assertTrue(any(overlay.overlay_type == "text_region" for overlay in result.overlays))
        self.assertIn("text evidence", result.warnings[0])

    def test_raster_count_abstains_without_visual_model(self):
        relative = "data/cubicasa5k/colorful-11397.png"
        path = DATA / "cubicasa5k" / "colorful-11397.png"
        with patch("backend.app.routing.available_tools", return_value=[]):
            result = answer_question(
                "real-raster-test",
                relative,
                path,
                "png",
                "How many windows are shown on this floor plan?",
            )
        self.assertEqual(result.status, "unable")
        self.assertIn("No compatible local detection", result.answer)
        self.assertFalse(result.evidence)

    def test_question_interpreter_uses_only_configured_provider_or_fallback(self):
        with patch.dict("os.environ", {}, clear=False):
            for name in ("STOA_LLM_API_URL", "GROQ_API_KEY", "GROQ_MODEL"):
                __import__("os").environ.pop(name, None)
            spec, source = interpret_with_provider("How many doors are in this model?")
        self.assertEqual(source, "deterministic")
        self.assertEqual(spec.operation, "count")
        self.assertEqual(spec.entity_concepts, ["door"])

    def test_question_interpreter_does_not_claim_unregistered_entities(self):
        spec = interpret_question("How many trees are shown?")
        self.assertEqual(spec.operation, "count")
        self.assertEqual(spec.entity_concepts, [])

    def test_question_interpreter_corrects_conservative_entity_typos(self):
        spec = interpret_question("How many windoms are shown on this floor plan?")
        self.assertEqual(spec.operation, "count")
        self.assertEqual(spec.entity_concepts, ["window"])
        self.assertEqual(spec.corrections, ["windoms → windows"])

    def test_question_interpreter_supports_finnish_floor_and_window_phrasing(self):
        floors = interpret_question("Kuinka monta kerrosta tässä mallissa on?")
        windows = interpret_question("Kuinka monta ikkunaa pohjapiirustuksessa on?")
        self.assertEqual(floors.operation, "count")
        self.assertEqual(floors.entity_concepts, ["storey"])
        self.assertEqual(windows.operation, "count")
        self.assertEqual(windows.entity_concepts, ["window"])

    def test_question_interpreter_supports_accented_finnish_count_and_correction(self):
        count_spec = interpret_question("Mikä on ovien lukumäärä?")
        self.assertEqual(count_spec.operation, "count")
        self.assertEqual(count_spec.entity_concepts, ["door"])

        typo_spec = interpret_question("How many windoms are there?")
        self.assertEqual(typo_spec.operation, "count")
        self.assertEqual(typo_spec.entity_concepts, ["window"])
        self.assertTrue(typo_spec.corrections)


if __name__ == "__main__":
    unittest.main()

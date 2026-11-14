import importlib.util
import unittest

from PIL import Image, ImageDraw

from backend.app.classical_cv import analyze_plan_image


@unittest.skipUnless(
    importlib.util.find_spec("cv2") and importlib.util.find_spec("numpy"),
    "OpenCV and NumPy are optional classical-CV dependencies",
)
class ClassicalCVTests(unittest.TestCase):
    def test_extracts_lines_and_components_without_semantic_labels(self):
        image = Image.new("RGB", (240, 180), "white")
        draw = ImageDraw.Draw(image)
        draw.line((20, 30, 220, 30), fill="black", width=4)
        draw.line((20, 30, 20, 150), fill="black", width=4)
        draw.rectangle((80, 70, 140, 120), outline="black", width=3)

        result = analyze_plan_image(image)

        self.assertTrue(result["lines"])
        self.assertTrue(result["components"])
        self.assertIn("edge_density", result)
        self.assertNotIn("door_count", result)
        self.assertNotIn("room_count", result)


if __name__ == "__main__":
    unittest.main()

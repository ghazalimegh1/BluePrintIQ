import unittest

from backend.app.tools import interpret_question


class BenchmarkQuestionTaxonomyTests(unittest.TestCase):
    def test_raster_fixture_and_room_program_classes_are_distinct(self):
        spec = interpret_question(
            "How many toilet bowls, sinks, showers, bathtubs, bedrooms, kitchens, "
            "bathrooms, separate WC rooms, saunas and balconies are shown?"
        )
        self.assertEqual(spec.question_type, "count")
        self.assertEqual(spec.intent, "count")
        self.assertIn("toilet", spec.entity_concepts)
        self.assertIn("sink", spec.entity_concepts)
        self.assertIn("shower", spec.entity_concepts)
        self.assertIn("bathtub", spec.entity_concepts)
        self.assertIn("bedroom", spec.entity_concepts)
        self.assertIn("separate wc", spec.entity_concepts)
        self.assertNotIn("sanitary fixture", spec.entity_concepts)

    def test_benchmark_measurement_types(self):
        self.assertEqual(
            interpret_question("What is the net floor area of the room in m2?").question_type,
            "area",
        )
        self.assertEqual(
            interpret_question("What is the total net volume of all slabs in m3?").question_type,
            "volume",
        )
        self.assertEqual(
            interpret_question("What is the total length of all walls in metres?").question_type,
            "length",
        )

    def test_ifc_summary_and_property_questions_are_text(self):
        summary = interpret_question(
            "What are the number of levels, building footprint area, total floor area, "
            "and total number of rooms/spaces?"
        )
        self.assertEqual(summary.question_type, "text")
        self.assertEqual(summary.intent, "aggregate")

        property_question = interpret_question(
            "Which two doors have the greatest widths in the building?"
        )
        self.assertEqual(property_question.question_type, "text")
        self.assertEqual(property_question.intent, "compare")


if __name__ == "__main__":
    unittest.main()

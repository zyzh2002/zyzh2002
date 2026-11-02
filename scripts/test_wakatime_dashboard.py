import unittest
from xml.etree import ElementTree as ET
from wakatime_dashboard import collect, svg, compact

class Tests(unittest.TestCase):
    def test_xml(self):
        for mode in ("light","dark"):
            s=svg(mode,collect(None,None))
            self.assertEqual(ET.fromstring(s).attrib["viewBox"],"0 0 1200 716")
            self.assertNotIn('<rect x="0" y="0" width="1200"',s)
            self.assertIn("N/A",s)
    def test_data(self):
        stats={"total_seconds":7200,"daily_average":1000,"languages":[{"name":"Other","total_seconds":5000},{"name":"Python","total_seconds":2200}]}
        days=[{"grand_total":{"total_seconds":7200,"ai_input_tokens":200,
          "ai_output_tokens":100,"ai_model_breakdown":[{"name":"GPT & Claude","input_tokens":200,"output_tokens":100,"cached_input_tokens":20}]}}]
        d=collect(stats,days)
        self.assertEqual(d["top"],"Python")
        self.assertEqual(d["days"],"1/7")
        self.assertEqual(d["tokens"],(320,200,100,20))
        self.assertIn("GPT &amp; Claude",svg("dark",d))
    def test_compact(self):
        self.assertEqual(compact(428000),"428K")

if __name__=="__main__":unittest.main()

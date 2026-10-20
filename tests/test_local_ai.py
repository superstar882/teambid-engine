"""Guard tests (always run) and live Ollama tests (run only when Ollama is up with the models installed)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from teambid import llm, resume_parse as rp, tailor  # noqa: E402
from tests import fixtures  # noqa: E402

DOCX, _ = fixtures.make()
DRAFT = """Hi Acme team,

I'm applying for the Frontend Engineer role at Acme. Your post asks for React, TypeScript and CSS, which is the work I do.

At Brightline Analytics I work as a Frontend Engineer. I rebuilt the reporting dashboard in React and TypeScript, cutting load time from 6 s to 1.8 s for 40,000 users.

At Pixelworks Studio I worked as a Junior Web Developer. I shipped 25+ marketing sites in Next.js and Vue.js with Jest and Cypress tests.

Happy to walk you through the work at Brightline Analytics anytime.

Maya Chen"""


class Guard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = rp.parse_file(DOCX)

    def test_clean_rewrite_passes(self):
        ok = DRAFT.replace("which is the work I do", "and that's my daily work")
        self.assertEqual(llm.guard(ok, DRAFT, self.p, "Acme"), [])

    def test_invented_facts_rejected(self):
        bad = DRAFT.replace("40,000 users", "90,000 users").replace("Jest and Cypress", "Jest, Cypress and Kubernetes")
        bad = bad.replace("which is the work I do", "and I leverage it daily")
        problems = " ".join(llm.guard(bad, DRAFT, self.p, "Acme"))
        self.assertIn("90,000", problems)
        self.assertIn("Kubernetes", problems)
        self.assertIn("leverage", problems)

    def test_dropped_company_rejected(self):
        self.assertTrue(any("company" in x for x in llm.guard(DRAFT.replace("Acme", "your company"), DRAFT, self.p, "Acme")))


def _ollama():
    from teambid import local_ai
    was, local_ai.DISABLED = local_ai.DISABLED, False
    local_ai._status.update(t=0, models=None)
    ok = local_ai.embed_available()
    local_ai.DISABLED = was
    local_ai._status.update(t=0, models=None)
    return ok


@unittest.skipUnless(_ollama(), "Ollama with nomic-embed-text is not running")
class LiveOllama(unittest.TestCase):
    def setUp(self):
        from teambid import local_ai
        self._was, local_ai.DISABLED = local_ai.DISABLED, False
        local_ai._status.update(t=0, models=None)

    def tearDown(self):
        from teambid import local_ai
        local_ai.DISABLED = self._was

    def test_semantic_ranking_prefers_meaning(self):
        from teambid import local_ai
        sims = local_ai.similarities("Improve web performance and page load speed for a large React app",
                                     ["Rebuilt the reporting dashboard, cutting load time from 6 s to 1.8 s for 40,000 users.",
                                      "Raised accessibility scores by fixing WCAG issues across checkout."])
        self.assertGreater(sims[0], sims[1])

    def test_tailoring_uses_meaning(self):
        p = rp.parse_file(DOCX)
        jd = tailor.analyze_jd("Requirements\n- Make our React pages load faster\n- Performance budgets", "Frontend Engineer", "Acme")
        spec = tailor.build_resume(p, jd)
        self.assertEqual(spec["ranking"], "keywords + meaning (local AI)")
        self.assertIn("load time", spec["roles"][0]["bullets"][0])

    @unittest.skipUnless(os.environ.get("TEAMBID_TEST_CHAT") == "1", "set TEAMBID_TEST_CHAT=1 to run the slow local-chat test")
    def test_local_polish_is_guarded(self):
        p = rp.parse_file(DOCX)
        text, note = llm.polish_letter(DRAFT, p, "Frontend Engineer, React, TypeScript", "Acme", prefer="local")
        self.assertTrue(note.startswith("polished") or "rejected" in note, note)
        if note.startswith("polished"):
            self.assertEqual(llm.guard(text, DRAFT, p, "Acme"), [])


if __name__ == "__main__":
    unittest.main()

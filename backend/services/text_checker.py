"""NLP engine of the Multimodal Compliance Inspector (text side).

Checks: terminology, tone/voice, claim verification against RAG evidence, required disclaimers,
PII (privacy shield), readability. Every issue carries a character span, a severity, an optional
auto-fix suggestion and a citation (guideline quote retrieved from the knowledge base).
"""
import math
import re

from backend.services import rag

SEV_WEIGHT = {"critical": 20, "high": 12, "medium": 6, "minor": 2}

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{4}|[6-9]\d{4}[\s-]?\d{5})(?!\d)")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)")
ACRONYM_OK = {"FAQ", "PDF", "WCAG", "USA", "HTML", "CSS", "NASA", "ESG", "CEO", "FSC", "OECD", "LED", "USB", "API", "URL", "SMS", "RSVP"}

SOFTEN = [  # (pattern, replacement) used to tone down an unsupported claim sentence
    (r"\b100%\s+", ""), (r"\bguaranteed\b", "designed"), (r"\bguarantees?\b", "aims to deliver"),
    (r"\bthe best\b", "a great"), (r"\bbest\b", "great"), (r"#1\b", "a leading"), (r"\bnumber one\b", "a leading"),
    (r"\bclinically proven\b", "designed"), (r"\bzero[- ]waste\b", "low-waste"), (r"\bcarbon[- ]neutral\b", "lower-carbon"),
    (r"\beco[- ]friendly\b", "thoughtfully made"), (r"\balways\b", "often"), (r"\bnever fails?\b", "is built to last"),
]


def _case(src, repl):
    if len(src) > 1 and src.isupper():
        return repl.upper()
    if src[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


def _excerpt(text, s, e, pad=45):
    a, b = max(0, s - pad), min(len(text), e + pad)
    return ("…" if a else "") + text[a:b].replace("\n", " ") + ("…" if b < len(text) else "")


def _sentences(text):
    return [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"[^.!?\n]+[.!?]*", text) if m.group(0).strip()]


def _best_sentence(chunk, query):
    """Quote only the guideline sentences most relevant to the rule (keeps citations short and precise)."""
    sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+", chunk) if x.strip()]
    q = rag.content_words(query)
    ranked = sorted(range(len(sents)), key=lambda i: -len(q & rag.content_words(sents[i])))
    keep = sorted(ranked[:2])
    return " ".join(sents[i] for i in keep)[:320] or chunk[:320]


class Checker:
    def __init__(self, rules, text):
        self.rules, self.text, self.issues, self.verified = [r for r in rules if r["active"]], text, [], []
        self._cites = {}

    # ------------------------------------------------------------------ helpers
    def cite(self, rule):
        if rule["key"] not in self._cites:
            hits = rag.search(f'{rule["name"]} {rule["description"]}', k=1)
            self._cites[rule["key"]] = {
                "source": rule["source"] or "Brand rule", "doc_title": hits[0]["doc_title"] if hits else None,
                "quote": _best_sentence(hits[0]["text"], rule["description"] + " " + rule["name"]) if hits else rule["description"],
                "score": hits[0]["score"] if hits else None,
            }
        return self._cites[rule["key"]]

    def add(self, rule, s, e, message, suggestion=None, severity=None, citation=None):
        self.issues.append({
            "category": rule["category"], "rule_key": rule["key"], "severity": severity or rule["severity"],
            "message": message, "start": s, "end": e, "match": self.text[s:e], "excerpt": _excerpt(self.text, s, e),
            "suggestion": suggestion, "auto_fix": suggestion is not None, "citation": citation or self.cite(rule), "bbox": None,
        })

    # ------------------------------------------------------------------ checks
    def terminology(self):
        for r in (x for x in self.rules if x["kind"] == "term"):
            flags = 0 if r["case_sensitive"] else re.I
            try:
                rx = re.compile(r"\b(?:%s)\b" % r["pattern"], flags)
            except re.error:
                continue
            for m in rx.finditer(self.text):
                sug = None
                if r["preferred"]:
                    try:
                        sug = _case(m.group(0), m.expand(r["preferred"])) if not r["case_sensitive"] else m.expand(r["preferred"])
                    except (re.error, IndexError):
                        sug = r["preferred"]
                    if sug == m.group(0):
                        continue
                msg = f'{r["name"]}: “{m.group(0)}”' + (f' → use “{sug}”.' if sug else ". Rephrase.")
                self.add(r, m.start(), m.end(), msg, sug)

    def tone(self):
        words = max(1, len(re.findall(r"\w+", self.text)))
        for r in (x for x in self.rules if x["kind"] == "exclaim"):
            allowed = max(1, math.ceil(words / 100 * float(r["pattern"] or 1)))
            marks = [m.start() for m in re.finditer(r"!", self.text)]
            for pos in marks[allowed:][:6]:
                self.add(r, pos, pos + 1, f"Too many exclamation marks ({len(marks)}; max {allowed} for {words} words).", ".")
        for r in (x for x in self.rules if x["kind"] == "caps"):
            allowed = int(float(r["pattern"] or 0))
            hits = [m for m in re.finditer(r"\b[A-Z]{3,}\b", self.text) if m.group(0) not in ACRONYM_OK]
            for m in hits[allowed:][:6]:
                self.add(r, m.start(), m.end(), f"Shouting in capitals: “{m.group(0)}”.", m.group(0).capitalize())
        for s, e, sent in _sentences(self.text):
            n = len(sent.split())
            if n > 35:
                r = next((x for x in self.rules if x["kind"] == "exclaim"), None)
                if r:
                    self.add({**r, "key": "readability", "category": "tone", "name": "Readability",
                              "description": "Keep sentences short and clear.", "source": "Brand Guidelines §1 Voice & Tone"},
                             s, e, f"Sentence is {n} words long; aim for under 25.", None, "minor")

    def claims(self):
        crules = [x for x in self.rules if x["kind"] == "claim"]
        for r in crules:
            try:
                rx = re.compile(r["pattern"], re.I)
            except re.error:
                continue
            for s, e, sent in _sentences(self.text):
                trig = [m for m in rx.finditer(sent)]
                if not trig:
                    continue
                if any(i["rule_key"] == r["key"] and i["start"] == s for i in self.issues):
                    continue
                ev = self.support(sent)
                st, en = s + (len(sent) - len(sent.lstrip())), e
                if ev["supported"]:
                    self.verified.append({"sentence": sent.strip(), "start": st, "end": en, "evidence": ev["evidence"]})
                    continue
                soft = sent
                for pat, rep in SOFTEN:
                    soft = re.sub(pat, rep, soft, flags=re.I)
                soft = soft.strip()
                sug = soft if soft != sent.strip() else None
                cit = {"source": r["source"], "doc_title": ev["evidence"]["doc_title"] if ev["evidence"] else None,
                       "quote": ev["evidence"]["text"][:320] if ev["evidence"] else "No supporting source found.",
                       "score": ev["score"]}
                self.add(r, st, en, f'Unverified claim “{trig[0].group(0).strip()}”: {ev["reason"]}', sug, citation=cit)

    def support(self, sentence):
        hits = rag.search(sentence, k=3)
        if not hits:
            return {"supported": False, "score": 0, "reason": "no approved source mentions this.", "evidence": None}
        best = hits[0]
        words = rag.content_words(sentence) - {"verdant"}
        cover = len(words & rag.content_words(best["text"])) / max(1, len(words))
        nums = re.findall(r"\d+(?:\.\d+)?", sentence)
        nums_ok = all(n in best["text"] for n in nums)
        ok = best["score"] >= 0.16 and cover >= 0.5 and nums_ok
        if ok:
            reason = "supported"
        elif not nums_ok:
            reason = "the figure(s) in this claim do not match the approved source."
        else:
            reason = "approved sources do not substantiate it."
        return {"supported": ok, "score": best["score"], "reason": reason,
                "evidence": {"doc_title": best["doc_title"], "heading": best["heading"], "text": best["text"], "score": best["score"]}}

    def disclaimers(self):
        for r in (x for x in self.rules if x["kind"] == "disclaimer"):
            try:
                trig = re.compile(r["pattern"], re.I).search(self.text)
            except re.error:
                continue
            if trig and not re.search(r"terms\s+(and conditions\s+)?apply|see\s+(full\s+)?terms|results may vary", self.text, re.I):
                end = len(self.text.rstrip())
                self.add(r, end, end, f'Missing required disclaimer for “{trig.group(0)}”.', " " + r["preferred"])

    def pii(self):
        fake = {"key": "pii-exposure", "name": "Personal data", "category": "privacy", "severity": "critical",
                "description": "Never publish personal contact data or payment details.", "source": "Brand Guidelines §6 Privacy"}
        seen = []
        for label, rx in (("email address", EMAIL), ("card number", CARD), ("phone number", PHONE)):
            for m in rx.finditer(self.text):
                if any(m.start() < b and m.end() > a for a, b in seen):
                    continue
                if label == "card number" and len(re.sub(r"\D", "", m.group(0))) < 13:
                    continue
                seen.append((m.start(), m.end()))
                if label == "email address" and m.group(0).lower().endswith("@brandguard.ai"):
                    continue
                self.add(fake, m.start(), m.end(), f"Possible {label} detected.", f"[REDACTED {label.split()[0].upper()}]")

    def run(self):
        self.terminology(); self.tone(); self.claims(); self.disclaimers(); self.pii()
        self.issues.sort(key=lambda i: (i["start"], i["end"]))
        words = re.findall(r"\w+", self.text)
        sents = _sentences(self.text)
        metrics = {"words": len(words), "sentences": len(sents),
                   "avg_sentence_words": round(len(words) / max(1, len(sents)), 1), "exclamations": self.text.count("!")}
        return {"issues": self.issues, "verified_claims": self.verified, "metrics": metrics}


def analyze_text(text, rules):
    return Checker(rules, text or "").run()


def score(issues):
    """100 minus weighted penalties; each rule's penalty is capped so one repeated slip can't zero a draft."""
    per_rule = {}
    for i in issues:
        if i.get("status", "open") == "open":
            per_rule[i["rule_key"]] = per_rule.get(i["rule_key"], 0) + SEV_WEIGHT.get(i["severity"], 4)
    return max(0, 100 - sum(min(v, 30) for v in per_rule.values()))


def mask_pii(text):
    text = EMAIL.sub("[EMAIL]", text)
    text = CARD.sub("[CARD]", text)
    return PHONE.sub("[PHONE]", text)

"""Numbers → spoken Hindi, so the TTS says "चालीस हज़ार तीन सौ चौवालीस रुपये"
instead of reading "₹40,344" digit by digit or in English.

Only used for text that is already in Devanagari; English replies keep digits
and rely on the TTS's own normalisation.
"""

from __future__ import annotations

import re

# 0–99 are irregular in Hindi; every one is listed.
_UNITS = ("शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस "
          "बीस इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस "
          "छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस "
          "उनचास पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ इकसठ बासठ तिरसठ चौंसठ पैंसठ "
          "छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी "
          "अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानबे बानबे तिरानबे "
          "चौरानबे पंचानबे छियानबे सत्तानबे अट्ठानबे निन्यानबे").split()
assert len(_UNITS) == 100


def hindi_words(n: int) -> str:
    """Indian place values: करोड़ (10^7), लाख (10^5), हज़ार (10^3), सौ (10^2)."""
    if n < 0:
        return "माइनस " + hindi_words(-n)
    if n < 100:
        return _UNITS[n]
    parts = []
    for value, word in ((10**7, "करोड़"), (10**5, "लाख"), (1000, "हज़ार"), (100, "सौ")):
        if n >= value:
            parts.append(f"{hindi_words(n // value)} {word}")
            n %= value
    if n:
        parts.append(_UNITS[n])
    return " ".join(parts)


_RUPEES = re.compile(r"(?:₹|rs\.?\s?|inr\s?)\s*(\d[\d,]*)(?:\.(\d{1,2}))?", re.I)
_PLAIN = re.compile(r"(?<![\w.])(\d[\d,]*)(?![\d.]*\w)")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def speak_numbers_hindi(text: str) -> str:
    """Rewrite amounts and plain numbers as Hindi words, only in Devanagari text."""
    if not _DEVANAGARI.search(text):
        return text

    def rupees(m: re.Match) -> str:
        whole = int(m.group(1).replace(",", ""))
        out = f"{hindi_words(whole)} रुपये"
        if m.group(2) and int(m.group(2)):
            out += f" {hindi_words(int(m.group(2).ljust(2, '0')))} पैसे"
        return out

    text = _RUPEES.sub(rupees, text)
    text = re.sub(r"(\d[\d,]*)\s*%", lambda m: f"{m.group(1)} प्रतिशत", text)
    # Plain numbers (days, percentages, scores): keep card/account codes like XX9269 untouched.
    return _PLAIN.sub(lambda m: hindi_words(int(m.group(1).replace(",", ""))) if len(m.group(1).replace(",", "")) <= 9 else m.group(1), text)

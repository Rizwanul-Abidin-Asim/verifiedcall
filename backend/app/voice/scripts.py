"""The scam-interrogation script, in the four languages our customers actually use.

TRANSLATION STATUS: written by the build, NOT yet reviewed by native speakers. The
Arabic is Modern Standard rather than Gulf dialect, deliberately: MSA is understood
everywhere in the region, and dialect synthesis quality is poor enough that a bad Gulf
accent would sound less trustworthy than clear MSA. Before any real customer hears
these, a native speaker of each language must review them. Tracked in the README.

Two design decisions worth knowing:

1. Every question is answerable with one word, and every question also accepts a keypad
   press. Speech recognition for Arabic and Urdu is the weakest link in this whole
   system, and a keypad digit is language-independent and exact. We ask by voice and
   accept either.

2. Question 4 is the one that matters. Scammers coach victims to keep the call secret,
   so a truthful "no" and a coached "no" sound identical. What separates them is how
   long the answer takes, which is why classify.py reads timing as well as words.
"""

from enum import StrEnum

from pydantic import BaseModel


class Language(StrEnum):
    EN = "en"
    AR = "ar"
    HI = "hi"
    UR = "ur"


LANGUAGE_NAMES = {
    Language.EN: "English",
    Language.AR: "Arabic",
    Language.HI: "Hindi",
    Language.UR: "Urdu",
}

# Transcriber locales, so the client does not have to map these itself.
#
# These are Deepgram codes and the accepted set is narrower than it looks: only en
# carries regional variants. ar-AE, hi-IN and ur-PK are rejected, which is worth
# knowing because the rejection lands when the call is placed, not when it is written.
# Checked against the provider's published schema.
SPEECH_LOCALE = {
    Language.EN: "en-US",
    Language.AR: "ar",
    Language.HI: "hi",
    Language.UR: "ur",
}

# Deepgram's non-English coverage is uneven, and Arabic in particular is weaker than
# its English. That is the reason the script offers a keypad answer in every language
# and the reason a keypad press outranks the transcript in classify.py: the decision
# should not rest on a transcriber being good at Gulf Arabic.



class Question(BaseModel):
    key: str
    text: str
    scam_if_yes: bool = False
    """True when a yes answer is itself evidence of coercion."""


class Script(BaseModel):
    language: Language
    opening: str
    questions: list[Question]
    closing_released: str
    closing_held: str

    def rendered_opening(self, amount: str, currency: str, beneficiary: str) -> str:
        return self.opening.format(amount=amount, currency=currency, beneficiary=beneficiary)


# --------------------------------------------------------------------- English

_EN = Script(
    language=Language.EN,
    opening=(
        "Hello. This is an automated security check from your bank. "
        "A payment of {amount} {currency} to {beneficiary} is on hold. "
        "I need to ask you three short questions. You can answer by speaking, "
        "or by pressing 1 for yes and 2 for no."
    ),
    questions=[
        Question(key="others_present",
                 text="Is anyone else on another call with you, or in the room with you "
                      "right now? Say yes or no, or press 1 for yes and 2 for no."),
        Question(key="asked_to_pay", scam_if_yes=True,
                 text="Did someone contact you and ask you to make this payment? "
                      "Say yes or no, or press 1 for yes and 2 for no."),
        Question(key="told_to_keep_secret", scam_if_yes=True,
                 text="Were you told not to discuss this payment with your bank? "
                      "Say yes or no, or press 1 for yes and 2 for no."),
    ],
    closing_released="Thank you. Your payment will go through as normal. Goodbye.",
    closing_held=(
        "Thank you. We have stopped this payment and your money is safe. "
        "Your bank will contact you shortly. Please do not continue any call you are "
        "currently on. Goodbye."
    ),
)

# ---------------------------------------------------------------------- Arabic

_AR = Script(
    language=Language.AR,
    opening=(
        "مرحباً. هذا فحص أمني آلي من مصرفك. "
        "هناك عملية دفع بقيمة {amount} {currency} إلى {beneficiary} قيد الإيقاف. "
        "سأطرح عليك ثلاثة أسئلة قصيرة. يمكنك الإجابة بالكلام، "
        "أو بالضغط على 1 للموافقة و 2 للرفض."
    ),
    questions=[
        Question(key="others_present",
                 text="هل يوجد شخص آخر على مكالمة معك، أو في الغرفة معك الآن؟ "
                      "قل نعم أو لا، أو اضغط 1 لنعم و 2 للا."),
        Question(key="asked_to_pay", scam_if_yes=True,
                 text="هل اتصل بك شخص وطلب منك إجراء هذه العملية؟ "
                      "قل نعم أو لا، أو اضغط 1 لنعم و 2 للا."),
        Question(key="told_to_keep_secret", scam_if_yes=True,
                 text="هل طُلب منك عدم التحدث عن هذه العملية مع مصرفك؟ "
                      "قل نعم أو لا، أو اضغط 1 لنعم و 2 للا."),
    ],
    closing_released="شكراً لك. سيتم إتمام عمليتك بشكل طبيعي. مع السلامة.",
    closing_held=(
        "شكراً لك. لقد أوقفنا هذه العملية وأموالك في أمان. "
        "سيتواصل معك مصرفك قريباً. من فضلك لا تكمل أي مكالمة أخرى الآن. مع السلامة."
    ),
)

# ----------------------------------------------------------------------- Hindi

_HI = Script(
    language=Language.HI,
    opening=(
        "नमस्ते। यह आपके बैंक की ओर से एक स्वचालित सुरक्षा जाँच है। "
        "{beneficiary} को {amount} {currency} का भुगतान अभी रोका गया है। "
        "मैं आपसे तीन छोटे सवाल पूछूँगा। आप बोलकर उत्तर दे सकते हैं, "
        "या हाँ के लिए 1 और नहीं के लिए 2 दबा सकते हैं।"
    ),
    questions=[
        Question(key="others_present",
                 text="क्या इस समय कोई और आपके साथ दूसरी कॉल पर है, या आपके कमरे में मौजूद है? "
                      "हाँ या नहीं कहें, या हाँ के लिए 1 और नहीं के लिए 2 दबाएँ।"),
        Question(key="asked_to_pay", scam_if_yes=True,
                 text="क्या किसी ने आपसे संपर्क करके यह भुगतान करने के लिए कहा? "
                      "हाँ या नहीं कहें, या हाँ के लिए 1 और नहीं के लिए 2 दबाएँ।"),
        Question(key="told_to_keep_secret", scam_if_yes=True,
                 text="क्या आपसे कहा गया था कि इस भुगतान के बारे में अपने बैंक को न बताएँ? "
                      "हाँ या नहीं कहें, या हाँ के लिए 1 और नहीं के लिए 2 दबाएँ।"),
    ],
    closing_released="धन्यवाद। आपका भुगतान सामान्य रूप से पूरा हो जाएगा। नमस्ते।",
    closing_held=(
        "धन्यवाद। हमने यह भुगतान रोक दिया है और आपका पैसा सुरक्षित है। "
        "आपका बैंक जल्द ही आपसे संपर्क करेगा। कृपया अभी चल रही कोई भी कॉल जारी न रखें। नमस्ते।"
    ),
)

# ------------------------------------------------------------------------ Urdu

_UR = Script(
    language=Language.UR,
    opening=(
        "السلام علیکم۔ یہ آپ کے بینک کی طرف سے ایک خودکار سیکیورٹی جانچ ہے۔ "
        "{beneficiary} کو {amount} {currency} کی ادائیگی اس وقت روکی گئی ہے۔ "
        "میں آپ سے تین مختصر سوال پوچھوں گا۔ آپ بول کر جواب دے سکتے ہیں، "
        "یا ہاں کے لیے 1 اور نہیں کے لیے 2 دبا سکتے ہیں۔"
    ),
    questions=[
        Question(key="others_present",
                 text="کیا اس وقت کوئی اور آپ کے ساتھ دوسری کال پر ہے، یا آپ کے کمرے میں موجود ہے؟ "
                      "ہاں یا نہیں کہیں، یا ہاں کے لیے 1 اور نہیں کے لیے 2 دبائیں۔"),
        Question(key="asked_to_pay", scam_if_yes=True,
                 text="کیا کسی نے آپ سے رابطہ کر کے یہ ادائیگی کرنے کو کہا؟ "
                      "ہاں یا نہیں کہیں، یا ہاں کے لیے 1 اور نہیں کے لیے 2 دبائیں۔"),
        Question(key="told_to_keep_secret", scam_if_yes=True,
                 text="کیا آپ سے کہا گیا تھا کہ اس ادائیگی کے بارے میں اپنے بینک کو نہ بتائیں؟ "
                      "ہاں یا نہیں کہیں، یا ہاں کے لیے 1 اور نہیں کے لیے 2 دبائیں۔"),
    ],
    closing_released="شکریہ۔ آپ کی ادائیگی معمول کے مطابق مکمل ہو جائے گی۔ خدا حافظ۔",
    closing_held=(
        "شکریہ۔ ہم نے یہ ادائیگی روک دی ہے اور آپ کی رقم محفوظ ہے۔ "
        "آپ کا بینک جلد آپ سے رابطہ کرے گا۔ براہ کرم اس وقت جاری کوئی بھی کال جاری نہ رکھیں۔ خدا حافظ۔"
    ),
)

SCRIPTS: dict[Language, Script] = {
    Language.EN: _EN, Language.AR: _AR, Language.HI: _HI, Language.UR: _UR,
}

# Spoken yes/no per language. Kept small on purpose: we only need to separate three
# cases, and a short closed vocabulary is far more robust than open transcription.
AFFIRMATIVE: dict[Language, tuple[str, ...]] = {
    Language.EN: ("yes", "yeah", "yep", "yes i did", "correct", "that's right", "affirmative"),
    Language.AR: ("نعم", "أجل", "ايوه", "أيوه", "صح", "بلى"),
    Language.HI: ("हाँ", "हां", "जी", "जी हाँ", "हाँ जी", "सही"),
    Language.UR: ("ہاں", "جی", "جی ہاں", "درست", "ٹھیک"),
}
NEGATIVE: dict[Language, tuple[str, ...]] = {
    Language.EN: ("no", "nope", "nah", "no i didn't", "negative", "not at all"),
    Language.AR: ("لا", "كلا", "أبداً", "ابدا"),
    Language.HI: ("नहीं", "ना", "नही", "बिल्कुल नहीं"),
    Language.UR: ("نہیں", "نہ", "بالکل نہیں"),
}

# Keypad, identical in every language. This is the reason a weak transcript is survivable.
DTMF_YES = "1"
DTMF_NO = "2"


def spoken_amount(amount) -> str:
    """Render an amount so a speech engine says a number, not a string of digits.

    Found on the first real call. We passed "42,000.00" and the assistant said
    "4 2 0 0 0 0 0", which the provider's own summary then recorded as AED 4,200,000.

    On a fraud check that is not cosmetic. A customer told the wrong amount says "that
    is not my payment" and the call is over, and the one number the call exists to
    confirm is the one we got wrong. Words remove the ambiguity in every voice and
    every locale, at the cost of being slightly longer to say.
    """
    whole = int(amount)
    cents = int(round((float(amount) - whole) * 100))
    words = _in_words(whole)
    if cents:
        words = f"{words} and {_in_words(cents)}"
    return words


_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
         "ninety")


def _under_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, rest = divmod(n, 10)
    return _TENS[tens] + (f"-{_ONES[rest]}" if rest else "")


def _under_thousand(n: int) -> str:
    if n < 100:
        return _under_hundred(n)
    hundreds, rest = divmod(n, 100)
    return _ONES[hundreds] + " hundred" + (f" and {_under_hundred(rest)}" if rest else "")


def _in_words(n: int) -> str:
    """English number words. Only the scales a payment can plausibly reach."""
    if n == 0:
        return "zero"
    if n < 0:
        return f"minus {_in_words(-n)}"
    parts: list[str] = []
    for size, name in ((1_000_000_000, "billion"), (1_000_000, "million"),
                       (1_000, "thousand")):
        if n >= size:
            count, n = divmod(n, size)
            parts.append(f"{_in_words(count)} {name}")
    if n:
        parts.append(_under_thousand(n))
    return " ".join(parts)


def normalise_language(locale: str | None) -> Language:
    """Map a customer locale onto a script. Unknown locales fall back to English."""
    if not locale:
        return Language.EN
    head = locale.strip().lower().replace("_", "-").split("-")[0]
    try:
        return Language(head)
    except ValueError:
        return Language.EN


def script_for(locale: str | None) -> Script:
    return SCRIPTS[normalise_language(locale)]

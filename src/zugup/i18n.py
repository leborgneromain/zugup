from zugup.locales import en, fr

LANGUAGES = ("fr", "en")
DEFAULT_LANGUAGE = "fr"
CATALOGS = {"fr": fr.MESSAGES, "en": en.MESSAGES}
CLIENT_PREFIX = "js."


class Translator:
    def __init__(self, lang):
        self.lang = lang if lang in CATALOGS else DEFAULT_LANGUAGE
        self.messages = CATALOGS[self.lang]

    def raw(self, key):
        return self.messages[key]

    def __call__(self, key, **params):
        count = params.get("count")
        if count is not None and f"{key}.one" in self.messages:
            key = f"{key}.one" if count == 1 else f"{key}.other"
        return self.messages[key].format(**params)

    def decimal(self, value, digits=1):
        text = f"{value:.{digits}f}"
        return text.replace(".", ",") if self.lang == "fr" else text

    def percent(self, value, digits=1):
        text = self.decimal(value, digits)
        return f"{text} %" if self.lang == "fr" else f"{text}%"

    def client_messages(self):
        return {key: value for key, value in self.messages.items() if key.startswith(CLIENT_PREFIX)}


def translator(lang=DEFAULT_LANGUAGE):
    return Translator(lang)

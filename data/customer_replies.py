"""Sample code-mixed customer replies across India's most common
transliteration patterns, bucketed by intent.

Per spec section 9: test the LLM's promise-to-pay extraction against these
BEFORE wiring the full LangGraph. Run this in isolation on Day 3:

    python -m data.customer_replies   # prints the full bank for inspection

Each bucket maps to what the Promise-to-Pay node (section 3, 7) needs to
output: a promised_date, "no commitment", or "disputing".

IMPORTANT — language is intentionally NOT a field the detector/agent is
given. In the real flow, the LLM has to identify which language a reply is
in AND extract the commitment from the same message, in the same call
(see README: language detection folds into the Promise-to-Pay node's
structured output, not a separate call). These buckets are grouped by
language here only so you can build a stratified eval set and score
per-language accuracy afterward — that grouping is for your evaluation
harness, not something fed to the model as input.

Dates in CLEAR_PROMISE are written as relative-to-today phrases on purpose
("naalaikku", "repu", "naale") — that's the actual extraction challenge,
not literal dates. The LLM has to resolve these against a reference date
you pass in the prompt.
"""

HINGLISH = {
    "clear_promise": [
        "Haan bhai, kal tak pay kar dunga, salary aane wali hai.",
        "Sorry for delay, Friday ko definitely kar dunga payment.",
        "Ok theek hai, is weekend tak clear kar dunga.",
        "Next Monday tak paisa aa jayega account mein, tab kar dunga.",
        "Aaj raat tak kar dunga, bas card update karna hai.",
        "2 din mein kar dunga, abhi thoda busy hoon.",
    ],
    "vague_stall": [
        "Dekhta hoon, jaldi karunga kuch.",
        "Abhi thoda tight chal raha hai, baad mein dekhta hoon.",
        "Haan haan karunga, thoda time do.",
        "Pata nahi kab tak, dekh lunga.",
        "Busy hoon abhi, baad mein baat karte hain.",
        "Try karunga, confirm nahi kar sakta abhi.",
    ],
    "dispute": [
        "Maine to already pay kar diya tha last week, phir se kyun maang rahe ho?",
        "Ye charge galat hai, maine subscription cancel kar diya tha.",
        "Mujhe ye service chahiye hi nahi thi, refund chahiye.",
        "Double charge ho gaya hai mera, ek transaction check karo.",
        "Main is amount se agree nahi karta, overcharge kiya hai aapne.",
        "Ye kisi aur ne liya hoga mere card se, main nahi janta.",
    ],
    "silence": ["", "Ok", "Hmm", "👍", "...", "Achha"],
}

TANGLISH = {
    "clear_promise": [
        "Sari bro, naalaiku kandippa pay pannuren, salary vandhaachu.",
        "Sorry delay ku, Friday ku pay pannitren.",
        "Idhu weekend ku clear pannitren, kandippa.",
        "Next Monday ku money varum, adhukappuram pannuren.",
        "Ipo card update pannanum, appuram immediate ah pay pannuren.",
        "Rendu naal la pannitren, konjam busy iruken.",
    ],
    "vague_stall": [
        "Paakalam, jaldi pannuren edhavadhu.",
        "Konjam tight ah iruku, appuram paakalam.",
        "Sari sari pannuren, konjam time kudunga.",
        "Theriyala eppo nu, paakalam.",
        "Busy ah iruken, appuram pesalam.",
        "Try pannuren, confirm panna mudiyala ipo.",
    ],
    "dispute": [
        "Naan already pay panniten last week, yen thirumba kekkarreenga?",
        "Idhu charge thappu, naan subscription cancel pannitten.",
        "Enakku indha service thevaye illa, refund venum.",
        "Rendu murai charge aayiduchu, oru transaction check pannunga.",
        "Naan indha amount ku agree pannala, over charge pannitinga.",
        "Idha vera yaaro eduthirupanga en card la, enakku theriyala.",
    ],
    "silence": ["", "Ok", "Hmm", "👍", "...", "Seri"],
}

TENGLISH = {
    "clear_promise": [
        "Sare bro, repu pay chesta, salary vastundi.",
        "Sorry delay ki, Friday ki pakka pay chesta.",
        "Ee weekend ki clear chesta.",
        "Next Monday ki money vastundi account lo, appudu chesta.",
        "Ee roju ratri ki chesta, card update cheyyali anthe.",
        "Rendu rojullo chesta, ippudu konchem busy ga unna.",
    ],
    "vague_stall": [
        "Chustanu, thondaraga chestha edo.",
        "Ippudu konchem tight ga undi, tarwata chustanu.",
        "Sare sare chestha, konchem time ivvu.",
        "Teliyadu eppudo, chustanu.",
        "Busy ga unna ippudu, tarwata matladdam.",
        "Try chestha, confirm cheyyalenu ippudu.",
    ],
    "dispute": [
        "Nenu already last week pay chesanu, malli enduku adugutunnaru?",
        "Ee charge tappu, nenu subscription cancel chesanu.",
        "Naaku ee service avasaram ledu, refund kavali.",
        "Rendu sarlu charge ayyindi, oka transaction check cheyandi.",
        "Nenu ee amount tho agree kaledu, overcharge chesaru.",
        "Idi evaro theesukoni untaru na card tho, naaku teliyadu.",
    ],
    "silence": ["", "Ok", "Hmm", "👍", "...", "Sare"],
}

KANGLISH = {
    "clear_promise": [
        "Sari bro, naale pay madtini, salary bartide.",
        "Sorry delay aagide, Friday ge pakka pay madtini.",
        "Ee weekend ge clear madtini.",
        "Next Monday ge money bartade account ge, aaga madtini.",
        "Ivattu ratri madtini, card update madbeku antashte.",
        "Eradu dinadalli madtini, ivaga konchu busy iddini.",
    ],
    "vague_stall": [
        "Nodona, bega madtini yenadru.",
        "Ivaga konchu tight ide, aamele nodona.",
        "Sari sari madtini, konchu time kodi.",
        "Gottilla yavaga anta, nodona.",
        "Busy iddini ivaga, aamele matadona.",
        "Try madtini, confirm madakke aagalla ivaga.",
    ],
    "dispute": [
        "Nanu already last week pay madidde, yaake matte keltiddira?",
        "Ee charge tappu, nanu subscription cancel madidde.",
        "Nanage ee service beku illa, refund beku.",
        "Eradu sala charge aagide, ondu transaction check madi.",
        "Nanu ee amount ge agree madilla, overcharge madiddira.",
        "Idu yaaro tegedukondirabahudu na card nalli, nanage gottilla.",
    ],
    "silence": ["", "Ok", "Hmm", "👍", "...", "Sari"],
}

MALAYALAM_ENGLISH = {
    "clear_promise": [
        "Sheri bro, naale pay cheyyam, salary varum.",
        "Sorry delay aayathinu, Friday aakumbol pay cheyyam.",
        "Ee weekend aakumbol clear cheyyam.",
        "Next Monday aakumbol money varum account il, appol cheyyam.",
        "Innu raathri cheyyam, card update cheyyanam ennu mathram.",
        "Randu divasathinullil cheyyam, ippo konjam busy aanu.",
    ],
    "vague_stall": [
        "Nokkam, pettannu cheyyam enthenkilum.",
        "Ippo konjam tight aanu, pinne nokkam.",
        "Sheri sheri cheyyam, konjam time tharu.",
        "Ariyilla eppo ennu, nokkam.",
        "Busy aanu ippo, pinne samsarikkam.",
        "Try cheyyam, confirm cheyyan pattilla ippo.",
    ],
    "dispute": [
        "Njan already last week pay cheythu, enthinaanu veendum chodikkunnathu?",
        "Ee charge thettanu, njan subscription cancel cheythu.",
        "Enikku ee service venda, refund venam.",
        "Randu thavana charge aayi, oru transaction check cheyyu.",
        "Njan ee amount thott agree alla, overcharge cheythu.",
        "Ithu vere aarenkilum edutha kaanum en card il, enikku ariyilla.",
    ],
    "silence": ["", "Ok", "Hmm", "👍", "...", "Sheri"],
}

# Registry: language code -> (display name, bucket dict).
# Keys chosen to be stable identifiers you can use in eval reports.
LANGUAGES = {
    "hinglish": {"name": "Hindi-English", "buckets": HINGLISH},
    "tanglish": {"name": "Tamil-English", "buckets": TANGLISH},
    "tenglish": {"name": "Telugu-English", "buckets": TENGLISH},
    "kanglish": {"name": "Kannada-English", "buckets": KANGLISH},
    "malayalam_english": {"name": "Malayalam-English", "buckets": MALAYALAM_ENGLISH},
}

# Flat list of (language_code, bucket, text) — convenient for building a
# stratified eval set or sampling during Day 3 conversation simulation.
ALL_REPLIES = [
    (lang_code, bucket, text)
    for lang_code, lang in LANGUAGES.items()
    for bucket, texts in lang["buckets"].items()
    for text in texts
]


if __name__ == "__main__":
    for lang_code, lang in LANGUAGES.items():
        print(f"\n{'=' * 10} {lang['name']} ({lang_code}) {'=' * 10}")
        for bucket, replies in lang["buckets"].items():
            print(f"\n  --- {bucket} ---")
            for r in replies:
                print(f"    - {r!r}")
    print(f"\n\nTotal replies across {len(LANGUAGES)} languages: {len(ALL_REPLIES)}")

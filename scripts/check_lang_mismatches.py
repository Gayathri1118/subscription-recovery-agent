import json
data = json.load(open("scripts/extraction_results_20260827_124532.json", encoding="utf-8"))
for r in data["results"]:
    if r["language_expected"] != r["language_predicted"]:
        print(r["language_expected"], "-> predicted", r["language_predicted"], "|", r["text"][:60])

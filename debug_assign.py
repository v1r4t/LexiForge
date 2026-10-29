from lexiforge.glossary.assign import assign_terms

glossary = {
    "real": [{"id": f"r{i}", "term": f"R{i}"} for i in range(10)],
    "fictional": [{"id": f"f{i}", "term": f"F{i}", "type": "fictional"} for i in range(8)],
}
calls = [{"id": f"c{i:02d}", "call_type": "upi"} for i in range(20)]
result = assign_terms(glossary, calls, seed=12345)
for k, v in list(result.items())[:3]:
    print(len(v["real"]), len(v["fictional"]))

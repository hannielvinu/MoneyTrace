"""Agreement between the LLM grounding judge and Hanniel's labels on the 20 hand-checked answers.

    python -m evaluation.judge_agreement results/rag_eval/<run_id>
Reads human_check.csv (column 'human_fully_grounded (1/0)') and writes judge_agreement.json.
"""
import csv
import json
import os
import sys


def main(run_dir):
    path = os.path.join(run_dir, "human_check.csv")
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    labelled = [r for r in rows if r["human_fully_grounded (1/0)"].strip() in ("0", "1")]
    if not labelled:
        print("No human labels yet: fill the 'human_fully_grounded (1/0)' column first.")
        return 1
    agree = sum(1 for r in labelled if int(r["judge_fully_grounded"]) == int(r["human_fully_grounded (1/0)"]))
    tp = sum(1 for r in labelled if r["judge_fully_grounded"] == "1" and r["human_fully_grounded (1/0)"].strip() == "1")
    jp = sum(1 for r in labelled if r["judge_fully_grounded"] == "1")
    hp = sum(1 for r in labelled if r["human_fully_grounded (1/0)"].strip() == "1")
    po = agree / len(labelled)
    pe = ((jp / len(labelled)) * (hp / len(labelled)) + (1 - jp / len(labelled)) * (1 - hp / len(labelled)))
    kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
    out = {"labelled": len(labelled), "agreement": round(po, 4), "cohens_kappa": round(kappa, 4),
           "judge_positive": jp, "human_positive": hp, "both_positive": tp}
    json.dump(out, open(os.path.join(run_dir, "judge_agreement.json"), "w"), indent=2)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

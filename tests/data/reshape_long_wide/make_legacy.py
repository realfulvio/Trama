"""Write legacy.json: Reshape replicates and Extract and rearrange on a fixed table, one recipe per variant.

Run on the base commit (4c07db6) before Reshape long and wide existed:
``python tests/data/reshape_long_wide/make_legacy.py``. test_reshape_long_wide compares the current results to it.
"""
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from analisi.workbench import analyse  # noqa: E402

TABLE = pd.DataFrame({
    "Dose $": [0.5, 1.0, 2.0, 0.5, 1.0, 2.0],
    "Response | A": [10.2, 11.8, 14.1, 9.7, 12.2, None],
    "Group à": ["Ctrl", "Ctrl", "Ctrl", "Drug", "Drug", "Drug"],
    "Subject": ["001", "002", "003", "001", "002", "003"],
    "Sex": ["F", "M", "F", "M", "F", "M"],
    "Count": [3, 5, 2, 4, 1, 6],
})
RECIPES = [
    ("Reshape replicates", {"Variables": ["Dose $", "Response | A"]}),
    ("Reshape replicates", {"Variables": ["Dose $", "Response | A"], "Row label": "Group à"}),
    ("Extract and rearrange", {"Output table": "XY", "Independent (X) variable": "Dose $",
                               "Response variable": "Response | A", "Grouping variable": "Group à",
                               "Subject/replicate variable": "Subject"}),
    ("Extract and rearrange", {"Output table": "Column", "Response variable": "Response | A",
                               "Grouping variable": "Group à", "Only include complete rows": False}),
    ("Extract and rearrange", {"Output table": "Grouped", "Response variable": "Response | A",
                               "Row factor variable": "Sex", "Column factor variable": "Group à"}),
    ("Extract and rearrange", {"Output table": "Contingency", "Row (treatment) variable": "Group à",
                               "Column (outcome) variable": "Sex", "Count variable": "Count"}),
]


def encode(result):
    tables = {}
    for name, table in result.tables.items():
        tables[name] = {"columns": [str(column) for column in table.columns],
                        "index": [repr(value) for value in table.index],
                        "rows": [[None if pd.isna(value) else repr(value) for value in row]
                                 for row in table.itertuples(index=False, name=None)]}
    return tables


def main():
    cases = [{"method": method, "options": options, "tables": encode(analyse(method, TABLE.copy(), options))}
             for method, options in RECIPES]
    path = Path(__file__).with_name("legacy.json")
    path.write_text(json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(path, len(cases))


if __name__ == "__main__":
    main()

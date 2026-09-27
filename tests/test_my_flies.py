import pytest

from flypicker import catalog, my_flies

FOODS = [
    {"id": "caddis", "name": "Caddisflies", "sizes": [12, 18], "water": {"RIVER": 1, "LAKE": 0.5}},
    {"id": "sowbug", "name": "Sowbugs", "sizes": [14, 18], "water": {"tailwater": 1.3}},
]
WATERS = {"RIVER", "LAKE", "tailwater", "freestone"}


def load(tmp_path, text, taken=()):
    path = tmp_path / "my_flies.csv"
    path.write_text("name,type,imitates,sizes,water,proven,notes\n" + text)
    return my_flies.load(path, FOODS, WATERS, set(taken), catalog.FLY_TYPES)


def test_minimal_row_fills_defaults(tmp_path):
    [fly] = load(tmp_path, "Olive Kenny,wet,sowbug:0.5; Caddisflies,,,,\n")
    assert fly["id"] == "olive_kenny"
    assert fly["imitates"] == [["caddis", 0.8], ["sowbug", 0.5]]
    assert fly["sizes"] == [12, 18]
    assert fly["water"] == ["LAKE", "RIVER", "tailwater"]
    assert fly["proven"] == 0.7


def test_full_row(tmp_path):
    [fly] = load(tmp_path, "Big Thing,Streamer,caddis:0.3,2/0-4,tailwater; freestone,0.9,note\n")
    assert fly["family"] == "streamer" and fly["sizes"] == [-1, 4]
    assert fly["water"] == ["tailwater", "freestone"] and fly["proven"] == 0.9


def test_comment_and_blank_rows_skipped(tmp_path):
    assert load(tmp_path, "# Example,wet,caddis,,,,\n,,,,,,\n") == []


@pytest.mark.parametrize("row, msg", [
    ("X,dryish,caddis,,,,", "type"),
    ("X,dry,hex,,,,", "unknown food"),
    ("X,dry,caddis:2,,,,", "between 0 and 1"),
    ("X,dry,caddis,,pond,,", "unknown water"),
    ("X,dry,caddis,big,,,", "hook number"),
    ("Kenny,wet,caddis,,,,", "already exists"),
])
def test_bad_rows_name_the_row(tmp_path, row, msg):
    with pytest.raises(ValueError, match=f"row 2 .*{msg}"):
        load(tmp_path, row + "\n", taken={"kenny"})


def test_shipped_file_loads():
    cat = catalog.load()
    assert "kenny" in cat.flies and "grey_ghost" in cat.flies
